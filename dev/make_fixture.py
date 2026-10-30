"""Builds a synthetic meeting recording: the files fetch.sh would leave in a work dir.

Usage: uv run --with edge-tts python dev/make_fixture.py <out_dir>

Three voices read a short scripted "Software stack meeting" over two slides, with chat
that holds a screenshot request, a note, and an off-record span. Nothing in it is a
real meeting, so it's safe to send to any model. The real chat.py turns the fake Zoom
player info into chat.json, as fetch.sh would.
"""

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

VOICES = {
    "Gina": "en-US-AvaNeural",
    "Marcos": "en-US-AndrewNeural",
    "Krister": "en-GB-RyanNeural",
}
SCRIPT = [
    (
        "Gina",
        "Okay, let's get started. This is the software stack meeting. Today Marcos wants to talk "
        "about how detector data gets from the time tagger to the analysis machines.",
    ),
    (
        "Marcos",
        "Right. So at the moment the detector server polls the Swabian Time Tagger and writes "
        "files to disk, and the analysis side picks them up every minute. It works, but the "
        "latency is bad and we lose the ordering between nodes.",
    ),
    (
        "Krister",
        "This is Krister. On our side at the attosecond layer, we'd really like timestamps "
        "within a second or so, not a minute.",
    ),
    (
        "Marcos",
        "So the proposal on this slide is to have the detector server publish each batch over "
        "ZeroMQ, and have the analysis service subscribe. Files stay as a backup.",
    ),
    ("Gina", "What happens if the subscriber is down? Do we lose data?"),
    ("Marcos", "No, the files are still written, so the analysis side can replay them when it comes back."),
    (
        "Krister",
        "Off topic, but please don't put this in the notes: the coffee machine on our floor is broken again.",
    ),
    ("Gina", "Ha. Okay. So are we agreed on ZeroMQ, with files as the fallback?"),
    ("Krister", "Agreed."),
    ("Gina", "Good. Marcos, can you write up the message format on the wiki before next week's meeting?"),
    ("Marcos", "Yes, I'll do that by Friday."),
    (
        "Gina",
        "Someone also needs to check whether the FPGA timestamps survive the trip. We can figure "
        "out who later. Thanks everyone.",
    ),
]
SLIDES = [
    ("Agenda", ["1. Detector data path", "2. Latency", "3. Next steps"]),
    (
        "Proposal: detector data over ZeroMQ",
        [
            "Time Tagger -> detector_server",
            "detector_server -> ZeroMQ PUB",
            "analysis service SUB",
            "files kept as replay backup",
        ],
    ),
]
SLIDE_AT = 3  # the second slide goes up when this line starts
START_MS = 1_793_120_400_000  # 2026-10-27 17:00:00 GMT
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    return float(out.stdout)


def slide(title: str, lines: list[str], out: Path) -> None:
    def esc(t: str) -> str:  # drawtext treats ':' as an option separator
        return t.replace(":", r"\:")

    draws = [f"drawtext=fontfile={FONT}:text='{esc(title)}':fontsize=44:fontcolor=white:x=60:y=60"]
    draws += [
        f"drawtext=fontfile={FONT}:text='{esc(t)}':fontsize=32:fontcolor=white:x=80:y={170 + 60 * i}"
        for i, t in enumerate(lines)
    ]
    sh("ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x1f3b57:s=1280x720", "-frames:v", "1",
       "-vf", ",".join(draws), str(out))  # fmt: skip


async def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    starts, clips, t = [], [], 1.0
    for i, (who, text) in enumerate(SCRIPT):
        clip = tmp / f"{i:02}.mp3"
        for attempt in range(4):  # the TTS service drops the odd request
            try:
                await edge_tts.Communicate(text, voice=VOICES[who]).save(str(clip))
                break
            except edge_tts.exceptions.NoAudioReceived:
                if attempt == 3:
                    raise
                await asyncio.sleep(2 + 3 * attempt)
        starts.append(t)
        clips.append(clip)
        t += duration(clip) + 0.6
    total = t + 1.0

    # audio: each line at its start time over silence
    inputs, filters = [], []
    for i, (clip, s) in enumerate(zip(clips, starts, strict=True)):
        inputs += ["-i", str(clip)]
        filters.append(f"[{i}:a]adelay={int(s * 1000)}|{int(s * 1000)}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(clips)))
    filters.append(f"{mix}amix=inputs={len(clips)}:normalize=0,apad=whole_dur={total}[out]")
    sh("ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
       "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out / "meeting.wav"))  # fmt: skip

    # video: the two slides, switching when line SLIDE_AT starts
    for i, (title, lines) in enumerate(SLIDES):
        slide(title, lines, tmp / f"slide{i}.png")
    switch = starts[SLIDE_AT]
    sh("ffmpeg", "-y",
       "-loop", "1", "-t", f"{switch}", "-i", str(tmp / "slide0.png"),
       "-loop", "1", "-t", f"{total - switch}", "-i", str(tmp / "slide1.png"),
       "-i", str(out / "meeting.wav"),
       "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,fps=5,format=yuv420p[v]",
       "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
       "-shortest", str(out / "meeting.mp4"))  # fmt: skip

    def at(line: int, offset: float = 2.0) -> int:
        return START_MS + int((starts[line] + offset) * 1000)

    def hms(s: float) -> str:
        return f"{int(s // 3600):02}:{int(s % 3600 // 60):02}:{s % 60:06.3f}"

    chat = [
        (at(1), "Marcos Frenkel", "slides are in the stack folder if anyone wants them"),
        (at(3, 4), "Gina Lorenz", "ai: screenshot the ZeroMQ proposal"),
        (at(6, -0.5), "Krister Shalm", "ai: off record"),
        (at(7, 0.2), "Krister Shalm", "ai: on record"),
        (at(9, 1), "Gina Lorenz", "ai: note decision: ZeroMQ with files as fallback"),
    ]
    play_info = {
        "fileStartTime": START_MS,
        "duration": int(total),
        "xmppList": [{"time": tm, "senderName": who, "content": text} for tm, who, text in chat],
        "vttRanges": {
            "share": [{"startTime": hms(0.5), "endTime": hms(total - 0.5), "text": "Sharing Started"}]
        },
    }
    (out / "play_info.json").write_text(json.dumps(play_info, indent=1))
    skill = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if skill:
        sh(sys.executable, str(skill / "scripts" / "chat.py"), str(out / "play_info.json"), str(out))
    (out / "recording_datetime.txt").write_text("2026-10-27 17:00:00 GMT\n")
    (out / "url.txt").write_text("https://illinois.zoom.us/rec/share/SYNTHETIC-fixture-recording\n")
    print(f"{len(SCRIPT)} lines, {total:.0f}s -> {out}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))

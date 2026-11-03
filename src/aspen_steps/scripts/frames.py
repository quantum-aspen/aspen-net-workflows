#!/usr/bin/env python3
"""Pull screenshots out of a meeting video with ffmpeg.

  frames.py at <video> <seconds> <out.png>
      The frame showing just before <seconds>. If the screen changed in the
      last 2 s it takes the frame from before that change, since people type
      after they've seen something, and a just-changed slide is usually not
      what they meant (or is still mid-transition).

  frames.py commands <video> <chat.json> <out_dir>
      One candidate frame per `ai:` chat command (see chat.py), using `at`,
      named cmd_<H-MM-SS>.png. Not every command asks for a screenshot;
      whoever reads the commands keeps or drops each frame.
      Writes <out_dir>/commands.json: [{t, at, sender, command, frame}].

There's no mode for "every slide": screenshots are taken when someone asks
for one, or for a moment the discussion clearly needs, never in bulk.

<video> is the screen-share-only stream if Zoom recorded one (share.mp4,
yt-dlp format `share`), else meeting.mp4. Times are seconds into
the recording, matching chat.py's `t`. Needs ffmpeg on PATH; stdlib only.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCENE_RECENT = 0.02  # checking a short window for a just-happened change
LOOKBACK = 2.0  # `at`: a change this close before the time means "take the earlier frame"
WIDTH = 1280


def ffmpeg(*args):
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", *args], capture_output=True, text=True, check=True
    ).stderr


def scene_changes(video, threshold, start=None, length=None):
    """Times (s, absolute) where the scene score exceeds threshold."""
    seek = ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-copyts"] if start is not None else []
    log = ffmpeg(
        *seek,
        "-i",
        str(video),
        "-an",
        "-vf",
        f"scale=640:-2,select='gt(scene,{threshold})',showinfo",
        "-f",
        "null",
        "-",
    )
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", log)]


def grab(video, t, out):
    ffmpeg(
        "-y",
        "-ss",
        f"{max(t, 0):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        f"scale={WIDTH}:-2",
        str(out),
    )


def stable_time(video, t):
    """The time of the last stable frame at or before t."""
    recent = [c for c in scene_changes(video, SCENE_RECENT, max(t - LOOKBACK, 0), LOOKBACK) if c <= t]
    return min(recent) - 0.5 if recent else t - 0.5


def cmd_at(a):
    grab(a.video, stable_time(a.video, a.seconds), a.out)
    print(a.out)


def cmd_commands(a):
    a.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for m in json.loads(a.chat.read_text()):
        if m["command"] is None or m["t"] < 0:
            continue
        png = a.out_dir / f"cmd_{m['at'].replace(':', '-')}.png"
        grab(a.video, stable_time(a.video, m["t"]), png)
        rows.append({**{k: m[k] for k in ("t", "at", "sender", "command")}, "frame": png.name})
    (a.out_dir / "commands.json").write_text(json.dumps(rows, indent=1))
    print(f"{len(rows)} command frames -> {a.out_dir}/commands.json")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("at")
    s.add_argument("video", type=Path)
    s.add_argument("seconds", type=float)
    s.add_argument("out", type=Path)
    s.set_defaults(fn=cmd_at)
    s = sub.add_parser("commands")
    s.add_argument("video", type=Path)
    s.add_argument("chat", type=Path)
    s.add_argument("out_dir", type=Path)
    s.set_defaults(fn=cmd_commands)
    a = p.parse_args()
    try:
        a.fn(a)
    except subprocess.CalledProcessError as e:
        sys.exit(f"ffmpeg failed: {' '.join(e.cmd)}\n{e.stderr[-2000:]}")


if __name__ == "__main__":
    main()

"""Review: re-check the passages of a Lumen transcript that look misheard, with whisper.

Lumen's speech model is fast but mishears technical terms, units and numbers, and it can't
be given a vocabulary. So after it, this step finds the chunks that look wrong and has
faster-whisper, which can take a vocabulary prompt, transcribe just those again:

- One call to a Lumen chat model flags lines that look misheard: a non sequitur, a garbled
  term, an implausible unit. Its guesses at the right words are often wrong, so they're
  only used to pick what to re-check, never as corrections.
- If Zoom made its own transcript (play_info.json's `transcriptList`), it's compared with
  ours chunk by chunk, and chunks where the two disagree on numbers or on several real
  words are flagged too. That catches what reads fine but is wrong ("45" for "40"). Only
  Zoom's text is used: its speaker labels are the account that spoke, and at in-person
  meetings one account carries a whole room.

Whisper re-transcribes whole chunks, which asr.py cut at pauses, so each one's text swaps
in cleanly. The vocabulary prompt is TRANSCRIBE_PROMPT plus the names on the team roster.
The transcript Lumen made is kept as transcript.granite.*, and review.json records what
was flagged and what changed."""

import difflib
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import asr
from .config import Config
from .errors import StepError

FILLERS = set(
    "um uh ah er like so yeah okay ok oh the a an and or but of to in on is it its i you we that this".split()
)
TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+")
# Disagreeing with Zoom on this many real words in one chunk is worth a re-check.
ZOOM_WORDS = 3

FLAG_PROMPT = """Below is a machine transcript of an ASPEN-NET meeting ($series). ASPEN-NET is a \
quantum-networking research collaboration. People who may be mentioned: $names.

The speech recogniser sometimes mishears technical terms, names, units and numbers. List \
every line where a word or phrase looks misheard: a non sequitur, a garbled technical term \
or name, or an implausible number or unit for what's being discussed. Don't flag ordinary \
disfluency (um, like, false starts, repeated words).

Answer with JSON only:
{"suspects": [{"at": "H:MM:SS", "heard": "<the suspicious words, exactly as written>", \
"why": "<a few words>"}]}

Transcript:
$transcript"""


def tokens(text: str) -> list[str]:
    """Words for comparing transcripts: lowercase, hyphens split, fillers dropped."""
    return [t for t in TOKEN.findall(text.lower().replace("-", " ")) if t not in FILLERS]


def _secs(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def zoom_words(play_info: dict) -> list[tuple[float, str]]:
    """Zoom's transcript as timed words, each line's spread evenly over its span."""
    out = []
    for row in play_info.get("transcriptList") or []:
        a, b = _secs(row["ts"]), _secs(row.get("end_ts") or row["ts"])
        words = tokens(row.get("text") or "")
        for k, w in enumerate(words):
            out.append((a + (b - a) * (k + 0.5) / len(words), w))
    return out


def zoom_disagreements(
    spans: list[tuple[float, float]], texts: list[str], zoom: list[tuple[float, str]], slop: float = 1.5
) -> dict[int, str]:
    """Chunks where our transcript and Zoom's differ on a number or on ZOOM_WORDS real words.
    Words missing at a chunk's edges don't count: the two transcripts' timings differ."""
    out = {}
    for i, ((a, b), text) in enumerate(zip(spans, texts, strict=True)):
        ours = tokens(text)
        theirs = [w for t, w in zoom if a - slop <= t < b + slop]
        if not ours or not theirs:
            continue
        ops = difflib.SequenceMatcher(None, ours, theirs, autojunk=False).get_opcodes()
        numbers, words = [], 0
        for k, (op, i1, i2, j1, j2) in enumerate(ops):
            if op == "equal" or (op != "replace" and k in (0, len(ops) - 1)):
                continue
            mine, zooms = ours[i1:i2], theirs[j1:j2]
            if any(t[0].isdigit() for t in mine + zooms):
                numbers.append(f"{' '.join(mine) or '…'} / {' '.join(zooms) or '…'}")
            words += sum(len(t) >= 4 for t in mine + zooms)
        if numbers:
            out[i] = "numbers differ from Zoom's: " + "; ".join(numbers)
        elif words >= ZOOM_WORDS:
            out[i] = f"{words} words differ from Zoom's"
    return out


def _chat(cfg: Config, prompt: str) -> str:
    body = {"model": cfg.review_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    req = urllib.request.Request(
        f"{cfg.lumen_base_url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.lumen_api_key.get_secret_value()}",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise StepError(f"Lumen refused the review call: HTTP {e.code}: {e.read()[:300]!r}") from e
            err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError) as e:
            err = str(e)
        if attempt == 3:
            raise StepError(f"the review call to Lumen failed: {err}")
        time.sleep(10 * 2**attempt)
    raise AssertionError("unreachable")


def parse_suspects(answer: str) -> list[dict]:
    m = re.search(r"\{.*\}", answer, re.S)
    if not m:
        raise StepError(f"the review model didn't answer in JSON: {answer[:200]!r}")
    try:
        suspects = json.loads(m.group(0)).get("suspects") or []
    except json.JSONDecodeError as e:
        raise StepError(f"the review model's JSON didn't parse: {e}") from e
    return [
        s for s in suspects if isinstance(s, dict) and re.fullmatch(r"\d+:\d\d:\d\d", str(s.get("at", "")))
    ]


def chunk_for(suspect: dict, spans: list[tuple[float, float]], texts: list[str]) -> int:
    """The chunk a flagged line is in: by its time, or a neighbour if the words are there."""
    t = _secs(suspect["at"])
    i = next((k for k, (a, b) in enumerate(spans) if a <= t < b), len(spans) - 1)
    heard = set(tokens(suspect.get("heard", "")))
    if not heard:
        return i
    near = [k for k in (i, i - 1, i + 1) if 0 <= k < len(spans)]
    return max(near, key=lambda k: (len(heard & set(tokens(texts[k]))), k == i))


def vocabulary(cfg: Config, wd: Path) -> str:
    """Whisper's prompt: TRANSCRIBE_PROMPT, then the roster's names. Whisper reads only the
    end of a long prompt, so it's kept short."""
    names = []
    team = wd / "context" / "team.json"
    if team.exists():
        names = [u["name"] for u in json.loads(team.read_text())]
    parts = [cfg.asr_prompt.strip()] if cfg.asr_prompt.strip() else []
    if names:
        parts.append("People: " + ", ".join(names) + ".")
    return " ".join(parts)[-800:]


def recheck(cfg: Config, wd: Path, spans: list[tuple[float, float]], idxs: list[int], prompt: str) -> dict:
    """Whisper's segments for each chunk in idxs, timed in the recording."""
    from faster_whisper import WhisperModel  # the image has it; tests don't need it

    t0 = time.time()
    model = WhisperModel(
        cfg.whisper_model, device="cpu", compute_type="int8",
        cpu_threads=cfg.whisper_threads, download_root=str(cfg.data_dir / "hf"),
    )  # fmt: skip
    print(f"loaded {cfg.whisper_model} in {time.time() - t0:.0f}s", flush=True)
    out = {}
    tmp = wd / "asr" / "recheck.wav"
    for i in idxs:
        a, b = spans[i]
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
             "-i", str(wd / "meeting.wav"), "-ac", "1", "-ar", "16000", str(tmp)],
            check=True,
        )  # fmt: skip
        segs, _ = model.transcribe(
            str(tmp), language="en", beam_size=5, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False, initial_prompt=prompt or None,
        )  # fmt: skip
        timed = [(a + s.start, min(a + s.end, b), s.text.strip()) for s in segs if s.text.strip()]
        if timed:  # whisper hearing nothing where Lumen heard something: keep Lumen's
            out[i] = timed
    tmp.unlink(missing_ok=True)
    return out


def review(cfg: Config, wd: Path) -> None:
    if (wd / "review.json").exists():
        print("already reviewed")
        return
    if not cfg.review_enabled:
        print(f"review is off (REVIEW={cfg.review!r}, TRANSCRIBER={cfg.transcriber!r})")
        return
    chunks = asr.load_chunks(wd)
    if chunks is None:
        print("nothing to review: the transcript isn't from Lumen")
        return
    spans, texts = chunks
    total = spans[-1][1] if spans else 0.0
    why: dict[int, list[str]] = {}

    suspects = []
    if cfg.review_model:
        job = json.loads((wd / "job.json").read_text())
        team = wd / "context" / "team.json"
        names = ", ".join(u["name"] for u in json.loads(team.read_text())) if team.exists() else "(unknown)"
        prompt = (
            FLAG_PROMPT.replace("$series", job.get("series", ""))
            .replace("$names", names)
            .replace("$transcript", (wd / "transcript.txt").read_text())
        )
        t0 = time.time()
        suspects = parse_suspects(_chat(cfg, prompt))
        print(f"{cfg.review_model} flagged {len(suspects)} lines in {time.time() - t0:.0f}s", flush=True)
        for s in suspects:
            why.setdefault(chunk_for(s, spans, texts), []).append(
                f"{s.get('heard', '')!r}: {s.get('why', '')}"
            )
    else:
        print("no REVIEW_MODEL: skipping the model's read-through")

    play_info = wd / "play_info.json"
    zoom = zoom_words(json.loads(play_info.read_text())) if play_info.exists() else []
    if zoom:
        found = zoom_disagreements(spans, texts, zoom)
        print(f"Zoom's transcript disagrees in {len(found)} chunks", flush=True)
        for i, reason in found.items():
            why.setdefault(i, []).append(reason)

    # Numbers first, then the rest, until the re-check reaches its share of the meeting.
    order = sorted(why, key=lambda i: (not any("numbers" in r for r in why[i]), i))
    chosen, seconds = [], 0.0
    for i in order:
        a, b = spans[i]
        if seconds + (b - a) > cfg.review_max_share * total:
            continue
        chosen.append(i)
        seconds += b - a
    chosen.sort()
    print(f"re-checking {len(chosen)} of {len(spans)} chunks ({seconds:.0f}s, {seconds / max(total, 1):.0%})")

    replaced = recheck(cfg, wd, spans, chosen, vocabulary(cfg, wd)) if chosen else {}
    for ext in (".txt", ".srt"):
        kept = wd / f"transcript.granite{ext}"
        if not kept.exists():
            shutil.copy(wd / f"transcript{ext}", kept)
    asr.write(asr.assemble(spans, texts, replaced), wd / "transcript")
    (wd / "review.json").write_text(
        json.dumps(
            {
                "review_model": cfg.review_model,
                "zoom_transcript": bool(zoom),
                "suspects": suspects,
                "rechecked_seconds": round(seconds),
                "chunks": [
                    {
                        "chunk": i,
                        "at": asr._ts(spans[i][0]),
                        "why": why[i],
                        "lumen": texts[i],
                        "whisper": " ".join(t for _, _, t in replaced.get(i, [])) or None,
                    }
                    for i in sorted(why)
                ],
            },
            indent=1,
        )
    )
    changed = sum(1 for i in replaced if " ".join(t for _, _, t in replaced[i]).strip() != texts[i].strip())
    print(f"REVIEW_DONE: {len(replaced)} chunks re-transcribed, {changed} changed")

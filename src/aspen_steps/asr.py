"""Transcription on Lumen's speech model, in place of the skill's local whisper.

Lumen's ASR model (granite-speech) returns text only: no `verbose_json`, so no
timestamps. To get them back, the audio goes up in chunks of about ASR_CHUNK_SECONDS,
cut in silences where there are any, and each chunk's text is timed by where the
chunk sits in the recording. Within a chunk, sentences are spread over its span by
length. Timestamps are good to a chunk, roughly, which is enough for the summary's
references and for cutting off-the-record spans.

Writes transcript.txt and transcript.srt in the same format as the skill's
transcribe.py. Each chunk's text is kept in asr/ as it arrives, so a retried step
only sends the chunks it hasn't got yet."""

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from .config import Config
from .errors import StepError

SILENCE = re.compile(r"silence_(start|end): (-?[\d.]+)")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def duration(wav: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(out.stdout.strip())


def silences(wav: Path) -> list[float]:
    """The middle of every pause of 0.3 s or more."""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af",
         "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    mids, start = [], None
    for kind, t in SILENCE.findall(p.stderr):
        if kind == "start":
            start = max(float(t), 0.0)
        elif start is not None:
            mids.append((start + float(t)) / 2)
            start = None
    return mids


def cuts(total: float, pauses: list[float], target: float) -> list[tuple[float, float]]:
    """Chunks of at most `target` seconds, each ending in the last pause after half of it,
    or at `target` if there's none."""
    spans, at = [], 0.0
    while total - at > target:
        inside = [p for p in pauses if at + target / 2 <= p <= at + target]
        end = inside[-1] if inside else at + target
        spans.append((at, end))
        at = end
    if total - at > 0.2:
        spans.append((at, total))
    return spans


def _audio(wav: Path, start: float, end: float, tmp: Path) -> bytes:
    # To a file, not a pipe: piped WAV has no length in its header.
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
         "-i", str(wav), "-ac", "1", "-ar", "16000", str(tmp)],
        capture_output=True, check=True,
    )  # fmt: skip
    try:
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


def _post(cfg: Config, audio: bytes) -> str:
    boundary = uuid.uuid4().hex
    fields = [("model", cfg.lumen_asr_model), ("response_format", "json")]
    if cfg.asr_prompt:
        fields.append(("prompt", cfg.asr_prompt))
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields
    )
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="chunk.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode()
    body += audio + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{cfg.lumen_base_url}/audio/transcriptions",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {cfg.lumen_api_key.get_secret_value()}",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["text"].strip()


def _transcribe_chunk(cfg: Config, wav: Path, cache: Path, i: int, span: tuple[float, float]) -> str:
    done = cache / f"{i:05}.txt"
    if done.exists():
        return done.read_text()
    audio = _audio(wav, *span, cache / f"{i:05}.wav")
    for attempt in range(4):
        try:
            text = _post(cfg, audio)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code < 500 and e.code != 429:
                raise StepError(f"Lumen ASR refused chunk {i}: HTTP {e.code}: {detail}") from e
            err = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError) as e:
            err = str(e)
        if attempt == 3:
            raise StepError(f"Lumen ASR failed on chunk {i} at {timedelta(seconds=int(span[0]))}: {err}")
        time.sleep(5 * 2**attempt)
    done.write_text(text)
    return text


def segments(text: str, start: float, end: float) -> list[tuple[float, float, str]]:
    """A chunk's text as sentences, each given a share of the chunk's span by its length."""
    parts = [s.strip() for s in SENTENCE.split(text) if s.strip()]
    total = sum(len(p) for p in parts) or 1
    out, at = [], start
    for p in parts:
        nxt = at + (end - start) * len(p) / total
        out.append((at, nxt, p))
        at = nxt
    return out


def _ts(s: float) -> str:
    return str(timedelta(seconds=int(s)))


def _srt_ts(s: float) -> str:
    ms = round(s * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


def write(segs: list[tuple[float, float, str]], out_base: Path) -> int:
    txt = "".join(f"[{_ts(a)}] {t}\n" for a, _, t in segs)
    srt = "".join(f"{n}\n{_srt_ts(a)} --> {_srt_ts(b)}\n{t}\n\n" for n, (a, b, t) in enumerate(segs, 1))
    # Renamed into place last: the step skips itself once transcript.srt exists.
    for ext, content in ((".txt", txt), (".srt", srt)):
        part = out_base.with_name(out_base.name + ext + ".part")
        part.write_text(content)
        part.replace(out_base.with_name(out_base.name + ext))
    return len(segs)


def transcribe(cfg: Config, wd: Path) -> None:
    if not cfg.lumen_api_key.get_secret_value():
        raise StepError("TRANSCRIBER=lumen needs LUMEN_API_KEY")
    if not cfg.lumen_asr_model:
        raise StepError("TRANSCRIBER=lumen needs LUMEN_ASR_MODEL (e.g. granite-speech-4.1-2b-plus)")
    wav = wd / "meeting.wav"
    t0 = time.time()
    total = duration(wav)
    spans = cuts(total, silences(wav), cfg.asr_chunk_seconds)
    cache = wd / "asr"
    cache.mkdir(exist_ok=True)
    print(f"{len(spans)} chunks over {_ts(total)}, {cfg.asr_concurrency} at a time, to {cfg.lumen_asr_model}")
    with ThreadPoolExecutor(cfg.asr_concurrency) as pool:
        texts = list(pool.map(lambda a: _transcribe_chunk(cfg, wav, cache, *a), enumerate(spans)))
    segs = [s for (a, b), t in zip(spans, texts, strict=True) for s in segments(t, a, b)]
    n = write(segs, wd / "transcript")
    el = time.time() - t0
    speed = f"{el / 60:.1f} min, {total / el:.1f}x realtime"
    print(f"LUMEN_ASR_DONE: {n} segments from {len(spans)} chunks in {speed}")

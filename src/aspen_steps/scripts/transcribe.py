"""Transcribe a WAV file with whisper, locally (default) or on a remote server.

Usage: python transcribe.py <wav> <model_name> <out_base>
  e.g. python transcribe.py meeting.wav large-v3-turbo transcript
Produces <out_base>.txt (timestamped lines) and <out_base>.srt.

Local (default): faster-whisper on the CPU. large-v3-turbo is the sweet spot
for CPU int8 — ~9x realtime on a 4-core box, near-large-v3 accuracy. Drop to
'medium' or 'small' if memory/CPU is tighter. TRANSCRIBE_THREADS sets
cpu_threads (default 4); match it to the cores you have.

Remote: set TRANSCRIBE_URL to an OpenAI-compatible base URL (e.g.
https://host/v1). The audio goes to <url>/audio/transcriptions as 32 kbps mono
MP3 (~14 MB per hour), and the server must return verbose_json with segment
timestamps. <model_name> is then ignored in favour of:
  TRANSCRIBE_MODEL    the server's model id (required), e.g. openai/whisper-large-v3-turbo
  TRANSCRIBE_API_KEY  sent as a Bearer token, if set
  TRANSCRIBE_PROMPT   optional vocabulary hint (names, jargon), both backends
"""
import os, sys, time, datetime, json, subprocess, tempfile, uuid, urllib.request, urllib.error

# Keep the ~1.6GB whisper model with the other models in <tools>/hf rather
# than ~/.cache, which may be small or quota-limited. HF_HOME overrides.
TOOLS = os.environ.get("MEETING_TOOLS_DIR") or os.path.dirname(sys.prefix)
os.environ.setdefault("HF_HOME", os.path.join(TOOLS, "hf"))

PROMPT = os.environ.get("TRANSCRIBE_PROMPT") or None


def local_segments(wav, model_name):
    """Yields (start, end, text) from faster-whisper on the CPU."""
    from faster_whisper import WhisperModel

    threads = int(os.environ.get("TRANSCRIBE_THREADS", "4"))
    print(f"loading {model_name} (int8, {threads} threads)...", flush=True)
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads)
    print("loaded, transcribing...", flush=True)
    segments, info = model.transcribe(
        wav, beam_size=5, vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=False, initial_prompt=PROMPT,
    )
    print(f"lang={info.language} ({info.language_probability:.2f}) dur={info.duration:.0f}s", flush=True)
    for seg in segments:
        yield seg.start, seg.end, seg.text


def _multipart(fields, file_field, filename, data, content_type):
    b = uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n".encode() + data + b"\r\n")
    return b"".join(parts) + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def remote_segments(wav, url):
    """Returns (start, end, text) from an OpenAI-compatible /audio/transcriptions."""
    model = os.environ.get("TRANSCRIBE_MODEL")
    if not model:
        sys.exit("TRANSCRIBE_URL is set but TRANSCRIBE_MODEL isn't")
    with tempfile.TemporaryDirectory() as d:
        mp3 = os.path.join(d, "audio.mp3")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-ac", "1", "-ar", "16000",
                        "-c:a", "libmp3lame", "-b:a", "32k", mp3], check=True)
        audio = open(mp3, "rb").read()
    fields = [("model", model), ("response_format", "verbose_json"),
              ("timestamp_granularities[]", "segment")] + ([("prompt", PROMPT)] if PROMPT else [])
    body, ctype = _multipart(fields, "file", "audio.mp3", audio, "audio/mpeg")
    req = urllib.request.Request(url.rstrip("/") + "/audio/transcriptions", data=body,
                                 headers={"Content-Type": ctype, "Accept": "application/json"})
    if key := os.environ.get("TRANSCRIBE_API_KEY"):
        req.add_header("Authorization", f"Bearer {key}")
    print(f"sending {len(audio) / 1e6:.1f} MB to {url} ({model})...", flush=True)
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"transcription server: HTTP {e.code} {e.read()[:500].decode(errors='replace')}")
    segs = out.get("segments")
    if not segs:
        sys.exit("transcription server returned no segments; it must support "
                 "response_format=verbose_json with segment timestamps")
    print(f"lang={out.get('language', '?')} dur={out.get('duration', 0):.0f}s", flush=True)
    return [(s["start"], s["end"], s["text"]) for s in segs]


def ts(s):
    return str(datetime.timedelta(seconds=int(s)))

def srt_ts(s):
    h, r = divmod(s, 3600); m, r = divmod(r, 60); sec = int(r)
    return f"{int(h):02}:{int(m):02}:{sec:02},{int((r-sec)*1000):03}"


def main():
    wav, model_name, out_base = sys.argv[1], sys.argv[2], sys.argv[3]
    url = os.environ.get("TRANSCRIBE_URL")
    t0 = time.time()
    segments = remote_segments(wav, url) if url else local_segments(wav, model_name)

    # Written as .part and renamed at the end, so a failed run never leaves a
    # transcript that looks finished (callers skip transcription if it exists).
    txt, srt = open(out_base + ".txt.part", "w"), open(out_base + ".srt.part", "w")
    n = 0
    for start, end, text in segments:
        n += 1
        line = text.strip()
        txt.write(f"[{ts(start)}] {line}\n"); txt.flush()
        srt.write(f"{n}\n{srt_ts(start)} --> {srt_ts(end)}\n{line}\n\n"); srt.flush()
        if n % 50 == 0:
            el = time.time() - t0
            print(f"  seg {n} @ {ts(start)} | {el/60:.1f}min | {end/el:.1f}x realtime", flush=True)
    txt.close(); srt.close()
    os.replace(out_base + ".txt.part", out_base + ".txt")
    os.replace(out_base + ".srt.part", out_base + ".srt")
    print(f"WHISPER_DONE: {n} segments in {(time.time()-t0)/60:.1f} min ({'remote' if url else 'local'})", flush=True)


if __name__ == "__main__":
    main()

"""Fallback: build a clean, timestamped paragraph transcript straight from
the Whisper .srt, with no speaker labels. Use this when qc_diarization.py
fails and speaker attribution can't be trusted.

Usage: python clean_transcript.py <transcript.srt> <out.md> [window_seconds]
window_seconds groups consecutive segments into a paragraph until that many
seconds of audio have accumulated (default 45).
"""
import datetime, re, sys

srt_path = sys.argv[1] if len(sys.argv) > 1 else "transcript.srt"
out = sys.argv[2] if len(sys.argv) > 2 else "transcript-clean.md"
window = float(sys.argv[3]) if len(sys.argv) > 3 else 45.0

def ts(s):
    return str(datetime.timedelta(seconds=int(s)))

def p(t):
    h, mn, rest = t.split(":"); s, ms = rest.split(",")
    return int(h)*3600 + int(mn)*60 + int(s) + int(ms)/1000

blocks, cur = [], []
for line in open(srt_path):
    line = line.rstrip("\n")
    if line == "":
        if len(cur) >= 3:
            m = re.match(r"(\S+) --> (\S+)", cur[1])
            blocks.append((p(m.group(1)), " ".join(cur[2:]).strip()))
        cur = []
    else:
        cur.append(line)

out_blocks, buf, start = [], [], None
for st, text in blocks:
    if start is None:
        start = st
    buf.append(text)
    if st - start >= window:
        out_blocks.append((start, " ".join(buf)))
        buf, start = [], None
if buf:
    out_blocks.append((start or 0, " ".join(buf)))

with open(out, "w") as f:
    for s, t in out_blocks:
        f.write(f"`{ts(s)}` {t}\n\n")
print(f"CLEAN_DONE: {len(out_blocks)} paragraphs -> {out}", flush=True)

#!/usr/bin/env python3
"""Extract the in-meeting chat from play_info.json, timed against the video.

Usage: chat.py <play_info.json> <out_dir>

Writes into <out_dir>:
  chat.json   [{t, at, sender, text, command}], sorted by time
  chat.md     the same as a readable list, for the summary's Chat section

`t` is seconds into the recording: (message `time` - `fileStartTime`) / 1000.
Don't use Zoom's `timeFromMeetingStart`, which counts from when the meeting
opened, not from when recording began (~334 s earlier on 2026-10-23).
Messages sent before recording started get a negative `t` and are kept.

`command` holds the text after an `ai:` prefix (case-insensitive, leading
spaces ignored), else null. Only the prefix is matched here; what a command
asks for ("screenshot", "snap", "note ...", "off record") is left to whoever
reads chat.json, since people won't use one fixed vocabulary.

Sender names come from Zoom, so they're reliable attribution, unlike
diarization. Only messages sent to everyone are in the recording.
"""
import json
import re
import sys
from pathlib import Path

COMMAND = re.compile(r"^\s*ai\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)


def hms(t):
    sign, t = ("-" if t < 0 else ""), abs(int(t))
    return f"{sign}{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}"


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    info = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)

    start = info["fileStartTime"]
    messages = []
    for m in info.get("xmppList") or []:
        if m.get("deleted"):
            continue
        text = (m.get("content") or "").strip()
        t = round((m["time"] - start) / 1000, 1)
        cmd = COMMAND.match(text)
        messages.append({
            "t": t,
            "at": hms(t),
            "sender": m.get("senderName"),
            "text": text,
            "command": cmd.group(1).strip() if cmd else None,
        })
    messages.sort(key=lambda m: m["t"])

    (out / "chat.json").write_text(json.dumps(messages, indent=1))
    lines = [f"- `{m['at']}` **{m['sender']}**: {m['text']}" for m in messages]
    (out / "chat.md").write_text("\n".join(lines) + ("\n" if lines else ""))

    n_cmd = sum(1 for m in messages if m["command"] is not None)
    print(f"{len(messages)} chat messages, {n_cmd} ai: commands -> {out}/chat.json")


if __name__ == "__main__":
    main()

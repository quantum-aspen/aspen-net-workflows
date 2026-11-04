"""The recording page: how people hand a meeting to the workflow.

Someone creates a page under a meeting series in the Meetings collection (from the
"Meeting recording" template), pastes the Zoom share link, adds `passcode: …` if the
recording has one, and ticks the box:

    https://illinois.zoom.us/rec/share/…
    passcode: …

    - [x] Ready to transcribe

The poller claims the page: it takes the passcode off, and swaps the ticked box for a
status callout that the steps keep current. When the summary is published it replaces
the page, so the page people made becomes the meeting's summary. If a run fails, the
callout says why and an unticked box comes back; ticking it again retries.
"""

import re
from dataclasses import dataclass

FLAG_TEXT = "Ready to transcribe"
FLAG = re.compile(rf"^[ \t]*[-*][ \t]+\[(?P<mark>[ xX])\][ \t]+{FLAG_TEXT}\b.*$", re.M | re.I)
# Its own line, optionally bulleted or bold, with an optional note in brackets:
# "passcode: x", "- **Passcode:** `x`", "* Passcode (optional): x". Not a sentence that
# mentions one, like the template's instructions.
# Spaces are any but newlines: Outline leaves no-break spaces around what people type.
PASSCODE = re.compile(
    r"^[^\S\n]*(?:[-*][^\S\n]+)?\**pass(?:code|word)\**(?:[^\S\n]*\([^)\n]*\))?\**[^\S\n]*[:=]"
    r"[^\S\n]*\**[^\S\n]*(?P<code>\S*)[^\S\n]*$\n?",
    re.M | re.I,
)
# What the template puts where the passcode goes, left as it was when there isn't one.
PLACEHOLDER = re.compile(r"pass(?:code|word)\??|…|\.\.\.|<code>", re.I)
# No backslash: Outline writes a Shift+Enter line break as a trailing `\`.
LINK = re.compile(r"https://[\w.-]*zoom\.us/rec/(?:share|play)/[^\s)\]>\\]+")
# A markdown link's target, which Outline's formatting (`[__url__](url)`) never touches.
HREF = re.compile(rf"\]\((?P<url>{LINK.pattern})\)")
# Outline's markdown backslash-escapes punctuation it could read as syntax ($, #, *, …).
ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
# Outline gives a callout back with blank lines inside its fences (`\n\n:::`), so allow them.
STATUS = re.compile(
    r"^:::(?P<kind>\w+)[ \t]*\n(?:[ \t]*\n)*[ \t]*\*\*Transcription:\*\*[ \t]*(?P<text>.*?)[ \t]*\n"
    r"(?:[ \t]*\n)*:::[ \t]*$",
    re.M,
)


@dataclass(frozen=True)
class RecordingPage:
    link: str | None
    passcode: str
    ticked: bool
    status: str | None

    @property
    def ready(self) -> bool:
        return bool(self.link) and self.ticked


def _passcode(raw: str) -> str:
    """The passcode as typed, from Outline's markdown of it."""
    if (len(raw) - len(raw.rstrip("\\"))) % 2:  # an odd one out is a Shift+Enter line break
        raw = raw[:-1]
    code = ESCAPE.sub(r"\1", raw.strip("`*_"))
    return "" if PLACEHOLDER.fullmatch(code) else code


def parse(text: str) -> RecordingPage:
    href = HREF.search(text)
    link = href.group("url") if href else (m.group(0) if (m := LINK.search(text)) else None)
    code = PASSCODE.search(text)
    flag = FLAG.search(text)
    status = STATUS.search(text)
    return RecordingPage(
        link=link,
        passcode=_passcode(code.group("code")) if code else "",
        ticked=bool(flag) and flag.group("mark").lower() == "x",
        status=status.group("text") if status else None,
    )


def _callout(status: str, kind: str) -> str:
    status = " ".join(status.split())  # one line, or STATUS can't find it again
    return f":::{kind}\n**Transcription:** {status}\n:::"


def claim(text: str, status: str) -> tuple[str, str]:
    """Takes the passcode off the page and swaps the ticked box for a status callout.
    Returns the new text and the passcode ("" if none). The passcode stays in the page's
    history, as it did with the old inbox doc."""
    passcode = parse(text).passcode
    text = PASSCODE.sub("", text)
    text = STATUS.sub("", text)
    text = FLAG.sub(lambda _: _callout(status, "info"), text, count=1)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n", passcode


def set_status(text: str, status: str, *, failed: bool = False) -> str:
    """Rewrites the status callout. A failure also puts back an unticked box to retry with."""
    block = _callout(status, "warning" if failed else "info")
    if failed:
        block += f"\n\n- [ ] {FLAG_TEXT}"
        text = FLAG.sub("", text)
    if STATUS.search(text):
        # Replace the first, and drop any others: before Outline's blank lines were allowed
        # for, each update added a callout instead of replacing one.
        first = iter([block])
        text = STATUS.sub(lambda _: next(first, ""), text)
    else:
        text = text.rstrip() + "\n\n" + block
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"

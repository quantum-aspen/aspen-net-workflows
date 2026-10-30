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
# Its own line, optionally bulleted or bold: "passcode: x", "- **Passcode:** `x`". Not a
# sentence that mentions one, like the template's instructions.
PASSCODE = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?\**pass(?:code|word)\**[ \t]*[:=][ \t]*\**[ \t]*(?P<code>\S*)[ \t]*$\n?",
    re.M | re.I,
)
LINK = re.compile(r"https://[\w.-]*zoom\.us/rec/(?:share|play)/[^\s)\]>]+")
STATUS = re.compile(
    r"^:::(?P<kind>\w+)[ \t]*\n[ \t]*\*\*Transcription:\*\*[ \t]*(?P<text>.*?)[ \t]*\n:::[ \t]*$", re.M
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


def parse(text: str) -> RecordingPage:
    link = LINK.search(text)
    code = PASSCODE.search(text)
    flag = FLAG.search(text)
    status = STATUS.search(text)
    return RecordingPage(
        link=link.group(0) if link else None,
        passcode=code.group("code").strip("`*_") if code else "",
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
        text = STATUS.sub(lambda _: block, text, count=1)
    else:
        text = text.rstrip() + "\n\n" + block
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"

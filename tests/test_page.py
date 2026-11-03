import pytest

from aspen_steps import page

LINK = "https://illinois.zoom.us/rec/share/abc_DEF-123.xyz"
PAGE = f"""Paste the link, then tick the box.

{LINK}
passcode: Fx7#k2

- [x] Ready to transcribe
"""


def test_parse_ticked_page():
    p = page.parse(PAGE)
    assert p.link == LINK
    assert p.passcode == "Fx7#k2"
    assert p.ticked and p.ready
    assert p.status is None


def test_instructions_mentioning_a_passcode_arent_one():
    text = f"If it has a passcode, add a line `passcode: …`. Then tick the box.\n\n{LINK}\npasscode:\n"
    p = page.parse(text)
    assert p.passcode == ""
    claimed, _ = page.claim(text + "\n- [x] Ready to transcribe\n", "queued")
    assert "add a line `passcode: …`" in claimed  # the instructions stay


def test_unticked_or_linkless_pages_arent_ready():
    assert not page.parse(PAGE.replace("[x]", "[ ]")).ready
    assert not page.parse(PAGE.replace(LINK, "no link yet")).ready


def test_outline_autolinked_url_and_bold_passcode():
    p = page.parse(f"[{LINK}]({LINK})\n**Passcode:** `abc`\n\n- [X] ready to transcribe\n")
    assert p.link == LINK
    assert p.passcode == "abc"
    assert p.ready


def test_claim_strips_passcode_and_replaces_the_box():
    text, passcode = page.claim(PAGE, "queued")
    assert passcode == "Fx7#k2"
    assert "Fx7#k2" not in text
    assert "Ready to transcribe" not in text
    assert LINK in text
    p = page.parse(text)
    assert p.status == "queued"
    assert not p.ready  # claimed pages aren't claimed twice


def test_status_updates_in_place():
    text, _ = page.claim(PAGE, "queued")
    text = page.set_status(text, "working: transcribing")
    assert page.parse(text).status == "working: transcribing"
    assert text.count("**Transcription:**") == 1


def test_failure_brings_back_an_unticked_box_and_retick_is_ready():
    text, _ = page.claim(PAGE, "queued")
    text = page.set_status(text, r"failed: odd \1 chars. Tick the box to try again.", failed=True)
    p = page.parse(text)
    assert p.status.startswith(r"failed: odd \1 chars")
    assert ":::warning" in text
    assert not p.ready
    retick = text.replace("- [ ] Ready", "- [x] Ready")
    assert page.parse(retick).ready
    again, _ = page.claim(retick, "queued")
    assert again.count("**Transcription:**") == 1
    assert page.parse(again).status == "queued"


# A Zoom share as people paste it: a "Link:" line with the recording's title, then the passcode.
ZOOM = "https://example.zoom.us/rec/share/Qx3vN8_fakeRecordingToken-a1B2c3D4e5F6g7H8j9K0.mN4pQ7rS1tU5vW2x"
TITLE = "Link: Jan 1 2026 - Test Speaker - Example Talk (TEST) "


@pytest.mark.parametrize(
    "pasted",
    [
        f"{TITLE}{ZOOM}\nPasscode: Q9$7ZKP#",  # as typed
        f"{TITLE}{ZOOM}\n\nPasscode: Q9$7ZKP#",  # Enter: separate paragraphs
        f"{TITLE}{ZOOM}\\\nPasscode: Q9$7ZKP#\\",  # Shift+Enter: Outline's hard breaks
        f"{TITLE}[{ZOOM}]({ZOOM})\nPasscode: Q9\\$7ZKP\\#",  # autolinked, punctuation escaped
    ],
)
def test_a_pasted_zoom_share(pasted):
    text = f"{pasted}\n\n- [x] Ready to transcribe\n"
    p = page.parse(text)
    assert p.link == ZOOM
    assert p.passcode == "Q9$7ZKP#"
    assert p.ready
    claimed, passcode = page.claim(text, "queued")
    assert passcode == "Q9$7ZKP#"
    assert "7ZKP" not in claimed
    assert "Example Talk (TEST)" in claimed


def test_an_escaped_backslash_in_a_passcode_survives():
    assert page.parse(f"{ZOOM}\npasscode: a\\\\b\\\\\n").passcode == "a\\b\\"


# The wiki's Meeting recording template, as Outline's API returns it.
WIKI_TEMPLATE = (
    ":::info\nYou can include any other relevant info below then check the “Ready to transcribe” box\n\n:::"
    "\n\n\n* Zoom Link: zoom link\n* Passcode (optional): passcode?\n\n  \\\n\n"
    "- [ ] Ready to transcribe\n\n\n\\"
)


def test_the_wiki_template_untouched_isnt_ready_and_has_no_passcode():
    p = page.parse(WIKI_TEMPLATE.replace("[ ]", "[x]"))
    assert p.passcode == ""
    assert not p.ready  # no link


def test_the_wiki_template_filled_in():
    text = (
        WIKI_TEMPLATE.replace("zoom link", f"[{ZOOM}]({ZOOM})")
        .replace("passcode?", "Q9\\$7ZKP\\#")
        .replace("[ ]", "[x]")
    )
    p = page.parse(text)
    assert p.link == ZOOM and p.ready
    assert p.passcode == "Q9$7ZKP#"
    claimed, _ = page.claim(text, "queued")
    assert "7ZKP" not in claimed and "Passcode (optional)" not in claimed
    assert "any other relevant info" in claimed  # their callout stays
    assert page.parse(claimed).status == "queued"


def test_a_filled_in_template_without_a_passcode():
    text = WIKI_TEMPLATE.replace("zoom link", ZOOM).replace("[ ]", "[x]")
    p = page.parse(text)
    assert p.ready and p.passcode == ""
    claimed, _ = page.claim(text, "queued")
    assert "passcode?" not in claimed  # the unused placeholder line goes too


def test_the_test_meeting_page_as_outline_returned_it():
    # Shape of a real filled-in template: underlined link text, and a no-break space
    # after the passcode. (Values are made up.)
    text = (
        WIKI_TEMPLATE.replace("zoom link", f"[__{ZOOM}__]({ZOOM})")
        .replace("passcode?", "a.b&cde$ ")
        .replace("[ ]", "[x]")
    )
    p = page.parse(text)
    assert p.link == ZOOM
    assert p.passcode == "a.b&cde$"
    claimed, _ = page.claim(text, "queued")
    assert "cde$" not in claimed

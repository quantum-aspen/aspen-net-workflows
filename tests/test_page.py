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

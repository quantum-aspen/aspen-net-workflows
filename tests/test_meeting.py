"""The steps' own logic, on a checked-in work dir. What they do against the wiki is tried
with a dry run on the real one (README: Development)."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import SecretStr

from aspen_steps import check, meeting
from aspen_steps.config import Config
from aspen_steps.outline import Outline

WORK = Path(__file__).parent / "fixtures" / "work"
GINA = "7a1e3f20-0c4b-4f0e-9a51-3b6d2e8c1f01"


def _agent_output(wd: Path, **over) -> None:
    """What a good agent run leaves in out/, with any field replaced."""
    url = json.loads((wd / "job.json").read_text())["url"]
    (wd / "out").mkdir(exist_ok=True)
    (wd / "out" / "summary.md").write_text(
        over.pop("summary", None)
        or f"| **Recording** | {url} |\n\n## Summary\n\nAttended by @[Gina Lorenz](mention://user/{GINA}).\n\n"
        "![ZeroMQ proposal — screenshot requested by Gina Lorenz (0:39)](frames/cmd_0-00-39.png)\n"
    )
    result = {
        "title": "Detector data over ZeroMQ",
        "date": "2026-10-27",
        "attendees": ["Gina Lorenz", "Marcos Frenkel", "Krister Shalm"],
        "corrections": [{"heard": "time tiger", "means": "Time Tagger"}],
        "off_record": [[55, 62]],
        "series_row": {
            "Date": "2026-10-27",
            "Summary": "[2026-10-27 Detector data over ZeroMQ]({{page_url}})",
        },
    } | over
    (wd / "out" / "result.json").write_text(json.dumps(result))


@pytest.fixture
def wd(tmp_path):
    wd = tmp_path / "work"
    shutil.copytree(WORK, wd)
    _agent_output(wd)
    return wd


def test_good_output_passes_the_checks(wd):
    result, summary = check.load(wd)
    assert check.problems(wd, result, summary, mentions=True) == []


@pytest.mark.parametrize(
    ("over", "expect"),
    [
        ({"date": "2026-10-30"}, "isn't the recording date"),
        ({"title": "2026-10-27 Detector data"}, "starts with a date"),
        ({"summary": "# Big title\n\nno link"}, "has an H1"),
        (
            {"summary": "!!Topic!! https://illinois.zoom.us/rec/share/SYNTHETIC-fixture-recording"},
            "placeholders",
        ),
        ({"series_row": {"Speaker": "x"}}, "columns the series table doesn't"),
        (
            {
                "summary": "@[X](mention://user/nobody) https://illinois.zoom.us/rec/share/SYNTHETIC-fixture-recording"
            },
            "aren't in context/team.json",
        ),
        (
            {
                "summary": "![x](frames/nope.png) https://illinois.zoom.us/rec/share/SYNTHETIC-fixture-recording"
            },
            "doesn't exist",
        ),
    ],
)
def test_bad_output_is_caught(wd, over, expect):
    _agent_output(wd, **over)
    result, summary = check.load(wd)
    found = check.problems(wd, result, summary, mentions=True)
    assert any(expect in p for p in found), found


def test_agent_gets_its_check_failures_back_once(wd, monkeypatch):
    prompts = []

    def sloppy_then_fixed(cfg, prompt, wd, **_):
        prompts.append(prompt)
        _agent_output(wd, date="2026-10-30" if len(prompts) == 1 else "2026-10-27")
        return 0

    monkeypatch.setattr(meeting.agent, "run", sloppy_then_fixed)
    meeting.summarise(Config.from_env({}), wd)
    assert len(prompts) == 2
    assert "isn't the recording date 2026-10-27" in prompts[1]


def test_an_agent_that_wrote_nothing_gets_the_original_prompt_again(wd, monkeypatch):
    shutil.rmtree(wd / "out")
    prompts = []

    def crash_then_write(cfg, prompt, wd, **_):
        prompts.append(prompt)
        if len(prompts) == 2:
            _agent_output(wd)
        return 1 if len(prompts) == 1 else 0

    monkeypatch.setattr(meeting.agent, "run", crash_then_write)
    meeting.summarise(Config.from_env({}), wd)
    assert len(prompts) == 2 and prompts[1] == prompts[0]


def test_the_prompt_carries_the_files_the_agent_needs(wd):
    (wd / "transcript.txt").write_text("[0:00:39] Here's the ZeroMQ proposal.\n")
    (wd / "chat.md").write_text("0:00:39 Gina Lorenz: ai: screenshot the ZeroMQ proposal\n")
    text = meeting._prompt(Config.from_env({}), wd) + meeting._materials(Config.from_env({}), wd)
    assert "## `transcript.txt`" in text and "Here's the ZeroMQ proposal." in text
    assert "## `context/team.json`" in text and "Gina Lorenz" in text
    assert "## `frames/commands.json`\n\n(none: no screenshot requests)" in text
    assert "Don't read those files again" in text
    # The rules are the workflow's own, and the agent's frames.py is the bundled one.
    assert "## `summary-rules.md`" in text and "## `chat-commands.md`" in text
    assert "A name said near a line doesn't tell you who said it." in text
    frames_py = Config.from_env({}).scripts_dir / "frames.py"
    assert f"python3 {frames_py} at" in text and frames_py.exists()
    assert "outline MCP" not in text and "$" + "scripts" not in text


def test_off_record_spans_are_cut_from_the_transcript(wd):
    srt = meeting._srt_without((wd / "transcript.srt").read_text(), [(55, 62)])
    assert "coffee" not in srt
    assert "Agreed on ZeroMQ" in srt


def test_series_row_goes_after_the_last_row():
    series = (WORK / "context" / "series.md").read_text()
    text = meeting._insert_row(series + "\nMore text.\n", {"Date": "2026-10-27", "Summary": "[x](/doc/x)"})
    assert text.index("2026-10-20") < text.index("| 2026-10-27 | [x](/doc/x) |  |") < text.index("More text.")


def test_a_dry_run_never_sends_a_write(tmp_path, monkeypatch):
    sent = []
    page = {"id": "d1", "title": "New recording", "text": "old text\n", "url": "/doc/new-recording-d1"}

    def post(self, method, body):
        sent.append(method)
        return page if method == "documents.info" else []

    monkeypatch.setattr(Outline, "_post", post)
    monkeypatch.setattr(Outline, "_send", lambda *a: pytest.fail("a dry run sent a request"))
    out = tmp_path / "would-write"
    ol = Outline("https://wiki.example", SecretStr("k"), would_write=out)
    frame = tmp_path / "frame.png"
    frame.write_bytes(b"png")

    assert ol.upload("d1", frame) == "dry-run:frame.png"
    assert ol.update("d1", title="2026-10-27 Done", text="new text\n")["url"] == page["url"]
    assert sent == ["documents.info"]
    assert (out / "01 upload frame.png.txt").exists()
    assert (out / "02 update New recording.md").read_text() == "new text\n"
    diff = (out / "02 update New recording.diff").read_text()
    assert "-old text" in diff and "+new text" in diff and "+# 2026-10-27 Done" in diff


NEW_SERIES = "# Test Series\n\nWhere new recordings are tried out.\n"
ROW = {"Date": "2026-10-27", "Meeting": "[x](/doc/x)", "Key outcomes": "ZeroMQ agreed"}


def test_a_series_page_without_a_table_gets_one():
    text = meeting._insert_row(NEW_SERIES, ROW)
    assert text.startswith(NEW_SERIES.rstrip())
    assert "## Meetings\n\n| Date | Meeting | Key outcomes |\n|---|---|---|\n" in text
    assert text.rstrip().endswith("| 2026-10-27 | [x](/doc/x) | ZeroMQ agreed |")
    # and the next meeting goes into that table, not a second one
    again = meeting._insert_row(text, ROW | {"Date": "2026-11-05"})
    assert again.count("## Meetings") == 1 and again.count("| Date |") == 1


def test_without_a_table_the_agent_writes_a_row_for_the_one_to_come(wd):
    (wd / "context" / "series.md").write_text(NEW_SERIES)
    prompt = meeting._prompt(Config.from_env({}), wd)
    assert "['Date', 'Meeting', 'Key outcomes']" in prompt and "no table yet" in prompt
    _agent_output(wd, series_row=ROW)
    result, summary = check.load(wd)
    assert check.problems(wd, result, summary, mentions=True) == []
    _agent_output(wd, series_row={"Speaker": "x"})
    result, summary = check.load(wd)
    assert any(
        "columns the series table doesn't" in p for p in check.problems(wd, result, summary, mentions=True)
    )


class _Wiki:
    """The reads context makes, from a wiki with one series and one earlier summary."""

    def users(self):
        return [{"name": "Gina Lorenz", "id": GINA}]

    def document(self, doc_id):
        return {"title": "Test Series", "url": "/doc/test-series-bZcTFyOMgH", "text": "Purpose.\n"}

    def children(self, collection, parent):
        return [
            {
                "title": "2026-09-10 Earlier talk",
                "url": "/doc/2026-09-10-earlier-talk-Ab12Cd34Ef",
                "text": "Summary text.\n",
            }
        ]

    def templates(self, collection):
        return [{"title": "Meeting summary", "text": "| Series | *!!series page!!* |\n"}]


def test_context_gives_the_agent_real_page_addresses(wd, monkeypatch):
    monkeypatch.setattr(meeting, "outline", lambda cfg, *a: _Wiki())
    meeting.context(Config.from_env({}), wd)
    assert "/doc/test-series-bZcTFyOMgH" in (wd / "context" / "series.md").read_text()
    earlier = (wd / "context" / "earlier" / "2026-09-10 Earlier talk.md").read_text()
    assert "/doc/2026-09-10-earlier-talk-Ab12Cd34Ef" in earlier
    prompt = meeting._prompt(Config.from_env({}), wd)
    series = json.loads((wd / "job.json").read_text())["series"]
    assert f"[{series}](/doc/test-series-bZcTFyOMgH)" in prompt


def test_a_made_up_wiki_link_is_sent_back(wd, monkeypatch):
    monkeypatch.setattr(meeting, "outline", lambda cfg, *a: _Wiki())
    meeting.context(Config.from_env({}), wd)
    url = json.loads((wd / "job.json").read_text())["url"]
    for link, ok in [
        ("https://wiki.quantum-aspen.net/doc/test-series", False),  # what the first live run wrote
        ("/doc/test-series", False),
        ("/doc/test-series-bZcTFyOMgH", True),
        ("https://wiki.quantum-aspen.net/doc/2026-09-10-earlier-talk-Ab12Cd34Ef", True),
        ("https://docs.example.org/doc/anything", True),  # not the wiki's
    ]:
        _agent_output(wd, summary=f"| Series | [Test Series]({link}) |\n| **Recording** | {url} |\n")
        result, summary = check.load(wd)
        found = check.problems(wd, result, summary, mentions=True, wiki="https://wiki.quantum-aspen.net")
        assert any("isn't a page in the context" in p for p in found) != ok, (link, found)

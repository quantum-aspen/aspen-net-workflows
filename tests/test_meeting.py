import json
import shutil
from pathlib import Path

import pytest

from aspen_steps import check, meeting, page
from aspen_steps.__main__ import main
from aspen_steps.config import Config

FIXTURE = Path(__file__).parent.parent / "dev" / "fixture"


def test_poll_claims_only_ticked_pages_under_a_series(env, wiki, tmp_path):
    _, ids, st = wiki
    queued = meeting.poll(Config.from_env())
    assert queued == [ids["ready"]]
    assert (tmp_path / "dagu.log").read_text().split() == [
        "enqueue",
        "meeting",
        "--",
        f"DOC_ID={ids['ready']}",
    ]

    claimed = st.doc(ids["ready"])
    assert page.parse(claimed["text"]).status == "queued"
    assert "Fx7#k2" not in claimed["text"]
    wd = Path(env["DATA_DIR"]) / "work" / ids["ready"]
    assert (wd / ".passcode").read_text() == "Fx7#k2"
    assert (wd / ".passcode").stat().st_mode & 0o077 == 0
    job = json.loads((wd / "job.json").read_text())
    assert job["series"] == "Software stack meeting"
    # orphan and unticked pages are left alone
    assert page.parse(st.doc(ids["orphan"])["text"]).ready
    assert page.parse(st.doc(ids["unticked"])["text"]).status is None
    # and nothing is claimed twice
    assert meeting.poll(Config.from_env()) == []


def test_failed_enqueue_marks_the_page(env, wiki, tmp_path, monkeypatch):
    _, ids, st = wiki
    bad = tmp_path / "bad-dagu"
    bad.write_text("#!/bin/sh\necho 'no such dag' >&2\nexit 1\n")
    bad.chmod(0o755)
    monkeypatch.setenv("DAGU_BIN", str(bad))
    assert meeting.poll(Config.from_env()) == []
    p = page.parse(st.doc(ids["ready"])["text"])
    assert p.status.startswith("failed to queue")
    assert not p.ready


def _claimed(env, wiki) -> Path:
    _, ids, _ = wiki
    meeting.poll(Config.from_env())
    return Path(env["DATA_DIR"]) / "work" / ids["ready"]


def test_context_writes_what_the_agent_needs(env, wiki):
    wd = _claimed(env, wiki)
    assert main(["context", wd.name]) == 0
    ctx = wd / "context"
    team = json.loads((ctx / "team.json").read_text())
    assert {u["name"] for u in team} >= {"Gina Lorenz", "Marcos Frenkel"}
    assert "| Date | Summary | Topics |" in (ctx / "series.md").read_text()
    assert [p.name for p in (ctx / "earlier").iterdir()] == ["2026-10-20 Deployment pipeline.md"]
    assert "!!Action!!" in (ctx / "template.md").read_text()
    assert check.table_header((ctx / "series.md").read_text()) == ["Date", "Summary", "Topics"]


def _fake_agent_output(wd: Path, team: list[dict], **over) -> None:
    gina = next(u for u in team if u["name"] == "Gina Lorenz")
    (wd / "frames").mkdir(exist_ok=True)
    (wd / "frames" / "cmd_0-00-39.png").write_bytes(b"\x89PNG fake")
    job = json.loads((wd / "job.json").read_text())
    (wd / "out").mkdir(exist_ok=True)
    (wd / "out" / "summary.md").write_text(
        over.pop("summary", None)
        or f"| **Recording** | {job['url']} |\n\n## Summary\n\nAttended by @[Gina Lorenz](mention://user/{gina['id']}).\n\n"
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
def summarised(env, wiki):
    if not (FIXTURE / "meeting.wav").exists():
        pytest.skip("no fixture: run dev/make_fixture.py")
    wd = _claimed(env, wiki)
    for f in ("recording_datetime.txt", "chat.json"):
        shutil.copy(FIXTURE / f, wd / f)
    (wd / "transcript.srt").write_text(
        "1\n00:00:01,000 --> 00:00:05,000\nOkay, let's get started.\n\n"
        "2\n00:00:56,000 --> 00:01:00,000\nThe coffee machine is broken again.\n\n"
        "3\n00:01:05,000 --> 00:01:08,000\nAgreed on ZeroMQ.\n"
    )
    assert main(["context", wd.name]) == 0
    _fake_agent_output(wd, json.loads((wd / "context" / "team.json").read_text()))
    return wd


def test_good_output_passes_the_checks(summarised):
    result, summary = check.load(summarised)
    assert check.problems(summarised, result, summary, mentions=True) == []


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
def test_bad_output_is_caught(summarised, over, expect):
    team = json.loads((summarised / "context" / "team.json").read_text())
    _fake_agent_output(summarised, team, **over)
    result, summary = check.load(summarised)
    found = check.problems(summarised, result, summary, mentions=True)
    assert any(expect in p for p in found), found


def test_publish_turns_the_page_into_the_summary(summarised, env, wiki):
    _, ids, st = wiki
    assert main(["publish", summarised.name]) == 0
    doc = st.doc(ids["ready"])
    assert doc["title"] == "2026-10-27 Detector data over ZeroMQ"
    assert "Transcription:" not in doc["text"]
    assert "/api/attachments.redirect?id=" in doc["text"]
    assert "frames/cmd_" not in doc["text"]
    series = st.doc(ids["series"])["text"]
    assert f"[2026-10-27 Detector data over ZeroMQ]({doc['url']})" in series
    assert series.index("2026-10-20") < series.index("2026-10-27")  # appended after the last row
    folder = Path(env["DATA_DIR"]) / "meetings" / "2026-10-27 Detector data over ZeroMQ"
    transcript = (folder / "transcript.md").read_text()
    assert "coffee" not in transcript  # the off-record span is cut
    assert "Agreed on ZeroMQ" in transcript
    assert "| time tiger | **Time Tagger** |" in transcript
    assert (folder / "frames" / "cmd_0-00-39.png").exists()


def test_dry_run_writes_nothing_to_the_wiki(summarised, wiki, monkeypatch):
    _, ids, st = wiki
    before = json.dumps(st.data)
    monkeypatch.setenv("DRY_RUN", "1")
    assert main(["publish", summarised.name]) == 0
    assert main(["fail", summarised.name]) == 0
    assert json.dumps(st.data) == before
    assert (summarised / "out" / "page.md").read_text().startswith("# 2026-10-27 Detector data over ZeroMQ")


def test_agent_giving_up_lands_on_the_page(env, wiki, monkeypatch):
    _, ids, st = wiki
    wd = _claimed(env, wiki)
    assert main(["context", wd.name]) == 0

    def gives_up(cfg, prompt, wd, **_):
        (wd / "out" / "result.json").write_text('{"error": "the whole recording is off the record"}')
        return 0

    monkeypatch.setattr(meeting.agent, "run", gives_up)
    assert main(["summarise", wd.name]) == 2  # a person has to look; no retry
    assert main(["fail", wd.name]) == 0
    p = page.parse(st.doc(ids["ready"])["text"])
    assert "the whole recording is off the record" in p.status
    assert "- [ ] Ready to transcribe" in st.doc(ids["ready"])["text"]


def test_agent_gets_its_check_failures_back_once(env, wiki, monkeypatch):
    wd = _claimed(env, wiki)
    shutil.copy(FIXTURE / "recording_datetime.txt", wd)
    assert main(["context", wd.name]) == 0
    prompts = []

    def sloppy_then_fixed(cfg, prompt, wd, **_):
        prompts.append(prompt)
        team = json.loads((wd / "context" / "team.json").read_text())
        _fake_agent_output(wd, team, date="2026-10-30" if len(prompts) == 1 else "2026-10-27")
        return 0

    monkeypatch.setattr(meeting.agent, "run", sloppy_then_fixed)
    assert main(["summarise", wd.name]) == 0
    assert len(prompts) == 2
    assert "isn't the recording date 2026-10-27" in prompts[1]


def test_a_parallel_steps_success_doesnt_erase_a_failure(env, wiki):
    _, ids, st = wiki
    wd = _claimed(env, wiki)
    st.data["templates"] = []
    assert main(["context", wd.name]) == 2
    (wd / "transcript.srt").write_text("")  # transcribe "already done": succeeds
    assert main(["transcribe", wd.name]) == 0
    assert main(["fail", wd.name]) == 0
    assert "no 'Meeting summary' template" in page.parse(st.doc(ids["ready"])["text"]).status

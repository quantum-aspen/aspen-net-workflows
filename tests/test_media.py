import json

import pytest

from aspen_steps import media
from aspen_steps.config import Config


@pytest.fixture
def wd(tmp_path):
    (tmp_path / "job.json").write_text(json.dumps({"url": "https://example.zoom.us/rec/share/fake"}))
    (tmp_path / ".passcode").write_text("Q9$7ZKP#")
    return tmp_path


@pytest.fixture
def runs(monkeypatch):
    calls = []
    monkeypatch.setattr(media, "_run", lambda cmd, wd, env=None, timeout=0: calls.append(env))
    return calls


def test_a_retry_downloads_the_video_again_after_clean(wd, runs):
    (wd / "transcript.srt").write_text("1\n")
    media.clean(wd)  # what the end of the stopped run did
    media.fetch(Config.from_env({}), wd)
    assert runs == [{"ZOOM_PASSCODE": "Q9$7ZKP#"}]
    assert (wd / ".passcode").exists()  # still there for the next retry


def test_fetch_skips_when_it_has_the_video_or_the_summary_is_written(wd, runs):
    (wd / "meeting.mp4").touch()
    (wd / "transcript.srt").touch()
    media.fetch(Config.from_env({}), wd)
    (wd / "meeting.mp4").unlink()
    (wd / "out").mkdir()
    (wd / "out" / "result.json").write_text("{}")
    media.fetch(Config.from_env({}), wd)
    assert runs == []


def test_the_passcode_goes_when_the_run_publishes(wd):
    media.forget_passcode(wd)
    assert not (wd / ".passcode").exists()

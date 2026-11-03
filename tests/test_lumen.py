import yaml

from aspen_steps import agent, asr
from aspen_steps.config import Config


def cfg(**env):
    return Config.from_env({"LUMEN_API_KEY": "lu-secret", **env})


def test_chunks_end_in_a_pause_when_there_is_one():
    spans = asr.cuts(100, [10, 24, 29.5, 31, 70], target=30)
    assert spans == [(0, 29.5), (29.5, 59.5), (59.5, 89.5), (89.5, 100)]
    assert all(b - a <= 30 for a, b in spans)


def test_a_tiny_tail_isnt_its_own_chunk():
    assert asr.cuts(60.1, [], target=30) == [(0, 30), (30, 60)]


def test_sentences_share_their_chunk_by_length():
    segs = asr.segments("Hello there. How are you doing today?", 30, 40)
    assert [t for _, _, t in segs] == ["Hello there.", "How are you doing today?"]
    assert segs[0][0] == 30 and segs[-1][1] == 40
    assert segs[0][1] == segs[1][0]
    assert asr.segments("", 0, 30) == []


def test_transcript_matches_the_skills_format(tmp_path):
    n = asr.write([(0, 2.5, "Hi."), (3661.25, 3662, "Bye.")], tmp_path / "transcript")
    assert n == 2
    assert (tmp_path / "transcript.txt").read_text() == "[0:00:00] Hi.\n[1:01:01] Bye.\n"
    assert (tmp_path / "transcript.srt").read_text() == (
        "1\n00:00:00,000 --> 00:00:02,500\nHi.\n\n2\n01:01:01,250 --> 01:01:02,000\nBye.\n\n"
    )
    assert not list(tmp_path.glob("*.part"))


def test_hermes_config_points_at_lumen_and_drops_mcp(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "model:\n  provider: openrouter\n  extra: kept\nagent:\n  x: 1\n"
        "mcp_servers:\n  outline:\n    url: https://wiki/mcp\n"
    )
    c = cfg(AGENT_MODEL="m", LUMEN_VISION_MODEL="v")
    text = agent.write_hermes_config(c, tmp_path).read_text()
    data = yaml.safe_load(text)
    assert data["model"] == {
        "provider": "custom", "extra": "kept", "base_url": "https://lumen.ncsa.illinois.edu/v1",
        "key_env": "LUMEN_API_KEY", "default": "m",
    }  # fmt: skip
    assert data["auxiliary"]["vision"]["model"] == "v"
    assert data["agent"] == {"x": 1, "api_max_retries": 6}
    assert "mcp_servers" not in data
    assert "lu-secret" not in text


def test_hermes_without_a_vision_model_gets_no_vision_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cmd = agent._hermes(cfg(AGENT_MODEL="m"), "p", tmp_path, [], [])
    assert cmd[cmd.index("--toolsets") + 1] == "terminal,file,todo"
    assert "vision" not in yaml.safe_load((tmp_path / "config.yaml").read_text())["auxiliary"]

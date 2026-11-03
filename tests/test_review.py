import json

import pytest

from aspen_steps import asr, review
from aspen_steps.config import Config
from aspen_steps.errors import StepError

SPANS = [(0.0, 30.0), (30.0, 58.5), (58.5, 80.0)]
TEXTS = [
    "So we have these modlock lasers at 1550.",
    "We would need around a 45 femtosecond lock. So that's much lower.",
    "Thanks, everyone.",
]


def zoom_row(ts, end, text):
    return {"ts": ts, "end_ts": end, "text": text, "username": "Room account"}


def test_tokens_drop_fillers_and_split_hyphens():
    assert review.tokens("Um, a 45-femtosecond lock, like, 0.6 fs") == [
        "45",
        "femtosecond",
        "lock",
        "0.6",
        "femtosecond",
    ]


def test_zoom_disagreement_on_a_number_is_flagged():
    zoom = review.zoom_words(
        {
            "transcriptList": [
                zoom_row("00:00:00.500", "00:00:29.000", "So we have these mode-locked lasers at 1550."),
                zoom_row(
                    "00:00:30.500",
                    "00:00:58.000",
                    "We would need around a 40 femtosecond lock. So that's much lower.",
                ),
                zoom_row("00:00:59.000", "00:01:19.000", "Thanks, everyone."),
            ]
        }
    )
    found = review.zoom_disagreements(SPANS, TEXTS, zoom)
    assert "45 / 40" in found[1]
    assert set(found) == {1}  # "modlock / mode locked" is left to the model


def test_zoom_agreeing_or_differing_only_at_the_edges_isnt_flagged():
    zoom = review.zoom_words(
        {
            "transcriptList": [
                # an extra word at the start that belongs to the previous chunk's timing
                zoom_row(
                    "00:00:29.500",
                    "00:00:58.000",
                    "lower. We would need around a 45 femtosecond lock. So that's much lower.",
                ),
            ]
        }
    )
    assert review.zoom_disagreements(SPANS[1:2], TEXTS[1:2], zoom) == {}


def test_numbers_and_units_are_compared_as_values():
    assert review.tokens("one GHz, twenty five femtoseconds, a hundred and 100 ps") == [
        "1", "gigahertz", "25", "femtosecond", "100", "100", "picosecond",
    ]  # fmt: skip
    zoom = review.zoom_words(
        {
            "transcriptList": [
                zoom_row(
                    "00:00:00.000", "00:00:30.000", "So we have these mode-locked lasers at fifteen fifty."
                )
            ]
        }
    )
    # "fifteen fifty" isn't 1550 to this, but it's spoken that way rarely enough to re-check
    assert set(
        review.zoom_disagreements(SPANS[:1], ["So we have these mode-locked lasers at 1 GHz."], zoom)
    ) == {0}
    agree = review.zoom_words(
        {"transcriptList": [zoom_row("00:00:00.000", "00:00:30.000", "measuring at one gigahertz now")]}
    )
    assert review.zoom_disagreements(SPANS[:1], ["measuring at 1 GHz now"], agree) == {}


def test_suspects_are_parsed_from_a_chatty_answer():
    answer = (
        'Here you go:\n```json\n{"suspects": [{"at": "0:00:31", "heard": "45 femtosecond", "why": "?"}, '
        '{"at": "soon"}]}\n```'
    )
    assert review.parse_suspects(answer) == [{"at": "0:00:31", "heard": "45 femtosecond", "why": "?"}]
    with pytest.raises(StepError):
        review.parse_suspects("I can't do that")


def test_a_suspect_lands_in_the_chunk_with_its_words():
    # Timestamps inside a chunk are approximate: a line timed just before a chunk starts
    # can belong to it.
    assert review.chunk_for({"at": "0:00:29", "heard": "45 femtosecond lock"}, SPANS, TEXTS) == 1
    assert review.chunk_for({"at": "0:00:05", "heard": "modlock"}, SPANS, TEXTS) == 0
    assert review.chunk_for({"at": "0:01:10", "heard": ""}, SPANS, TEXTS) == 2


def test_assemble_swaps_in_a_rechecked_chunk():
    segs = asr.assemble(SPANS, TEXTS, {1: [(31.0, 40.0, "We would need around a 40 femtosecond lock.")]})
    assert [t for _, _, t in segs] == [
        "So we have these modlock lasers at 1550.",
        "We would need around a 40 femtosecond lock.",
        "Thanks, everyone.",
    ]


def test_review_is_on_only_for_lumen_and_borrows_hermes_model():
    lumen = Config.from_env({"TRANSCRIBER": "lumen", "AGENT_MODEL": "deepseek"})
    assert lumen.review_enabled and lumen.review_model == "deepseek"
    assert not Config.from_env({"TRANSCRIBER": "whisper"}).review_enabled
    assert not Config.from_env({"TRANSCRIBER": "lumen", "REVIEW": "0"}).review_enabled
    assert (
        Config.from_env({"TRANSCRIBER": "lumen", "AGENT": "claude", "AGENT_MODEL": "opus"}).review_model == ""
    )


def test_review_rechecks_flagged_chunks_and_keeps_the_original(tmp_path, monkeypatch):
    wd = tmp_path
    (wd / "asr").mkdir()
    (wd / "asr" / "chunks.json").write_text(json.dumps(SPANS))
    for i, t in enumerate(TEXTS):
        (wd / "asr" / f"{i:05}.txt").write_text(t)
    asr.write(asr.assemble(SPANS, TEXTS), wd / "transcript")
    (wd / "job.json").write_text(json.dumps({"series": "Seminar"}))
    (wd / "context").mkdir()
    (wd / "context" / "team.json").write_text(json.dumps([{"name": "Michael Raymer", "id": "u1"}]))
    (wd / "play_info.json").write_text(
        json.dumps(
            {
                "transcriptList": [
                    zoom_row(
                        "00:00:30.500",
                        "00:00:58.000",
                        "We would need around a 40 femtosecond lock. So that's much lower.",
                    )
                ]
            }
        )
    )
    monkeypatch.setattr(
        review,
        "_chat",
        lambda cfg, p: '{"suspects": [{"at": "0:00:02", "heard": "modlock", "why": "garbled"}]}',
    )
    calls = {}

    def fake_recheck(cfg, wd, spans, idxs, prompt):
        calls["idxs"], calls["prompt"] = idxs, prompt
        return {
            1: [(31.0, 40.0, "We would need around a 40 femtosecond lock.")],
            0: [(0.5, 9.0, "So we have these mode-locked lasers at 1550.")],
        }

    monkeypatch.setattr(review, "recheck", fake_recheck)
    cfg = Config.from_env(
        {
            "TRANSCRIBER": "lumen",
            "AGENT_MODEL": "m",
            "TRANSCRIBE_PROMPT": "Terms: femtoseconds.",
            "REVIEW_MAX_SHARE": "1",
        }
    )
    review.review(cfg, wd)

    assert calls["idxs"] == [0, 1]  # 0 from the model, 1 from Zoom's 40
    assert calls["prompt"] == "Terms: femtoseconds."  # no names: whisper writes them in as labels
    text = (wd / "transcript.txt").read_text()
    assert "40 femtosecond" in text and "mode-locked" in text and "Thanks, everyone." in text
    assert "45 femtosecond" in (wd / "transcript.granite.txt").read_text()
    rec = json.loads((wd / "review.json").read_text())
    assert rec["zoom_transcript"] and [c["chunk"] for c in rec["chunks"]] == [0, 1]
    review.review(cfg, wd)  # a retry skips itself


def test_review_stays_within_its_share_of_the_meeting(tmp_path, monkeypatch):
    wd = tmp_path
    (wd / "asr").mkdir()
    (wd / "asr" / "chunks.json").write_text(json.dumps(SPANS))
    for i, t in enumerate(TEXTS):
        (wd / "asr" / f"{i:05}.txt").write_text(t)
    asr.write(asr.assemble(SPANS, TEXTS), wd / "transcript")
    (wd / "job.json").write_text("{}")
    flagged = json.dumps(
        {
            "suspects": [
                {"at": t, "heard": h}
                for t, h in (("0:00:02", "modlock"), ("0:00:40", "45"), ("0:01:05", "x"))
            ]
        }
    )
    monkeypatch.setattr(review, "_chat", lambda cfg, p: flagged)
    seen = {}
    monkeypatch.setattr(
        review, "recheck", lambda cfg, wd, spans, idxs, prompt: seen.setdefault("idxs", idxs) and {}
    )
    review.review(
        Config.from_env({"TRANSCRIBER": "lumen", "AGENT_MODEL": "m", "REVIEW_MAX_SHARE": "0.5"}), wd
    )
    assert sum(SPANS[i][1] - SPANS[i][0] for i in seen["idxs"]) <= 40


def test_whisper_gets_the_glossary_unless_the_env_gives_a_prompt():
    assert "Hong-Ou-Mandel" in Config.from_env({}).asr_prompt
    assert Config.from_env({"TRANSCRIBE_PROMPT": "Just this."}).asr_prompt == "Just this."


def test_near_misses_of_glossary_terms_are_flagged():
    texts = [
        "we talked about hongol mandal interference",
        "these modlock lasers at 1550",
        "Hong-Ou-Mandel interference and mode-locked lasers, spelled right",
        "the rep rate of the time tagger",
        "a quantum repeater, separate from the rep at the desk",
    ]
    found = review.near_misses(
        texts, ["Hong-Ou-Mandel", "mode-locked lasers", "rep rate", "time taggers", "quantum repeater"]
    )
    assert set(found) == {0, 1}
    assert "looks like Hong-Ou-Mandel" in found[0] and "looks like mode-locked lasers" in found[1]


def test_the_glossary_is_terms_and_whisper_gets_it_as_a_sentence():
    from aspen_steps.config import glossary

    assert "HOM dip" in glossary() and not any(t.startswith("#") for t in glossary())
    assert Config.from_env({}).asr_prompt.startswith("An ASPEN-NET meeting about quantum networking: ")


def test_only_number_and_unit_flags_are_rechecked():
    assert review.rechecks({"kind": "number", "heard": "45"})
    assert review.rechecks({"kind": "unit", "heard": "10 seconds"})
    assert review.rechecks({"heard": "a 45 femtosecond lock"})  # no kind, but a number
    assert not review.rechecks({"kind": "term", "heard": "beamsuit"})
    assert not review.rechecks({"kind": "unit", "heard": "600 femtoseconds", "likely": "600 fs"})
    assert review.rechecks({"kind": "unit", "heard": "10 seconds", "likely": "10 femtoseconds"})

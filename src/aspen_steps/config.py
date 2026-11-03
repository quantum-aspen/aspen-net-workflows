"""Settings, all from environment variables. The DAGs pass them through."""

import os
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path

from pydantic import SecretStr


def _hours(spec: str) -> tuple[int, int] | None:
    """Parses "22-6" into (22, 6). Empty means any time."""
    if not spec.strip():
        return None
    start, end = (int(x) for x in spec.split("-"))
    if not (0 <= start < 24 and 0 <= end <= 24):
        raise ValueError(f"RUN_HOURS out of range: {spec}")
    return start, end


def glossary() -> list[str]:
    """prompts/glossary.txt: terms meetings use that speech-to-text gets wrong."""
    text = files("aspen_steps").joinpath("prompts/glossary.txt").read_text()
    return [t.strip() for t in text.splitlines() if t.strip() and not t.startswith("#")]


def _vocabulary() -> str:
    """Whisper's prompt from the glossary, as a sentence: whisper follows a prompt's style,
    and a bare list (or a list of names) gets written into the transcript as one."""
    return "An ASPEN-NET meeting about quantum networking: " + ", ".join(glossary()) + "."


def in_window(hours: tuple[int, int] | None, now: datetime | None = None) -> bool:
    if hours is None:
        return True
    h = (now or datetime.now()).hour
    start, end = hours
    return start <= h < end if start < end else h >= start or h < end


@dataclass(frozen=True)
class Config:
    # Keys are SecretStr so a logged or printed Config shows ********** instead.
    outline_url: str
    outline_api_key: SecretStr
    meetings_collection: str
    data_dir: Path
    whisper_model: str
    # "whisper" runs scripts/transcribe.py locally; "lumen" sends the audio to
    # Lumen's speech model (asr.py).
    transcriber: str
    lumen_base_url: str
    lumen_api_key: SecretStr
    lumen_asr_model: str
    lumen_vision_model: str
    asr_chunk_seconds: float
    asr_concurrency: int
    asr_prompt: str
    whisper_threads: int
    # review.py: "auto" re-checks a Lumen transcript's suspect chunks with whisper, "0" doesn't.
    review: str
    review_model: str
    review_max_share: float
    run_hours: tuple[int, int] | None
    agent: str
    agent_model: str
    agent_max_turns: int
    agent_budget: int
    mentions: bool
    dagu: str
    # Read the wiki but don't write to it: outline.Outline records each write instead.
    dry_run: bool

    @property
    def work_root(self) -> Path:
        return self.data_dir / "work"

    @property
    def scripts_dir(self) -> Path:
        """The meeting scripts: download, transcription, chat, frames. Plain files in the
        package, so the agent can run `frames.py` too."""
        return Path(str(files("aspen_steps").joinpath("scripts")))

    @property
    def meetings_dir(self) -> Path:
        return self.data_dir / "meetings"

    @property
    def review_enabled(self) -> bool:
        return self.review not in ("0", "false", "off", "") and self.transcriber == "lumen"

    def work_dir(self, doc_id: str) -> Path:
        # One recording page is one job, so its id names the work dir.
        return self.work_root / doc_id

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        e = os.environ if env is None else env
        return cls(
            outline_url=e.get("OUTLINE_URL", "https://wiki.quantum-aspen.net").rstrip("/"),
            outline_api_key=SecretStr(e.get("OUTLINE_API_KEY", "")),
            meetings_collection=e.get("MEETINGS_COLLECTION_ID", ""),
            data_dir=Path(e.get("DATA_DIR", "/opt/data")),
            whisper_model=e.get("WHISPER_MODEL", "large-v3-turbo"),
            transcriber=e.get("TRANSCRIBER", "whisper"),
            lumen_base_url=e.get("LUMEN_BASE_URL", "https://lumen.ncsa.illinois.edu/v1").rstrip("/"),
            lumen_api_key=SecretStr(e.get("LUMEN_API_KEY", "")),
            lumen_asr_model=e.get("LUMEN_ASR_MODEL", ""),
            lumen_vision_model=e.get("LUMEN_VISION_MODEL", ""),
            asr_chunk_seconds=float(e.get("ASR_CHUNK_SECONDS", "30")),
            asr_concurrency=int(e.get("ASR_CONCURRENCY", "4")),
            # Whisper's vocabulary hint: the checked-in glossary unless the env gives one.
            asr_prompt=e.get("TRANSCRIBE_PROMPT") or _vocabulary(),
            whisper_threads=int(e.get("TRANSCRIBE_THREADS", "4")),
            review=e.get("REVIEW", "auto"),
            # The Lumen model that reads the transcript for misheard lines; hermes' by default.
            review_model=e.get("REVIEW_MODEL")
            or (e.get("AGENT_MODEL", "") if e.get("AGENT", "hermes") == "hermes" else ""),
            review_max_share=float(e.get("REVIEW_MAX_SHARE", "0.5")),
            run_hours=_hours(e.get("RUN_HOURS", "")),
            agent=e.get("AGENT", "hermes"),
            agent_model=e.get("AGENT_MODEL", ""),
            agent_max_turns=int(e.get("AGENT_MAX_TURNS", "90")),
            agent_budget=int(e.get("AGENT_BUDGET_SECONDS", "2700")),
            mentions=e.get("MENTIONS", "1") not in ("", "0", "false"),
            dagu=e.get("DAGU_BIN", "dagu"),
            dry_run=e.get("DRY_RUN", "") not in ("", "0", "false"),
        )

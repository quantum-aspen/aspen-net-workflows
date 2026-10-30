"""Settings, all from environment variables. The DAGs pass them through."""

import os
from dataclasses import dataclass
from datetime import datetime
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
    skill_dir: Path
    whisper_model: str
    run_hours: tuple[int, int] | None
    agent: str
    agent_model: str
    agent_max_turns: int
    agent_budget: int
    mentions: bool
    dagu: str

    @property
    def work_root(self) -> Path:
        return self.data_dir / "work"

    @property
    def meetings_dir(self) -> Path:
        return self.data_dir / "meetings"

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
            skill_dir=Path(e.get("SKILL_DIR", "/opt/skills/local-meeting-transcript")),
            whisper_model=e.get("WHISPER_MODEL", "large-v3-turbo"),
            run_hours=_hours(e.get("RUN_HOURS", "")),
            agent=e.get("AGENT", "hermes"),
            agent_model=e.get("AGENT_MODEL", ""),
            agent_max_turns=int(e.get("AGENT_MAX_TURNS", "90")),
            agent_budget=int(e.get("AGENT_BUDGET_SECONDS", "2700")),
            mentions=e.get("MENTIONS", "1") not in ("", "0", "false"),
            dagu=e.get("DAGU_BIN", "dagu"),
        )

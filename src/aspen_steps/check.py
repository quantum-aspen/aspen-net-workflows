"""What the agent hands back, and the checks it has to pass before anything is published.

The agent decides what the summary says. These checks hold the things it must not get
wrong: the date, the template, the roster, and files that exist."""

import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator

MENTION = re.compile(r"mention://user/([\w-]+)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


class Correction(BaseModel):
    heard: str
    means: str


class Result(BaseModel):
    title: str = ""
    date: str = ""
    attendees: list[str] = []
    corrections: list[Correction] = []
    off_record: list[tuple[float, float]] = []
    series_row: dict[str, str] | None = None
    error: str | None = None

    @field_validator("off_record")
    @classmethod
    def _spans(cls, v):
        for a, b in v:
            if not 0 <= a < b:
                raise ValueError(f"off_record span [{a}, {b}] isn't start < end")
        return v


def table_header(markdown: str) -> list[str] | None:
    """The column names of the first markdown table, if there is one."""
    lines = markdown.splitlines()
    for i, line in enumerate(lines[:-1]):
        if line.strip().startswith("|") and re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", lines[i + 1]):
            return [c.strip() for c in line.strip().strip("|").split("|")]
    return None


# The table a series page gets when it has none: the columns the existing series use.
NEW_SERIES_HEADER = ["Date", "Meeting", "Key outcomes"]


def series_header(markdown: str) -> list[str]:
    """The series table's columns: the page's own table, or the one publish will add."""
    return table_header(markdown) or NEW_SERIES_HEADER


def load(wd: Path) -> tuple[Result, str]:
    try:
        result = Result.model_validate_json((wd / "out" / "result.json").read_text())
    except FileNotFoundError:
        raise ValueError("out/result.json is missing") from None
    except ValidationError as e:
        raise ValueError(f"out/result.json doesn't match the expected shape: {e}") from None
    summary = wd / "out" / "summary.md"
    return result, summary.read_text() if summary.exists() else ""


def problems(wd: Path, result: Result, summary: str, *, mentions: bool) -> list[str]:
    """Everything wrong with the agent's output, as lines it can act on. [] means publishable."""
    if result.error:
        return []
    out = []
    if not summary.strip():
        out.append("out/summary.md is missing or empty")
    recorded = (
        (wd / "recording_datetime.txt").read_text().strip()[:10]
        if (wd / "recording_datetime.txt").exists()
        else ""
    )
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", result.date):
        out.append(f"date {result.date!r} isn't YYYY-MM-DD")
    elif recorded and result.date != recorded:
        out.append(f"date {result.date} isn't the recording date {recorded} (recording_datetime.txt)")
    if not result.title.strip() or "\n" in result.title:
        out.append("title is empty or spans lines")
    elif re.match(r"\d{4}-\d{2}-\d{2}", result.title):
        out.append("title starts with a date; give it without one (the workflow adds it)")
    if re.search(r"^# ", summary, re.M):
        out.append("summary.md has an H1; the title is a separate field, so start at ## or lower")
    if "!!" in summary:
        out.append("summary.md still has template placeholders (`!!…!!`)")
    job = json.loads((wd / "job.json").read_text())
    if job["url"] not in summary:
        out.append(f"summary.md doesn't link the recording ({job['url']})")
    team = json.loads((wd / "context" / "team.json").read_text())
    ids = {u["id"] for u in team}
    found = set(MENTION.findall(summary))
    if found and not mentions:
        out.append("summary.md @mentions people, but this run uses plain names")
    if bad := found - ids:
        out.append(f"summary.md mentions user ids that aren't in context/team.json: {sorted(bad)}")
    for ref in IMAGE.findall(summary):
        if re.match(r"https?://", ref):
            continue
        if not ref.startswith("frames/") or ".." in ref:
            out.append(f"image {ref} isn't under frames/")
        elif not (wd / ref).is_file():
            out.append(f"image {ref} doesn't exist")
    header = series_header((wd / "context" / "series.md").read_text())
    if result.series_row is not None:
        if extra := set(result.series_row) - set(header):
            out.append(f"series_row has columns the series table doesn't: {sorted(extra)}; it has {header}")
    return out

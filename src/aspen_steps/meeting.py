"""The meeting workflow's wiki-facing steps: claim, context, summarise, publish, status.

Media steps are in media.py. Every step takes the recording page's document id; the
work dir is named after it, so a page is a job."""

import json
import re
import shutil
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path
from string import Template

from . import agent, check, media, page
from .config import Config, in_window
from .errors import NeedsPerson, StepError
from .outline import Outline

EARLIER = 3  # summaries from the same series the agent reads for cross-references


def outline(cfg: Config, wd: Path | None = None) -> Outline:
    """A dry run records the writes it would make in would-write/<doc id>/ (or the data
    dir's, for writes that aren't a job's)."""
    if not cfg.outline_api_key.get_secret_value():
        raise StepError("OUTLINE_API_KEY isn't set")
    # Outside the work dir, which the agent works in: it has no business reading it.
    would_write = cfg.data_dir / "would-write" / (wd.name if wd else "") if cfg.dry_run else None
    return Outline(cfg.outline_url, cfg.outline_api_key, would_write=would_write)


# ---- status on the page --------------------------------------------------------------


def status(cfg: Config, doc_id: str, text: str, *, failed: bool = False) -> None:
    """Shows progress on the recording page. Best effort."""
    ol = outline(cfg, cfg.work_dir(doc_id))
    doc = ol.document(doc_id)
    ol.update(doc_id, text=page.set_status(doc["text"], text, failed=failed))


def record_error(wd: Path, step: str, reason: str) -> None:
    (wd / "errors").mkdir(exist_ok=True)
    (wd / "errors" / f"{step}.txt").write_text(reason)


def fail(cfg: Config, doc_id: str) -> None:
    """The failure handler: puts the failing step's reason on the page, with a box to retry."""
    errs = sorted((cfg.work_dir(doc_id) / "errors").glob("*.txt"), key=lambda f: f.stat().st_mtime)
    reason = errs[-1].read_text().strip() if errs else "the run failed; see the workflow log"
    reason = (reason.splitlines() or ["the run failed"])[0][:300]
    status(cfg, doc_id, f"failed: {reason}. Tick the box to try again.", failed=True)


# ---- poll ----------------------------------------------------------------------------


def claim(cfg: Config, doc_id: str, series: dict[str, str] | None = None) -> Path:
    """Makes a recording page a job: writes job.json and the passcode to its work dir, and
    swaps the page's tick box for a status callout. Takes the page's id or its link's url id,
    and returns the work dir, which is named by the id."""
    ol = outline(cfg)
    if series is None:
        series = {n["id"]: n["title"] for n in ol.tree(cfg.meetings_collection)}
    doc = ol.document(doc_id)
    parent = doc.get("parentDocumentId")
    rec = page.parse(doc.get("text") or "")
    if parent not in series:
        raise NeedsPerson(f"{doc['title']!r} isn't directly under a series page in Meetings")
    if not rec.link:
        raise NeedsPerson(f"{doc['title']!r} has no Zoom recording link")
    wd = cfg.work_dir(doc["id"])
    wd.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(wd / "errors", ignore_errors=True)
    ol = outline(cfg, wd)
    (wd / "job.json").write_text(
        json.dumps(
            {"doc_id": doc["id"], "url": rec.link, "series_id": parent, "series": series[parent]}, indent=1
        )
    )
    text, passcode = page.claim(doc["text"], "queued")
    if passcode:
        # A re-tick without a passcode keeps the one from last time: it's kept until publish.
        secret = wd / ".passcode"
        secret.touch(mode=0o600)
        secret.write_text(passcode)
    ol.update(doc["id"], text=text)
    return wd


def poll(cfg: Config) -> list[str]:
    """Claims every ticked recording page under a series and queues a meeting run for it."""
    if not cfg.meetings_collection:
        raise StepError("MEETINGS_COLLECTION_ID isn't set")
    ol = outline(cfg)
    series = {n["id"]: n["title"] for n in ol.tree(cfg.meetings_collection)}
    queued = []
    for doc in ol.recently_updated(cfg.meetings_collection):
        if doc.get("parentDocumentId") not in series or not page.parse(doc.get("text") or "").ready:
            continue
        claim(cfg, doc["id"], series)
        try:
            out = subprocess.run(
                [cfg.dagu, "enqueue", "meeting", "--", f"DOC_ID={doc['id']}"],
                check=True, capture_output=True, text=True, timeout=60,
            )  # fmt: skip
            print(out.stdout.strip())
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            detail = getattr(e, "stderr", "") or str(e)
            status(cfg, doc["id"], f"failed to queue: {detail[-200:]}", failed=True)
            continue
        print(f"queued {doc['title']!r} ({doc['id']}) in {series[doc['parentDocumentId']]!r}")
        queued.append(doc["id"])
    return queued


def wait_for_window(cfg: Config) -> None:
    """Holds the run (and, since meetings run one at a time, the queue) until RUN_HOURS."""
    if in_window(cfg.run_hours):
        return
    print(f"waiting for RUN_HOURS {cfg.run_hours}", flush=True)
    while not in_window(cfg.run_hours):
        time.sleep(60)


# ---- context -------------------------------------------------------------------------


def context(cfg: Config, wd: Path) -> None:
    """Everything the agent would otherwise read from the wiki, written to context/."""
    ol = outline(cfg)
    job = json.loads((wd / "job.json").read_text())
    ctx = wd / "context"
    shutil.rmtree(ctx, ignore_errors=True)
    (ctx / "earlier").mkdir(parents=True)

    team = sorted(({"name": u["name"], "id": u["id"]} for u in ol.users()), key=lambda u: u["name"])
    (ctx / "team.json").write_text(json.dumps(team, indent=1) + "\n")

    s = ol.document(job["series_id"])
    (ctx / "series.md").write_text(f"# {s['title']}\n\n{s['text']}")

    dated = re.compile(r"\d{4}-\d{2}-\d{2} ")
    earlier = sorted(
        (d for d in ol.children(cfg.meetings_collection, job["series_id"]) if dated.match(d["title"])),
        key=lambda d: d["title"],
        reverse=True,
    )[:EARLIER]
    for d in earlier:
        (ctx / "earlier" / f"{d['title'].replace('/', '-')}.md").write_text(f"# {d['title']}\n\n{d['text']}")

    template = next(
        (t for t in ol.templates(cfg.meetings_collection) if t["title"] == "Meeting summary"), None
    )
    if template is None:
        raise NeedsPerson("the Meetings collection has no 'Meeting summary' template")
    # templates.list gives ProseMirror JSON (`data`), not markdown; documents.info on the
    # template's id gives its `text`.
    text = template.get("text") or ol.document(template["id"])["text"]
    (ctx / "template.md").write_text(text)
    print(f"context: {len(team)} users, series {s['title']!r}, {len(earlier)} earlier summaries")


# ---- summarise -----------------------------------------------------------------------


def _prompt(cfg: Config, wd: Path) -> str:
    job = json.loads((wd / "job.json").read_text())
    header = check.table_header((wd / "context" / "series.md").read_text())
    if header:
        row = (
            f"- `series_row` is this meeting's row for the table on the series page, which has the "
            f"columns {header}: one key per column, in the same style as the existing rows. Link "
            "this summary as `{{page_url}}`; the workflow fills in its address."
        )
        example = ', "series_row": {' + ", ".join(f'"{h}": "…"' for h in header) + "}"
    else:
        row, example = "", ""
    mentions = (
        "@mention attendees and action-item owners who are in `context/team.json`: "
        "`@[Name](mention://user/<id>)`."
        if cfg.mentions
        else "Write people's names plainly, with no @mentions."
    )
    text = files("aspen_steps").joinpath("prompts/meeting-summary.md").read_text()
    return Template(text).substitute(
        skill=cfg.skill_dir,
        wd=wd.resolve(),
        series=job["series"],
        url=job["url"],
        mentions=mentions,
        series_row=row,
        series_row_example=example,
    )


def _materials(cfg: Config, wd: Path) -> str:
    """The files the agent needs, inlined after the instructions, so it spends no turns
    reading them. Each turn on Lumen takes 15-100 s, and the first run spent a dozen on this."""
    refs = cfg.skill_dir / "references"
    files_ = [
        (refs / "aspen-net-output.md", "aspen-net-output.md"),
        (refs / "chat-commands.md", "chat-commands.md"),
        (wd / "context" / "template.md", "context/template.md"),
        (wd / "context" / "series.md", "context/series.md"),
        (wd / "context" / "team.json", "context/team.json"),
        *((f, f"context/earlier/{f.name}") for f in sorted((wd / "context" / "earlier").glob("*.md"))),
        (wd / "recording_datetime.txt", "recording_datetime.txt"),
        (wd / "chat.md", "chat.md"),
        (wd / "frames" / "commands.json", "frames/commands.json"),
        (wd / "transcript.txt", "transcript.txt"),
    ]
    parts = ["# The files"]
    for path, name in files_:
        if path.exists():
            parts.append(f"## `{name}`\n\n````\n{path.read_text().strip()}\n````")
        elif name in ("chat.md", "frames/commands.json"):
            parts.append(
                f"## `{name}`\n\n(none: {'no chat' if name == 'chat.md' else 'no screenshot requests'})"
            )
    return "\n\n".join(parts) + "\n"


def summarise(cfg: Config, wd: Path, attempts: int = 2) -> None:
    """Runs the agent, then checks what it wrote. Problems go back to it once."""
    (wd / "out").mkdir(exist_ok=True)
    (wd / "out" / "result.json").unlink(missing_ok=True)
    original = _prompt(cfg, wd) + "\n\n" + _materials(cfg, wd)
    prompt = original
    frames_at = f"python3 {cfg.skill_dir}/scripts/frames.py at"
    for attempt in range(1, attempts + 1):
        rc = agent.run(cfg, prompt, wd, read_dirs=[cfg.skill_dir], commands=[frames_at])
        try:
            result, summary = check.load(wd)
            found = check.problems(wd, result, summary, mentions=cfg.mentions)
        except ValueError as e:
            found = [str(e)]
        if not found:
            if result.error:
                raise NeedsPerson(f"the agent couldn't summarise this meeting: {result.error}")
            print(f"summary passed its checks on attempt {attempt}")
            return
        print(f"attempt {attempt} (agent exit {rc}) failed its checks:", *found, sep="\n- ", flush=True)
        if not any((wd / "out" / f).exists() for f in ("summary.md", "result.json")):
            # The agent stopped before writing anything (a provider error, say): start again.
            prompt = original
            continue
        prompt = (
            "You already wrote out/summary.md and out/result.json for this meeting, but they failed "
            "these checks. Fix them, changing nothing else, and stop.\n\n"
            + "\n".join(f"- {p}" for p in found)
            + "\n\nThe original instructions follow.\n\n"
            + original
        )
    raise StepError(f"the summary failed its checks: {'; '.join(found)}")


# ---- publish -------------------------------------------------------------------------


def _srt_without(srt: str, spans: list[tuple[float, float]]) -> str:
    """Drops every subtitle block that overlaps an off-record span."""

    def secs(t: str) -> float:
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    kept = []
    for block in srt.strip().split("\n\n"):
        m = re.search(r"(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)", block)
        if m and any(secs(m.group(1)) < b and secs(m.group(2)) > a for a, b in spans):
            continue
        kept.append(block)
    # clean_transcript.py only takes a block once it sees the blank line after it
    return "\n\n".join(kept) + "\n\n"


def _transcribed_by(cfg: Config, wd: Path) -> str:
    if cfg.transcriber == "lumen":
        if (wd / "review.json").exists():
            n = sum(1 for c in json.loads((wd / "review.json").read_text())["chunks"] if c["whisper"])
            if n:
                return (
                    f"{cfg.lumen_asr_model} on NCSA Lumen, with {n} misheard-looking passages "
                    f"re-transcribed by faster-whisper {cfg.whisper_model}; timestamps approximate"
                )
        chunk = f"{cfg.asr_chunk_seconds:g}"
        return f"{cfg.lumen_asr_model} on NCSA Lumen, timestamps approximate (~{chunk}s chunks)"
    return f"faster-whisper {cfg.whisper_model}, run locally"


def _transcript_folder(cfg: Config, wd: Path, result: check.Result, title: str, wiki_url: str) -> Path:
    """The local transcript folder, per aspen-net-output §2."""
    out = cfg.meetings_dir / title.replace("/", "-")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    srt = _srt_without((wd / "transcript.srt").read_text(), result.off_record)
    (out / "transcript.srt").write_text(srt)
    clean = wd / "out" / "transcript-body.md"
    subprocess.run(
        [
            sys.executable,
            str(cfg.skill_dir / "scripts" / "clean_transcript.py"),
            str(out / "transcript.srt"),
            str(clean),
        ],
        check=True,
    )
    errors = "\n".join(f"| {c.heard} | **{c.means}** |" for c in result.corrections) or "| (none found) | |"
    (out / "transcript.md").write_text(
        f"---\ndate: {result.date}\ntitle: {result.title}\n"
        "source: Zoom cloud recording\n"
        f"transcription: {_transcribed_by(cfg, wd)}; no speaker labels\n"
        f"attendees: {json.dumps(result.attendees)}\nsummary: {wiki_url}\n---\n\n"
        f"# {title} — transcript\n\n## Known transcription errors\n\n"
        f"| Transcript says | Means |\n|---|---|\n{errors}\n\n---\n\n{clean.read_text()}"
    )
    for name in ("chat.json",):
        if (wd / name).exists():
            shutil.copy(wd / name, out / name)
    job = json.loads((wd / "job.json").read_text())
    (out / "meta.json").write_text(
        json.dumps(
            {
                "url": job["url"],
                "recording_datetime": (wd / "recording_datetime.txt").read_text().strip()
                if (wd / "recording_datetime.txt").exists()
                else None,
                "attendees": result.attendees,
                "wiki_url": wiki_url,
            },
            indent=1,
        )
    )
    return out


def _insert_row(markdown: str, row: dict[str, str]) -> str:
    """Adds a row after the last row of the first table."""
    header = check.table_header(markdown)
    lines = markdown.splitlines()
    start = next(
        i for i, line in enumerate(lines) if [c.strip() for c in line.strip().strip("|").split("|")] == header
    )
    end = start + 2
    while end < len(lines) and lines[end].strip().startswith("|"):
        end += 1
    lines.insert(end, "| " + " | ".join(row.get(h, "") for h in header) + " |")
    return "\n".join(lines) + "\n"


def publish(cfg: Config, wd: Path) -> None:
    """Turns the recording page into the summary, adds the series row, saves the transcript."""
    result, summary = check.load(wd)
    job = json.loads((wd / "job.json").read_text())
    title = f"{result.date} {result.title}"
    ol = outline(cfg, wd)

    used = {}
    for ref in dict.fromkeys(check.IMAGE.findall(summary)):
        if ref.startswith("frames/"):
            used[ref] = ol.upload(job["doc_id"], wd / ref)
    for ref, url in used.items():
        summary = summary.replace(f"]({ref})", f"]({url})")

    path = ol.update(job["doc_id"], title=title, text=summary)["url"]
    print(f"published {title!r}: {cfg.outline_url}{path}")
    wiki_url = cfg.outline_url + path

    if result.series_row:
        # relative, like the links people make in the wiki's own editor
        row = {k: v.replace("{{page_url}}", path) for k, v in result.series_row.items()}
        series = ol.document(job["series_id"])
        ol.update(job["series_id"], text=_insert_row(series["text"], row))
        print(f"added a row to {job['series']!r}")

    out = _transcript_folder(cfg, wd, result, title, wiki_url)
    for ref in used:
        shutil.copy(wd / ref, out / "frames" / Path(ref).name)
    print(f"transcript saved to {out}")
    media.forget_passcode(wd)

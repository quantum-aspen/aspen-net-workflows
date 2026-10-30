"""Download, transcribe, and pull chat and frames: the skill's scripts, no model involved.

Each step skips itself if its output already exists, so a retried or re-ticked run
picks up where the last one stopped."""

import json
import os
import subprocess
import sys
from pathlib import Path

from .config import Config
from .errors import NeedsPerson, StepError

MEDIA = ("meeting.mp4", "share.mp4", "meeting.wav")
RETICK = "add `passcode: …` to the page and tick the box again"


def _run(cmd: list[str], wd: Path, env: dict | None = None, timeout: int = 3600) -> None:
    """Runs one skill script with its output going to the step's log (stdout)."""
    print("$", " ".join(cmd), flush=True)
    p = subprocess.run(
        cmd,
        cwd=wd,
        env=os.environ | (env or {}),
        timeout=timeout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    out = p.stdout.decode(errors="replace")
    sys.stdout.write(out)
    sys.stdout.flush()
    if p.returncode:
        name = Path(cmd[1]).name if cmd[0] in ("sh", sys.executable) else cmd[0]
        raise StepError(
            f"{name} exited {p.returncode}: {out.strip().splitlines()[-1] if out.strip() else ''}"
        )


def job(wd: Path) -> dict:
    return json.loads((wd / "job.json").read_text())


def fetch(cfg: Config, wd: Path) -> None:
    """The passcode reaches fetch.sh as ZOOM_PASSCODE and nothing else, and is deleted
    once the download has worked."""
    secret = wd / ".passcode"
    if (wd / "meeting.wav").exists() or (wd / "transcript.srt").exists():
        print("already downloaded")
        secret.unlink(missing_ok=True)
        return
    passcode = secret.read_text().strip() if secret.exists() else ""
    try:
        _run(
            ["sh", str(cfg.skill_dir / "scripts" / "fetch.sh"), job(wd)["url"], str(wd)],
            wd,
            env={"ZOOM_PASSCODE": passcode} if passcode else None,
            timeout=2400,
        )
    except StepError as e:
        if "needs a passcode" in str(e):
            raise NeedsPerson(f"the recording needs a passcode: {RETICK}") from e
        if "rejected the passcode" in str(e):
            raise NeedsPerson(f"Zoom rejected the passcode: {RETICK}") from e
        raise
    secret.unlink(missing_ok=True)


def transcribe(cfg: Config, wd: Path) -> None:
    if (wd / "transcript.srt").exists():
        print("already transcribed")
        return
    env = {"HF_HOME": str(cfg.data_dir / "hf")}
    _run(
        [
            sys.executable,
            str(cfg.skill_dir / "scripts" / "transcribe.py"),
            "meeting.wav",
            cfg.whisper_model,
            "transcript",
        ],
        wd,
        env=env,
        timeout=3 * 3600,
    )


def frames(cfg: Config, wd: Path) -> None:
    """Candidate frames for each `ai:` command and each screen change. The agent picks."""
    script = [sys.executable, str(cfg.skill_dir / "scripts" / "frames.py")]
    video = wd / ("share.mp4" if (wd / "share.mp4").exists() else "meeting.mp4")
    if video.exists():
        if (wd / "chat.json").exists() and not (wd / "frames" / "commands.json").exists():
            _run([*script, "commands", video.name, "chat.json", "frames"], wd)
        if (wd / "play_info.json").exists() and not (wd / "frames" / "scenes.json").exists():
            _run([*script, "scenes", video.name, "play_info.json", "frames"], wd)
    # whisper is done with it; the video stays for `frames.py at` until the run ends
    (wd / "meeting.wav").unlink(missing_ok=True)


def clean(wd: Path) -> None:
    for name in MEDIA:
        (wd / name).unlink(missing_ok=True)

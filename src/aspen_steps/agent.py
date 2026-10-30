"""Runs an agent unattended in a work directory, with no wiki access.

The agent reads files and writes files. Steps before it put everything it needs in
the work directory, and steps after it check and publish what it wrote, so it never
holds the Outline key: it's taken out of the agent's environment here.

AGENT picks the harness: `hermes` (production, on Lumen) or `claude` (Claude Code on
whatever account the machine is logged into, for development)."""

import os
import subprocess
import sys
from pathlib import Path

from .config import Config
from .errors import StepError

# Never reaches an agent: the workflow's own credentials.
WITHHELD = ("OUTLINE_API_KEY",)
# Claude Code refuses to start inside another Claude Code session; a dev machine may be one.
NESTING = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")


def _env(extra_scrub: tuple[str, ...] = ()) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in WITHHELD + extra_scrub}


def _claude(cfg: Config, prompt: str, wd: Path, read_dirs: list[Path], commands: list[str]) -> list[str]:
    allowed = ["Read", "Write", "Edit", "Glob", "Grep", *(f"Bash({c}:*)" for c in commands)]
    cmd = [
        "claude", "-p", prompt,
        "--max-turns", str(cfg.agent_max_turns),
        "--allowedTools", ",".join(allowed),
        "--disallowedTools", "WebFetch,WebSearch",
        # deny anything not allowed above, rather than wait for an answer nobody gives
        "--permission-mode", "dontAsk",
    ]  # fmt: skip
    for d in read_dirs:
        cmd += ["--add-dir", str(d)]
    if cfg.agent_model:
        cmd += ["--model", cfg.agent_model]
    return cmd


def _hermes(cfg: Config, prompt: str, wd: Path, read_dirs: list[Path], commands: list[str]) -> list[str]:
    (wd / "prompt.md").write_text(prompt)
    return [
        "hermes", "chat",
        "--query-file", str(wd / "prompt.md"),
        "--quiet",
        # terminal is for the frames.py command; the container holds no wiki credentials
        "--toolsets", "terminal,file,vision,todo",
        "--max-turns", str(cfg.agent_max_turns),
        "--run-budget", str(cfg.agent_budget),
        "--yolo",  # no one is there to approve tool calls
    ]  # fmt: skip


HARNESSES = {"claude": _claude, "hermes": _hermes}


def run(cfg: Config, prompt: str, wd: Path, *, read_dirs: list[Path] = (), commands: list[str] = ()) -> int:
    """One unattended agent run in wd. Its output goes to the step log; returns the exit code."""
    if cfg.agent not in HARNESSES:
        raise StepError(f"AGENT={cfg.agent!r}; expected one of {sorted(HARNESSES)}")
    cmd = HARNESSES[cfg.agent](cfg, prompt, wd, list(read_dirs), list(commands))
    print(f"$ {cmd[0]} … ({cfg.agent}, max {cfg.agent_max_turns} turns)", flush=True)
    try:
        p = subprocess.run(
            cmd, cwd=wd, env=_env(NESTING), timeout=cfg.agent_budget + 300,
            stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=subprocess.STDOUT,
        )  # fmt: skip
    except subprocess.TimeoutExpired as e:
        raise StepError(f"the agent ran past its {cfg.agent_budget}s budget") from e
    return p.returncode

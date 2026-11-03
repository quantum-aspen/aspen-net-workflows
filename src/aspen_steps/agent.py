"""Runs an agent unattended in a work directory, with no wiki access.

The agent reads files and writes files. Steps before it put everything it needs in
the work directory, and steps after it check and publish what it wrote, so it never
holds the Outline key: it's taken out of the agent's environment here.

AGENT picks the harness: `hermes` (production, on Lumen) or `claude` (Claude Code on
whatever account the machine is logged into, for development). For hermes, AGENT_MODEL is
the Lumen model id, and LUMEN_VISION_MODEL the one that looks at screenshots."""

import os
import subprocess
import sys
from pathlib import Path

import yaml

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


def hermes_settings(cfg: Config) -> dict:
    """What we set in Hermes' config.yaml: Lumen for the model and for vision, and nothing
    that carries over between meetings."""
    lumen = {"provider": "custom", "base_url": cfg.lumen_base_url, "key_env": "LUMEN_API_KEY"}
    s = {
        "model": lumen | {"default": cfg.agent_model},
        # Each run is independent: nothing should carry over between meetings.
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "auxiliary": {"title_generation": {"enabled": False}},
    }
    if cfg.lumen_vision_model:
        s["auxiliary"]["vision"] = lumen | {"model": cfg.lumen_vision_model}
    return s


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def write_hermes_config(cfg: Config, home: Path | None = None) -> Path:
    """Merges our settings into $HERMES_HOME/config.yaml before each run, so the config
    always matches this image and env. The key stays in the env (key_env), not the file.
    MCP servers are dropped: the agent has no wiki access, and nothing else to reach."""
    if cfg.agent_model == "":
        raise StepError("AGENT=hermes needs AGENT_MODEL, the Lumen model id (e.g. deepseek-v4.1-flash)")
    if not cfg.lumen_api_key.get_secret_value():
        raise StepError("AGENT=hermes needs LUMEN_API_KEY")
    home = home or Path(os.environ.get("HERMES_HOME", "/opt/data"))
    path = home / "config.yaml"
    current = (yaml.safe_load(path.read_text()) if path.exists() else None) or {}
    merged = _merge(current, hermes_settings(cfg))
    merged.pop("mcp_servers", None)
    home.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(merged, sort_keys=False))
    return path


def _hermes(cfg: Config, prompt: str, wd: Path, read_dirs: list[Path], commands: list[str]) -> list[str]:
    print(f"hermes config: {write_hermes_config(cfg)} (Lumen, {cfg.agent_model})", flush=True)
    (wd / "prompt.md").write_text(prompt)
    # vision without a vision model would fall back to the main model, which can't see
    toolsets = "terminal,file,vision,todo" if cfg.lumen_vision_model else "terminal,file,todo"
    return [
        "hermes", "chat",
        "--query-file", str(wd / "prompt.md"),
        "--quiet",
        # terminal is for the frames.py command; the container holds no wiki credentials
        "--toolsets", toolsets,
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

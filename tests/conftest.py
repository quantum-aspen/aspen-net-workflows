import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

DEV = Path(__file__).parent.parent / "dev"
sys.path.insert(0, str(DEV))

import mock_outline  # noqa: E402


@pytest.fixture
def wiki(tmp_path):
    """A seeded mock Outline on a free port: (base url, seed ids, State)."""
    state = tmp_path / "outline.json"
    ids = json.loads(subprocess.run([sys.executable, str(DEV / "seed.py"), str(state)], check=True,
                                    capture_output=True, text=True).stdout)  # fmt: skip

    class H(mock_outline.Handler):
        st = mock_outline.State(state)
        token = "dev"
        files = tmp_path / "files"

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", ids, H.st
    srv.shutdown()


@pytest.fixture
def env(wiki, tmp_path, monkeypatch):
    """Steps' environment pointed at the mock, with a fake dagu that logs its arguments."""
    url, ids, _ = wiki
    fake = tmp_path / "dagu"
    fake.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/dagu.log\necho queued\n')
    fake.chmod(0o755)
    values = {
        "OUTLINE_URL": url,
        "OUTLINE_API_KEY": "dev",
        "MEETINGS_COLLECTION_ID": ids["collection"],
        "DATA_DIR": str(tmp_path / "data"),
        "DAGU_BIN": str(fake),
        "SKILL_DIR": os.environ.get(
            "SKILL_DIR", str(DEV.parent.parent / "aspen-net-skills/skills/local-meeting-transcript")
        ),
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("DRY_RUN", raising=False)
    return values

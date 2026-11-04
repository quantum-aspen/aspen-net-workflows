import os
import subprocess
import sys

STEP = """
import subprocess, sys
from aspen_steps import console
stop = console.tee("[fetch 9ab305e4] ", {fifo!r})
print("from python")
print("an error", file=sys.stderr)
subprocess.run(["sh", "-c", "echo from a child; echo child error >&2"])
stop()
sys.exit(3)
"""


def _drain(fd: int) -> bytes:
    out = b""
    while True:
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            return out
        if not chunk:
            return out
        out += chunk


def test_step_output_is_copied_to_the_container_log_with_a_prefix(tmp_path):
    fifo = str(tmp_path / "log")
    os.mkfifo(fifo)
    # Open for reading first, as the start script's cat does; the FIFO keeps what the step
    # writes until it's read. Reading after the step has exited avoids racing its two
    # pumps (stdout and stderr), which can finish in either order.
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        p = subprocess.run(
            [sys.executable, "-c", STEP.format(fifo=fifo)], capture_output=True, text=True, timeout=30
        )
        got = _drain(reader)
    finally:
        os.close(reader)

    # Dagu's own log files get the output unchanged, and the exit code survives
    assert p.returncode == 3
    assert p.stdout.splitlines() == ["from python", "from a child"]
    assert p.stderr.splitlines() == ["an error", "child error"]
    # the container log gets every line, prefixed
    assert sorted(got.decode().splitlines()) == sorted(
        [
            "[fetch 9ab305e4] from python",
            "[fetch 9ab305e4] an error",
            "[fetch 9ab305e4] from a child",
            "[fetch 9ab305e4] child error",
        ]
    )


def test_without_the_fifo_a_step_runs_as_before(tmp_path):
    step = STEP.format(fifo=str(tmp_path / "missing"))
    p = subprocess.run([sys.executable, "-c", step], capture_output=True, text=True, timeout=30)
    assert p.returncode == 3
    assert sorted(p.stdout.splitlines()) == ["from a child", "from python"]


def test_a_fifo_nobody_reads_doesnt_block_the_step(tmp_path):
    fifo = str(tmp_path / "log")
    os.mkfifo(fifo)
    p = subprocess.run(
        [sys.executable, "-c", STEP.format(fifo=fifo)], capture_output=True, text=True, timeout=30
    )
    assert p.returncode == 3 and "from a child" in p.stdout

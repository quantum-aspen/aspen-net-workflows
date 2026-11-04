"""Copies a step's output to the container's log, so it reaches Grafana.

Dagu writes each step's stdout and stderr to its own log files, and only its own server
log reaches `docker logs`. The image's start script (bin/start-workflows) makes a FIFO
and keeps a `cat` reading it into the container's stdout. `tee` points this process's
stdout and stderr at pipes, so the output of every subprocess it runs (hermes, ffmpeg,
yt-dlp) is caught too, and copies each line to the FIFO with a prefix naming the step
and the meeting. Dagu's log files still get the output unchanged.

A missing FIFO (dev, `just try`) or one nobody reads never stops a step: then lines are
only dropped from the container log."""

import os
import stat
import sys
import threading
from collections.abc import Callable

FIFO = "/tmp/aspen-steps.log"
# A FIFO write up to PIPE_BUF bytes is atomic, so lines from steps running in parallel
# don't interleave mid-line. Longer lines are cut.
MAX_LINE = 4000


def _open_sink(path: str) -> int | None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:  # no FIFO, or no reader
        return None
    if not stat.S_ISFIFO(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    return fd


def _send(sink: int, line: bytes) -> None:
    try:
        os.write(sink, line)
    except OSError:  # full (the reader is behind) or gone: the container log loses a line
        pass


def _pump(src: int, dest: int, sink: int, prefix: bytes) -> None:
    pending = b""
    while chunk := os.read(src, 65536):
        os.write(dest, chunk)
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in lines:
            _send(sink, (prefix + line.rstrip(b"\r"))[:MAX_LINE] + b"\n")
    if pending:
        _send(sink, (prefix + pending)[:MAX_LINE] + b"\n")
    os.close(src)


def tee(prefix: str, path: str = FIFO) -> Callable[[], None]:
    """Starts copying stdout and stderr to the container log. Returns the function that
    stops it, which waits briefly for the last lines."""
    sink = _open_sink(path)
    if sink is None:
        return lambda: None
    sys.stdout.flush()
    sys.stderr.flush()
    # stdout becomes a pipe, which Python block-buffers: a step's own lines would land
    # after its subprocesses' in the log.
    sys.stdout.reconfigure(line_buffering=True)
    pumps = []
    for fd in (1, 2):
        original = os.dup(fd)
        r, w = os.pipe()
        os.dup2(w, fd)
        os.close(w)
        t = threading.Thread(target=_pump, args=(r, original, sink, prefix.encode()), daemon=True)
        t.start()
        pumps.append((fd, original, t))

    def stop() -> None:
        sys.stdout.flush()
        sys.stderr.flush()
        for fd, original, _ in pumps:
            os.dup2(original, fd)  # closes our write end of the pipe, so the pump sees EOF
        for _, original, t in pumps:
            # A daemon a step started could still hold the pipe; don't wait on it for long.
            t.join(5)
            if not t.is_alive():
                os.close(original)
        os.close(sink)

    return stop

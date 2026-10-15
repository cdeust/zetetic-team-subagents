"""Find the processes a test left running (used by the autouse guard in conftest.py).

A process belongs to a test when its argv names the test's ``tmp_path``: the task
tests put every fifo, state dir and worker argument under it. Existence is read
from the OS (``/proc`` on Linux, ``ps -ww`` elsewhere: without ``-ww`` macOS cuts argv at the
terminal width and the path is lost), never from a timer. Zombies
are skipped: they have exited and wait only to be reaped.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path

from task_support import wait_exit


def _linux_processes() -> list[tuple[int, str, str]]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            state = (entry / "stat").read_text().rpartition(")")[2].split()[0]
            argv = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue  # exited while we looked: that is the event we wanted
        found.append((int(entry.name), state, argv))
    return found


def _ps_processes() -> list[tuple[int, str, str]]:
    out = subprocess.run(["ps", "-ww", "-A", "-o", "pid=,stat=,args="], capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            rows.append((int(parts[0]), parts[1], parts[2]))
    return rows


def live_processes_naming(path: Path) -> list[tuple[int, str]]:
    """(pid, argv) of every live, non-zombie process other than this one whose argv contains ``path``."""
    rows = _linux_processes() if os.path.isdir("/proc/self") else _ps_processes()
    named = re.compile(re.escape(str(path)) + r"(?:/|\s|$)")  # test_x1 must not match test_x10/
    return [(pid, argv) for pid, state, argv in rows
            if named.search(argv) and not state.startswith("Z") and pid != os.getpid()]


def stop_pii_daemon(memory_root: Path) -> None:
    """Stop the PII daemon ``memory-tool.sh`` started for ``memory_root``, through its documented path.

    The daemon is long-lived by design (memory/pii-daemon.py: one per MEMORY_ROOT, idle exit
    after 30 s), so a test that drives the tool owns stopping it. Documented stop = SIGTERM to
    the pid in the ``.pii-daemon.sock.pid`` sidecar; the daemon then removes its socket and
    sidecar and exits. We wait for that exit as an OS event (see task_support.wait_exit).
    """
    pid_file = memory_root / ".pii-daemon.sock.pid"
    try:
        pid = int(pid_file.read_text())
    except (FileNotFoundError, ValueError):
        return  # never started (scan disabled, or no write reached the gate): nothing to stop
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return  # already exited on its own
    wait_exit(pid)

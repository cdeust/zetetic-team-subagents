"""Find the processes a test left running (used by the autouse guard in conftest.py).

A process belongs to a test when its argv names the test's ``tmp_path``: the task
tests put every fifo, state dir and worker argument under it. Existence is read
from the OS (``/proc`` on Linux, ``ps`` elsewhere), never from a timer. Zombies
are skipped: they have exited and wait only to be reaped.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


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
    out = subprocess.run(["ps", "-A", "-o", "pid=,stat=,args="], capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            rows.append((int(parts[0]), parts[1], parts[2]))
    return rows


def live_processes_naming(path: Path) -> list[tuple[int, str]]:
    """(pid, argv) of every live, non-zombie process other than this one whose argv contains ``path``."""
    rows = _linux_processes() if os.path.isdir("/proc/self") else _ps_processes()
    needle = str(path)
    return [(pid, argv) for pid, state, argv in rows
            if needle in argv and not state.startswith("Z") and pid != os.getpid()]

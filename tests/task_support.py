"""Helpers for the async-task tests (tools/lib/tasks.py).

Nothing here sleeps, polls or times out. Synchronisation is by OS events only:
a process exit (kqueue NOTE_EXIT / pidfd), a FIFO open/read/EOF, a thread Event.
"""
from __future__ import annotations

import os
import select
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "lib"))

import task_store  # noqa: E402,F401
import tasks  # noqa: E402,F401


def wait_exit(pid: int) -> None:
    """Block until ``pid`` has exited. Works for a child and for a non-child."""
    if hasattr(select, "kqueue"):
        queue = select.kqueue()
        watch = select.kevent(pid, select.KQ_FILTER_PROC, select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                              select.KQ_NOTE_EXIT)
        try:
            queue.control([watch], 1, None)
        except ProcessLookupError:
            pass  # already gone: that is the event we wanted
        finally:
            queue.close()
        return
    fd = os.pidfd_open(pid)
    try:
        select.select([fd], [], [])
    finally:
        os.close(fd)


def make_fifo(directory: Path, name: str) -> str:
    path = str(directory / name)
    os.mkfifo(path)
    return path


def fire(fifo: str) -> None:
    """Release a command blocked on ``cat FIFO``: open for write and close (EOF)."""
    os.close(os.open(fifo, os.O_WRONLY))


def read_line(fifo: str) -> str:
    """Block until a writer sends one line on ``fifo``."""
    with open(fifo, encoding="utf-8") as handle:
        return handle.readline().strip()

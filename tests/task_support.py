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

import task_proc  # noqa: E402,F401
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
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return  # already gone (and reaped): that is the event we wanted
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


def blocked_task(state: Path, key: str):
    """Start a task whose command announces itself, then blocks. Returns (started, hold, command_pid).

    The shell ``exec``s into ``cat``: the announced pid is the one process blocked on the fifo, so
    waiting for that pid to exit waits for the blocker itself and no child of it can outlive it.
    """
    hold, ready = make_fifo(state, f"{key}.hold"), make_fifo(state, f"{key}.ready")
    started = tasks.start("unit", key, ["sh", "-c", f"echo $$ > {ready}; exec cat {hold} >/dev/null"], str(state))
    return started, hold, int(read_line(ready))  # the line proves: running record written, command alive

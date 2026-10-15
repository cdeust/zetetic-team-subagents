"""task_proc.py -- is a process alive, dead, or unknown? (docs/async-tasks.md, "Staleness").

Three outcomes, never two. A probe that cannot answer raises ``LivenessUnknown``;
it is never read as "dead", because a dead verdict reaps a live worker and
launches a second one.

Backends, chosen by platform, never by trying commands until one works:
  Linux   /proc/<pid>/stat: state is field 3, starttime (clock ticks since boot,
          unaffected by wall-clock steps) is field 22, process group is field 5.
          Parsed after the LAST ')' because the command name (field 2) may hold
          spaces and parentheses (proc(5)).
  Darwin  ps(1) ``lstart,stat`` / ``pgid,stat`` (macOS ships a ps with both).
  other   no backend: ``LivenessUnknown`` naming the platform.

Stdlib only, Python >= 3.9.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import NamedTuple


PLATFORM = sys.platform  # source: sys.platform at import; a module attribute so tests can name another platform


class LivenessUnknown(RuntimeError):
    """The platform offers no way to tell whether a process is alive."""


class ProcInfo(NamedTuple):
    token: str  # identifies the process incarnation, so a reused pid is not mistaken for it
    state: str  # first letter 'Z' marks a zombie (exited, not yet reaped)


def _backend() -> str:
    """Post: 'linux' | 'darwin'; else raises LivenessUnknown naming the platform."""
    if PLATFORM == "darwin":
        return "darwin"
    if PLATFORM.startswith("linux") and os.path.exists("/proc/self/stat"):
        return "linux"
    raise LivenessUnknown(
        f"cannot tell whether a process is alive on platform {PLATFORM!r}: "
        "need /proc/<pid>/stat (Linux) or ps -o lstart,stat (macOS)")


class _Stat(NamedTuple):
    state: str
    pgrp: int
    starttime: str


def parse_proc_stat(text: str) -> _Stat:
    """Pre: ``text`` is the content of /proc/<pid>/stat. Post: fields 3, 5, 22.

    Everything before the last ')' is "pid (comm" and is skipped; the fields
    after it are space-separated and start at field 3 (state).
    """
    rest = text[text.rindex(")") + 1:].split()
    # source: proc(5): after ')' the fields are 3 state, 4 ppid, 5 pgrp, ..., 22 starttime -> indexes 0, 2, 19
    return _Stat(state=rest[0], pgrp=int(rest[2]), starttime=rest[19])


def _read_stat(pid: int) -> _Stat | None:
    """The stat of ``pid``; None iff the process does not exist."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
            return parse_proc_stat(handle.read())
    except (FileNotFoundError, ProcessLookupError):
        return None  # FAILS_ON: the process exited, or /proc hides it from us (callers disambiguate)


def _ps(args: list[str]) -> str:
    try:
        probe = subprocess.run(["ps", *args], capture_output=True, text=True, check=False,
                               env={**os.environ, "LC_ALL": "C"})
    except FileNotFoundError as exc:
        raise LivenessUnknown(f"cannot tell whether a process is alive on platform {PLATFORM!r}: "
                              "ps is not installed") from exc
    return probe.stdout


def proc_info(pid: int) -> ProcInfo | None:
    """Post: ProcInfo of ``pid``; None iff no such process; LivenessUnknown if the platform cannot say."""
    if _backend() == "linux":
        stat = _read_stat(pid)
        return None if stat is None else ProcInfo(stat.starttime, stat.state)
    parts = _ps(["-o", "lstart=,stat=", "-p", str(pid)]).split()
    return ProcInfo(" ".join(parts[:-1]), parts[-1]) if len(parts) >= 2 else None


def proc_token(pid: int) -> str | None:
    info = proc_info(pid)
    return info.token if info else None


def is_alive(pid: int | None, token: str | None) -> bool:
    """True iff ``pid`` is a running (not zombie) process of the recorded incarnation.

    Pre: ``token`` is the proc_token recorded for the process, or None to skip the
    identity check. Raises LivenessUnknown when the process exists but the
    platform cannot describe it (never answers False for "unknown").
    """
    if pid is None:
        return False
    foreign = False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        foreign = True  # exists, owned by someone else
    info = proc_info(pid)
    if info is None:
        if foreign:
            raise LivenessUnknown(f"pid {pid} exists but its start time is not readable here")
        return False  # exited between kill(2) and the read
    if info.state.startswith("Z"):
        return False
    return token is None or info.token == token


def _group_members(pgid: int) -> list[tuple[int, str]]:
    """(pid, state) of every process whose group is ``pgid``."""
    if _backend() == "darwin":
        rows = [line.split() for line in _ps(["-A", "-o", "pid=,pgid=,stat="]).splitlines()]
        return [(int(row[0]), row[2]) for row in rows if len(row) == 3 and row[1] == str(pgid)]
    members = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            stat = _read_stat(int(name))
        except PermissionError:
            continue  # FAILS_ON: stat unreadable; the kill(2) probe in group_alive already saw the group
        if stat is not None and stat.pgrp == pgid:
            members.append((int(name), stat.state))
    return members


def group_alive(pgid: int | None, leader: int | None = None) -> bool:
    """True iff some non-zombie process other than ``leader`` is in process group ``pgid``.

    A killed worker leaves its command running in the worker's group; that
    command is a live process nobody supervises. ``leader`` (the worker's own
    pid) is excluded: a worker that has just written its terminal state and is
    still exiting is not an orphan. Zombies do not count: they have exited and
    only await their (possibly never-reaping) parent.
    """
    if pgid is None:
        return False
    foreign = False
    try:
        os.kill(-pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        foreign = True
    members = _group_members(pgid)
    if any(pid != leader and not state.startswith("Z") for pid, state in members):
        return True
    if foreign and not members and _backend() == "linux":
        # kill(2) says the group exists but /proc (hidepid) shows no member: unknown, not dead.
        # (macOS answers EPERM for a group holding only zombies; there ps -A sees every process.)
        raise LivenessUnknown(f"process group {pgid} exists but its members are not readable here")
    return False

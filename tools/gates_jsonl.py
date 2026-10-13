#!/usr/bin/env python3
"""gates_jsonl.py -- the append-only JSONL ledger contract shared by the gates.

Extracted from ``reflection_ledger.py`` when the per-task cycle ledger
(``cycle_ledger.py``) became its second user. The contract, unchanged:
  * one JSON object per line, one file per repository and per purpose, under
    ``<git-common-dir>/zetetic-gates/`` (beside ``failures.jsonl`` written by
    ``scripts/gate.sh``), so every worktree of a repository shares it;
  * the file only ever grows by whole lines, written with one O_APPEND write so
    concurrent hook processes never interleave inside a line; no row is rewritten;
  * mode 0600: rows quote transcripts, which Claude Code writes owner-only;
  * a torn or undecodable line is skipped and never hides the rows after it;
  * a writer that must read before it appends (one open task per agent) holds
    ``locked(path)``, an exclusive OS lock on the sibling ``<file>.lock``.

Pre: ``cwd`` is a directory inside a git work tree for ``ledger_path``.
Post: see each function.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import subprocess
import time
from typing import Dict, Iterator, List, Optional

try:
    import fcntl
except ImportError:  # Windows has no fcntl; hooks run natively there (README "Windows prerequisites")
    fcntl = None  # type: ignore[assignment]
    import msvcrt

LEDGER_DIR = "zetetic-gates"
# Rows carry transcript excerpts, which Claude Code writes owner-only; the
# ledger must not be wider. source: ls -l ~/.claude/projects/*/*.jsonl
# (-rw-------) and CodeQL py/overly-permissive-file alert #45 on PR #153.
LEDGER_FILE_MODE = 0o600
# One git rev-parse is local and instant; the bound only stops a wedged git
# from wedging the hook. source: stop-gate-ledger.py _GIT_TIMEOUT (8 s).
GIT_TIMEOUT_S = 8
# A lock holder does one ledger read and one append; the bound only stops a
# wedged peer from wedging the hook, and equals the git bound for the same
# reason. source: GIT_TIMEOUT_S above.
LOCK_TIMEOUT_S = GIT_TIMEOUT_S
# Poll period while another hook process holds the lock. source: chosen, not
# measured: a free lock is taken on the first try, so the period only matters
# under contention, where a holder's read and append take milliseconds.
LOCK_POLL_S = 0.01


class LedgerError(Exception):
    """The ledger cannot be located, read or written; the caller must report it."""


class LockTimeout(LedgerError):
    """The ledger lock was still held after LOCK_TIMEOUT_S."""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def text(value: object) -> str:
    """A payload field as stripped text; anything but a string is empty."""
    return value.strip() if isinstance(value, str) else ""


def git(cwd: str, *args: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run ``git <args>`` in ``cwd``, bounded by GIT_TIMEOUT_S; the caller reads
    the return code. Raises LedgerError when git cannot be run at all."""
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_S, check=False, input=stdin,
                              stdin=None if stdin is not None else subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LedgerError(f"git could not be run in {cwd!r}: {exc}") from exc


def git_common_dir(cwd: str) -> str:
    """Absolute git common dir of the repository containing ``cwd``.

    Post: returns the path, or raises LedgerError naming why not.
    """
    proc = git(cwd, "rev-parse", "--git-common-dir")
    common = proc.stdout.strip()
    if proc.returncode != 0 or not common:
        raise LedgerError(f"{cwd!r} is not inside a git repository: {proc.stderr.strip()}")
    return os.path.normpath(os.path.join(cwd, common))


def ledger_path(cwd: str, name: str) -> str:
    """``<git-common-dir>/zetetic-gates/<name>`` for the repository of ``cwd``."""
    return os.path.join(git_common_dir(cwd), LEDGER_DIR, name)


def _parse_row(line: bytes) -> Optional[Dict]:
    try:
        row = json.loads(line.decode("utf-8"))
    except ValueError:  # includes UnicodeDecodeError
        return None  # a torn line is skipped, never allowed to hide the rest
    return row if isinstance(row, dict) else None


def read_rows(path: str) -> List[Dict]:
    """Every well-formed JSON object row; an absent file is an empty ledger."""
    try:
        with open(path, "rb") as fh:
            parsed = [_parse_row(line) for line in fh]
    except FileNotFoundError:
        return []
    except OSError as exc:  # FAILS_ON: ledger unreadable (permissions, a directory at the path)
        raise LedgerError(f"cannot read the ledger {path}: {exc}") from exc
    return [row for row in parsed if row is not None]


def append_row(path: str, row: Dict) -> None:
    """Append one whole line with a single write."""
    line = json.dumps(row, ensure_ascii=False) + "\n"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, LEDGER_FILE_MODE)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        raise LedgerError(f"cannot append to {path}: {exc}") from exc


def _try_lock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


def _unlock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _acquire(fd: int, lock_path: str) -> None:
    """Take the lock on ``fd``, polling until LOCK_TIMEOUT_S; LockTimeout after."""
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            _try_lock(fd)
            return
        except OSError as exc:  # held by another hook process
            if time.monotonic() >= deadline:
                raise LockTimeout(f"{lock_path} still held after {LOCK_TIMEOUT_S} s: {exc}") from exc
        time.sleep(LOCK_POLL_S)


@contextlib.contextmanager
def locked(path: str) -> Iterator[None]:
    """Hold an exclusive lock on ``<path>.lock`` for a read-then-append.

    The OS releases the lock when the process dies, so a killed hook leaves no
    stale lock. Raises LockTimeout when the lock cannot be taken within
    LOCK_TIMEOUT_S, LedgerError when the lock file cannot be opened."""
    lock_path = path + ".lock"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, LEDGER_FILE_MODE)
    except OSError as exc:
        raise LedgerError(f"cannot open the lock {lock_path}: {exc}") from exc
    try:
        _acquire(fd, lock_path)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)

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
  * a torn or undecodable line is skipped and never hides the rows after it.

Pre: ``cwd`` is a directory inside a git work tree for ``ledger_path``.
Post: see each function.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from typing import Dict, List, Optional

LEDGER_DIR = "zetetic-gates"
# Rows carry transcript excerpts, which Claude Code writes owner-only; the
# ledger must not be wider. source: ls -l ~/.claude/projects/*/*.jsonl
# (-rw-------) and CodeQL py/overly-permissive-file alert #45 on PR #153.
LEDGER_FILE_MODE = 0o600
# One git rev-parse is local and instant; the bound only stops a wedged git
# from wedging the hook. source: stop-gate-ledger.py _GIT_TIMEOUT (8 s).
GIT_TIMEOUT_S = 8


class LedgerError(Exception):
    """The ledger cannot be located, read or written; the caller must report it."""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def git_common_dir(cwd: str) -> str:
    """Absolute git common dir of the repository containing ``cwd``.

    Post: returns the path, or raises LedgerError naming why not.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=cwd, capture_output=True,
            text=True, timeout=GIT_TIMEOUT_S, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LedgerError(f"git could not be run in {cwd!r}: {exc}") from exc
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

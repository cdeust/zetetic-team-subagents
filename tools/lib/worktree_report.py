#!/usr/bin/env python3
"""worktree_report.py -- the session-start report of stale worktrees and branches. It deletes nothing.

Usage: worktree_report.py [REPO]     (via ``worktree-manager.sh report``)

Classifying a repo's branches (is the tip pushed, are its changes on main) runs
several git processes per branch. That is slow work, so it is a detached async
task (tools/lib/tasks.py, docs/async-tasks.md), never done here:

  1. key = hash of the repo's refs state (heads, remotes, worktree list);
  2. start-or-find the task ``wtclass-<key>`` running ``worktree-manager.sh sweep --dry-run``,
     the read-only mode of the very code the explicit sweep uses;
  3. print the finished result for this key, else "classification running" and
     the last finished result it printed for an earlier refs state. Nothing waits.

The report names what the explicit ``sweep`` would clean and the exact command.
Cleaning is never done at session start: a boot hook that deletes work is the
defect this replaces (a real sweep deleted six local branches on 2026-10-15).

Contract:
  pre : REPO is a directory (a non-repo prints one line).
  post: prints to stdout, exits 0, changes no ref, worktree or file of REPO;
        the only writes are the task record and output under the repo's
        ``<git-common-dir>/zetetic-tasks/``. No decision reads a clock.
"""
from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import task_proc as proc  # noqa: E402
import task_store as store  # noqa: E402
import tasks  # noqa: E402

KIND = "wtclass"
MANAGER = os.path.join(os.path.dirname(HERE), "worktree-manager.sh")
WOULD = "  would "


def _git(repo: str, *args: str) -> str | None:
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    return done.stdout if done.returncode == 0 else None


def refs_key(repo: str) -> str | None:
    """Hash of the refs state the classification depends on; None when REPO is not a git repo."""
    refs = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/remotes")
    trees = _git(repo, "worktree", "list", "--porcelain")
    if refs is None or trees is None:
        return None
    return hashlib.sha256((refs + "\0" + trees).encode()).hexdigest()[:40]  # source: 160 bits, within task_store KEY_RE's 128 chars


def stale_lines(rec: dict) -> list[str]:
    """The "would ..." lines of a finished dry-run, read from its full output file."""
    with open(rec["output_path"], encoding="utf-8", errors="replace") as handle:
        return [ln.rstrip("\n") for ln in handle if ln.startswith(WOULD)]


def render(lines: list[str], command: str, label: str = "") -> list[str]:
    if not lines:
        return [f"  nothing to clean{label}"]
    return [f"  stale: {ln[len(WOULD):]}{label}  -> run: {command}" for ln in lines]


def _pointer(repo: str) -> str:
    return os.path.join(store.tasks_dir(repo), f"latest-{KIND}-green.json")


def _last_printed_green(repo: str) -> dict | None:
    """The finished result most recently printed. A pointer, not a clock: the
    task module's ``latest`` moves to the new task the moment it starts."""
    seen = store.read_record(_pointer(repo))
    rec = tasks.status(seen["id"], repo) if seen else None
    return rec if tasks.is_green(rec) else None


def report(repo: str) -> list[str]:
    key = refs_key(repo)
    if key is None:
        return ["  (not a git repository)"]
    command = shlex.join(["bash", MANAGER, "sweep", repo])
    prior = _last_printed_green(repo)
    outcome = tasks.start(KIND, key, ["bash", MANAGER, "sweep", "--dry-run", repo], repo)
    rec = outcome.record
    if tasks.is_green(rec):
        store.atomic_write(_pointer(repo), {"id": rec["id"]})
        return render(stale_lines(rec), command)
    if rec["state"] == "failed" or outcome.disposition in ("stale", "orphaned"):
        why = rec.get("reason") or f"rc={rec.get('rc')}"
        return [f"  classification failed ({why}); run it by hand: bash {shlex.quote(MANAGER)} sweep --dry-run {shlex.quote(repo)}"]
    lines = ["  classification running (its result is printed at a later session start)"]
    if prior and prior["id"] != rec["id"]:
        lines += render(stale_lines(prior), command, label="  (earlier refs state)")
    return lines


def main(argv: list[str]) -> int:
    repo = os.path.abspath(argv[0]) if argv else os.getcwd()
    try:
        out = report(repo)
    except (proc.LivenessUnknown, OSError, ValueError) as exc:  # FAILS_ON: platform cannot prove liveness, state dir unwritable
        out = [f"  worktree report unavailable: {exc}"]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

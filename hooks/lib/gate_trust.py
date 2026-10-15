"""Which repositories may have their gate commands run on this machine.

A gate runs commands that the repository itself declares (`.zetetic/gate.json`, `scripts/gate.sh`, a
stack's test command), started by `git add`, with no prompt. In a repository whose owner you do not trust
that is code execution. So the worker runs only for repositories the USER listed:

    ~/.claude/zetetic/gate-trusted-repos     one absolute path per line; blank lines and `#` lines ignored

An unlisted repository that declares a gate is DENIED at commit/push with the exact line to add. There is
no silent pass and nothing is run. This module never writes the file: the user's trust is the user's act.

A path matches by its real path (symlinks resolved). A linked worktree matches through the repository it
belongs to (the parent of the git common dir), so listing the main checkout trusts its worktrees; a listed
worktree trusts that worktree only. ``ZETETIC_GATE_TRUSTED_REPOS`` replaces the file path (tests, and
non-default layouts); it is read from the environment of the user's session, never from a repository.
"""
from __future__ import annotations

import os

ENV_FILE = "ZETETIC_GATE_TRUSTED_REPOS"  # source: path override of the trusted-repos file, as ZETETIC_TASKS_DIR is for the task state


def trusted_file() -> str:
    return os.environ.get(ENV_FILE) or os.path.join(os.path.expanduser("~"), ".claude", "zetetic", "gate-trusted-repos")


def listed() -> set:
    """Real paths named in the trusted-repos file; an absent or unreadable file lists nothing. Only absolute
    lines count: a relative one would mean a different directory for every caller."""
    try:
        with open(trusted_file(), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return set()
    entries = (line.strip() for line in lines)
    return {os.path.realpath(e) for e in entries if os.path.isabs(e)}  # relative lines and `#` comments name no repository


def repo_root(top: str, common: str) -> str:
    """The checkout that owns ``common``: its parent when ``common`` is a `.git` directory, else ``top``."""
    return os.path.dirname(common) if os.path.basename(common) == ".git" else top


def is_trusted(top: str, common: str) -> bool:
    names = listed()
    return os.path.realpath(top) in names or os.path.realpath(repo_root(top, common)) in names


def refusal(top: str, common: str) -> str:
    line = os.path.realpath(repo_root(top, common))
    return (f"GATE-PROOF: {top} declares a gate, so verifying it would run commands written in that repository, "
            f"and the repository is not in your trusted list. Nothing was run.\n"
            f"If you trust it, add this line to {trusted_file()} (create the file if it is absent):\n"
            f"{line}\n"
            f"Then retry. See docs/gate.md (trusted repositories).")

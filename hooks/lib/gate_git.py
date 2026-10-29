"""The git calls on the gate's hot path (the PreToolUse/PostToolUse/Stop hooks), bounded by construction.

There is no timer anywhere in this module: no call can wait on the network, and none scans the working
tree. What bounds each call is what it reads:

  rev-parse --show-toplevel --git-common-dir   refs/config only
  write-tree                                   the index file -> tree objects (no stat of the working tree)
  rev-parse --verify HEAD^{tree} / HEAD^^{tree}  one ref + one commit object
  rev-parse @{u}                               two refs
  hash-object -t tree --stdin                  hashes empty stdin; writes nothing

``GIT_NO_LAZY_FETCH=1`` forbids a partial clone from fetching a missing object, ``GIT_OPTIONAL_LOCKS=0``
stops read-only commands from taking the index lock, ``GIT_TERMINAL_PROMPT=0`` forbids a credential
prompt. Anything that can be slow (the changed-file list, the checkout of the tree, the checks) runs in
the gate task (gate_run.py), never here.

``run`` is the ONE place a git process of the gate is started, the worker's included (gate_run, gate_source),
and every call reads the objects that are really there. git substitutes objects when told to: a replace ref
(``git replace``, in ``refs/replace/`` or in the namespace ``GIT_REPLACE_REF_BASE`` names) stands for another
object, so the blob of ``.zetetic/gate.json`` could read as ``{"off": true}`` and a checked file as clean content;
a graft (``.git/info/grafts``, or the file ``GIT_GRAFT_FILE`` names) gives a commit other parents, so the base a
change is measured from moves. ``SAME_OBJECTS`` turns both off (``GIT_NO_REPLACE_OBJECTS=1`` disables every
replace ref, whatever its namespace; grafts are read from the null device, which is empty) and
``GIT_REPLACE_REF_BASE`` is removed from the environment as well. Measured on git 2.50.1: with a replace ref the
blob reads as the substitute and with ``GIT_NO_REPLACE_OBJECTS=1`` as the original, under ``GIT_REPLACE_REF_BASE``
too; ``GIT_NO_REPLACE_OBJECTS=1`` leaves grafts in force and ``GIT_GRAFT_FILE`` set to the null device removes them.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import NamedTuple

TREE_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
BOUNDS = {"GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}  # source: the hot-path bounds above
SAME_OBJECTS = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_GRAFT_FILE": os.devnull}  # source: git(1) ENVIRONMENT; measured above
DROPPED = frozenset({"GIT_REPLACE_REF_BASE"})  # source: git(1) ENVIRONMENT, the replace-ref namespace


class Unavailable(Exception):
    """git is missing or the repository cannot be read; callers refuse (closed by default)."""


class Repo(NamedTuple):
    top: str
    common: str  # absolute git common dir


def environment(base: dict | None = None, bounded: bool = True) -> dict:
    """The environment of a git process of the gate: ``base`` (default: ours) without ``DROPPED``, with
    ``SAME_OBJECTS`` always and ``BOUNDS`` on the hot path (``bounded``; the worker may fetch, it is not there)."""
    kept = {k: v for k, v in (os.environ if base is None else base).items() if k not in DROPPED}
    return {**kept, **(BOUNDS if bounded else {}), **SAME_OBJECTS}


def run(directory: str, args: list, env: dict | None = None, text: bool = True,
        bounded: bool = True) -> subprocess.CompletedProcess:
    """Run ``git ARGS`` in ``directory`` with ``environment(env, bounded)``; output as text or bytes.
    Raises Unavailable when git cannot be started."""
    try:
        return subprocess.run(["git", *args], cwd=directory, capture_output=True, text=text, check=False,
                              stdin=subprocess.DEVNULL, env=environment(env, bounded))
    except OSError as exc:  # FAILS_ON: git not installed / not executable / cwd vanished
        raise Unavailable(exc.__class__.__name__) from exc


def git(directory: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run git in ``directory`` on the hot path, output as text. ``env`` replaces the inherited environment (the
    worker passes one without GIT_*, so a stray GIT_DIR cannot redirect the plumbing)."""
    return run(directory, list(args), env)


def locate(directory: str) -> Repo | None:
    """The repository containing ``directory``, or None when it is not inside one."""
    out = git(directory, "rev-parse", "--show-toplevel", "--git-common-dir")
    lines = out.stdout.strip().splitlines()
    if out.returncode != 0 or len(lines) != 2:
        return None
    top, common = lines
    return Repo(top, common if os.path.isabs(common) else os.path.normpath(os.path.join(directory, common)))


def staged_tree(top: str) -> str:
    """The tree the next ``git commit`` would record. Raises Unavailable (e.g. unmerged index)."""
    out = git(top, "write-tree")
    tree = out.stdout.strip()
    if out.returncode != 0 or not TREE_RE.match(tree):
        raise Unavailable("cannot compute the staged tree: " + out.stderr.strip()[:200])
    return tree


def tree_of(top: str, rev: str) -> str | None:
    """The tree of ``rev`` (e.g. ``HEAD``, ``HEAD^``), or None when that revision does not exist."""
    out = git(top, "rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}")
    tree = out.stdout.strip()
    return tree if out.returncode == 0 and TREE_RE.match(tree) else None


def head_ahead_of_upstream(top: str) -> bool:
    """True when HEAD exists, has an upstream, and differs from it. No upstream: not counted as ahead."""
    head = git(top, "rev-parse", "--verify", "--quiet", "HEAD")
    upstream = git(top, "rev-parse", "--verify", "--quiet", "@{u}")
    return head.returncode == 0 and upstream.returncode == 0 and head.stdout.strip() != upstream.stdout.strip()


def empty_tree(top: str) -> str:
    """The hash of the empty tree in this repository's object format (computed, nothing written)."""
    return git(top, "hash-object", "-t", "tree", "--stdin").stdout.strip()

#!/usr/bin/env python3
"""The gate task's command: verify ONE tree, exactly as committed, and exit 0 only if every check passed.

    gate_run.py run --repo TOP --tree TREE --base BASE|- --kind commit|push

Started detached by tools/lib/tasks.py as task `gate-<TREE>` (hooks/lib/gate_state.py); its stdout/stderr
are the task's output file. Contract:

  pre   TREE is a tree object of the repository at TOP; BASE is the tree the change is measured from
        (`-`: the empty tree).
  post  exit 0  <=> every selected check passed on the files of TREE.
        The checks run in a private checkout of TREE (never in the working tree), so a verdict is a
        function of TREE alone: editing the working tree while this runs cannot change it.
        The checkout is removed on every exit path.

Which checks run is hooks/lib/gate_config.plan(): the repo's `.zetetic/gate.json` read FROM TREE,
else the legacy `scripts/gate.sh`, else the stack's whole suite.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_config as config  # noqa: E402
import gate_git as gitq  # noqa: E402

_PY_NAMES = (os.path.join("bin", "python"), os.path.join("Scripts", "python.exe"))


def _say(text: str) -> None:
    print(text, flush=True)


def _git(top: str, args: list, env: dict | None = None) -> bytes:
    out = subprocess.run(["git", "-C", top, *args], env=env, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.decode(errors='replace').strip()}")
    return out.stdout


def changed_files(top: str, base: str, tree: str) -> list:
    """Paths that differ between the two trees (additions, modifications, deletions), repo-relative."""
    base = gitq.empty_tree(top) if base == "-" else base
    raw = _git(top, ["diff-tree", "-r", "--name-only", "--no-renames", "-z", base, tree])
    return [os.fsdecode(p) for p in raw.split(b"\0") if p]


def materialize(top: str, tree: str, dest: str) -> None:
    """Check ``tree`` out into the empty directory ``dest`` through a private index (the real index is untouched)."""
    index = dest + ".index"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_INDEX_FILE"] = index
    try:
        _git(top, ["read-tree", tree], env)
        _git(top, ["checkout-index", "--all", "--force", f"--prefix={dest}/"], env)
    finally:
        if os.path.exists(index):
            os.unlink(index)
    subprocess.run(["git", "-C", dest, "init", "-q"], check=False, capture_output=True)  # tools that expect a repo


def resolve_python(top: str, common: str) -> str:
    """The checkout's own venv python, else the main checkout's (a linked worktree has none), else ours."""
    for base in (top, os.path.dirname(common)):
        for name in _PY_NAMES:
            cand = os.path.join(base, ".venv", name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return sys.executable


def _substitute(argv: list, python: str) -> list:
    return [python if token == config.PY else token for token in argv]


def _check_env(extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return {**env, **extra}


def execute(steps: list, cwd: str, python: str, extra_env: dict | None = None) -> int:
    """Run each step in ``cwd``; stop at the first failure. 0 only if all passed."""
    env = _check_env(extra_env or {})
    for step in steps:
        argv = _substitute(step.argv, python)
        _say(f"[gate:{step.name}] {' '.join(argv)}")
        try:
            rc = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, check=False).returncode
        except OSError as exc:  # FAILS_ON: the check's command is missing or not executable
            _say(f"[gate:{step.name}] cannot start: {exc!r}")
            rc = 127
        if rc != 0:
            _say(f"[gate:{step.name}] FAILED rc={rc}")
            return rc if rc > 0 else 1
    return 0


def _plan_for(snap: str, top: str, args: argparse.Namespace) -> tuple[dict, list, str]:
    """(config, steps, cwd) for the tree checked out in ``snap``; config {} when nothing is declared."""
    kind = config.declaration(snap)
    if kind == "legacy":  # the repo's own script judges the real checkout (it needs .git); see docs/gate.md
        return {}, [config.Step("legacy-gate", ["sh", config.LEGACY_SCRIPT, args.kind])], top
    if kind is None:
        _say("[gate] no gate is declared for this tree: nothing to verify")
        return {}, [], snap
    cfg = config.load(snap) or config.stack_config(snap)
    changed = changed_files(top, args.base, args.tree)
    _say(f"[gate] {len(changed)} changed path(s) against {args.base[:12]}: {' '.join(changed[:20])}")
    steps = config.plan(cfg, snap, changed)
    if not steps:
        _say("[gate] no check applies to this change")
    return cfg, steps, snap


def _link(top: str, snap: str, paths: list) -> None:
    """Symlink untracked dependency directories from the checkout into the private one (never overwrite)."""
    for rel in paths:
        source, target = os.path.join(top, rel), os.path.join(snap, rel)
        if os.path.exists(source) and not os.path.lexists(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.symlink(source, target)


def _snapshot_dir(tree: str, common: str) -> str:
    """A fresh private directory named by (tree, repository). A leftover of an attempt that was SIGKILLed
    (nothing can clean up after that) is replaced: the task layer starts a new attempt only once the
    previous one's process group is gone, so the leftover has no owner."""
    owner = hashlib.sha1(os.path.realpath(common).encode()).hexdigest()[:8]
    path = os.path.join(tempfile.gettempdir(), f"zetetic-gate-{tree[:16]}-{owner}")
    shutil.rmtree(path, ignore_errors=True)
    os.mkdir(path)
    return path


def run(args: argparse.Namespace) -> int:
    top = args.repo
    repo = gitq.locate(top)
    if repo is None:
        _say(f"[gate] {top} is not a git repository")
        return 1
    snap = _snapshot_dir(args.tree, repo.common)
    try:
        materialize(top, args.tree, snap)
        cfg, steps, cwd = _plan_for(snap, top, args)
        env, links = config.setup_for(cfg, top, repo.common)
        _link(top, snap, links)
        return execute(steps, cwd, resolve_python(top, repo.common), env)
    except (config.ConfigError, RuntimeError) as exc:  # FAILS_ON: invalid gate config in the tree, or git could not read it
        _say(f"[gate] {exc}")
        return 1
    finally:
        shutil.rmtree(snap, ignore_errors=True)


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="gate_run.py")
    sub = parser.add_subparsers(dest="verb", required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--repo", required=True)
    runner.add_argument("--tree", required=True)
    runner.add_argument("--base", required=True)
    runner.add_argument("--kind", choices=("commit", "push"), required=True)
    args = parser.parse_args(argv)
    if not gitq.TREE_RE.match(args.tree) or (args.base != "-" and not gitq.TREE_RE.match(args.base)):
        parser.error("--tree and --base must be tree hashes")
    return run(args)


def _lower_priority() -> None:
    if hasattr(os, "nice"):
        os.nice(10)  # the verification must not starve the session that started it


if __name__ == "__main__":
    _lower_priority()
    sys.exit(main(sys.argv[1:]))

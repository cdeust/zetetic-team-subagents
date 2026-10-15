"""Scratch repositories and a git shim for the worktree sweep and boot-report tests.

Every repository lives under pytest's tmp_path. Nothing here touches a real
checkout. Nothing sleeps, polls or times out: the shim logs each git call so a
test can say "this command was never run".
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGER = Path(os.environ.get("SWEEP_MANAGER", ROOT / "tools" / "worktree-manager.sh"))
REAL_GIT = shutil.which("git")

SHIM = """#!/bin/bash
echo "$*" >> "$GIT_LOG"
exec "$REAL_GIT" "$@"
"""


def git(repo, *args):
    done = subprocess.run([REAL_GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """A repo whose main holds f.txt; origin/main is simulated by a remote-tracking ref."""
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    git(repo, "remote", "add", "origin", str(repo))  # a configured remote, as in every real clone
    write_commit(repo, "f.txt", "x y\n", "base")
    publish(repo, "main")
    return repo


def write_commit(repo, name: str, text: str, message: str) -> str:
    (Path(repo) / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def publish(repo, branch: str) -> None:
    """Pretend `git push origin <branch>`: the remote-tracking ref now holds the tip."""
    git(repo, "update-ref", f"refs/remotes/origin/{branch}", f"refs/heads/{branch}")


def branch_from_base(repo, branch: str, name: str, text: str) -> None:
    """A local branch off main with one commit that rewrites <name>; main is checked out again."""
    git(repo, "checkout", "-q", "-b", branch, "main")
    write_commit(repo, name, text, f"work on {branch}")
    git(repo, "checkout", "-q", "main")


def shimmed_env(tmp_path: Path, **extra) -> dict:
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "git"
    shim.write_text(SHIM)
    shim.chmod(0o755)
    log = tmp_path / "git.log"
    env = {**os.environ, "REAL_GIT": REAL_GIT, "GIT_LOG": str(log), "WORKTREE_GRACE_SECONDS": "0",
           "WORKTREE_AUDIT_LOG": str(tmp_path / "audit.log"), **extra}
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    return env


def git_calls(tmp_path: Path) -> list:
    log = tmp_path / "git.log"
    return log.read_text().splitlines() if log.exists() else []


def sweep(repo, tmp_path: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(MANAGER), "sweep", *flags, str(repo)], env=shimmed_env(tmp_path),
                          capture_output=True, text=True, check=False)


def heads(repo) -> dict:
    out = git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")
    return dict(line.split(" ") for line in out.splitlines())


def worktrees(repo) -> list:
    return [ln for ln in git(repo, "worktree", "list", "--porcelain").splitlines() if ln.startswith("worktree ")]


def mutating(calls: list) -> list:
    """The git calls that delete a branch, a worktree or a ref (the proof ref excepted)."""
    bad = []
    for call in calls:
        words = call.split()
        if "branch" in words and ("-d" in words or "-D" in words or "--delete" in words):
            bad.append(call)
        elif "worktree" in words and "remove" in words:
            bad.append(call)
        elif "update-ref" in words and "-d" in words and not any("refs/zetetic-sweep/" in w for w in words):
            bad.append(call)
    return bad

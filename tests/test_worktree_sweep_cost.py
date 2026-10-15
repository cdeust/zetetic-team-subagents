"""`worktree-manager.sh sweep` costs the same number of git processes however long main is.

Measured 2026-10-15: session-start's 8 s budget was spent by the `worktrees`
section, whose MAIN process was still running (not a leftover descendant):
for every branch not merged into origin/main, the squash-merge test forked
`git diff` + `git patch-id` once per main commit since the merge-base, up to
a 500-commit scan limit (Cortex: 31 branches, 94 s). The patch-id test is gone
(it also deleted unpreserved work, see test_worktree_sweep_preserve.py); the
changes-on-main proof is one `git merge-tree` per branch, so the cost cannot
depend on the length of main and there is no scan limit.

The test decides by counting git invocations (a wrapper on PATH), never by
elapsed time: the count for a main of 3 commits and for a main of 30 must be
equal, one merge-tree per pushed unmerged branch, no log -p and no patch-id.
"""

from pathlib import Path
import os
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "tools" / "worktree-manager.sh"
BRANCHES = 4  # source: any number > 1 shows a per-branch scan repeated; kept small for speed
SHORT_MAIN, LONG_MAIN = 3, 30  # source: two lengths that differ by an order of magnitude


pytestmark = pytest.mark.spawns  # leak guard applies (tests/conftest.py)


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _repo(tmp_path, main_commits):
    repo = tmp_path / f"repo{main_commits}"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    for n in range(BRANCHES):  # unmerged branches: their diff matches nothing, so the scan runs in full
        _git(repo, "checkout", "-q", "-b", f"feat/{n}", "main")
        (repo / f"f{n}.txt").write_text(f"branch {n}\n")
        _git(repo, "add", f"f{n}.txt")
        _git(repo, "commit", "-q", "-m", f"branch {n}")
        _git(repo, "checkout", "-q", "main")
    for n in range(BRANCHES):  # pushed, so the changes-on-main proof runs for each
        _git(repo, "update-ref", f"refs/remotes/origin/feat/{n}", f"refs/heads/feat/{n}")
    for n in range(main_commits):
        (repo / f"m{n}.txt").write_text(f"main {n}\n")
        _git(repo, "add", f"m{n}.txt")
        _git(repo, "commit", "-q", "-m", f"main {n}")
    _git(repo, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    return repo


def _git_invocations(tmp_path, repo):
    real = subprocess.run(["which", "git"], check=True, capture_output=True, text=True).stdout.strip()
    log = tmp_path / f"calls{repo.name}"
    log.write_text("")
    wrapper = tmp_path / "bin" / "git"
    wrapper.parent.mkdir(exist_ok=True)
    wrapper.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{log}"\nexec "{real}" "$@"\n')
    wrapper.chmod(0o755)
    env = {**os.environ, "PATH": f"{wrapper.parent}:{os.environ['PATH']}",
           "WORKTREE_AUDIT_LOG": str(tmp_path / "audit.log")}
    done = subprocess.run(["bash", str(MANAGER), "sweep", str(repo)], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "branches deleted: 0" in done.stdout  # the branches really were unmerged: each was proven in full
    calls = log.read_text().splitlines()
    assert not any(" log -p " in f" {c} " or "patch-id" in c for c in calls), calls  # no patch-id scan of main
    assert sum("merge-tree" in c for c in calls) == BRANCHES, calls  # one proof per branch, not per main commit
    return len(calls)


def test_sweep_git_invocations_do_not_scale_with_main_length(tmp_path):
    short = _git_invocations(tmp_path, _repo(tmp_path, SHORT_MAIN))
    long_ = _git_invocations(tmp_path, _repo(tmp_path, LONG_MAIN))
    assert long_ == short, f"sweep forked {short} git processes for {SHORT_MAIN} main commits but {long_} for {LONG_MAIN}"


def _sweep(repo, tmp_path):
    env = {**os.environ, "WORKTREE_AUDIT_LOG": str(tmp_path / "audit.log")}
    return subprocess.run(["bash", str(MANAGER), "sweep", str(repo)], env=env, capture_output=True, text=True).stdout


def _commit_file(repo, name, text, message):
    (repo / name).write_text(text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)


def test_change_that_predates_the_merge_base_is_not_a_squash_merge(tmp_path):
    """A branch re-adding what main once had and removed is NOT merged: the match must lie after its merge-base."""
    repo = tmp_path / "revert"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _commit_file(repo, "a.txt", "same\n", "add a")
    _git(repo, "rm", "-q", "a.txt")
    _git(repo, "commit", "-q", "-m", "remove a")
    _git(repo, "checkout", "-q", "-b", "feat/readd", "main")
    _commit_file(repo, "a.txt", "same\n", "re-add a")
    _git(repo, "checkout", "-q", "main")
    _commit_file(repo, "later.txt", "later\n", "later")
    _git(repo, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    _git(repo, "update-ref", "refs/remotes/origin/feat/readd", "refs/heads/feat/readd")  # pushed: the tree check decides
    assert "branches deleted: 0" in _sweep(repo, tmp_path)


def test_squash_merged_branch_is_deleted(tmp_path):
    repo = tmp_path / "squash"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "feat/done", "main")
    _commit_file(repo, "b.txt", "b\n", "work")
    _git(repo, "checkout", "-q", "main")
    _commit_file(repo, "other.txt", "o\n", "other")
    _commit_file(repo, "b.txt", "b\n", "squash of feat/done")
    _commit_file(repo, "after.txt", "x\n", "after")
    _git(repo, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    _git(repo, "update-ref", "refs/remotes/origin/feat/done", "refs/heads/feat/done")  # pushed, not yet pruned
    assert "branches deleted: 1" in _sweep(repo, tmp_path)

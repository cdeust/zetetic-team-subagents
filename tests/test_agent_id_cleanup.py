"""Regression for the 2026-09-17 EXIT cleanup deleting caller worktrees.

Regression base: 77b4f78 (v2.41.0), whose EXIT trap iterated an empty
TARGETS array and removed every linked worktree of the current repository.
Measured with tools/fail-before-checker.sh --base 77b4f78 --files <this file>
on 2026-09-17: both cases fail there. Against db5f697 (#141, the guarded loop)
they pass, because that guard and the owned-directory trap of #140 are
observably equivalent: TARGETS stays empty in the parent shell, so only
rm -rf "$TMP" ever acts. A VACUOUS finding against a base at or after #141 is
therefore expected, not a defect of this test.
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def make_outer_repo(tmp_path):
    repo = tmp_path / "caller"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Cleanup Test")
    git(repo, "config", "user.email", "cleanup@example.com")
    (repo / "tracked.txt").write_text("original\n")
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "-qm", "fixture")
    sentinel = tmp_path / "unrelated-linked-worktree"
    git(repo, "worktree", "add", "--detach", str(sentinel))
    (sentinel / "tracked.txt").write_text("dirty tracked work\n")
    (sentinel / "untracked.txt").write_text("uncommitted work\n")
    return repo, sentinel


@pytest.mark.parametrize("spawn_fails", [False, True])
def test_cleanup_preserves_caller_worktrees(tmp_path, spawn_fails):
    repo, sentinel = make_outer_repo(tmp_path)
    scripts = repo / "scripts"
    scripts.mkdir()
    script = scripts / "test-agent-id-propagation.sh"
    shutil.copyfile(ROOT / "scripts" / script.name, script)
    agents = repo / "agents"
    agents.mkdir()
    for name in ("engineer", "feynman"):
        (agents / f"{name}.md").write_text("test agent\n")
    spawn = scripts / "spawn-agent.sh"
    spawn.write_text(
        "#!/usr/bin/env bash\n"
        + ("exit 1\n" if spawn_fails else 'MEMORY_AGENT_ID="$3" claude\n')
    )
    spawn.chmod(0o755)
    owned = tmp_path / "owned-temp"
    owned.mkdir()
    env = dict(os.environ, TMPDIR=str(owned), GIT_CONFIG_NOSYSTEM="1")
    env.update(GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com")
    env.update(GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
    before = git(repo, "worktree", "list", "--porcelain").stdout
    result = subprocess.run(
        ["bash", str(script)], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == int(spawn_fails), result.stdout + result.stderr
    assert sentinel.is_dir(), "EXIT cleanup deleted unrelated dirty worktree"
    assert (sentinel / "tracked.txt").read_text() == "dirty tracked work\n"
    assert (sentinel / "untracked.txt").read_text() == "uncommitted work\n"
    assert git(repo, "worktree", "list", "--porcelain").stdout == before
    assert list(owned.iterdir()) == [], "owned temporary repositories were leaked"

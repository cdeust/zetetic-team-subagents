"""The sweep's branch delete works on branches made the way real ones are, and never hides a refusal.

Review of #166 reproduced that `git checkout -b x origin/main` and
`git worktree add -b x origin/main` persist branch.x.remote=origin and
branch.x.merge=refs/heads/main. branch.<b>.merge is multi-valued, so the delete's
`-c branch.x.merge=<proof>` was appended after it, git resolved the upstream to local
main, and `git branch -d` refused a squash-merged tip as "not fully merged". The
dry run said "would delete", the sweep kept the branch, and on the worktree path the
refusal was swallowed. Every branch here is created WITH that upstream config
(sweep_support's other fixtures use a local start point, which has none).
"""
import os
import subprocess

import pytest

from sweep_support import MANAGER, REAL_GIT, git, git_calls, heads, make_repo, publish, shimmed_env, sweep, worktrees, write_commit

BRANCH = "feat/up"
SHIM_MOVES_THE_TIP = """#!/bin/bash
echo "$*" >> "$GIT_LOG"
if [[ " $* " == *" branch -d "* ]]; then
  tip="$("$REAL_GIT" -C "$MOVE_REPO" rev-parse "refs/heads/$MOVE_BRANCH")"
  GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@invalid \
    new="$("$REAL_GIT" -C "$MOVE_REPO" commit-tree "$tip^{tree}" -p "$tip" -m "added after the proof")"
  "$REAL_GIT" -C "$MOVE_REPO" update-ref "refs/heads/$MOVE_BRANCH" "$new"
fi
exec "$REAL_GIT" "$@"
"""


def tracked_via_checkout(repo):
    """`git checkout -b feat/up origin/main` + one commit; main checked out again."""
    git(repo, "checkout", "-q", "-b", BRANCH, "origin/main")
    write_commit(repo, "up.txt", "u\n", "work on feat/up")
    git(repo, "checkout", "-q", "main")
    return None


def tracked_via_worktree(repo):
    """`git worktree add -b feat/up <path> origin/main` + one commit in it; returns the worktree."""
    wt = repo / ".claude" / "worktrees" / "w"
    git(repo, "worktree", "add", "-q", "-b", BRANCH, str(wt), "origin/main")
    write_commit(wt, "up.txt", "u\n", "work on feat/up")
    return wt


def squash_merge(repo):
    """The squash lands on main, as GitHub leaves it: no merge commit, the tip is not an ancestor."""
    write_commit(repo, "up.txt", "u\n", "squash of feat/up")
    publish(repo, "main")
    publish(repo, BRANCH)  # its remote ref is still there: only the tracking config is under test


VIA = [pytest.param(tracked_via_checkout, id="checkout-b"), pytest.param(tracked_via_worktree, id="worktree-add-b")]


def world(tmp_path, via):
    repo = make_repo(tmp_path)
    wt = via(repo)
    squash_merge(repo)
    assert git(repo, "config", "--get-all", f"branch.{BRANCH}.merge") == "refs/heads/main", "the scenario is vacuous: no tracking"
    assert not subprocess.run([REAL_GIT, "-C", str(repo), "merge-base", "--is-ancestor", BRANCH, "origin/main"]).returncode == 0
    return repo, wt


def tracking(repo):
    done = subprocess.run([REAL_GIT, "-C", str(repo), "config", "--get-regexp", rf"^branch\.{BRANCH}\."],
                          capture_output=True, text=True, check=False)
    return done.stdout


def proofs(repo):
    return git(repo, "for-each-ref", "refs/zetetic-sweep")


@pytest.mark.parametrize("via", VIA)
def test_a_squash_merged_branch_with_persisted_tracking_is_deleted(tmp_path, via):
    repo, wt = world(tmp_path, via)
    run = sweep(repo, tmp_path)
    assert f"refs/heads/{BRANCH}" not in heads(repo), run.stdout
    assert "keep branch" not in run.stdout and "refused" not in run.stdout, run.stdout
    assert tracking(repo) == "" and proofs(repo) == ""
    assert wt is None or not wt.exists()


@pytest.mark.parametrize("via", VIA)
def test_dry_run_and_the_real_sweep_decide_alike(tmp_path, via):
    repo, _ = world(tmp_path, via)
    dry = sweep(repo, tmp_path, "--dry-run")
    would = "would delete branch" in dry.stdout or "would remove" in dry.stdout
    assert would, dry.stdout
    real = sweep(repo, tmp_path)
    assert (f"refs/heads/{BRANCH}" not in heads(repo)) == would, dry.stdout + real.stdout


def test_dry_run_and_the_real_sweep_both_keep_a_branch_checked_out_in_a_deliberate_worktree(tmp_path, unswept_dir):
    repo = make_repo(tmp_path)
    tracked_via_checkout(repo)
    squash_merge(repo)
    git(repo, "worktree", "add", "-q", str(unswept_dir / "deliberate-wt"), BRANCH)  # outside every swept path
    dry = sweep(repo, tmp_path, "--dry-run")
    real = sweep(repo, tmp_path)
    assert "would delete" not in dry.stdout and "would remove" not in dry.stdout, dry.stdout
    assert f"refs/heads/{BRANCH}" in heads(repo) and "deleted branch" not in real.stdout, real.stdout


def sweep_that_moves_the_tip(repo, tmp_path):
    """A sweep whose `git branch -d` finds a commit added to the branch since the proof."""
    env = shimmed_env(tmp_path, MOVE_REPO=str(repo), MOVE_BRANCH=BRANCH)
    shim = tmp_path / "shim" / "git"
    shim.write_text(SHIM_MOVES_THE_TIP)
    return subprocess.run(["bash", str(MANAGER), "sweep", str(repo)], env=env, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("via", VIA)
def test_a_refused_delete_is_reported_with_git_reason_and_leaves_the_config_exactly_as_it_was(tmp_path, via):
    repo, wt = world(tmp_path, via)
    before = tracking(repo)
    assert before.count("branch.feat/up.") == 2, before  # remote and merge
    run = sweep_that_moves_the_tip(repo, tmp_path)
    assert f"refs/heads/{BRANCH}" in heads(repo), run.stdout
    (line,) = [ln for ln in run.stdout.splitlines() if f"keep branch: {BRANCH}" in ln]
    assert "git branch -d refused it" in line and "not fully merged" in line, line
    assert tracking(repo) == before and proofs(repo) == ""
    if wt is not None:
        assert not wt.exists()  # the worktree was clean and preserved: it went, the branch stayed, and it said so


def dead_pid():
    done = subprocess.Popen(["true"])
    done.wait()
    return done.pid


def test_proof_refs_left_by_a_killed_sweep_are_purged_at_the_next_sweep_but_a_running_ones_is_not(tmp_path):
    repo = make_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    leftover = f"refs/zetetic-sweep/proof-{dead_pid()}-1"
    running = f"refs/zetetic-sweep/proof-{os.getpid()}-1"  # this test process is alive
    for ref in (leftover, running):
        git(repo, "update-ref", ref, head)
    dry = sweep(repo, tmp_path, "--dry-run")
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/zetetic-sweep").splitlines() == sorted([leftover, running]), dry.stdout
    sweep(repo, tmp_path)
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/zetetic-sweep").splitlines() == [running]
    assert not [c for c in git_calls(tmp_path) if "branch -D" in c]
    assert worktrees(repo)  # the repo itself is untouched

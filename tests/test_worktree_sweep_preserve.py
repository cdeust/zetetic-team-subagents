"""`worktree-manager.sh sweep` deletes a branch only when its work is provably kept elsewhere.

Review of #165 reproduced two ways the patch-id squash test destroyed work, each
deleted with `git branch -D`:
  (a) a local-only branch whose whitespace-only change patch-id-matches a
      DIFFERENT main commit (git patch-id ignores whitespace);
  (b) a branch squash-merged and then reverted on main: the matching commit is
      still in main's log, the work is not in main's tree.
A branch may go only when BOTH hold: its changes are on origin/main (ancestor, or a
clean no-op merge-tree, which already proves they are on the remote) and it is
checked out nowhere. Whether a remote ref still holds its tip is no condition: a
squash-merged branch whose remote ref was pruned is deleted too. The scenarios
here are built so each condition is, alone, the one that keeps the branch (a
mutation that drops the tree check must turn a test red).
"""
import subprocess

import pytest

from sweep_support import (branch_from_base, git, git_calls, heads, make_repo, mutating, publish, sweep,
                           worktrees, write_commit)

NOT_ON_MAIN = ("not all on origin/main", "not a clean no-op")


pytestmark = pytest.mark.spawns  # leak guard applies (tests/conftest.py)


def whitespace(repo):
    """(a): the branch's diff and main's later commit differ only in whitespace: same patch-id."""
    base = git(repo, "rev-parse", "main")
    branch_from_base(repo, "feat/ws", "f.txt", "x  y\n")
    other = write_commit(repo, "f.txt", "x   y\n", "different main commit, same change modulo whitespace")
    publish(repo, "main")
    ours = git(repo, "diff", base, "feat/ws")
    theirs = git(repo, "diff", base, other)
    ids = [_patch_id(repo, d) for d in (ours, theirs)]
    assert ids[0] == ids[1] != "", "the scenario is vacuous: the patch-ids differ"
    return "feat/ws"


def reverted(repo):
    """(b): squash-merged, then reverted: the commit is in main's log, the work is not in its tree."""
    branch_from_base(repo, "feat/rev", "b.txt", "b\n")
    write_commit(repo, "b.txt", "b\n", "squash of feat/rev")
    git(repo, "revert", "--no-edit", "HEAD")
    write_commit(repo, "later.txt", "later\n", "later")
    publish(repo, "main")
    assert not (repo / "b.txt").exists(), "the scenario is vacuous: the work is still on main"
    return "feat/rev"


def squashed(repo, name="b.txt"):
    """The case sweep exists for: squash-merged, work on main."""
    branch_from_base(repo, "feat/done", name, "b\n")
    write_commit(repo, name, "b\n", "squash of feat/done")
    write_commit(repo, "after.txt", "after\n", "after")
    publish(repo, "main")
    return "feat/done"


def _patch_id(repo, diff):
    done = subprocess.run(["git", "patch-id", "--stable"], input=diff + "\n", capture_output=True, text=True, check=False)
    return done.stdout.split(" ")[0]


@pytest.mark.parametrize("pushed", [False, True], ids=["local-only", "pushed"])
@pytest.mark.parametrize("scenario", [whitespace, reverted])
def test_a_branch_whose_work_is_not_on_main_is_kept_whatever_a_patch_id_says(tmp_path, scenario, pushed):
    repo = make_repo(tmp_path)
    branch = scenario(repo)
    if pushed:
        publish(repo, branch)
    tip = heads(repo)[f"refs/heads/{branch}"]
    run = sweep(repo, tmp_path)
    assert heads(repo).get(f"refs/heads/{branch}") == tip, run.stdout
    (line,) = [ln for ln in run.stdout.splitlines() if f"keep branch: {branch}" in ln]
    assert any(why in line for why in NOT_ON_MAIN), line
    assert not mutating(git_calls(tmp_path)), git_calls(tmp_path)


def test_a_squash_merged_branch_whose_remote_ref_is_gone_is_deleted(tmp_path):
    # `fetch --prune` after GitHub deletes the merged branch: no remote ref holds the
    # tip, yet the tree check proves the work is on origin/main (the remote).
    repo = make_repo(tmp_path)
    branch = squashed(repo)
    assert git(repo, "for-each-ref", f"refs/remotes/origin/{branch}") == ""
    run = sweep(repo, tmp_path)
    assert f"refs/heads/{branch}" not in heads(repo), run.stdout
    assert any(" branch -d " in f" {c} " for c in git_calls(tmp_path))


def test_a_pushed_squash_merged_branch_is_deleted_with_branch_d_never_D(tmp_path):
    repo = make_repo(tmp_path)
    branch = squashed(repo)
    publish(repo, branch)
    run = sweep(repo, tmp_path)
    assert f"refs/heads/{branch}" not in heads(repo), run.stdout
    calls = git_calls(tmp_path)
    assert any(" branch -d " in f" {c} " for c in calls), calls
    assert not any(" -D " in f" {c} " or "--force" in c for c in calls if "branch" in c.split()), calls
    assert git(repo, "for-each-ref", "refs/zetetic-sweep") == "", "the private proof ref was left behind"


def test_an_ancestor_of_main_that_is_pushed_is_deleted(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "branch", "feat/ff")
    write_commit(repo, "more.txt", "m\n", "main moves on")
    publish(repo, "main")
    run = sweep(repo, tmp_path)
    assert "refs/heads/feat/ff" not in heads(repo), run.stdout


def test_a_branch_checked_out_in_another_worktree_is_kept(tmp_path, unswept_dir):
    repo = make_repo(tmp_path)
    branch = squashed(repo)
    publish(repo, branch)
    deliberate = unswept_dir / "deliberate-wt"  # outside /tmp roots and .claude/worktrees: never swept
    git(repo, "worktree", "add", "-q", str(deliberate), branch)
    run = sweep(repo, tmp_path)
    assert f"refs/heads/{branch}" in heads(repo) and deliberate.is_dir(), run.stdout
    assert not mutating(git_calls(tmp_path))


@pytest.mark.parametrize("pushed", [False, True], ids=["local-only", "pushed"])
@pytest.mark.parametrize("scenario", [whitespace, reverted])
def test_a_worktree_whose_branch_is_not_preserved_is_kept_with_its_branch(tmp_path, scenario, pushed):
    repo = make_repo(tmp_path)
    branch = scenario(repo)
    if pushed:
        publish(repo, branch)
    wt = repo / ".claude" / "worktrees" / "w"
    git(repo, "worktree", "add", "-q", str(wt), branch)
    run = sweep(repo, tmp_path)
    assert wt.is_dir() and len(worktrees(repo)) == 2, run.stdout
    assert f"refs/heads/{branch}" in heads(repo)
    assert not mutating(git_calls(tmp_path))


def test_a_clean_worktree_with_a_preserved_branch_is_removed_with_it(tmp_path):
    repo = make_repo(tmp_path)
    branch = squashed(repo)
    publish(repo, branch)
    wt = repo / ".claude" / "worktrees" / "w"
    git(repo, "worktree", "add", "-q", str(wt), branch)
    run = sweep(repo, tmp_path)
    assert not wt.exists() and f"refs/heads/{branch}" not in heads(repo), run.stdout


@pytest.mark.parametrize("scenario", [whitespace, reverted, squashed])
def test_dry_run_changes_nothing_and_says_what_it_would_do(tmp_path, scenario):
    repo = make_repo(tmp_path)
    branch = scenario(repo)
    publish(repo, branch)
    wt = repo / ".claude" / "worktrees" / "w"
    git(repo, "worktree", "add", "-q", str(wt), branch)
    before = (heads(repo), worktrees(repo), git(repo, "for-each-ref"))
    run = sweep(repo, tmp_path, "--dry-run")
    assert (heads(repo), worktrees(repo), git(repo, "for-each-ref")) == before, run.stdout
    assert not mutating(git_calls(tmp_path)), git_calls(tmp_path)
    assert not (tmp_path / "audit.log").exists(), "a dry run wrote to the audit log"
    assert ("would remove" in run.stdout) == (scenario is squashed), run.stdout

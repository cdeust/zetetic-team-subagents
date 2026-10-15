"""A sweep that cannot prove ownership of a half-removed worktree deletes nothing.

hooks/lib/run_sections.py kills the boot sweep when it outlives its 8 s budget,
and `git worktree remove` is a recursive delete followed by the removal of the
worktree's admin directory. A kill in between leaves a registered worktree whose
checkout is partly gone, and the sweep's marker in its admin directory. The next
sweep cannot tell that wreck from a user's checkout (a stale marker, a lock, a
`status.showUntrackedFiles=no` config and an empty untracked directory each fooled
a deleting resume), so it deletes nothing and does not run `git worktree prune`
(which would drop OTHER sessions' admin entries whose directories are momentarily
missing). It prints one precise line with the commands a human runs, and keeps the
marker so the line repeats until the case is resolved.

The kills are real: a `git` shim on PATH SIGKILLs the sweep's own bash at the
chosen step, after doing what `git worktree remove` would have done by then.
The shim also logs every git invocation, so "never pruned" is observed, not assumed.
Nothing decides on elapsed time.
"""

from pathlib import Path
import os
import shutil
import signal
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "tools" / "worktree-manager.sh"
REAL_GIT = shutil.which("git")
MARKER = "zetetic-sweep-removing"

SHIM = """#!/bin/bash
# Stand-in for git: log the call, then at the step named by KILL_AT do the partial
# work of the real command and SIGKILL the sweep (our parent) and ourselves.
echo "$*" >> "$GIT_LOG"
if [[ "$1" == "-C" && "$3" == "worktree" && "$4" == "remove" && "$KILL_AT" == remove-* ]]; then
  case "$KILL_AT" in
    remove-files)  rm -f "$5/tracked.txt" ;;
    remove-nolink) rm -f "$5/.git" ;;
    remove-gone)   rm -rf "$5" ;;
  esac
  kill -KILL "$PPID"; kill -KILL "$$"
fi
if [[ "$1" == "-C" && " $* " == *" branch -d "* && "$KILL_AT" == branch-delete ]]; then
  kill -KILL "$PPID"; kill -KILL "$$"
fi
exec "$REAL_GIT" "$@"
"""


pytestmark = pytest.mark.spawns  # leak guard applies (tests/conftest.py)


def _git(repo, *args):
    return subprocess.run([REAL_GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Sweep Test")
    (root / "tracked.txt").write_text("content\n")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    _git(root, "worktree", "add", "-q", str(root / ".claude" / "worktrees" / "w"), "-b", "b/w", "origin/main")
    return root


def _sweep(repo, tmp_path, kill_at=None):
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "git"
    shim.write_text(SHIM)
    shim.chmod(0o755)
    env = {**os.environ, "WORKTREE_GRACE_SECONDS": "0", "WORKTREE_AUDIT_LOG": str(tmp_path / "audit.log"),
           "REAL_GIT": REAL_GIT, "KILL_AT": kill_at or "", "GIT_LOG": str(tmp_path / "git.log")}
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    return subprocess.run(["bash", str(MANAGER), "sweep", str(repo)], env=env, capture_output=True, text=True)


def _git_calls(tmp_path):
    log = tmp_path / "git.log"
    return log.read_text().splitlines() if log.exists() else []


def _registered(repo):
    return [line for line in _git(repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]


def _wt(repo, name="w"):
    return repo / ".claude" / "worktrees" / name


def _admin(repo, name="w"):
    for gitdir in (repo / ".git" / "worktrees").glob("*/gitdir"):
        if gitdir.read_text().strip() == f"{_wt(repo, name)}/.git":
            return gitdir.parent
    return None


def _snapshot(root):
    """Every path under root with its content (None for a directory): a deletion shows."""
    if not root.exists():
        return None
    return {str(p.relative_to(root)): (None if p.is_dir() else p.read_bytes()) for p in sorted(root.rglob("*"))}


def _state(repo):
    return {"wt": _snapshot(_wt(repo)), "admin": _snapshot(_admin(repo)) if _admin(repo) else None,
            "registered": _registered(repo)}


def _add_worktree(repo, name):
    _git(repo, "worktree", "add", "-q", str(_wt(repo, name)), "-b", f"b/{name}", "origin/main")


KILL_STEPS = ["remove-files", "remove-nolink", "remove-gone"]


@pytest.mark.parametrize("kill_at", KILL_STEPS)
def test_an_interrupted_removal_deletes_nothing_and_reports_the_exact_commands(repo, tmp_path, kill_at):
    killed = _sweep(repo, tmp_path, kill_at=kill_at)
    assert killed.returncode == -signal.SIGKILL, "the shim did not kill the sweep"
    assert (_admin(repo) / MARKER).exists(), "the scenario is vacuous: no marker left by the kill"
    before = _state(repo)
    again = _sweep(repo, tmp_path)
    assert _state(repo) == before, again.stdout
    assert again.returncode == 0, again.stdout
    lines = [ln for ln in again.stdout.splitlines() if "interrupted removal" in ln]
    assert len(lines) == 1, again.stdout
    assert str(_wt(repo)) in lines[0] and "b/w" in lines[0]
    assert f"git -C {repo} worktree remove --force {_wt(repo)}" in lines[0]
    assert f"git -C {repo} worktree prune --expire now" in lines[0]
    assert not any(c.split()[:3][-2:] == ["worktree", "prune"] or " worktree prune" in c for c in _git_calls(tmp_path)), \
        "the sweep ran git worktree prune"


@pytest.mark.parametrize("kill_at", KILL_STEPS)
def test_the_marker_stays_so_the_report_repeats_until_a_human_resolves_it(repo, tmp_path, kill_at):
    assert _sweep(repo, tmp_path, kill_at=kill_at).returncode == -signal.SIGKILL
    first = _sweep(repo, tmp_path)
    second = _sweep(repo, tmp_path)
    assert (_admin(repo) / MARKER).exists(), "the sweep dropped the marker: the report would not repeat"
    for run in (first, second):
        assert sum("interrupted removal" in ln for ln in run.stdout.splitlines()) == 1, run.stdout
    # The printed commands work: the human finishes the job and the report is gone.
    subprocess.run([REAL_GIT, "-C", str(repo), "worktree", "remove", "--force", str(_wt(repo))], capture_output=True)
    subprocess.run([REAL_GIT, "-C", str(repo), "worktree", "prune", "--expire", "now"], check=True, capture_output=True)
    after = _sweep(repo, tmp_path)
    assert "interrupted removal" not in after.stdout and len(_registered(repo)) == 1, after.stdout


def test_a_kill_after_the_removal_loses_nothing_the_branch_goes_through_the_stale_branch_pass(repo, tmp_path):
    # The worktree and its admin directory are already gone: there is no half-removed
    # checkout. Only the merged branch lingers; deleting it is the pre-existing,
    # merge-verified stale-branch pass, not a resume.
    assert _sweep(repo, tmp_path, kill_at="branch-delete").returncode == -signal.SIGKILL
    assert not _wt(repo).exists() and _admin(repo) is None
    again = _sweep(repo, tmp_path)
    assert again.returncode == 0 and "interrupted removal" not in again.stdout, again.stdout
    assert len(_registered(repo)) == 1


def test_a_registered_checkout_without_git_link_and_without_marker_is_reported_and_kept(repo, tmp_path):
    (_wt(repo) / ".git").unlink()
    before = _state(repo)
    again = _sweep(repo, tmp_path)
    assert _state(repo) == before, again.stdout
    (line,) = [ln for ln in again.stdout.splitlines() if "no .git link" in ln]
    assert str(_wt(repo)) in line and f"git -C {repo} worktree remove --force {_wt(repo)}" in line
    assert "dirty working tree" not in again.stdout


@pytest.mark.parametrize("name", ["untracked.txt", "ignored.cache"])
def test_status_config_hiding_untracked_files_does_not_make_a_checkout_deletable(repo, tmp_path, name):
    (repo / ".git" / "info" / "exclude").write_text("*.cache\n")
    _git(repo, "config", "status.showUntrackedFiles", "no")
    (_wt(repo) / name).write_text("precious\n")
    run = _sweep(repo, tmp_path)
    assert (_wt(repo) / name).read_text() == "precious\n", run.stdout
    assert _admin(repo) is not None and len(_registered(repo)) == 2, run.stdout
    assert "dirty working tree" in run.stdout, run.stdout


def test_status_config_hiding_untracked_files_does_not_make_an_interrupted_checkout_deletable(repo, tmp_path):
    (repo / ".git" / "info" / "exclude").write_text("*.cache\n")
    _git(repo, "config", "status.showUntrackedFiles", "no")
    assert _sweep(repo, tmp_path, kill_at="remove-files").returncode == -signal.SIGKILL
    (_wt(repo) / "untracked.txt").write_text("precious\n")
    (_wt(repo) / "ignored.cache").write_text("precious\n")
    again = _sweep(repo, tmp_path)
    assert (_wt(repo) / "untracked.txt").read_text() == "precious\n", again.stdout
    assert (_wt(repo) / "ignored.cache").read_text() == "precious\n", again.stdout


def test_another_sessions_worktree_whose_directory_is_away_keeps_its_admin_entry(repo, tmp_path):
    assert _sweep(repo, tmp_path, kill_at="remove-files").returncode == -signal.SIGKILL
    _add_worktree(repo, "other")
    # Another session's checkout is momentarily elsewhere (renamed, unmounted volume).
    parked = tmp_path / "parked"
    _wt(repo, "other").rename(parked)
    admin_other = _admin(repo, "other")
    assert admin_other is not None
    again = _sweep(repo, tmp_path)
    assert admin_other.is_dir(), "the sweep pruned another session's admin entry: " + again.stdout
    assert (admin_other / "gitdir").exists() and parked.is_dir()
    parked.rename(_wt(repo, "other"))
    assert _git(repo, "-C", str(_wt(repo, "other")), "status", "--porcelain") == ""


def test_an_empty_untracked_directory_survives_a_sweep_of_an_interrupted_checkout(repo, tmp_path):
    assert _sweep(repo, tmp_path, kill_at="remove-files").returncode == -signal.SIGKILL
    (_wt(repo) / "scratch" / "deep").mkdir(parents=True)  # git status does not list an empty directory
    again = _sweep(repo, tmp_path)
    assert (_wt(repo) / "scratch" / "deep").is_dir(), again.stdout


def test_an_empty_untracked_directory_survives_a_sweep_of_a_clean_looking_checkout(repo, tmp_path):
    (_wt(repo) / "scratch").mkdir()
    run = _sweep(repo, tmp_path)
    assert (_wt(repo) / "scratch").is_dir(), run.stdout


def test_a_failed_removal_clears_its_marker_and_the_user_data_written_after_it_survives(repo, tmp_path):
    # lock -> remove fails (clean failure): the marker is cleared, so it vouches for nothing.
    _git(repo, "worktree", "lock", str(_wt(repo)))
    failed = _sweep(repo, tmp_path)
    assert failed.returncode == 1 and "worktree remove failed" in failed.stdout, failed.stdout
    assert not (_admin(repo) / MARKER).exists(), "a failed removal left its marker behind"
    (_wt(repo) / "data.txt").write_text("precious\n")
    _git(repo, "worktree", "unlock", str(_wt(repo)))
    again = _sweep(repo, tmp_path)
    assert (_wt(repo) / "data.txt").read_text() == "precious\n", again.stdout
    assert "interrupted removal" not in again.stdout

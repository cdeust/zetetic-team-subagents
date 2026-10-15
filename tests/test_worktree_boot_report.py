"""The session-start `worktrees` section only REPORTS: it deletes nothing and waits for nothing.

A real sweep run from session start deleted six local branches of a real repo
on 2026-10-15. The section now prints what the explicit `worktree-manager.sh sweep`
would clean, with the command, from a detached async task keyed by the repo's
refs state (tools/lib/worktree_report.py, tools/lib/tasks.py). The task runs
`sweep --dry-run`, the read-only mode of the sweep's own code.

Nothing decides on elapsed time. "Does not wait" is shown by a classification task
that is provably still in flight (blocked on a fifo nobody has released) while the
section returns; had it waited, the test would hang. "Deletes nothing" is shown on
the repo's refs and worktrees AND on the git calls of the section and of the
detached worker (a shim on PATH), after the worker has exited (pid event).
"""
import contextlib
import subprocess

import pytest

from sweep_support import MANAGER, ROOT, git, git_calls, heads, make_repo, mutating, publish, shimmed_env, worktrees
from task_support import fire, make_fifo, read_line, task_store as store, tasks, wait_exit
from test_worktree_sweep_preserve import reverted, squashed, whitespace

import worktree_report  # noqa: E402  (tools/lib is on sys.path through task_support)

SECTIONS = ROOT / "hooks" / "lib" / "session-sections.sh"


pytestmark = pytest.mark.spawns  # leak guard applies (tests/conftest.py)


@pytest.fixture
def state(tmp_path, monkeypatch):
    directory = tmp_path / "tasks"
    directory.mkdir()
    monkeypatch.setenv(store.ENV_DIR, str(directory))
    return directory


def boot(repo, tmp_path):
    env = shimmed_env(tmp_path, TOOLS=str(ROOT / "tools"), REPO_ROOT=str(repo), WHITE="", BOLD="", RESET="", SUBTLE="")
    done = subprocess.run(["bash", "-c", 'set -euo pipefail; source "$1"; section_worktrees', "boot", str(SECTIONS)],
                          cwd=repo, env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def finish_classification(repo):
    """Block on the exit of the detached worker of the latest classification (an OS event)."""
    rec = tasks.latest("wtclass", None, str(repo))
    wait_exit(rec["pid"])
    return tasks.latest("wtclass", None, str(repo))


def world(tmp_path):
    """Branches a deleting sweep would take (squashed, pushed, in a worktree) and ones it must never take."""
    repo = make_repo(tmp_path)
    whitespace(repo)
    reverted(repo)
    done = squashed(repo, name="d.txt")  # its own file: feat/rev's work must stay off main
    publish(repo, done)
    (repo / ".claude" / "worktrees").mkdir(parents=True)
    git(repo, "worktree", "add", "-q", str(repo / ".claude" / "worktrees" / "w"), done)
    return repo


def snapshot(repo):
    return heads(repo), worktrees(repo), git(repo, "for-each-ref")


def test_boot_deletes_nothing_and_reports_what_the_explicit_sweep_would_clean(tmp_path, state):
    repo = world(tmp_path)
    before = snapshot(repo)
    first = boot(repo, tmp_path)
    assert "classification running" in first and "stale:" not in first, first
    assert finish_classification(repo)["state"] == "done"
    second = boot(repo, tmp_path)
    assert snapshot(repo) == before, second  # the worker has exited: nothing it did is pending
    stale = [ln for ln in second.splitlines() if "stale:" in ln]
    assert stale, second
    command = f"bash {MANAGER} sweep {repo}"
    assert all(ln.endswith(f"-> run: {command}") for ln in stale), stale
    assert any("worktrees/w" in ln for ln in stale), stale
    assert not any("feat/ws" in ln or "feat/rev" in ln for ln in stale), stale  # unproven work is not offered
    assert not mutating(git_calls(tmp_path)), git_calls(tmp_path)


@contextlib.contextmanager
def in_flight(repo, tmp_path):
    """A classification task for the repo's current refs state, blocked on a fifo until the block exits
    (also when an assertion fails, so no worker or command outlives the test)."""
    ready, hold = make_fifo(tmp_path, "ready"), make_fifo(tmp_path, "hold")
    key = worktree_report.refs_key(str(repo))
    started = tasks.start("wtclass", key, ["sh", "-c", f"echo $$ > {ready}; cat {hold} >/dev/null"], str(repo))
    command_pid = int(read_line(ready))  # the line proves: the record is written and the command is alive
    try:
        yield started.record
    finally:
        fire(hold)
        wait_exit(command_pid)
        wait_exit(started.record["pid"])


def test_boot_does_not_wait_for_a_classification_in_flight(tmp_path, state):
    repo = world(tmp_path)
    with in_flight(repo, tmp_path) as record:
        out = boot(repo, tmp_path)  # returns while the task is blocked: it did not wait
        assert "classification running" in out and "stale:" not in out, out
        assert tasks.status(record["id"], str(repo))["alive"] is True
        calls = git_calls(tmp_path)
        assert calls and not any(w in c for c in calls for w in ("merge-tree", "patch-id", "log -p", "diff")), calls


def test_boot_shows_the_last_finished_result_while_the_new_refs_state_is_classified(tmp_path, state):
    repo = world(tmp_path)
    boot(repo, tmp_path)
    finish_classification(repo)
    boot(repo, tmp_path)  # prints the finished result: that is the one remembered
    git(repo, "branch", "feat/new-ref-state")  # a new refs state: a new key, a new task
    with in_flight(repo, tmp_path):
        out = boot(repo, tmp_path)
        assert "classification running" in out, out
        assert any("stale:" in ln and "(earlier refs state)" in ln for ln in out.splitlines()), out


def test_a_failed_classification_is_reported_with_the_command_to_run_by_hand(tmp_path, state):
    repo = world(tmp_path)
    key = worktree_report.refs_key(str(repo))
    started = tasks.start("wtclass", key, ["sh", "-c", "exit 3"], str(repo))
    wait_exit(started.record["pid"])
    out = boot(repo, tmp_path)
    assert "classification failed" in out and f"sweep --dry-run {repo}" in out, out
    assert "stale:" not in out


def test_a_repo_with_nothing_to_clean_says_so(tmp_path, state):
    repo = make_repo(tmp_path)
    boot(repo, tmp_path)
    finish_classification(repo)
    assert "nothing to clean" in boot(repo, tmp_path)

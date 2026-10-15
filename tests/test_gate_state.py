"""hooks/lib/gate_state.py and gate_git.py: the verdict is a function of the task record, nothing else.

In-process, synthetic records: no worker is started and nothing waits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from gate_support import git
from task_support import tasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_git as gitq  # noqa: E402
import gate_state as state  # noqa: E402

TREE = "a" * 40
ARGV = ["x"]


def record(**over) -> dict:
    base = {"id": f"gate-{TREE}", "key": TREE, "state": "done", "rc": 0, "signal": None, "reason": None,
            "attempt": 1, "output_path": "/o/gate.a1.out", "result_excerpt": "line1\nthe failing line\n", "pgid": 7}
    return {**base, **over}


def judge(disposition: str, **over):
    return state.verdict_of("/repo", TREE, tasks.Started(record(**over), disposition), ARGV)


def test_cached_green_allows():
    assert judge("cached") == state.Verdict(True, "")


def test_failed_denies_with_cause_output_path_tail_and_the_requeue_command():
    verdict = judge("failed", state="failed", rc=3)
    assert verdict.allow is False
    for part in (f"tree {TREE}", "rc=3", "/o/gate.a1.out", "the failing line", "gate_task.py requeue --repo /repo"):
        assert part in verdict.message
    assert "signal 9" in judge("failed", state="failed", rc=-9, signal=9).message
    assert "worker died" in judge("failed", state="failed", rc=None, reason="worker died").message


@pytest.mark.parametrize("disposition,word", [("started", "started"), ("in-flight", "running")])
def test_pending_denies_with_the_retry_message_and_the_status_command(disposition, word):
    verdict = judge(disposition, state="running", rc=None)
    assert verdict.allow is False
    assert f"verification {word} for tree {TREE}; retry the commit when it finishes" in verdict.message
    assert f"tools/task.sh status gate-{TREE} --repo /repo" in verdict.message


def test_the_tail_is_bounded():
    long = "\n".join(f"row{i}" for i in range(100))
    message = judge("failed", state="failed", rc=1, result_excerpt=long).message
    assert "row99" in message and "row88" in message and "row87" not in message  # exactly the last 12 lines


def test_stale_requeues_once_and_orphaned_says_so(monkeypatch):
    calls = []

    def fake_requeue(kind, key, argv, cwd):
        calls.append((kind, key, argv, cwd))
        return tasks.Started(record(attempt=2, state="queued"), "started")

    monkeypatch.setattr(state.tasks, "requeue", fake_requeue)
    verdict = judge("stale", state="running")
    assert calls == [("gate", TREE, ARGV, "/repo")]
    assert "attempt 2" in verdict.message and "previous worker died" in verdict.message and not verdict.allow
    assert f"verification started for tree {TREE}" in verdict.message  # a fresh attempt has just been launched
    monkeypatch.setattr(state.tasks, "requeue", lambda *a: tasks.Started(record(state="failed"), "orphaned"))
    orphan = judge("stale", state="running")
    assert "process group 7" in orphan.message and "orphaned" in orphan.message and not orphan.allow


def test_job_argv_names_the_worker_and_the_base():
    argv = state.job_argv("/repo", "push", TREE, None)
    assert argv[2:] == [state.RUN, "run", "--repo", "/repo", "--tree", TREE, "--base", "-", "--kind", "push"]
    assert state.job_argv("/repo", "commit", TREE, "b" * 40)[-3] == "b" * 40


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a").write_text("1\n")
    git(tmp_path, "add", "a")
    return tmp_path


def commit(repo: Path, text: str) -> str:
    (repo / "a").write_text(text)
    git(repo, "add", "a")
    git(repo, "commit", "-q", "-m", "c", "--no-verify")
    return git(repo, "rev-parse", "HEAD^{tree}")


def test_commit_trees_before_the_first_commit_and_with_an_empty_index(repo, monkeypatch):
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}.items():
        monkeypatch.setenv(key, value)
    staged = git(repo, "write-tree")
    assert state.commit_trees(str(repo), False, False) == (staged, None)  # first commit: measured from the empty tree
    first = commit(repo, "1\n")
    assert state.commit_trees(str(repo), False, False) is None  # nothing staged: git refuses it
    assert state.commit_trees(str(repo), False, True) == (first, first)  # --allow-empty
    assert state.commit_trees(str(repo), True, False) == (first, None)  # --amend of a root commit
    second = commit(repo, "2\n")
    assert state.commit_trees(str(repo), True, False) == (second, first)  # amend: measured from the parent
    assert state.push_trees(str(repo)) == (second, first)


def test_empty_index_before_any_commit_is_nothing_to_commit(tmp_path):
    git(tmp_path, "init", "-q")
    assert state.commit_trees(str(tmp_path), False, False) is None
    with pytest.raises(gitq.Unavailable):
        state.push_trees(str(tmp_path))  # unborn HEAD: no tree to judge, refused closed


def test_locate_and_head_ahead_of_upstream(repo, tmp_path_factory, monkeypatch):
    assert gitq.locate(str(repo)).top == str(repo.resolve())
    assert gitq.locate(str(tmp_path_factory.mktemp("plain"))) is None
    assert gitq.head_ahead_of_upstream(str(repo)) is False  # unborn HEAD
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}.items():
        monkeypatch.setenv(key, value)
    commit(repo, "1\n")
    assert gitq.head_ahead_of_upstream(str(repo)) is False  # no upstream: not counted as ahead


def test_a_missing_git_is_unavailable_not_a_crash(repo, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(gitq.Unavailable):
        gitq.git(str(repo), "status")


def test_check_begin_and_peek_are_wired_to_the_task_layer(monkeypatch):
    seen = []
    green = tasks.Started(record(), "cached")
    monkeypatch.setattr(state.tasks, "start", lambda *a: seen.append(("start", a)) or green)
    monkeypatch.setattr(state.tasks, "status", lambda *a: seen.append(("status", a)) or record(state="running"))
    assert state.check("/repo", "commit", TREE, "b" * 40) == state.Verdict(True, "")
    assert state.begin("/repo", "push", TREE, None) is green
    assert state.peek("/repo", TREE)["state"] == "running"
    argv_commit = state.job_argv("/repo", "commit", TREE, "b" * 40)
    argv_push = state.job_argv("/repo", "push", TREE, None)
    assert seen == [("start", ("gate", TREE, argv_commit, "/repo")), ("start", ("gate", TREE, argv_push, "/repo")),
                    ("status", (f"gate-{TREE}", "/repo"))]


def test_waivers_survive_a_torn_line_and_foreign_rows(tmp_path, monkeypatch):
    monkeypatch.setenv(state.task_store.ENV_DIR, str(tmp_path / "state"))
    import gate_ledger as ledger  # noqa: E402
    assert ledger.waived_trees("/anywhere") == set()  # no file yet
    ledger.waive("/anywhere", TREE, "because")
    path = ledger._waiver_path("/anywhere")
    with open(path, "a") as fh:
        fh.write("{torn\n[1, 2]\n" + json.dumps({"tree": 5}) + "\n" + json.dumps({"no_tree": 1}) + "\n")
    ledger.waive("/anywhere", "c" * 40, "also")
    assert ledger.waived_trees("/anywhere") == {TREE, "c" * 40}

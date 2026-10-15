"""The async gate (hooks/gate-proof.py, gate-start.py): a tree is verified by the task `gate-<tree>`; the
commit hook only reads its state. Real git repository, real hooks as subprocesses, a real detached worker.

Event-synchronised only (docs/async-tasks.md): FIFO lines the check itself writes, worker process exit.
No sleep, poll or timeout decides pass or fail; "the hook returned" is the proof that it did not wait.
"""
from __future__ import annotations

import ast
import os
import signal
from pathlib import Path

import pytest

from gate_support import Gate, git, payload, run_hook, write_config
from task_support import tasks, wait_exit

COMMIT = 'git commit -m "wip"'


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    yield g
    g.close()


def test_staging_starts_one_task_and_dedups_by_tree(gate):
    tree = gate.stage("two\n")
    assert gate.head_start()[0] == 0
    running = gate.await_running(tree)
    assert running["state"] == "running" and running["key"] == tree and running["kind"] == "gate"
    gate.head_start()  # a second add of the same tree, then the commit hook: neither starts another task
    assert gate.gate(COMMIT)[0] == 2
    assert gate.finish(tree)["state"] == "done"
    assert gate.runs() == 1


def test_commit_with_a_running_task_is_blocked_at_once_with_the_message(gate):
    tree = gate.stage("two\n")
    gate.head_start()
    gate.await_running(tree)
    rc, _, err = gate.gate(COMMIT)  # the check is still blocked on HOLD: returning at all proves no wait
    assert rc == 2
    assert f"verification running for tree {tree}; retry the commit when it finishes" in err
    assert f"tools/task.sh status gate-{tree}" in err
    gate.finish(tree)


def test_commit_hook_starts_the_task_when_none_exists_then_reports_it(gate):
    tree = gate.stage("two\n")
    rc, _, err = gate.gate(COMMIT)  # no head start happened
    assert rc == 2 and f"verification started for tree {tree}" in err
    assert gate.await_running(tree)["state"] == "running"
    gate.finish(tree)


def test_commit_after_green_is_allowed_without_running_again(gate):
    tree = gate.stage("two\n")
    gate.head_start()
    gate.await_running(tree)
    assert gate.finish(tree)["state"] == "done"
    assert gate.gate(COMMIT) == (0, "", "")
    assert gate.runs() == 1


def test_a_changed_tree_is_a_new_task(gate):
    first = gate.stage("two\n")
    gate.head_start()
    gate.await_running(first)
    gate.finish(first)
    second = gate.stage("three\n")
    assert second != first
    rc, _, err = gate.gate(COMMIT)  # the proof of the old tree does not cover the new index
    assert rc == 2 and f"tree {second}" in err
    assert gate.await_running(second)["id"] == f"gate-{second}"
    gate.finish(second)
    assert gate.runs() == 2


def test_failed_task_blocks_with_the_output_path_and_excerpt(gate):
    write_config(gate.repo, [{"name": "boom", "argv": ["sh", "-c", "echo the-assertion-text; exit 3"]}])
    git(gate.repo, "add", ".zetetic/gate.json")  # the rules come from the staged tree
    tree = gate.stage("two\n")
    gate.head_start()
    wait_exit(gate.record(tree)["pid"])
    rec = gate.record(tree)
    assert (rec["state"], rec["rc"]) == ("failed", 3)  # the worker exits with the failing check's code
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2
    assert "verification FAILED" in err and rec["output_path"] in err and "the-assertion-text" in err
    assert Path(rec["output_path"]).read_text().count("[gate:boom] FAILED rc=3") == 1


def test_push_reuses_the_commit_verification(gate):
    tree = gate.stage("two\n")
    gate.head_start()
    gate.await_running(tree)
    gate.finish(tree)
    assert gate.commit() == tree
    for command in ("git push", "gh pr create --fill"):
        assert gate.gate(command) == (0, "", ""), command
    assert gate.runs() == 1


def test_push_of_an_unverified_head_starts_its_verification(gate):
    (gate.repo / "a.txt").write_text("two\n")
    git(gate.repo, "add", "a.txt")
    tree = gate.commit()  # committed with --no-verify: never verified
    rc, _, err = gate.gate("git push")
    assert rc == 2 and f"verification started for tree {tree}" in err
    gate.await_running(tree)
    gate.finish(tree)
    assert gate.gate("git push") == (0, "", "")


def test_a_dead_worker_is_requeued_once_and_said_so(gate):
    tree = gate.stage("two\n")
    gate.head_start()
    dead = gate.await_running(tree)
    os.killpg(dead["pgid"], signal.SIGKILL)  # the worker and its check vanish without a terminal state
    wait_exit(dead["pid"])
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "attempt 2" in err and "previous worker died" in err
    assert gate.await_running(tree)["attempt"] == 2
    gate.finish(tree)
    assert gate.gate(COMMIT) == (0, "", "")


def test_staging_in_the_same_call_or_with_a_flag_is_refused_before_any_task(gate):
    gate.stage("two\n")
    for command in ("git add . && git commit -m x", "git commit -a -m x", "git commit -m x -- a.txt"):
        rc, _, err = gate.gate(command)
        assert rc == 2 and "stage in a separate call" in err, command
    assert gate.started() == []


def test_undeclared_repo_is_not_gated_and_starts_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    repo = tmp_path / "plain"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    assert run_hook("gate-proof.py", payload(COMMIT, repo), repo)[0] == 0
    assert run_hook("gate-start.py", payload("git add a.txt", repo), repo)[0] == 0
    assert not list((tmp_path / "state").glob("gate-*.json"))


def test_invalid_config_refuses_closed(gate):
    (gate.repo / ".zetetic" / "gate.json").write_text('{"version": 2}')
    gate.stage("two\n")
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "gate config" in err and "invalid" in err


def test_unreadable_payload_in_a_gated_repo_is_refused(gate):
    assert run_hook("gate-proof.py", "{not json", gate.repo, gate.env)[0] == 2
    assert run_hook("gate-proof.py", "[1, 2]", gate.repo, gate.env)[0] == 2


def test_no_git_is_refused_where_a_gate_is_declared(gate):
    gate.stage("two\n")
    rc, _, err = run_hook("gate-proof.py", payload(COMMIT, gate.repo), gate.repo, {**gate.env, "PATH": "/nonexistent"})
    assert rc == 2 and "git unavailable" in err


def test_empty_index_is_left_to_git(gate):
    assert gate.gate(COMMIT) == (0, "", "")
    assert gate.started() == []


def test_amend_of_an_empty_index_needs_the_head_tree_verified(gate):
    rc, _, err = gate.gate("git commit --amend -m x")
    head = git(gate.repo, "rev-parse", "HEAD^{tree}")
    assert rc == 2 and f"tree {head}" in err
    gate.await_running(head)
    gate.finish(head)
    assert gate.gate("git commit --amend -m x") == (0, "", "")


def _time_bounds(source: str) -> list:
    """Every call that bounds by time: a timeout= keyword, sleep(), alarm(), settimeout()."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in ("sleep", "alarm", "settimeout", "wait") or any(k.arg and "timeout" in k.arg for k in node.keywords):
                found.append(name)
    return found


def test_the_hot_path_has_no_timer():
    """Regression for the 8 s git kill: no hook-path module may bound a call by time."""
    from gate_support import HOOKS
    for name in ("gate-proof.py", "gate-start.py", "stop-gate-ledger.py", "lib/gate_git.py", "lib/gate_state.py",
                 "lib/gate_ledger.py", "lib/gate_actions.py", "lib/gate_config.py", "lib/gate_shell.py"):
        assert _time_bounds((HOOKS / name).read_text()) == [], name

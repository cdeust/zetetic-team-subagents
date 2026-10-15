"""hooks/stop-gate-ledger.py and hooks/lib/gate_task.py: a failed verification of a tree at risk is a todo.

Event-synchronised: a verification is awaited by the exit of its worker, never by a delay.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from gate_support import HOOKS, Gate, git, run_hook, write_config
from task_support import tasks, wait_exit

STOP = {"hook_event_name": "Stop", "stop_hook_active": False}


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    yield g
    g.close()


def failing(gate: Gate, script: str = "echo the-failure-text; exit 1") -> str:
    """Stage a change whose verification fails; return its tree once the worker has finished."""
    write_config(gate.repo, [{"name": "boom", "argv": ["sh", "-c", script]}])
    git(gate.repo, "add", ".zetetic/gate.json")
    tree = gate.stage("two\n")
    gate.head_start()
    wait_exit(gate.record(tree)["pid"])
    assert gate.record(tree)["state"] == "failed"
    return tree


def stop(gate: Gate, **extra):
    return run_hook("stop-gate-ledger.py", {**STOP, "cwd": str(gate.repo), **extra}, gate.repo, gate.env)


def test_failed_staged_tree_blocks_the_stop_and_names_the_output(gate):
    tree = failing(gate)
    rc, out, _ = stop(gate)
    decision = json.loads(out)
    assert rc == 0 and decision["decision"] == "block"
    assert tree in decision["reason"] and gate.record(tree)["output_path"] in decision["reason"]


def test_a_running_verification_does_not_block(gate):
    tree = gate.stage("two\n")
    gate.head_start()
    gate.await_running(tree)
    assert stop(gate)[1] == ""
    gate.finish(tree)


def test_green_or_no_change_does_not_block(gate):
    assert stop(gate)[1] == ""
    tree = gate.stage("two\n")
    gate.head_start()
    gate.await_running(tree)
    gate.finish(tree)
    assert stop(gate)[1] == ""


def test_stop_hook_active_is_a_one_shot_nudge(gate):
    failing(gate)
    assert stop(gate, stop_hook_active=True)[1] == ""


def test_a_failure_of_a_tree_no_longer_at_risk_is_history(gate):
    failing(gate)
    git(gate.repo, "restore", "--staged", "--worktree", "a.txt")  # back to HEAD's content...
    git(gate.repo, "restore", "--staged", ".zetetic/gate.json")
    # the staged tree now equals HEAD's: the failed tree is not the one to commit any more
    assert stop(gate)[1] == ""


def test_a_waiver_lifts_the_stop_block_but_not_the_commit_block(gate):
    tree = failing(gate)
    waive = subprocess.run([sys.executable, str(HOOKS / "lib" / "gate_task.py"), "waive", "--repo", str(gate.repo),
                            "--tree", tree, "--reason", "check is broken upstream"],
                           capture_output=True, text=True, env={**os.environ, **gate.env})
    assert waive.returncode == 0 and json.loads(waive.stdout)["tree"] == tree
    assert stop(gate)[1] == ""
    assert gate.gate('git commit -m "x"')[0] == 2  # the waiver never lets a commit through


def test_unpushed_head_with_a_failed_verification_blocks(gate):
    tree = failing(gate)
    git(gate.repo, "commit", "-q", "-m", "x", "--no-verify")
    remote = gate.tmp / "remote.git"
    git(gate.tmp, "init", "-q", "--bare", str(remote))
    git(gate.repo, "remote", "add", "origin", str(remote))
    git(gate.repo, "push", "-q", "-u", "origin", "main")
    git(gate.repo, "commit", "-q", "--allow-empty", "-m", "ahead", "--no-verify")  # HEAD != upstream, same tree
    rc, out, _ = stop(gate)
    assert json.loads(out)["decision"] == "block" and tree in json.loads(out)["reason"]
    git(gate.repo, "push", "-q")
    assert stop(gate)[1] == ""  # pushed: no longer at risk


def test_repo_without_a_gate_is_out_of_scope(tmp_path, monkeypatch):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    repo = tmp_path / "plain"
    repo.mkdir()
    git(repo, "init", "-q")
    assert run_hook("stop-gate-ledger.py", {**STOP, "cwd": str(repo)}, repo)[1:] == ("", "")


def test_garbage_payload_never_raises(gate):
    assert run_hook("stop-gate-ledger.py", "{not json", gate.repo, gate.env) == (0, "", "")
    assert run_hook("stop-gate-ledger.py", "[1]", gate.repo, gate.env) == (0, "", "")


def test_requeue_retries_a_failed_task_as_attempt_two(gate):
    ok = gate.tmp / "ok"
    tree = failing(gate, f"test -f {ok}")
    ok.write_text("now it passes\n")
    out = subprocess.run([sys.executable, str(HOOKS / "lib" / "gate_task.py"), "requeue", "--repo", str(gate.repo)],
                         capture_output=True, text=True, env={**os.environ, **gate.env})
    result = json.loads(out.stdout)
    assert (result["id"], result["disposition"], result["attempt"]) == (f"gate-{tree}", "started", 2)
    wait_exit(gate.record(tree)["pid"])
    assert gate.record(tree)["state"] == "done"
    assert gate.gate('git commit -m "x"') == (0, "", "")

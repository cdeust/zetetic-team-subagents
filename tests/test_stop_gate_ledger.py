"""hooks/stop-gate-ledger.py and hooks/lib/gate_task.py: an open gate failure is a todo while work is at risk.

The baseline (~/.claude/hooks/stop-gate-ledger.py) blocked on ANY open failure while tracked changes remained
uncommitted or HEAD was ahead of its upstream; these tests pin that, including the case the first version of
this hook missed: a failed tree that was unstaged again with its edits left in the working copy.

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
    """Stage a change whose verification fails; return its tree once the worker has finished.
    The failing rules are committed first: they are read from HEAD, the trusted tree."""
    write_config(gate.repo, [{"name": "boom", "argv": ["sh", "-c", script]}])
    git(gate.repo, "add", ".zetetic/gate.json")
    git(gate.repo, "commit", "-q", "-m", "rules", "--no-verify")
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


def test_a_failure_with_nothing_left_at_risk_is_history(gate):
    failing(gate)
    git(gate.repo, "restore", "--staged", "--worktree", "a.txt")  # back to HEAD's content: the edits are gone
    assert stop(gate)[1] == ""


def test_a_failed_tree_unstaged_with_its_edits_left_in_the_working_copy_still_blocks(gate):
    tree = failing(gate)
    git(gate.repo, "restore", "--staged", "a.txt")  # the index equals HEAD again; the edit remains uncommitted
    assert git(gate.repo, "write-tree") == git(gate.repo, "rev-parse", "HEAD^{tree}")
    rc, out, _ = stop(gate)
    decision = json.loads(out)
    assert rc == 0 and decision["decision"] == "block" and tree in decision["reason"]


def test_a_later_green_verification_of_the_same_kind_lifts_the_failure(gate):
    ok = gate.tmp / "ok"
    failing(gate, f"test -f {ok}")
    assert json.loads(stop(gate)[1])["decision"] == "block"
    ok.write_text("fixed\n")
    second = gate.stage("three\n")  # a different tree: the fix
    gate.head_start()
    wait_exit(gate.record(second)["pid"])
    assert gate.record(second)["state"] == "done"
    assert stop(gate)[1] == ""  # edits remain uncommitted, but the failure was lifted by a later green line


def test_the_ledger_orders_by_line_not_by_clock(gate):
    import gate_ledger  # noqa: E402
    top = str(gate.repo)
    for verb, tree, rc in (("commit", "a" * 40, 1), ("push", "b" * 40, 1), ("commit", "c" * 40, 0), ("commit", "d" * 40, 2)):
        gate_ledger.record(top, gate_ledger.Result(verb, tree, f"{verb}-{tree}-x", rc))
    open_ = [(r["verb"], r["tree"]) for r in gate_ledger.open_failures(top)]
    # the green commit line lifts the EARLIER commit failure only; the push failure and the later commit failure stay open
    assert open_ == [("push", "b" * 40), ("commit", "d" * 40)]


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


def test_requeue_retries_a_failed_task_as_attempt_two_with_its_own_runner_from_any_shell(gate):
    """The requeue command runs in the agent's shell, whose environment need not be the hook's. It relaunches the
    recorded command, runner included, so the hook's next commit attempt finds the retried verification."""
    ok = gate.tmp / "ok"
    tree = failing(gate, f"test -f {ok}")
    ok.write_text("now it passes\n")
    shell = {**os.environ, **gate.env, "TERM": "a-terminal-unlike-the-hooks", "LANG": "C"}
    out = subprocess.run([sys.executable, str(HOOKS / "lib" / "gate_task.py"), "requeue", "--repo", str(gate.repo),
                          "--id", gate.record_id(tree)], capture_output=True, text=True, env=shell)
    result = json.loads(out.stdout)
    assert (result["disposition"], result["attempt"]) == ("started", 2)
    assert result["id"] == gate.record_id(tree)
    wait_exit(gate.record(tree)["pid"])
    assert gate.record(tree)["state"] == "done"
    assert gate.gate('git commit -m "x"') == (0, "", "")


def test_more_than_five_open_failures_are_listed_five_and_the_rest_counted(gate):
    import gate_ledger  # noqa: E402
    for n in range(7):
        gate_ledger.record(str(gate.repo), gate_ledger.Result("commit", str(n) * 40, f"commit-{n}", 1))
    gate.stage("two\n")  # work is at risk
    reason = json.loads(stop(gate)[1])["reason"]
    assert len([line for line in reason.splitlines() if line.startswith("- commit tree ")]) == 5
    assert reason.endswith("(+2 more)")

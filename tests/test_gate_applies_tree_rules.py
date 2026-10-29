"""The gates apply the rules present in the tree they judge and compare them with nothing.

Owner rule, 2026-10-29, verbatim: "Supprime le sha de main et la comparaison des gates".

No floor kept by the user, no acknowledgement by hash, no "no weaker than" relation, no rule of a remote-tracking
ref (main included): a change that edits the rules is judged by the rules of the trusted tree and of the judged
tree (gate_rules.effective), and nothing is refused for having changed them. Real repository, real hooks as
subprocesses, a worker awaited by its exit.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gate_support import HOOKS, Gate, git, write_config
from task_support import tasks
from test_gate_attacks import COMMIT, FAIL_IF_BAD, commit_rules, settle

OTHER = {"name": "other", "argv": ["true"]}


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    commit_rules(g, [FAIL_IF_BAD, OTHER])
    yield g
    g.close()


def test_a_commit_that_removes_a_check_is_not_refused_for_it(gate):
    write_config(gate.repo, [OTHER])  # FAIL_IF_BAD removed: formerly refused until the owner acknowledged it
    git(gate.repo, "add", ".zetetic/gate.json")
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "verification started" in err and "weakens" not in err, err
    assert settle(gate)["state"] == "done"
    assert gate.gate(COMMIT)[0] == 0


def test_a_commit_that_drops_every_rule_is_not_refused_for_it(gate):
    git(gate.repo, "rm", "-q", "--cached", ".zetetic/gate.json")
    rc, _, err = gate.gate(COMMIT)
    assert "weakens" not in err and "acknowledg" not in err, err
    assert rc == 2 and "verification started" in err, err  # the trusted tree's rules still judge it
    assert settle(gate)["state"] == "done"
    assert gate.gate(COMMIT)[0] == 0


def test_a_commit_that_adds_a_check_passes(gate):
    write_config(gate.repo, [FAIL_IF_BAD, OTHER, {"name": "more", "argv": ["true", "more"]}])
    git(gate.repo, "add", ".zetetic/gate.json")
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "done"
    assert gate.gate(COMMIT)[0] == 0


def push(g: Gate) -> tuple:
    rc, _, err = g.hook("gate-proof.py", "git push origin main")
    return rc, err


def test_nothing_depends_on_the_remote_tracking_main(gate):
    """A refs/remotes/origin/main whose rules are stronger than the pushed tip's changes nothing: the push is
    verified by the tree's rules (started, then allowed) and never refused as a weakening."""
    git(gate.repo, "remote", "add", "origin", str(gate.tmp / "nowhere.git"))  # never contacted
    git(gate.repo, "update-ref", "refs/remotes/origin/main", "HEAD")  # its rules hold FAIL_IF_BAD and OTHER
    write_config(gate.repo, [OTHER])
    git(gate.repo, "add", ".zetetic/gate.json")
    git(gate.repo, "commit", "-q", "-m", "fewer rules", "--no-verify")
    first = push(gate)
    settle(gate)
    second = push(gate)
    assert "weakens" not in first[1] + second[1], (first, second)
    assert [first[0], second[0]] == [2, 0] and "verification started" in first[1]


def test_no_gate_module_reads_a_floor_an_acknowledgement_or_a_remote_tracking_ref():
    forbidden = ("gate_floor", "gate_ack", "gate_superset", "state_hash", "gate-rule-floor", "gate-rule-changes",
                 "refs/remotes/origin/main", "RULE_FLOOR", "RULE_CHANGES")
    found = [f"{path.name}: {token}" for path in sorted(HOOKS.rglob("gate*.py")) + sorted(HOOKS.glob("lib/gate*.py"))
             for token in forbidden if token in path.read_text()]
    assert found == []
    for removed in ("gate_floor.py", "gate_ack.py", "gate_superset.py"):
        assert not (HOOKS / "lib" / removed).exists()

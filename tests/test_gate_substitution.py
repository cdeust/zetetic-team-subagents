"""The commit gate reads a command substitution as bash runs it, double quotes included (review round 5, B4).

Real hooks as subprocesses against a throwaway repository. Before the fix the lexer read a double-quoted string to
the next `"`: `out="$(git commit ...)"` and `out="$(git push ...)"` reached git unjudged (p6), and a heredoc
message holding a `"` (an inch mark) ended the string early, so its last words read as paths to commit and a green
tree was refused with "stage in a separate call" (p7).

Event-synchronised only: a worker's end is its process exit.
"""
from __future__ import annotations

import pytest

from gate_support import Gate, git, write_config
from task_support import tasks, wait_exit

INCH = "git commit -m \"$(cat <<'EOF'\nfix: a 5\" display\n\nBody.\nEOF\n)\""


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(g.repo, "remote", "add", "origin", str(remote))
    yield g
    g.close()


def rules(g: Gate, argv: list) -> None:
    write_config(g.repo, [{"name": "only", "argv": argv}])
    git(g.repo, "add", "-A")
    git(g.repo, "commit", "-q", "-m", "rules", "--no-verify")


def verified(g: Gate) -> str:
    """Stage a change and let its verification end (the worker's process exit); return the tree."""
    tree = g.stage("two\n")
    g.head_start()
    wait_exit(g.record(tree)["pid"])
    return tree


@pytest.mark.parametrize("command", ['out="$(git commit -m "capture form" 2>&1)"; echo "$out"',
                                     'echo "$(git commit -m \\"x\\")"', 'x="`git commit -m y`"'])
def test_a_commit_inside_a_quoted_substitution_is_judged(gate, command):
    rules(gate, ["false"])
    verified(gate)
    rc, _, err = gate.gate(command)
    assert rc == 2 and "verification FAILED" in err


def test_a_push_inside_a_quoted_substitution_is_judged(gate):
    rules(gate, ["false"])
    gate.stage("two\n")
    gate.commit()  # made outside the hooks: an unverified head
    rc, _, err = gate.gate('out="$(git push origin main 2>&1)"; echo "$out"')
    assert rc == 2 and "[main] GATE-PROOF: verification started" in err
    wait_exit(tasks.status(tasks.latest("gate", None, str(gate.repo))["id"], str(gate.repo))["pid"])


@pytest.mark.parametrize("command", ['git push origin "$(git branch --show-current)"',
                                     "git push origin $(git branch --show-current)"])
def test_a_refspec_computed_by_a_substitution_is_refused_with_the_reason(gate, command):
    rules(gate, ["true"])
    rc, _, err = gate.gate(command)
    assert rc == 2 and "cannot tell which commits this publishes" in err


def test_a_heredoc_message_with_an_inch_mark_commits_a_green_tree(gate):
    rules(gate, ["true"])
    verified(gate)
    assert gate.gate(INCH) == (0, "", "")

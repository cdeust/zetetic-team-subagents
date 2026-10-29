"""Every git process the gate starts reads the objects that are really there (PR #169, round 3, finding 2).

The attack, reproduced at b851aa4 (review-r3/transcripts/a2_replace.txt): the gate reads its rules and the tree it
checks through git objects, and git substitutes objects when told to. One ungated `git replace` of the blob of
HEAD's `.zetetic/gate.json` by an `{"off": true}` blob made the rules read as off, so a failing commit was allowed
and pushed. The same substitution works through `GIT_REPLACE_REF_BASE` (any ref namespace), through `git replace`
of a checked file's blob (the worker then checks the substitute, not the committed content), and grafts
(`.git/info/grafts`, `GIT_GRAFT_FILE`) rewrite a commit's parent, which is the base a change is measured from.

The gate's git runner (hooks/lib/gate_git.run) sets GIT_NO_REPLACE_OBJECTS=1 and GIT_GRAFT_FILE=<null device> and
drops GIT_REPLACE_REF_BASE for every call, the worker's included. Each test is the attack, written to pass at
b851aa4 (the attack works there) and to fail here. Real repository, real hooks as subprocesses, a real worker
awaited by its exit; no sleep, poll or timeout.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from gate_support import GIT_ENV, HOOKS, Gate, git
from task_support import tasks
from test_gate_attacks import COMMIT, commit_rules, settle

sys.path.insert(0, str(HOOKS / "lib"))
import gate_git as gitq  # noqa: E402

# source: the check of review-r3/bin/a2_replace.py, with a pattern its own config does not contain
NO_BAD = {"name": "no-bad", "argv": ["sh", "-c", "! grep -rqE --exclude-dir=.git 'B[A]D' ."]}
OFF = json.dumps({"version": 1, "off": True})  # source: the substitute blob of review-r3/bin/a2_replace.py


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    commit_rules(g, [NO_BAD])
    yield g
    g.close()


def blob(g: Gate, text: str) -> str:
    out = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=g.repo, input=text, capture_output=True,
                         text=True, check=True, env={**GIT_ENV, "PATH": "/usr/bin:/bin"})
    return out.stdout.strip()


def stage_bad(g: Gate) -> None:
    (g.repo / "a.txt").write_text("BAD\n")
    git(g.repo, "add", "a.txt")


def refused_and_failed(g: Gate) -> None:
    """The commit is not allowed: the verification starts (rc 2), runs HEAD's real rule, and fails."""
    rc, _, err = g.gate(COMMIT)
    assert rc == 2, f"the commit was allowed: {err}"
    assert settle(g)["state"] == "failed"
    rc, _, err = g.gate(COMMIT)
    assert rc == 2 and "verification FAILED" in err


def test_a_replace_ref_does_not_switch_the_rules_off(gate):
    git(gate.repo, "replace", git(gate.repo, "rev-parse", "HEAD:.zetetic/gate.json"), blob(gate, OFF))
    stage_bad(gate)
    refused_and_failed(gate)


def test_a_replace_ref_base_in_the_environment_does_not_switch_the_rules_off(gate):
    git(gate.repo, "update-ref", "refs/elsewhere/" + git(gate.repo, "rev-parse", "HEAD:.zetetic/gate.json"), blob(gate, OFF))
    gate.env["GIT_REPLACE_REF_BASE"] = "refs/elsewhere/"
    stage_bad(gate)
    refused_and_failed(gate)


def test_the_worker_checks_the_committed_content_not_a_replacement_of_it(gate):
    stage_bad(gate)
    git(gate.repo, "replace", git(gate.repo, "rev-parse", ":a.txt"), blob(gate, "clean\n"))
    refused_and_failed(gate)


def test_a_replace_ref_of_head_itself_does_not_choose_the_trusted_tree(gate):
    """`git replace HEAD <a commit with no rules>`: HEAD^{tree} would read as ungated, so dropping the config would
    be read as having no rules and the failing change would pass unjudged."""
    empty = git(gate.repo, "hash-object", "-t", "tree", "/dev/null")
    git(gate.repo, "replace", git(gate.repo, "rev-parse", "HEAD"), git(gate.repo, "commit-tree", empty, "-m", "no rules"))
    git(gate.repo, "rm", "-q", "--cached", ".zetetic/gate.json")
    stage_bad(gate)
    refused_and_failed(gate)  # the real HEAD's rules still judge the staged tree


def grafted(g: Gate) -> tuple:
    """Three commits; the grafts file gives the last the first as its parent. (real parent tree, grafted parent tree)."""
    git(g.repo, "update-ref", "refs/remotes/origin/main", "HEAD")  # as after a fetch: the remote has the rules commit
    for text in ("two\n", "three\n"):
        (g.repo / "a.txt").write_text(text)
        git(g.repo, "commit", "-q", "-am", text.strip(), "--no-verify")
    real, fake = git(g.repo, "rev-parse", "HEAD~1^{tree}"), git(g.repo, "rev-parse", "HEAD~2^{tree}")
    return real, fake


def push_base(g: Gate, env: dict | None = None) -> str:
    """The `--base` the push verification of HEAD was started with (the task record's argv)."""
    rc, _, err = g.hook("gate-proof.py", "git push origin main") if env is None else _hook_env(g, env)
    assert rc == 2 and "verification started" in err, err
    argv = settle(g)["input"]["argv"]
    return argv[argv.index("--base") + 1]


def _hook_env(g: Gate, env: dict):
    saved = dict(g.env)
    g.env.update(env)
    try:
        return g.hook("gate-proof.py", "git push origin main")
    finally:
        g.env.clear()
        g.env.update(saved)


def test_a_grafts_file_does_not_choose_the_base_a_push_is_measured_from(gate):
    real, fake = grafted(gate)
    head, root = git(gate.repo, "rev-parse", "HEAD"), git(gate.repo, "rev-parse", "HEAD~2")
    (gate.repo / ".git" / "info").mkdir(exist_ok=True)
    (gate.repo / ".git" / "info" / "grafts").write_text(f"{head} {root}\n")
    assert git(gate.repo, "rev-parse", "HEAD^^{tree}") == fake != real  # git itself follows the graft
    assert push_base(gate) == real


def test_a_graft_file_named_in_the_environment_does_not_choose_the_base(gate, tmp_path):
    real, fake = grafted(gate)
    head, root = git(gate.repo, "rev-parse", "HEAD"), git(gate.repo, "rev-parse", "HEAD~2")
    grafts = tmp_path / "grafts"
    grafts.write_text(f"{head} {root}\n")
    assert push_base(gate, {"GIT_GRAFT_FILE": str(grafts)}) == real and real != fake


def test_the_hot_path_runs_git_bounded_and_on_the_same_objects(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(gitq.subprocess, "run", lambda argv, **kw: seen.append((argv, kw["env"])) or None)
    gitq.git(str(tmp_path), "rev-parse", "HEAD")
    gitq.run(str(tmp_path), ["cat-file", "blob", "x"], {}, text=False, bounded=False)
    (hot_argv, hot), (_, worker) = seen
    assert hot_argv == ["git", "rev-parse", "HEAD"]
    assert hot["GIT_NO_LAZY_FETCH"] == "1" and hot["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert "GIT_NO_LAZY_FETCH" not in worker and worker["GIT_NO_REPLACE_OBJECTS"] == "1"


def test_the_runner_environment_neutralises_every_substitution(monkeypatch):
    monkeypatch.setenv("GIT_REPLACE_REF_BASE", "refs/elsewhere/")
    monkeypatch.setenv("GIT_GRAFT_FILE", "/somewhere/grafts")
    monkeypatch.setenv("GIT_NO_REPLACE_OBJECTS", "0")
    for env in (gitq.environment(), gitq.environment({"GIT_REPLACE_REF_BASE": "x", "KEEP": "1"}, bounded=False)):
        assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert env["GIT_GRAFT_FILE"] == gitq.os.devnull
        assert "GIT_REPLACE_REF_BASE" not in env
    assert gitq.environment({"KEEP": "1"}, bounded=False)["KEEP"] == "1"
    assert "GIT_NO_LAZY_FETCH" not in gitq.environment({}, bounded=False)  # the worker may fetch: it is not the hot path
    assert gitq.environment({})["GIT_NO_LAZY_FETCH"] == "1"

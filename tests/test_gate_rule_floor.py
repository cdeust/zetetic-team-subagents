"""Rules may only grow without the owner (PR #169, round 3, blocking item 1).

The attack, reproduced at ea62083: commit A deletes `.zetetic/gate.json` (or replaces it by `["true"]`). It
passes, because HEAD's OLD checks still pass on it. Commit B is then judged by a HEAD with no rules, and a
failing `bad.txt` is allowed. Each weakening form below is the attack: written to pass at ea62083 (the commit is
let through) and to fail here. Real repository, real hook as a subprocess; no sleep, poll or timeout.

Superset, precisely (docs/gate.md, "Rule changes"): a commit may add checks, paths, tests, full_on entries; it may
not remove or replace one that HEAD's rules have. Anything else is a weakening and needs a line in the user's
acknowledgement file, which the hooks never write.
"""
from __future__ import annotations

import copy
import json
import os
import re
import stat

import pytest

from gate_support import ACK_ENV, Gate, git, payload, run_hook, write_config
from task_support import tasks
from test_gate_attacks import COMMIT, settle

PATHLESS = {"name": "always", "argv": ["true"]}
SCOPED = {"name": "scoped", "argv": ["sh", "-c", "test ! -e bad.txt"], "paths": ["a/**", "b/**", "**/*.txt"]}
RATCHET = {"name": "ratchet", "argv": ["true"], "paths": ["**/*.py"], "scope": "added"}  # judges added files only
BASE = {
    "version": 1,
    "full_on": ["Makefile", "pyproject.toml"],
    "env": {"KEEP": "1"},
    "checks": [PATHLESS, SCOPED, RATCHET],
    "tests": {
        "argv": ["sh", "-c", "true", "gate", "{tests}"],
        "files": ["tests/test_*.py"],
        "same_name": "tests/test_{stem}.py",
        "fast": ["tests/test_fast.py"],
        "map": [{"paths": ["src/**", "lib/**"], "tests": ["tests/test_src.py", "tests/test_lib.py"]}],
    },
}


def edit(fn):
    def apply(cfg):
        cfg = copy.deepcopy(cfg)
        fn(cfg)
        return cfg
    return apply


def drop(*keys):
    def fn(cfg):
        node = cfg
        for key in keys[:-1]:
            node = node[key]
        del node[keys[-1]]
    return edit(fn)


# form id -> (a function BASE -> the weakened config, the fragment the denial must name)
WEAKENINGS = {
    "off": (edit(lambda c: c.update(off=True)), "off"),
    "replaced-by-true": (lambda c: {"version": 1, "checks": [{"name": "yes", "argv": ["true"]}]}, "scoped"),
    "check-removed": (edit(lambda c: c["checks"].pop(1)), "scoped"),
    "check-argv-replaced": (edit(lambda c: c["checks"][1].update(argv=["true"])), "scoped"),
    "pathless-check-narrowed": (edit(lambda c: c["checks"][0].update(paths=["**"])), "always"),
    "selection-narrowed": (edit(lambda c: c["checks"][1].update(paths=["a/**"])), "scoped"),
    "path-replaced-by-a-narrower-one": (edit(lambda c: c["checks"][1].update(paths=["a/**", "b/**", "src/*.txt"])), "scoped"),
    "tests-removed": (drop("tests"), "tests"),
    "tests-argv-replaced": (edit(lambda c: c["tests"].update(argv=["true", "{tests}"])), "tests"),
    "tests-files-changed": (edit(lambda c: c["tests"].update(files=["tests/test_x.py"])), "tests"),
    "same-name-removed": (edit(lambda c: c["tests"].update(same_name="")), "same_name"),
    "fast-removed": (drop("tests", "fast"), "fast"),
    "map-entry-removed": (drop("tests", "map"), "map"),
    "map-test-removed": (edit(lambda c: c["tests"]["map"][0].update(tests=["tests/test_src.py"])), "map"),
    "map-pattern-added": (edit(lambda c: c["tests"]["map"].append({"paths": ["docs/**"], "tests": ["tests/test_fast.py"]})), "map"),
    "full-on-shrunk": (edit(lambda c: c.update(full_on=["Makefile"])), "full_on"),
    "env-changed": (edit(lambda c: c["env"].update(HIJACK="1")), "env"),
    "env-removed": (drop("env"), "env"),
    "check-scoped-to-added-files": (edit(lambda c: c["checks"][1].update(scope="added")), "scoped"),
}


def commit_config(g: Gate, cfg: dict) -> None:
    (g.repo / ".zetetic").mkdir(exist_ok=True)
    (g.repo / ".zetetic" / "gate.json").write_text(json.dumps(cfg))
    git(g.repo, "add", ".zetetic/gate.json")
    git(g.repo, "commit", "-q", "-m", "rules", "--no-verify")


def stage_config(g: Gate, cfg: dict) -> None:
    (g.repo / ".zetetic").mkdir(exist_ok=True)
    (g.repo / ".zetetic" / "gate.json").write_text(json.dumps(cfg))
    git(g.repo, "add", ".zetetic/gate.json")


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    commit_config(g, BASE)
    yield g
    g.close()


def ack_line(err: str) -> str:
    found = re.findall(r"^(/\S+ [0-9a-f]{32})$", err, re.M)
    assert len(found) == 1, err
    return found[0]


def assert_weakening(err: str, fragment: str) -> None:
    assert "weakens the gate rules" in err and "Nothing was run" in err, err
    assert fragment in err, err


@pytest.mark.parametrize("form", sorted(WEAKENINGS))
def test_a_commit_that_weakens_the_rules_is_denied_naming_the_rule_and_the_line_to_add(gate, form):
    change, fragment = WEAKENINGS[form]
    gate.stage("two\n")
    stage_config(gate, change(BASE))
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2, err
    assert_weakening(err, fragment)
    assert os.path.realpath(gate.repo) in ack_line(err) and str(gate.ack_file) in err
    assert gate.started() == [] and gate.runs() == 0  # nothing declared by the weakening change was run
    assert not gate.ack_file.exists()  # the hook never writes the user's file


def test_deleting_the_config_is_denied_and_so_is_deleting_it_without_staging_anything_else(gate):
    git(gate.repo, "rm", "-q", ".zetetic/gate.json")
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2
    assert_weakening(err, "gate.json")
    assert gate.started() == []


def test_the_two_commit_attack_does_not_get_its_first_step_without_the_owner(gate):
    """A deletes the rules; B (a failing bad.txt) is then judged by nothing. Without the owner A never lands."""
    git(gate.repo, "rm", "-q", ".zetetic/gate.json")
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "weakens the gate rules" in err
    git(gate.repo, "reset", "-q", "--", ".zetetic/gate.json")  # A could not be committed: the rules are still HEAD's
    git(gate.repo, "checkout", "--", ".zetetic/gate.json")
    (gate.repo / "bad.txt").write_text("fails HEAD's rule\n")
    git(gate.repo, "add", "bad.txt")
    assert gate.gate(COMMIT)[0] == 2
    assert settle(gate)["state"] == "failed"  # still judged by the rules A tried to delete
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "verification FAILED" in err


def test_the_owner_can_acknowledge_exactly_one_rules_state(gate):
    """The line the denial prints, copied into the user's file, lets that state through; no other."""
    gate.stage("two\n")
    stage_config(gate, {"version": 1, "checks": [{"name": "yes", "argv": ["true"]}]})
    _, _, err = gate.gate(COMMIT)
    line = ack_line(err)
    gate.ack_file.write_text(line.rsplit(" ", 1)[0] + " " + "0" * 32 + "\n")  # the right repository, another state
    assert "weakens the gate rules" in gate.gate(COMMIT)[2]
    gate.ack_file.write_text("/another/repo " + line.rsplit(" ", 1)[1] + "\n")  # another repository, this state
    assert "weakens the gate rules" in gate.gate(COMMIT)[2]
    gate.ack_file.write_text("# a note\n\n" + line + "\n")
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "weakens" not in err and "verification started" in err  # acknowledged: now it is judged
    assert settle(gate)["state"] == "done"
    assert gate.gate(COMMIT) == (0, "", "")
    gate.commit()
    (gate.repo / "bad.txt").write_text("the owner accepted these rules\n")
    git(gate.repo, "add", "bad.txt")
    assert gate.gate(COMMIT)[0] == 2 and settle(gate)["state"] == "done"  # the new state is the floor now
    stage_config(gate, {"version": 1, "off": True})  # a further weakening: a state nobody acknowledged
    assert "weakens the gate rules" in gate.gate(COMMIT)[2]


def test_the_acknowledgement_file_is_not_honoured_from_inside_the_repository(gate):
    gate.stage("two\n")
    stage_config(gate, {"version": 1, "checks": [{"name": "yes", "argv": ["true"]}]})
    _, _, err = gate.gate(COMMIT)
    own = gate.repo / ".zetetic" / "rule-changes"
    own.write_text(ack_line(err) + "\n")
    rc, _, err = run_hook("gate-proof.py", payload(COMMIT, gate.repo), gate.repo, {**gate.env, ACK_ENV: str(own)})
    assert rc == 2 and "weakens the gate rules" in err


@pytest.mark.parametrize("grow", [
    "check-added", "check-renamed", "check-reordered", "path-added", "pathless-stays", "test-added-to-a-map-pattern",
    "full-on-grown", "fast-grown", "tests-added-from-none", "ratchet-widened-to-every-file",
])
def test_growth_is_not_a_weakening(gate, grow):
    cfg = copy.deepcopy(BASE)
    if grow == "check-added":
        cfg["checks"].append({"name": "extra", "argv": ["true"]})
    elif grow == "check-renamed":
        cfg["checks"][1]["name"] = "renamed"
    elif grow == "check-reordered":
        cfg["checks"].reverse()
    elif grow == "path-added":
        cfg["checks"][1]["paths"].append("docs/**")
    elif grow == "test-added-to-a-map-pattern":
        cfg["tests"]["map"][0]["tests"].append("tests/test_more.py")
    elif grow == "full-on-grown":
        cfg["full_on"].append("setup.py")
    elif grow == "fast-grown":
        cfg["tests"]["fast"].append("tests/test_other.py")
    elif grow == "tests-added-from-none":
        commit_config(gate, drop("tests")(BASE))
    elif grow == "ratchet-widened-to-every-file":
        del cfg["checks"][2]["scope"]
    gate.stage("two\n")
    stage_config(gate, cfg)
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "weakens" not in err and "verification started" in err, err


def test_a_repository_with_no_rules_may_gain_some(gate):
    git(gate.repo, "rm", "-q", "-f", ".zetetic/gate.json")
    git(gate.repo, "commit", "-q", "-m", "no rules", "--no-verify")
    gate.stage("two\n")
    stage_config(gate, BASE)
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "weakens" not in err


# ------------------------------------------------------------------ the legacy scripts/gate.sh


@pytest.fixture
def legacy(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    git(g.repo, "rm", "-q", ".zetetic/gate.json")
    script = g.repo / "scripts" / "gate.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\ntest ! -e bad.txt\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    git(g.repo, "add", "scripts/gate.sh")
    git(g.repo, "commit", "-q", "-m", "legacy gate", "--no-verify")
    yield g
    g.close()


def test_deleting_the_legacy_script_when_no_config_exists_is_a_weakening(legacy):
    git(legacy.repo, "rm", "-q", "scripts/gate.sh")
    rc, _, err = legacy.gate(COMMIT)
    assert rc == 2
    assert_weakening(err, "scripts/gate.sh")
    assert legacy.started() == []


def test_making_the_legacy_script_non_executable_is_a_weakening(legacy):
    git(legacy.repo, "update-index", "--chmod=-x", "scripts/gate.sh")
    rc, _, err = legacy.gate(COMMIT)
    assert rc == 2
    assert_weakening(err, "scripts/gate.sh")


def test_replacing_the_legacy_script_is_a_weakening_its_content_cannot_be_compared(legacy):
    (legacy.repo / "scripts" / "gate.sh").write_text("#!/bin/sh\nexit 0\n")
    git(legacy.repo, "add", "scripts/gate.sh")
    rc, _, err = legacy.gate(COMMIT)
    assert rc == 2
    assert_weakening(err, "scripts/gate.sh")


def test_replacing_the_legacy_script_by_a_config_is_a_weakening(legacy):
    write_config(legacy.repo, [{"name": "yes", "argv": ["true"]}])
    git(legacy.repo, "add", ".zetetic/gate.json")
    rc, _, err = legacy.gate(COMMIT)
    assert rc == 2
    assert_weakening(err, "scripts/gate.sh")


def test_an_unrelated_change_beside_an_untouched_legacy_script_is_judged_not_refused(legacy):
    (legacy.repo / "scripts" / "other.sh").write_text("#!/bin/sh\n")  # another file of scripts/ changes the scripts tree
    git(legacy.repo, "add", "scripts/other.sh")
    rc, _, err = legacy.gate(COMMIT)
    assert rc == 2 and "weakens" not in err and "verification started" in err

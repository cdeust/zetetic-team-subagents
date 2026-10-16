"""The rule floor is kept by the user, not by HEAD (PR #169, review round 3, finding 1).

The attack, reproduced at b851aa4 (review-r3/transcripts/a1_floor.txt): the round-3 floor was "the rules at HEAD",
and HEAD moves under commands the gate does not judge. `git checkout --orphan nogate` keeps the index; after
`git rm --cached .zetetic/gate.json` the commit that drops the config weakened nothing (HEAD had no rules), the next
failing commit was ungated, and `git push -f origin nogate:main` and `git push origin nogate` published it. The
same with `git reset --soft` to a commit before the gate.

The invariant (docs/gate.md, "Rule changes"): no commit and no push the hook judges is allowed when the rules it
would leave in force (in the new commit, or on a destination ref) are weaker than a state of the floor the user
keeps for the repository, than HEAD's rules (commit) or than a destination ref's rules (push), unless the user's
acknowledgement file holds the exact `<repository> <hash>` line for that end state. The floor (hooks/lib/
gate_floor.py) lives outside every repository and records what the hooks saw in force; it starts empty, so each
attack below begins with one judged commit in the gated repository, as a user who has used the gate has.

Each test is the attack, written to pass at b851aa4 and to fail here, except the controls (named so). Real
repository, real hooks as subprocesses, a real worker awaited by its exit; no sleep, poll or timeout.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys

import pytest

from gate_support import FLOOR_ENV, HOOKS, Gate, git, payload, run_hook, write_config
from task_support import tasks
from test_gate_attacks import COMMIT, commit_rules, settle

sys.path.insert(0, str(HOOKS / "lib"))

# source: the check of review-r3/bin/a1_floor.py, with a pattern its own config does not contain
NO_BAD = {"name": "no-bad", "argv": ["sh", "-c", "! grep -rqE --exclude-dir=.git 'B[A]D' ."]}
OTHER = {"name": "other", "argv": ["true"]}  # source: a second check that always passes, for growth and lowering
ACK_LINE = re.compile(r"^(/\S+ [0-9a-f]{32})$", re.M)  # source: the line gate_ack.refusal prints


@pytest.fixture
def gate(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(tasks.store.ENV_DIR, str(tmp_path / "state"))
    g = Gate(tmp_path)
    commit_rules(g, [NO_BAD])
    yield g
    g.close()


def floor_files(g: Gate) -> list:
    directory = g.tmp / "floor"
    return sorted(directory.glob("*.jsonl")) if directory.is_dir() else []


def floor_rows(g: Gate) -> list:
    return [json.loads(line) for f in floor_files(g) for line in f.read_text().splitlines()]


def allowed_commit(g: Gate, text: str = "two\n") -> None:
    """One judged commit: the verification runs and passes, the hook allows the commit, git makes it."""
    g.stage(text)
    assert g.gate(COMMIT)[0] == 2
    assert settle(g)["state"] == "done"
    rc, _, err = g.gate(COMMIT)
    assert rc == 0, err
    g.commit()


def seeded(g: Gate) -> None:
    allowed_commit(g)
    assert [row["op"] for row in floor_rows(g)] == ["raise"]  # the rules in force are recorded


def with_remote(g: Gate) -> None:
    git(g.tmp, "init", "-q", "--bare", "remote.git")
    git(g.repo, "remote", "add", "origin", str(g.tmp / "remote.git"))
    git(g.repo, "push", "-q", "origin", "main")
    git(g.repo, "fetch", "-q", "origin")


def orphan_without_rules(g: Gate) -> None:
    git(g.repo, "checkout", "-q", "--orphan", "nogate")
    git(g.repo, "rm", "-q", "--cached", ".zetetic/gate.json")


def stage_bad(g: Gate) -> None:
    (g.repo / "a.txt").write_text("BAD\n")
    git(g.repo, "add", "a.txt")


def weakens(result: tuple, *fragments: str) -> str:
    rc, _, err = result
    assert rc == 2 and "weakens the gate rules" in err, err
    for fragment in fragments:
        assert fragment in err, err
    return err


# ------------------------------------------------------------------ the attacks of a1_floor


def test_an_orphan_branch_cannot_drop_the_rules(gate):
    seeded(gate)
    orphan_without_rules(gate)
    weakens(gate.gate(COMMIT), 'check "no-bad" was removed', "the floor recorded for this repository")


def test_a_failing_commit_on_an_ungated_orphan_is_refused(gate):
    seeded(gate)
    orphan_without_rules(gate)
    git(gate.repo, "commit", "-q", "-m", "drop-gate", "--no-verify")  # made without the hook
    stage_bad(gate)
    weakens(gate.gate(COMMIT))


def test_an_ungated_orphan_cannot_be_pushed(gate):
    seeded(gate)
    with_remote(gate)
    orphan_without_rules(gate)
    stage_bad(gate)
    git(gate.repo, "commit", "-q", "-m", "broken", "--no-verify")
    weakens(gate.hook("gate-proof.py", "git push -f origin nogate:main"), "refs/remotes/origin/main")
    weakens(gate.hook("gate-proof.py", "git push origin nogate"), "the floor recorded for this repository")


def test_reset_soft_to_a_commit_before_the_gate_cannot_drop_the_rules(gate):
    seeded(gate)
    empty = git(gate.repo, "hash-object", "-t", "tree", "/dev/null")
    git(gate.repo, "reset", "-q", "--soft", git(gate.repo, "commit-tree", empty, "-m", "pregate"))
    git(gate.repo, "rm", "-q", "--cached", ".zetetic/gate.json")
    stage_bad(gate)
    weakens(gate.gate(COMMIT), "the floor recorded for this repository")


def test_a_push_cannot_replace_a_fetched_branch_by_a_weaker_tip_even_with_no_floor(gate):
    """No judged act yet, so no floor: the destination's own rules, as of the last fetch, are the anchor."""
    with_remote(gate)
    orphan_without_rules(gate)
    git(gate.repo, "commit", "-q", "-m", "drop", "--no-verify")
    weakens(gate.hook("gate-proof.py", "git push -f origin nogate:main"), "refs/remotes/origin/main, as of the last fetch")
    weakens(gate.hook("gate-proof.py", "git push -f origin HEAD:refs/heads/main"), "refs/remotes/origin/main")
    assert floor_files(gate) == []  # nothing was allowed and HEAD (the orphan) has no rules: nothing recorded


def test_an_invalid_config_on_a_destination_refuses_and_names_the_ref(gate):
    (gate.repo / ".zetetic" / "gate.json").write_text('{"version": 1, "checks": "not a list"}')
    git(gate.repo, "commit", "-q", "-am", "invalid", "--no-verify")
    git(gate.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(gate.repo, "remote", "add", "origin", str(gate.tmp / "nowhere.git"))
    git(gate.repo, "reset", "-q", "--hard", "HEAD~1")
    rc, _, err = gate.hook("gate-proof.py", "git push origin main")
    assert rc == 2 and "is invalid (refs/remotes/origin/main: " in err, err


def test_a_denied_commit_records_the_rules_of_head(gate):
    """HEAD's rules are in force whatever the verdict: the first judged commit seeds the floor even when denied."""
    gate.stage("two\n")
    assert gate.gate(COMMIT)[0] == 2  # verification started: denied for now
    assert [row["op"] for row in floor_rows(gate)] == ["raise"]
    settle(gate)
    orphan_without_rules(gate)
    weakens(gate.gate(COMMIT), "the floor recorded for this repository")


def test_a_denied_call_never_lowers_the_floor(gate):
    """An acknowledged weakening whose verification is still running is denied: the floor keeps what it had."""
    seeded(gate)
    git(gate.repo, "checkout", "-q", "-b", "exp")
    write_config(gate.repo, [NO_BAD, OTHER])
    git(gate.repo, "add", ".zetetic/gate.json")
    allowed_commit(gate, "three\n")  # the floor is now no-bad + other, more than main's HEAD has
    git(gate.repo, "checkout", "-q", "main")
    gate.stage("four\n")
    acknowledge(gate, gate.gate(COMMIT))
    rc, _, err = gate.gate(COMMIT)  # acknowledged, then denied: its verification starts
    assert rc == 2 and "verification started" in err, err
    settle(gate)
    assert [row["op"] for row in floor_rows(gate)] == ["raise", "raise"]  # no `set` from a denied call


def test_the_acknowledged_drop_of_every_rule_is_allowed_and_empties_the_floor(gate):
    seeded(gate)
    orphan_without_rules(gate)
    acknowledge(gate, gate.gate(COMMIT))
    rc, _, err = gate.gate(COMMIT)
    assert rc == 0, err  # no rules left: nothing to verify, the owner's line lets it through
    assert floor_rows(gate)[-1]["op"] == "set" and floor_rows(gate)[-1]["states"] == []


def test_a_floor_that_cannot_be_written_refuses_what_it_would_have_to_record(gate):
    """An allowed call that cannot record what it leaves in force is refused; a denied one says it could not."""
    seeded(gate)
    directory = gate.tmp / "floor"
    write_config(gate.repo, [NO_BAD, OTHER])  # a growth: allowing it must append a line
    git(gate.repo, "add", ".zetetic/gate.json")
    gate.stage("three\n")
    assert gate.gate(COMMIT)[0] == 2
    settle(gate)
    floor_files(gate)[0].chmod(stat.S_IRUSR)
    directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        rc, _, err = gate.gate(COMMIT)
        assert rc == 2 and "rule floor" in err and "cannot be recorded" in err, err
        git(gate.repo, "checkout", "-q", "-b", "other-head")
        git(gate.repo, "commit", "-q", "-m", "x", "--no-verify")  # HEAD now holds rules the floor lacks
        gate.stage("four\n")
        rc, _, err = gate.gate(COMMIT)  # denied (verification starts); observing HEAD cannot be recorded
        assert rc == 2 and "could not be recorded in the floor" in err, err
        settle(gate)
    finally:
        directory.chmod(stat.S_IRWXU)
        floor_files(gate)[0].chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_a_growth_on_one_branch_is_the_floor_of_every_branch(gate):
    """The floor is the repository's, not a branch's: a check added on one branch is kept on the others."""
    seeded(gate)
    git(gate.repo, "checkout", "-q", "-b", "exp")
    write_config(gate.repo, [NO_BAD, OTHER])
    git(gate.repo, "add", ".zetetic/gate.json")
    allowed_commit(gate, "three\n")
    git(gate.repo, "checkout", "-q", "main")
    gate.stage("four\n")
    weakens(gate.gate(COMMIT), 'check "other" was removed')


# ------------------------------------------------------------------ the owner lowers the floor


def acknowledge(g: Gate, result: tuple) -> None:
    g.ack_file.write_text(ACK_LINE.findall(weakens(result))[0] + "\n")


def test_the_acknowledgement_line_lowers_the_floor(gate):
    seeded(gate)
    write_config(gate.repo, [OTHER])  # no-bad removed: a weakening
    git(gate.repo, "add", ".zetetic/gate.json")
    acknowledge(gate, gate.gate(COMMIT))
    allowed_commit(gate, "three\n")
    assert [row["op"] for row in floor_rows(gate)][-1] == "set"
    # from the lowered floor, a growth needs no acknowledgement: the removed check is no longer the floor
    write_config(gate.repo, [OTHER, {"name": "more", "argv": ["true", "more"]}])
    git(gate.repo, "add", ".zetetic/gate.json")
    allowed_commit(gate, "four\n")


def test_an_acknowledged_ungated_branch_pushed_with_main_keeps_mains_floor(gate, monkeypatch):
    """`git push origin main pages`, pages acknowledged without rules: the floor keeps main's rules (HEAD's)."""
    seeded(gate)
    with_remote(gate)
    orphan_without_rules(gate)
    git(gate.repo, "commit", "-q", "-m", "pages", "--no-verify")
    git(gate.repo, "checkout", "-q", "-f", "main")
    git(gate.repo, "commit", "-q", "--allow-empty", "-m", "ahead", "--no-verify")
    push = "git push origin main nogate"
    first = gate.hook("gate-proof.py", push)  # main's push verification starts; nogate weakens the floor
    settle(gate)
    acknowledge(gate, first)
    rc, _, err = gate.hook("gate-proof.py", push)  # acknowledged: nogate is now verified, by HEAD's rules (the union)
    assert rc == 2 and "[nogate] GATE-PROOF: verification started" in err, err
    settle(gate)
    rc, _, err = gate.hook("gate-proof.py", push)
    assert rc == 0, err
    monkeypatch.setenv(FLOOR_ENV, gate.env[FLOOR_ENV])
    import gate_floor  # here, not at the top: at b851aa4 the module does not exist and the other tests must run
    kept = gate_floor.read(str(gate.repo), str(gate.repo / ".git"))
    assert [s.cfg["checks"] for s in kept] == [[NO_BAD]]


# ------------------------------------------------------------------ closed by default


def ungated_orphan(g: Gate) -> None:
    seeded(g)
    orphan_without_rules(g)


@pytest.mark.parametrize("content", ["not json\n", '{"repo": "/elsewhere", "op": "raise", "states": []}\n',
                                     '{"op": "raise"}\n', '{"repo": "R", "op": "lower", "states": []}\n'])
def test_a_floor_that_cannot_be_parsed_refuses(gate, content):
    ungated_orphan(gate)
    floor_files(gate)[0].write_text(content.replace('"R"', json.dumps(os.path.realpath(gate.repo))))
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "rule floor" in err and "cannot be read" in err, err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_a_floor_that_cannot_be_read_refuses(gate):
    ungated_orphan(gate)
    path = floor_files(gate)[0]
    path.chmod(0)
    try:
        rc, _, err = gate.gate(COMMIT)
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert rc == 2 and "cannot be read" in err, err


def test_a_floor_directory_inside_the_repository_is_refused(gate):
    gate.env[FLOOR_ENV] = str(gate.repo / ".floor")
    gate.stage("two\n")
    rc, _, err = gate.gate(COMMIT)
    assert rc == 2 and "inside the repository" in err, err


def test_a_hook_that_cannot_judge_refuses_where_only_the_floor_holds(gate, tmp_path):
    """An orphan declares nothing, not even in the working copy: the floor alone makes the repository gated, so a
    crash of the hook and an unreadable payload refuse there, as they do where a gate is declared."""
    ungated_orphan(gate)
    (gate.repo / ".zetetic" / "gate.json").unlink()
    crashing = {"cwd": str(gate.repo), "tool_name": "Bash", "tool_input": ["not", "an", "object"]}
    rc, _, err = run_hook("gate-proof.py", crashing, tmp_path, gate.env)
    assert rc == 2 and "crashed" in err, err
    rc, _, err = run_hook("gate-proof.py", "{not json", gate.repo, gate.env)
    assert rc == 2 and "unreadable" in err, err
    inside = {**gate.env, FLOOR_ENV: str(gate.repo / ".floor")}  # a floor the repository controls is not known empty
    (gate.tmp / "floor").rename(gate.tmp / "floor-away")
    rc, _, err = run_hook("gate-proof.py", crashing, tmp_path, inside)
    assert rc == 2 and "crashed" in err, err


def test_an_override_cannot_hide_the_floor_kept_in_the_default_place(gate, monkeypatch, tmp_path):
    """A session variable can be set by a project's settings: pointing the floor at an empty directory must not
    empty it. The default place is always read too."""
    monkeypatch.delenv(FLOOR_ENV, raising=False)
    del gate.env[FLOOR_ENV]
    gate.env["HOME"] = str(tmp_path / "home")
    allowed_commit(gate)
    assert list((tmp_path / "home" / ".claude" / "zetetic" / "gate-rule-floor").glob("*.jsonl"))
    orphan_without_rules(gate)
    gate.env[FLOOR_ENV] = str(tmp_path / "empty")
    weakens(gate.gate(COMMIT), "the floor recorded for this repository")


def test_the_floor_files_are_private_to_the_user(gate):
    seeded(gate)
    assert stat.S_IMODE(floor_files(gate)[0].stat().st_mode) == 0o600


# ------------------------------------------------------------------ controls


def test_control_a_repository_with_no_rules_and_no_floor_stays_ungated(tmp_path):
    repo = tmp_path / "plain"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    env = {FLOOR_ENV: str(tmp_path / "floor"), tasks.store.ENV_DIR: str(tmp_path / "state")}
    assert run_hook("gate-proof.py", payload(COMMIT, repo), repo, env)[0] == 0
    assert not (tmp_path / "floor").exists()


def test_control_the_head_start_never_writes_the_floor(gate):
    gate.stage("two\n")
    assert gate.head_start()[0] == 0
    assert floor_files(gate) == []


def test_an_unchanged_floor_appends_nothing(gate):
    seeded(gate)
    allowed_commit(gate, "three\n")
    assert len(floor_rows(gate)) == 1

"""hooks/lib/gate_floor.py in-process: the replay of the floor file, the maximal states, the destinations of a push.

The attacks against the real hooks are tests/test_gate_floor_user.py; this file pins the data rules they rest on.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from gate_support import FLOOR_ENV, git

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_floor as floor  # noqa: E402
import gate_publish as pub  # noqa: E402
import gate_pushargs as pushargs  # noqa: E402
import gate_rules as rules  # noqa: E402


def cfg(*names: str) -> rules.RuleSet:
    return rules.RuleSet("config", {"version": 1, "checks": [{"name": n, "argv": ["true", n]} for n in names]}, None)


A, B, AB = cfg("a"), cfg("b"), cfg("a", "b")
A_RENAMED = rules.RuleSet("config", {"version": 1, "checks": [{"name": "other name", "argv": ["true", "a"]}]}, None)
LEGACY = rules.RuleSet("legacy", None, "1" * 40, "2" * 40)


def hashes(states: list) -> list:
    return sorted(rules.state_hash(s) for s in states)


def test_maximal_keeps_incomparable_states_and_drops_covered_ones():
    assert hashes(floor.maximal([A, B])) == hashes([A, B])
    assert hashes(floor.maximal([A, B, AB])) == hashes([AB])
    assert floor.maximal([None, None]) == []
    assert hashes(floor.maximal([A, A, None])) == hashes([A])
    assert hashes(floor.maximal([LEGACY, A])) == hashes([LEGACY, A])  # a script and rules do not compare


def test_of_two_states_that_cover_each_other_the_smaller_hash_stays():
    kept = floor.maximal([A, A_RENAMED])
    assert hashes(kept) == [min(rules.state_hash(A), rules.state_hash(A_RENAMED))]
    assert hashes(floor.maximal([A_RENAMED, A])) == hashes(kept)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv(FLOOR_ENV, str(tmp_path / "floor"))
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    return str(path), str(path / ".git")


def test_raise_accumulates_and_set_replaces(repo):
    top, common = repo
    assert floor.read(top, common) == []
    assert floor.record(top, common, [A], lowered=False)
    assert floor.record(top, common, [B], lowered=False)
    assert hashes(floor.read(top, common)) == hashes([A, B])
    assert not floor.record(top, common, [A], lowered=False)  # covered: nothing appended
    assert floor.record(top, common, [AB], lowered=False)
    assert hashes(floor.read(top, common)) == hashes([AB])
    assert floor.record(top, common, [A], lowered=True)
    assert hashes(floor.read(top, common)) == hashes([A])
    assert floor.record(top, common, [None], lowered=True)
    assert floor.read(top, common) == []
    rows = [json.loads(line) for line in Path(floor.path_of(top, common)).read_text().splitlines()]
    assert [r["op"] for r in rows] == ["raise", "raise", "raise", "set", "set"]
    assert {r["repo"] for r in rows} == {os.path.realpath(top)}


def test_every_state_kind_survives_the_file(repo):
    top, common = repo
    stack = rules.RuleSet("stack", {"version": 1, "checks": [{"name": "t", "argv": ["x"]}], "env": {}, "link": []}, None)
    floor.record(top, common, [LEGACY, stack, A], lowered=False)
    assert hashes(floor.read(top, common)) == hashes([LEGACY, stack, A])


@pytest.mark.parametrize("state", [
    {"kind": "config", "cfg": {"version": 1, "checks": "x"}, "scripts": None, "script": None},
    {"kind": "config", "cfg": {"version": 1, "checks": [{"name": "a", "argv": ["x"]}]}, "scripts": "1" * 40, "script": None},
    {"kind": "legacy", "cfg": {}, "scripts": None, "script": None},
    {"kind": "legacy", "cfg": None, "scripts": "not an id", "script": None},
    {"kind": "other", "cfg": None, "scripts": None, "script": None},
    {"kind": "config", "cfg": None, "scripts": None},
])
def test_a_malformed_state_makes_the_floor_unreadable(repo, state):
    top, common = repo
    path = floor.path_of(top, common)
    os.makedirs(os.path.dirname(path))
    Path(path).write_text(json.dumps({"repo": os.path.realpath(top), "op": "raise", "states": [state]}) + "\n")
    with pytest.raises(floor.Unreadable, match="line 1"):
        floor.read(top, common)


def test_a_worktree_shares_the_floor_of_its_main_checkout(repo, tmp_path):
    top, common = repo
    git(top, "commit", "-q", "--allow-empty", "-m", "x")
    git(top, "worktree", "add", "-q", str(tmp_path / "wt"))
    wt = str(tmp_path / "wt")
    assert floor.path_of(wt, common) == floor.path_of(top, common)


@pytest.fixture
def pushed(tmp_path, monkeypatch):
    for key, value in {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(key, value)
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "commit", "-q", "--allow-empty", "-m", "c")
    git(path, "branch", "feat")
    git(path, "remote", "add", "origin", str(tmp_path / "nowhere.git"))  # never contacted: nothing here fetches
    for ref in ("main", "feat", "other"):
        git(path, "update-ref", f"refs/remotes/origin/{ref}", "HEAD")
    return str(path)


def dests(top: str, command: str) -> dict:
    words = command.split()[2:]
    return {tip.name: tip.dests for tip in pub.resolve(top, pushargs.publish(words))}


def test_a_push_names_the_remote_tracking_refs_of_its_destinations(pushed):
    assert dests(pushed, "git push origin feat") == {"feat": ("refs/remotes/origin/feat",)}
    assert dests(pushed, "git push origin feat:other")["feat"] == ("refs/remotes/origin/other",)
    assert dests(pushed, "git push origin feat:refs/heads/main")["feat"] == ("refs/remotes/origin/main",)
    assert dests(pushed, "git push origin HEAD")["HEAD"] == ("refs/remotes/origin/main",)
    assert dests(pushed, "git push origin feat:never-fetched")["feat"] == ()
    ahead = git(pushed, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "ahead")  # a commit the remote lacks
    git(pushed, "update-ref", "refs/heads/feat", ahead)
    assert dests(pushed, "git push origin feat:refs/tags/t")["tag t"] == ()  # a tag has no remote-tracking ref


def test_a_refspec_less_push_also_names_the_upstream(pushed):
    git(pushed, "checkout", "-q", "feat")
    git(pushed, "branch", "-q", "--set-upstream-to", "origin/other")
    assert set(dests(pushed, "git push origin")["feat"]) == {"refs/remotes/origin/feat", "refs/remotes/origin/other"}
    assert dests(pushed, "git push origin feat")["feat"] == ("refs/remotes/origin/feat",)  # a refspec: no upstream


def test_all_and_glob_pushes_name_each_branch(pushed):
    found = dests(pushed, "git push --all origin")  # feat and main are one commit: one tip, both destinations
    assert {d for tip in found.values() for d in tip} == {"refs/remotes/origin/feat", "refs/remotes/origin/main"}
    glob = dests(pushed, "git push origin refs/heads/*:refs/heads/*")
    assert set(next(iter(glob.values()))) == {"refs/remotes/origin/feat", "refs/remotes/origin/main"}

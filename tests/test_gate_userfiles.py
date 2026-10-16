"""The user's files (trusted list, rule-change acknowledgements), and the relation "no weaker than", on data.

HOME as a dotfiles repository (PR #169 round 3): at ea62083 a repository whose root contains
`~/.claude/zetetic` could never be trusted, because the rule "a list inside the repository is the
repository's own claim" also covered the user's default file. Only the two files themselves are exempt now,
and only while $HOME is the account's home; every other path inside the repository is still the repository's.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from gate_support import git

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "lib"))
import gate_ack  # noqa: E402
import gate_git  # noqa: E402
import gate_rules as rules  # noqa: E402
import gate_superset as superset  # noqa: E402
import gate_trust  # noqa: E402


@pytest.fixture
def dotfiles(tmp_path, monkeypatch):
    """A repository at HOME holding ~/.claude/zetetic/{gate-trusted-repos,gate-rule-changes} (the user's files)."""
    home = tmp_path / "home"
    (home / ".claude" / "zetetic").mkdir(parents=True)
    git(home, "init", "-q", "-b", "main")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(gate_trust.ENV_FILE, raising=False)
    monkeypatch.delenv(gate_ack.ENV_FILE, raising=False)
    monkeypatch.setattr("pwd.getpwuid", lambda uid: types.SimpleNamespace(pw_dir=str(home)))  # the account's home is HOME
    top = os.path.realpath(home)
    (home / ".claude" / "zetetic" / "gate-trusted-repos").write_text(top + "\n")
    (home / ".claude" / "zetetic" / "gate-rule-changes").write_text(f"{top} {'a' * 32}\n")
    return home, top, gate_git.locate(str(home)).common


def test_a_repository_that_contains_the_default_trust_file_can_be_trusted(dotfiles):
    _, top, common = dotfiles
    assert gate_trust.is_trusted(top, common)


def test_a_repository_that_contains_the_default_acknowledgement_file_can_be_acknowledged(dotfiles):
    _, top, common = dotfiles
    assert gate_ack.acknowledged(top, common, "a" * 32)
    assert not gate_ack.acknowledged(top, common, "b" * 32)


def test_an_override_inside_the_dotfiles_repository_is_still_the_repositorys_own_claim(dotfiles, monkeypatch):
    home, top, common = dotfiles
    own = home / "evil-list"
    own.write_text(top + "\n")
    monkeypatch.setenv(gate_trust.ENV_FILE, str(own))
    assert not gate_trust.is_trusted(top, common)
    ack = home / "evil-acks"
    ack.write_text(f"{top} {'b' * 32}\n")
    monkeypatch.setenv(gate_ack.ENV_FILE, str(ack))
    assert not gate_ack.acknowledged(top, common, "b" * 32)


def test_a_home_redirected_into_the_repository_is_not_the_users_home(dotfiles, monkeypatch, tmp_path):
    """A project's settings can set HOME: the default file under a HOME that is not the account's home is the
    repository's claim, wherever the account database says the user lives."""
    home, top, common = dotfiles
    monkeypatch.setattr("pwd.getpwuid", lambda uid: types.SimpleNamespace(pw_dir=str(tmp_path / "real-home")))
    assert not gate_trust.is_trusted(top, common)
    assert not gate_ack.acknowledged(top, common, "a" * 32)


def test_a_repository_below_home_is_trusted_by_the_default_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "zetetic").mkdir(parents=True)
    repo = home / "work" / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(gate_trust.ENV_FILE, raising=False)
    monkeypatch.setattr("pwd.getpwuid", lambda uid: types.SimpleNamespace(pw_dir=str(home)))
    (home / ".claude" / "zetetic" / "gate-trusted-repos").write_text(os.path.realpath(repo) + "\n")
    assert gate_trust.is_trusted(os.path.realpath(repo), gate_git.locate(str(repo)).common)


def test_the_acknowledgement_file_is_parsed_strictly(tmp_path, monkeypatch):
    listing = tmp_path / "acks"
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    listing.write_text(f"# a note\n\n   {link}   {'1' * 32}  \nrelative/path {'2' * 32}\n{real} {'3' * 32} extra\n{real}\n")
    monkeypatch.setenv(gate_ack.ENV_FILE, str(listing))
    assert gate_ack._entries() == {(os.path.realpath(real), "1" * 32)}  # symlinks resolved; relative, 3-field, 1-field lines name nothing
    monkeypatch.setenv(gate_ack.ENV_FILE, str(tmp_path / "missing"))
    assert gate_ack._entries() == set()


def test_the_refusal_names_every_weakened_rule_and_the_exact_line(tmp_path, monkeypatch):
    monkeypatch.setenv(gate_ack.ENV_FILE, str(tmp_path / "acks"))
    text = gate_ack.refusal("/w/repo", "/w/repo/.git", "f" * 32, ["check \"a\" was removed", "env changed"])
    assert "  - check \"a\" was removed\n  - env changed\n" in text and f"\n{os.path.realpath('/w/repo')} {'f' * 32}\n" in text
    assert str(tmp_path / "acks") in text and "Nothing was run" in text
    assert not (tmp_path / "acks").exists()  # building the refusal writes nothing


# ------------------------------------------------------------------ the relation, on data


def cfg(**extra):
    return {"version": 1, "checks": [{"name": "a", "argv": ["x"]}], **extra}


def rs(kind="config", config=None, script=None):
    return rules.RuleSet(kind, config, None, script)


def test_a_superset_is_not_a_weakening():
    old = rs(config=cfg(full_on=["a"], tests={"argv": ["t", "{tests}"], "map": [{"paths": ["p"], "tests": ["t1"]}], "fast": ["f"]}))
    new = rs(config=cfg(full_on=["a", "b"], checks=[{"name": "z", "argv": ["x"]}, {"name": "b", "argv": ["y"], "paths": ["a"]}],
                        tests={"argv": ["t", "{tests}"], "map": [{"paths": ["p"], "tests": ["t1", "t2"]}], "fast": ["f", "g"]}))
    assert superset.weakenings(old, new) == [] and superset.weakenings(old, old) == [] and superset.weakenings(None, new) == []
    assert superset.weakenings(None, None) == []


def test_a_stack_is_compared_as_the_rules_it_generates():
    stack = rs("stack", {"version": 1, "checks": [{"name": "test", "argv": ["{python}", "-m", "pytest", "-q"]}], "env": {}, "link": []})
    keeps = rs("config", {"version": 1, "checks": [{"name": "t", "argv": ["{python}", "-m", "pytest", "-q"]}], "env": {}, "link": []})
    drops = rs("config", {"version": 1, "checks": [{"name": "t", "argv": ["true"]}]})
    assert superset.weakenings(stack, keeps) == []
    assert any("test" in w for w in superset.weakenings(stack, drops))


def test_a_legacy_script_is_not_comparable_with_anything_but_itself():
    legacy = rs("legacy", None, "a" * 40)
    assert superset.weakenings(legacy, rs("legacy", None, "a" * 40)) == []
    assert superset.weakenings(legacy, rs("legacy", None, "b" * 40))
    assert superset.weakenings(legacy, None) and superset.weakenings(legacy, rs(config=cfg()))
    assert superset.weakenings(rs(config=cfg()), legacy)
    assert superset.weakenings(None, legacy) == []


def test_the_state_hash_names_one_state():
    assert rules.state_hash(rs(config=cfg())) == rules.state_hash(rs(config=cfg()))
    assert rules.state_hash(rs(config=cfg())) != rules.state_hash(rs(config=cfg(env={"A": "1"})))
    assert rules.state_hash(None) != rules.state_hash(rs(config=cfg()))
    assert len(rules.state_hash(None)) == 32 and rules.state_hash(rs("legacy", None, "a" * 40)) != rules.state_hash(rs("legacy", None, "b" * 40))

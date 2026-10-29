"""The user's trusted-repositories list.

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
import gate_git  # noqa: E402
import gate_trust  # noqa: E402


@pytest.fixture
def dotfiles(tmp_path, monkeypatch):
    """A repository at HOME holding ~/.claude/zetetic/gate-trusted-repos (the user's file)."""
    home = tmp_path / "home"
    (home / ".claude" / "zetetic").mkdir(parents=True)
    git(home, "init", "-q", "-b", "main")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(gate_trust.ENV_FILE, raising=False)
    monkeypatch.setattr("pwd.getpwuid", lambda uid: types.SimpleNamespace(pw_dir=str(home)))  # the account's home is HOME
    top = os.path.realpath(home)
    (home / ".claude" / "zetetic" / "gate-trusted-repos").write_text(top + "\n")
    return home, top, gate_git.locate(str(home)).common


def test_a_repository_that_contains_the_default_trust_file_can_be_trusted(dotfiles):
    _, top, common = dotfiles
    assert gate_trust.is_trusted(top, common)


def test_an_override_inside_the_dotfiles_repository_is_still_the_repositorys_own_claim(dotfiles, monkeypatch):
    home, top, common = dotfiles
    own = home / "evil-list"
    own.write_text(top + "\n")
    monkeypatch.setenv(gate_trust.ENV_FILE, str(own))
    assert not gate_trust.is_trusted(top, common)


def test_a_home_redirected_into_the_repository_is_not_the_users_home(dotfiles, monkeypatch, tmp_path):
    """A project's settings can set HOME: the default file under a HOME that is not the account's home is the
    repository's claim, wherever the account database says the user lives."""
    home, top, common = dotfiles
    monkeypatch.setattr("pwd.getpwuid", lambda uid: types.SimpleNamespace(pw_dir=str(tmp_path / "real-home")))
    assert not gate_trust.is_trusted(top, common)


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


@pytest.mark.parametrize("common,expected", [("/w/main/.git", "/w/main"), ("/srv/r.git", "/w/top"), ("/w/main/.git/", "/w/top")])
def test_the_checkout_that_owns_a_git_directory(common, expected):
    assert gate_trust.repo_root("/w/top", common) == expected  # only a directory named .git has a parent that is a checkout

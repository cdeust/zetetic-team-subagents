"""The file the USER owns that the gate consults: the trusted-repositories list. It lives in
``~/.claude/zetetic/`` and is never written by a hook.

    ~/.claude/zetetic/gate-trusted-repos     one absolute repository path per line

Blank lines and `#` lines are ignored. The file has an override variable (tests, non-default layouts).

A project's settings can set session environment variables, so an OVERRIDE that points inside the repository
being judged (its working tree or its git directory) is ignored: a repository cannot vouch for itself. The
default location is not an override. It is exempt from that rule so that a repository whose root contains
``~/.claude/zetetic`` (a dotfiles repository at HOME) can still be trusted, with one condition: ``$HOME`` is
the account's home directory. A session whose HOME was redirected (into the repository) is not the user's home,
and its default location counts as an override.
"""
from __future__ import annotations

import os

try:
    import pwd
except ImportError:  # FAILS_ON: a platform without the pwd module (Windows): HOME is then the only home there is
    pwd = None


def _account_home() -> str | None:
    """The home directory the account database gives this user, or None when it cannot say."""
    if pwd is None:
        return None
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:  # FAILS_ON: a uid with no passwd entry (a container running as an arbitrary uid)
        return None


def _home_is_the_account_home() -> bool:
    account = _account_home()
    return account is None or os.path.realpath(account) == os.path.realpath(os.path.expanduser("~"))


def default(file_name: str) -> str:
    """The default location of the user's file ``file_name``: ``~/.claude/zetetic/<file_name>``."""
    return os.path.join(os.path.expanduser("~"), ".claude", "zetetic", file_name)


def location(env_name: str, file_name: str) -> tuple[str, bool]:
    """(path, is_default) of the user's file: the override variable when set, else the default under HOME."""
    override = os.environ.get(env_name)
    if override:
        return override, False
    return default(file_name), True


def _inside(path: str, directory: str) -> bool:
    inner, outer = os.path.realpath(path), os.path.realpath(directory)
    return inner == outer or inner.startswith(outer + os.sep)


def usable(path: str, is_default: bool, top: str, common: str) -> bool:
    """False when ``path`` is the repository's own claim: inside its working tree or git directory (an override,
    or a default under a redirected HOME). The default under the account's home is the user's, wherever it is."""
    if is_default and _home_is_the_account_home():
        return True
    return not (_inside(path, top) or _inside(path, common))


def lines(path: str) -> list:
    """The stripped lines of the file; an absent or unreadable file has none."""
    try:
        with open(path, encoding="utf-8") as fh:
            return [line.strip() for line in fh.read().splitlines()]
    except OSError:
        return []


def repo_root(top: str, common: str) -> str:
    """The checkout that owns ``common``: its parent when ``common`` is a `.git` directory, else ``top``."""
    return os.path.dirname(common) if os.path.basename(common) == ".git" else top

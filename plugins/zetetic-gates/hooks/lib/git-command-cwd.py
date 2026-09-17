#!/usr/bin/env python3
"""Print the working directory targeted by a git commit/push command."""

from __future__ import annotations

import os
import shlex
import sys

# Shell command boundaries emitted as standalone tokens by the configured
# ``shlex`` punctuation set. Sources: POSIX Shell Command Language §2.9.3 and
# Python 3 ``shlex.shlex(..., punctuation_chars=...)`` documentation.
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "{", "}"}


def _git_target(tokens: list[str], base: str) -> str | None:
    """Return the cwd of the first commit/push in one shell command segment."""
    for index, candidate in enumerate(tokens):
        if os.path.basename(candidate) != "git":
            continue
        current = base
        cursor = index + 1
        while cursor < len(tokens):
            token = tokens[cursor]
            if token == "-C" and cursor + 1 < len(tokens):
                path = tokens[cursor + 1]
                current = path if os.path.isabs(path) else os.path.join(current, path)
                current = os.path.abspath(current)
                cursor += 2
                continue
            if token in {"commit", "push"}:
                return current
            cursor += 1
    return None


def _cd_target(tokens: list[str], base: str) -> str | None:
    """Resolve a simple `cd [--] path` segment without evaluating the shell."""
    if not tokens or os.path.basename(tokens[0]) != "cd":
        return None
    args = tokens[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if len(args) != 1 or args[0] == "-" or "$" in args[0]:
        return None
    path = os.path.expanduser(args[0])
    target = path if os.path.isabs(path) else os.path.join(base, path)
    target = os.path.abspath(target)
    return target if os.path.isdir(target) else None


def main() -> None:
    command, base = sys.argv[1:3]
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|(){}")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return

    current = os.path.abspath(base)
    segment: list[str] = []
    for token in [*tokens, ";"]:
        if token not in SEPARATORS:
            segment.append(token)
            continue
        if target := _git_target(segment, current):
            print(target)
            return
        # A successful `cd path &&` (or `cd path;`) changes the cwd used by the
        # following command. Pipelines/background jobs do not share that cwd.
        if token in {"&&", ";"} and (target := _cd_target(segment, current)):
            current = target
        segment = []


if __name__ == "__main__":
    main()

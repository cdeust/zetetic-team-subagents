#!/usr/bin/env python3
"""Resolve a push event without executing its command.

Source: hooks/lib/git-command-cwd.py, packaged for standalone installs.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

# Shell command boundaries emitted as standalone tokens by the configured
# ``shlex`` punctuation set. Sources: POSIX Shell Command Language §2.9.3 and
# Python 3 ``shlex.shlex(..., punctuation_chars=...)`` documentation.
SEPARATORS = {";", "\n", "&&", "||", "|", "&", "(", ")", "{", "}"}


def _git_target(tokens: list[str], base: str) -> str | None:
    """Return the cwd of the first push in one shell command segment."""
    for index, candidate in enumerate(tokens):
        if candidate in {"sudo", "command", "env"} or "=" in candidate:
            continue
        if os.path.basename(candidate) != "git":
            return None
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
            if token == "push":
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
    try:
        event = json.load(sys.stdin)
        tool = event.get("tool_input", {})
        command = tool.get("command", "")
        base = tool.get("workdir") or tool.get("cwd") or event.get("cwd") or os.getcwd()
        if not isinstance(command, str) or not isinstance(base, str):
            raise ValueError("command and cwd must be strings")
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|(){}\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = []
        for token in lexer:
            if all(char in ";&|(){}\n" for char in token):
                tokens.extend(re.findall(r"&&|\|\||[\s\S]", token))
            else:
                tokens.append(token)
    except (ValueError, AttributeError) as error:
        print(f"INCONCLUSIVE fail-before: invalid hook input: {error}", file=sys.stderr)
        return

    current = os.path.abspath(base)
    segment: list[str] = []
    scopes: list[str] = []
    for token in [*tokens, ";"]:
        if token not in SEPARATORS:
            segment.append(token)
            continue
        if target := _git_target(segment, current):
            print(target, end="\0")
        # A successful `cd path &&` (or `cd path;`) changes the cwd used by the
        # following command. Pipelines/background jobs do not share that cwd.
        if token in {"&&", ";", "\n"} and (target := _cd_target(segment, current)):
            current = target
        if token == "(":
            scopes.append(current)
        elif token == ")" and scopes:
            current = scopes.pop()
        segment = []


if __name__ == "__main__":
    main()

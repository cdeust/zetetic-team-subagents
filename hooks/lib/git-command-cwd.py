#!/usr/bin/env python3
"""Print the working directory targeted by a git commit/push command."""

from __future__ import annotations

import os
import shlex
import sys


def main() -> None:
    command, base = sys.argv[1:3]
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|(){}")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return

    for index, candidate in enumerate(tokens):
        if os.path.basename(candidate) != "git":
            continue
        current = os.path.abspath(base)
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
                print(current)
                return
            cursor += 1


if __name__ == "__main__":
    main()

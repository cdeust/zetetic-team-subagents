#!/usr/bin/env python3
"""ci_contract.py -- validates a repository's ``ci.json`` before any test runs.

The contract (docs/superpowers/specs/2026-10-22-single-ci-design.md, "Repository
contract: ci.json"): exactly the keys ``unit``, ``regression``, ``e2e``,
``environment`` and ``install``, each a non-empty shell command, plus an
optional ``version_file`` (decision 9; default ``.claude-plugin/plugin.json``)
that must exist, read by the ``tag`` job. A missing file, a missing key or an
empty command fails the pipeline here, with one line per fault, so a step that
has nothing to run never passes (the design's first anti-goal).

This file is also embedded verbatim in ``templates/ci/pipeline.yml`` as an inline
``python3 -`` step: standard library only, arguments through ``sys.argv``.

Usage: ``python3 tools/ci_contract.py [repo-root]`` (default: the current
directory). Exit 0 and the five commands plus ``version_file`` on stdout when
valid; exit 1 and the faults on stderr otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

KEYS = ("unit", "regression", "e2e", "environment", "install")
VERSION_KEY = "version_file"
DEFAULT_VERSION_FILE = ".claude-plugin/plugin.json"
ALLOWED = ", ".join(KEYS + (VERSION_KEY,))


def _load(root: Path):
    """The parsed document, or the one fault that stops validation."""
    path = root / "ci.json"
    if not path.is_file():
        return None, "ci.json: missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return None, f"ci.json: not valid JSON ({exc})"
    if not isinstance(data, dict):
        return None, "ci.json: must be a JSON object"
    return data, None


def _version_faults(data: dict, root: Path) -> List[str]:
    value = data.get(VERSION_KEY, DEFAULT_VERSION_FILE)
    if not isinstance(value, str):
        return [f"{VERSION_KEY}: not a string"]
    if not value.strip():
        return [f"{VERSION_KEY}: empty path"]
    if not (root / value).is_file():
        return [f"{VERSION_KEY}: {value} does not exist"]
    return []


def faults(root: Path) -> List[str]:
    """Every fault of ``root/ci.json``, in key order then unknown keys; empty
    when the file honours the contract."""
    data, fatal = _load(root)
    if fatal:
        return [fatal]
    found: List[str] = []
    for key in KEYS:
        if key not in data:
            found.append(f"{key}: missing")
        elif not isinstance(data[key], str):
            found.append(f"{key}: not a string")
        elif not data[key].strip():
            found.append(f"{key}: empty command")
    found.extend(f"{key}: unknown key (allowed: {ALLOWED})" for key in data if key not in KEYS + (VERSION_KEY,))
    found.extend(_version_faults(data, root))
    return found


def main(argv: List[str]) -> int:
    root = Path(argv[0]) if argv else Path(".")
    found = faults(root)
    if found:
        for line in found:
            print(line, file=sys.stderr)
        return 1
    data, _ = _load(root)
    for key in KEYS:
        print(f"{key}: {data[key]}")
    print(f"{VERSION_KEY}: {data.get(VERSION_KEY, DEFAULT_VERSION_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

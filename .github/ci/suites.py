#!/usr/bin/env python3
"""Partition the authoritative tests/run-all.sh inventory without dropping new suites.

Source: tests/run-all.sh at 6fa8cc5deeeb63d65b767f2e9d79486858eb710b.
The upstream list command checks nested orphans; unknown suites default to regression.
"""

import os
from pathlib import Path
import subprocess
import sys

CATEGORIES = {
    "e2e": {
        "scripts/test-memory-e2e.sh",
        "scripts/test-memory-mcp.sh",
        "scripts/test-spawn-agent.sh",
    },
    "environment": {
        "scripts/test-memory-concurrency.sh",
        "scripts/test-memory-stale-lock.sh",
        "scripts/test-session-cache.sh",
    },
    "installation": {
        "scripts/test-state-layout.sh",
        "tools/tests/setup-plugin-served/run-tests.sh",
        "tools/tests/release-verify/run-tests.sh",
    },
}


def partition(lines):
    expected = os.environ.get("PYTHON_BIN", "python3") + " -m pytest"
    if not lines or lines[0] != expected:
        raise ValueError(
            "tests/run-all.sh Python command changed; review the CI unit invocation"
        )
    suites = lines[1:]
    if not suites or len(suites) != len(set(suites)):
        raise ValueError("Empty or duplicate shell suite inventory")
    selected = {name: [] for name in ("regression", *CATEGORIES)}
    for suite in suites:
        if not suite.endswith(".sh") or not Path(suite).is_file():
            raise ValueError("Invalid discovered suite: " + suite)
        matches = [name for name, paths in CATEGORIES.items() if suite in paths]
        if len(matches) > 1:
            raise ValueError("Overlapping categories: " + suite)
        selected[matches[0] if matches else "regression"].append(suite)
    if any(not entries for entries in selected.values()):
        raise ValueError("Empty test category")
    return selected


def main():
    result = subprocess.run(
        ["bash", "tests/run-all.sh", "--list"],
        check=True,
        capture_output=True,
        text=True,
    )
    groups = partition(result.stdout.splitlines())
    if sys.argv[1:] == ["--list"]:
        for category, suites in groups.items():
            for suite in suites:
                print(category + " " + suite)
        return
    for suite in groups[sys.argv[1]]:
        print("Running " + suite, flush=True)
        subprocess.run(["bash", suite], check=True)


if __name__ == "__main__":
    main()

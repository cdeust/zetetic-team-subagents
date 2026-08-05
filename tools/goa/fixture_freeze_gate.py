#!/usr/bin/env python3
"""fixture_freeze_gate.py — CI HARD GATE: `external_testbase_v1.json` (and any
future `external_testbase_v<N>.json`) is APPEND-ONLY once committed.

EXTERNAL-TESTBASE.md §3 step 5 / GOA-DESIGN.md Phase 1 CI gate column: "Fixture
is append-only and frozen per version". A version bump to a new filename
(`external_testbase_v2.json`) is not a modification of v1 and is untouched by
this gate — freezing is PER FILE, matching "per version" in the spec.

Comparison is by `case_id`: every case_id present in the base ref's copy of a
fixture file must be present, byte-identical (canonical JSON), in HEAD's copy.
A case_id can be ADDED; it cannot be removed or changed. `manifest` (the
non-row metadata) is exempt from the identical-row check — it legitimately
grows (row_count changes every append) — but the gate DOES verify
`manifest.row_count` in HEAD is never less than at base (monotonic, matching
append-only in spirit even for the summary field).

Exit codes: 0 no committed fixture changed, or every change was a pure
addition; 1 an existing row was modified or removed; 2 usage/parse error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

FIXTURE_JSON_GLOB_RE = r"external_testbase_v\d+\.json$"


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def resolve_base_ref(repo_root: Path, pr_base_sha: str | None) -> str:
    if pr_base_sha:
        return pr_base_sha
    try:
        return _git(repo_root, "rev-parse", "HEAD^").strip()
    except RuntimeError:
        return _git(repo_root, "rev-parse", "HEAD").strip()


def fixture_paths_at_head(repo_root: Path) -> list[str]:
    import re

    tracked = _git(repo_root, "ls-files").splitlines()
    pattern = re.compile(FIXTURE_JSON_GLOB_RE)
    return [p for p in tracked if pattern.search(p)]


def load_fixture_at_ref(repo_root: Path, ref: str, path: str) -> dict | None:
    """Return the fixture JSON at `ref`, or None if the file did not exist there."""
    try:
        content = _git(repo_root, "show", f"{ref}:{path}")
    except RuntimeError:
        return None
    return json.loads(content)


def diff_rows(base_rows: list[dict], head_rows: list[dict]) -> list[str]:
    """Return named violations: a base case_id missing from head, or present but changed."""
    head_by_id = {r["case_id"]: r for r in head_rows}
    violations: list[str] = []
    for base_row in base_rows:
        case_id = base_row["case_id"]
        head_row = head_by_id.get(case_id)
        if head_row is None:
            violations.append(f"{case_id}: removed from fixture (append-only violation)")
            continue
        if json.dumps(base_row, sort_keys=True) != json.dumps(head_row, sort_keys=True):
            violations.append(f"{case_id}: existing row modified (append-only violation)")
    return violations


def check_fixture_file(repo_root: Path, base_ref: str, path: str) -> list[str]:
    base_fixture = load_fixture_at_ref(repo_root, base_ref, path)
    if base_fixture is None:
        return []  # new file at HEAD, nothing to freeze against
    head_fixture = json.loads((repo_root / path).read_text(encoding="utf-8"))
    violations = diff_rows(base_fixture.get("rows", []), head_fixture.get("rows", []))
    base_count = base_fixture.get("manifest", {}).get("row_count", len(base_fixture.get("rows", [])))
    head_count = head_fixture.get("manifest", {}).get("row_count", len(head_fixture.get("rows", [])))
    if head_count < base_count:
        violations.append(f"manifest.row_count regressed: {base_count} -> {head_count}")
    return [f"{path}: {v}" for v in violations]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo-root", type=Path, default=None)
    p.add_argument("--pr-base-sha", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root
    if repo_root is None:
        repo_root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip())

    try:
        base_ref = resolve_base_ref(repo_root, args.pr_base_sha)
        fixture_files = fixture_paths_at_head(repo_root)
    except (RuntimeError, OSError) as exc:
        print(f"fixture_freeze_gate: {exc}", file=sys.stderr)
        return 2

    if not fixture_files:
        print("fixture_freeze_gate: no external_testbase_v*.json tracked — passing")
        return 0

    violations: list[str] = []
    for path in fixture_files:
        try:
            violations += check_fixture_file(repo_root, base_ref, path)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"fixture_freeze_gate: {path}: parse error: {exc}", file=sys.stderr)
            return 2

    if violations:
        print("fixture_freeze_gate: VIOLATIONS found", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print(f"fixture_freeze_gate: clean ({len(fixture_files)} fixture file(s) checked against {base_ref})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

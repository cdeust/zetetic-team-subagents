#!/usr/bin/env python3
"""ci_no_raw_corpus_text.py — CI HARD GATE: no committed raw SE/NTSB/SWE-bench/
Defects4J corpus text, ever. Two independent checks, both must pass:

  1. SCHEMA check — every row of every tracked `external_testbase_v1.json`
     (the frozen shape-labeled fixture) and every tracked read-only-slice
     reference file must carry no forbidden raw-text field
     (fixture_features.FORBIDDEN_ROW_FIELDS) and must carry `source_id` +
     `license`. This is the primary, deterministic enforcement of
     EXTERNAL-TESTBASE.md §3 step 4(b) and the user's 2026-08-05 arbitration
     ("references + locally computed features ONLY, never raw text in the
     repo").

  2. NAME/SIZE sweep — defense in depth against accidentally committing an
     actual dump artifact (a site's `Posts.xml`, an NTSB export, a SWE-bench/
     Defects4J export). Any tracked file whose name matches a raw-dump pattern
     is rejected UNLESS it is a tiny, explicitly-marked synthetic test fixture
     (path contains `.synthetic.` and is <= SYNTHETIC_FIXTURE_MAX_BYTES) — the
     task's own instruction to build "tiny FORMAT-ONLY synthetic fixtures" for
     the parser tests, made an enforceable convention rather than a suggestion.

No `|| echo` anywhere in this gate or its shell wrapper — rules/coding-standards
§9 and the explicit task instruction citing ci.yml's prior "|| echo" defect.

Exit codes: 0 clean, 1 at least one violation, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.fixture_features import assert_no_raw_text

SYNTHETIC_FIXTURE_MAX_BYTES = 8192  # pre-registered convention: "tiny", per task instructions
RAW_DUMP_NAME_RE = re.compile(
    r"(^|/)Posts\.xml$"
    r"|\.7z$"
    r"|(^|/).*ntsb.*\.(csv|jsonl)$"
    r"|(^|/).*swebench.*\.(csv|jsonl)$"
    r"|(^|/).*defects4j.*\.(csv|jsonl)$",
    re.IGNORECASE,
)
FIXTURE_JSON_RE = re.compile(r"(^|/)external_testbase_v\d+\.json$")
READONLY_REFERENCE_RE = re.compile(r"(^|/).*readonly.*reference.*\.jsonl$", re.IGNORECASE)


def list_tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def check_fixture_schema(repo_root: Path, tracked: list[str]) -> list[str]:
    violations: list[str] = []
    for rel_path in tracked:
        if not FIXTURE_JSON_RE.search(rel_path):
            continue
        payload = json.loads((repo_root / rel_path).read_text(encoding="utf-8"))
        for row in payload.get("rows", []):
            row_violations = assert_no_raw_text(row)
            if not row.get("source_id") or not row.get("license"):
                row_violations.append("missing-source_id-or-license")
            for v in row_violations:
                violations.append(f"{rel_path}::{row.get('case_id', '?')}: {v}")
    return violations


def check_readonly_references(repo_root: Path, tracked: list[str]) -> list[str]:
    violations: list[str] = []
    for rel_path in tracked:
        if not READONLY_REFERENCE_RE.search(rel_path):
            continue
        for line_no, line in enumerate((repo_root / rel_path).read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row_violations = assert_no_raw_text(row)
            if not row.get("source_id") or not row.get("license"):
                row_violations.append("missing-source_id-or-license")
            for v in row_violations:
                violations.append(f"{rel_path}:{line_no}: {v}")
    return violations


def _is_marked_synthetic(rel_path: str) -> bool:
    """A tracked file is exempt from the raw-dump-name ban only if it is
    EXPLICITLY marked: either `.synthetic.` in its filename (e.g.
    `Posts.synthetic.xml`) or a `synthetic/` path segment (e.g.
    `tests/fixtures/goa/synthetic/Posts.xml`). Either form is an unambiguous,
    deliberate marker — a directory or file that merely happens to be small
    is NOT exempt, because "small today" is not "marked as a format-only
    fixture forever" (a real corpus slice could shrink to fixture-size by
    accident and pass silently otherwise).
    """
    return ".synthetic." in rel_path or "/synthetic/" in rel_path or rel_path.startswith("synthetic/")


def find_suspicious_raw_dump_files(repo_root: Path, tracked: list[str]) -> list[str]:
    suspicious: list[str] = []
    for rel_path in tracked:
        if not RAW_DUMP_NAME_RE.search(rel_path):
            continue
        if _is_marked_synthetic(rel_path):
            size = (repo_root / rel_path).stat().st_size
            if size <= SYNTHETIC_FIXTURE_MAX_BYTES:
                continue
            suspicious.append(f"{rel_path}: marked synthetic but {size}B exceeds {SYNTHETIC_FIXTURE_MAX_BYTES}B cap")
            continue
        suspicious.append(f"{rel_path}: matches raw-dump naming pattern and is not a marked synthetic fixture")
    return suspicious


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo-root", type=Path, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root
    if repo_root is None:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
        repo_root = Path(result.stdout.strip())
    tracked = list_tracked_files(repo_root)

    violations = []
    violations += check_fixture_schema(repo_root, tracked)
    violations += check_readonly_references(repo_root, tracked)
    violations += find_suspicious_raw_dump_files(repo_root, tracked)

    if violations:
        print("ci_no_raw_corpus_text: VIOLATIONS found", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print(f"ci_no_raw_corpus_text: clean ({len(tracked)} tracked files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

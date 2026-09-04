"""Tests for tools/frontmatter_validator.py — the strict, independent
frontmatter oracle for HC-ZETETIC-003 (strict-frontmatter-portability).

Scope of what this test file DOES verify (per HC-ZETETIC-003's verdict
ledger):
  - "Immutable parser artifact": a version-pinned strict YAML parser applied
    to every declared frontmatter block, source tree AND packaged
    (plugins/*/skills/) surfaces, returns a stable {file, line, rule}
    record for a seeded syntax fixture, and zero failures for the release.
  - The 7 files named in the HC-ZETETIC-003 dossier parse cleanly at HEAD
    (post-fix) and are individually asserted by name so a regression on any
    one of them fails this test, not just an aggregate count.

Scope of what this test file does NOT verify (explicitly out of scope,
named rather than silently absent): "Packaged Claude and Codex discovery"
and "Full-tree regression" against live Claude/Codex host installs — those
require actual host binaries and isolated homes per the dossier's
reproduction protocol, which this repository's CI environment does not
provide. Running a plain YAML parse over the packaged artifact (which this
test does) is a necessary but not sufficient stand-in for "the host
actually discovers and retrieves the procedure."
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import frontmatter_validator as fv  # noqa: E402

FIXTURE_DIR = ROOT / "tools" / "tests" / "frontmatter-validator"

# The exact 7 files named in HC-ZETETIC-003's "Observed condition".
PREVIOUSLY_FAILING_FILES = [
    "skills/research/lab-notebook.md",
    "skills/compose/failure-resilient-design.md",
    "skills/compose/conjecture-to-code.md",
    "skills/compose/performance-investigation.md",
    "skills/compose/statistical-intervention.md",
    "skills/compose/anomaly-to-explanation.md",
    "skills/compose/product-quality-audit.md",
]


def test_valid_fixture_passes() -> None:
    assert fv.validate_file(FIXTURE_DIR / "fixture-valid.md") == []


def test_unquoted_colon_fixture_reports_stable_file_line_rule() -> None:
    errors = fv.validate_file(FIXTURE_DIR / "fixture-invalid-unquoted-colon.md")
    assert len(errors) == 1
    error = errors[0]
    assert error.file.endswith("fixture-invalid-unquoted-colon.md")
    assert error.rule == "STRICT_YAML_PARSE_ERROR"
    assert error.line == 5  # the `output:` line


def test_missing_required_key_fixture_reports_schema_violation() -> None:
    errors = fv.validate_file(FIXTURE_DIR / "fixture-missing-required-key.md")
    assert len(errors) == 1
    assert errors[0].rule == "SCHEMA_MISSING_REQUIRED_KEY"
    assert "description" in errors[0].message


def test_no_frontmatter_fixture_is_not_a_violation() -> None:
    """commands/*.md in this repo are plain markdown by convention — absence
    of a frontmatter block is out of scope, not a failure."""
    assert fv.validate_file(FIXTURE_DIR / "fixture-no-frontmatter.md") == []


@pytest.mark.parametrize("relative_path", PREVIOUSLY_FAILING_FILES)
def test_previously_failing_file_now_parses_clean(relative_path: str) -> None:
    errors = fv.validate_file(ROOT / relative_path)
    assert errors == [], f"{relative_path}: {errors}"


def test_full_tree_scan_zero_failures() -> None:
    """HC-ZETETIC-003 acceptance: "returns zero syntax or schema failures
    for the release" — scans skills/, agents/, commands/, and every
    packaged plugins/*/skills/ tree in one pass."""
    errors = fv.run_all(ROOT)
    assert errors == [], f"{len(errors)} frontmatter failure(s): {errors[:5]}"


def test_packaged_artifact_included_in_scan() -> None:
    """The packaged surface (plugins/zetetic-reasoning/skills/) must be
    reachable by the same validator run as the source tree — HC-ZETETIC-003:
    "CI runs the same strict validator against the packaged artifact, not
    only the working tree.\""""
    files = list(fv._iter_target_files(ROOT))
    assert any("plugins/zetetic-reasoning/skills" in str(f) for f in files)


def test_cli_exits_zero_on_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "frontmatter_validator.py"), str(ROOT), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_exits_nonzero_on_seeded_failure(tmp_path: Path) -> None:
    bad_repo = tmp_path / "repo"
    (bad_repo / "skills").mkdir(parents=True)
    (bad_repo / "skills" / "broken.md").write_text(
        (FIXTURE_DIR / "fixture-invalid-unquoted-colon.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "frontmatter_validator.py"), str(bad_repo), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "STRICT_YAML_PARSE_ERROR" in result.stdout

#!/usr/bin/env python3
"""frontmatter_validator.py — strict, full-tree YAML frontmatter validator.

Single responsibility: parse EVERY frontmatter block under the declared
metadata trees (skills/, agents/ incl. agents/genius/, commands/, and the
packaged plugin surfaces under plugins/*/skills/) with a version-pinned
strict YAML parser (PyYAML's safe_load — no permissive fallback), against a
minimal declared schema, and report every failure as a stable, machine
readable {file, line, rule, message} record.

Closes HC-ZETETIC-003 (strict-frontmatter-portability): "A versioned
full-tree validator parses every frontmatter block with the declared schema
and returns zero syntax or schema failures for the release" and "A fixture
containing an unquoted mapping delimiter fails with a stable machine
readable file, line, and rule identifier."

This module intentionally does NOT depend on Claude's or Codex's own
frontmatter parser — it is the independent oracle the acceptance criteria
call for ("not a host's self-reported health"). It also does not attempt
host package discovery; run_all() covers only the source-tree + packaged
artifact SCAN half of HC-ZETETIC-003 (its "Immutable parser artifact"
verdict rung) — a full Claude/Codex install-and-discover matrix (its
"Packaged Claude and Codex discovery" rung) requires actual host installs
and is out of this module's scope; see the accompanying test file's module
docstring for what is and is not exercised.

Exit codes (CLI mode): 0 = zero failures, 1 = at least one failure, 2 = usage.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import yaml

PARSER_NAME = "PyYAML"
PARSER_VERSION = yaml.__version__

FRONTMATTER_DELIM = "---"

# Minimal declared schema (coding-standards §8: no invented requirement —
# these two keys are the ones every discovery path actually reads: `name`
# resolves the identifier, `description` is what routing matches against).
REQUIRED_KEYS = ("name", "description")


@dataclass(frozen=True)
class ValidationError:
    file: str
    line: int
    rule: str
    message: str


def _extract_frontmatter(text: str) -> tuple[str, int] | None:
    """Return (frontmatter_text, start_line_of_frontmatter_body) for the
    first '---'-delimited block, or None if the file has no frontmatter.
    start_line is 1-indexed and points at the line AFTER the opening '---',
    so a YAML parser error's own (0-indexed) line number can be added to it
    directly to get the true file line."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONTMATTER_DELIM:
        return None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == FRONTMATTER_DELIM:
            return "\n".join(lines[1:idx]), 2
    return None


def _schema_errors(data: object, path: Path, base_line: int) -> list[ValidationError]:
    if not isinstance(data, dict):
        return [ValidationError(str(path), base_line, "SCHEMA_NOT_A_MAPPING", "frontmatter is not a YAML mapping")]
    errors = []
    for key in REQUIRED_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(
                ValidationError(str(path), base_line, "SCHEMA_MISSING_REQUIRED_KEY", f"missing or empty required key: {key}")
            )
    return errors


def validate_file(path: Path) -> list[ValidationError]:
    """precondition: path is a readable .md file.
    postcondition: returns [] iff the file has frontmatter that parses
    under strict YAML AND satisfies REQUIRED_KEYS; otherwise returns every
    violation found (parse errors short-circuit schema checks, since a
    non-parseable block has no schema to check)."""
    text = path.read_text(encoding="utf-8")
    extracted = _extract_frontmatter(text)
    if extracted is None:
        # Not every tracked .md file declares frontmatter (this project's
        # commands/*.md are plain markdown by convention — enforced
        # elsewhere, e.g. tools/agent-definition-auditor.sh's F1 for
        # agents/*.md). Absence of a frontmatter block is out of this
        # validator's scope: it checks that DECLARED frontmatter parses and
        # meets the schema, not that every file must declare one.
        return []
    frontmatter_text, base_line = extracted

    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = base_line + mark.line if mark is not None else base_line
        return [ValidationError(str(path), line, "STRICT_YAML_PARSE_ERROR", str(exc).splitlines()[0])]

    return _schema_errors(data, path, base_line)


def _iter_target_files(root: Path) -> Iterable[Path]:
    trees = [
        root / "skills",
        root / "agents",
        root / "commands",
    ]
    for tree in trees:
        if tree.is_dir():
            yield from sorted(tree.rglob("*.md"))

    for plugin_dir in sorted((root / "plugins").glob("*")):
        skills_dir = plugin_dir / "skills"
        if skills_dir.is_dir():
            yield from sorted(skills_dir.rglob("*.md"))


def run_all(root: Path) -> list[ValidationError]:
    """Validate every frontmatter-bearing file the declared trees contain.
    postcondition: [] iff every file in _iter_target_files(root) passes
    validate_file — this is the "zero syntax or schema failures" acceptance
    check, run against source-tree AND packaged (plugins/*) paths in one pass."""
    errors: list[ValidationError] = []
    for path in _iter_target_files(root):
        errors.extend(validate_file(path))
    return errors


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path("."), help="repo root to scan")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a human table")
    args = parser.parse_args(argv)

    errors = run_all(args.root.resolve())

    if args.json:
        print(json.dumps({"parser": PARSER_NAME, "parser_version": PARSER_VERSION, "errors": [asdict(e) for e in errors]}))
    else:
        print(f"frontmatter_validator ({PARSER_NAME} {PARSER_VERSION}): {len(errors)} failure(s)")
        for e in errors:
            print(f"  {e.file}:{e.line}: [{e.rule}] {e.message}")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

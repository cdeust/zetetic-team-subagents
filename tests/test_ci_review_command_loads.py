"""The review command file asks for no permission to load (Cortex ADR-1139).

The review workflow sets `track_progress`, so the prompt does not reach the
CLI as a slash command: the model loads `/review-pr` with the Skill tool. A
command file whose frontmatter carries `allowed-tools` needs an approval for
that call (Cortex ADR-1139, probe of 2026-11-13 on Claude Code 2.1.323: with
the header the Skill call is refused, without it the command loads).

`disable-model-invocation` is refused too: the review of Cortex pull request
1027 names it as a key that keeps the model from loading a command. Its
effect was not measured here. Other frontmatter keys were not measured
either and are not constrained.

Two copies are held: the one this repository's reviews run, and the one
`templates/ci/review` carries, Cortex's files byte for byte.

The copy of `templates/ci/native/assets` is not one of them. That template
is pinned as a whole to an earlier Cortex commit (`templates/ci/native/
source.json`), whose command file has the header; the last test holds that
pin, so that the day the native template is brought to a Cortex commit after
ADR-1139 the header goes with it, and not before, by a hand edit that would
leave the pin behind.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COPIES = (ROOT, ROOT / "templates/ci/review")
# The three commands the header allowed, which the review still needs.
GH_COMMANDS = ("Bash(gh pr comment:*)", "Bash(gh pr diff:*)", "Bash(gh pr view:*)")


def frontmatter_keys(text: str) -> list[str]:
    """The keys of the YAML frontmatter of a command file."""
    assert text.startswith("---\n"), "the command file has no frontmatter"
    block = text.split("---\n", 2)[1]
    return [m.group(1) for m in re.finditer(r"^([A-Za-z][A-Za-z0-9_-]*):", block, re.M)]


@pytest.mark.parametrize("base", COPIES, ids=["repository", "templates/ci/review"])
def test_the_command_file_can_be_loaded_by_the_model(base: Path) -> None:
    keys = frontmatter_keys((base / ".claude/commands/review-pr.md").read_text())
    assert "allowed-tools" not in keys
    assert "disable-model-invocation" not in keys
    assert "description" in keys


@pytest.mark.parametrize("base", COPIES, ids=["repository", "templates/ci/review"])
def test_the_workflow_allows_what_the_header_allowed(base: Path) -> None:
    workflow = (base / ".github/workflows/claude-review.yml").read_text()
    match = re.search(r'--allowedTools\s+("[^"]*")', workflow)
    assert match, "claude-review.yml passes no --allowedTools"
    allowed = shlex.split(match.group(1))[0].split(",")
    for command in GH_COMMANDS:
        assert command in allowed


def test_the_two_copies_are_the_same_file() -> None:
    first, second = ((base / ".claude/commands/review-pr.md").read_bytes() for base in COPIES)
    assert first == second


def test_the_reader_of_the_frontmatter_sees_a_header() -> None:
    keys = frontmatter_keys("---\nallowed-tools: Bash(gh pr view:*)\ndescription: x\n---\nbody\n")
    assert keys == ["allowed-tools", "description"]


def test_the_native_template_copy_is_the_one_its_pin_names() -> None:
    native = ROOT / "templates/ci/native"
    pinned = json.loads((native / "source.json").read_text())["assets"][".claude/commands/review-pr.md"]
    copy = (native / "assets/.claude/commands/review-pr.md").read_bytes()
    assert hashlib.sha256(copy).hexdigest() == pinned
    # The pinned file is the one with the header: this is what a review run
    # from the native template loads.
    assert "allowed-tools" in frontmatter_keys(copy.decode())

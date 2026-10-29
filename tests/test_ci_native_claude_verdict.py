"""The native Claude review ends with a machine-readable verdict for its head.

Contract read by the Cortex convergence planner (cdeust/Cortex #834,
scripts/ci_autopilot_converge_observe.py): exactly one line
`<!-- claude-review-verdict:v1 {"head":"<40-hex sha>","merge":true|false} -->`.
Without it every held PR reads as "claude_verdict_unreadable".
Fixture: the real final comment of cdeust/claude-mods PR51,
issuecomment-6491944909 ("Verdict: merge"), which carries no marker.
"""
import json
from pathlib import Path
import re

import yaml

from scripts.lib import render_ci as renderer

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/claude_review/claude-mods-pr51-6491944909.md"
HEAD = "ec9bbc76ae9f954570122a0f93f85fb25cde5bdd"
MARKER = re.compile(r"^<!-- claude-review-verdict:v1 (\{.*\}) -->$", re.MULTILINE)
EXPRESSION = "${{ github.event.pull_request.head.sha }}"


def verdict(body: str) -> dict | None:
    """Reference reader: one marker, exact keys, full sha, boolean merge."""
    found = MARKER.findall(body)
    if len(found) != 1:
        return None
    value = json.loads(found[0])
    if set(value) != {"head", "merge"} or type(value["merge"]) is not bool:
        return None
    if not re.fullmatch(r"[0-9a-f]{40}", value["head"]):
        return None
    return value


def prompt(tmp_path) -> str:
    files = renderer.prepare_files(tmp_path, native_review=True)
    document = yaml.safe_load(files[tmp_path / ".github/workflows/claude-review.yml"])
    return document["jobs"]["review"]["steps"][-1]["with"]["prompt"]


def instructed_marker(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if "claude-review-verdict:v1" in line]
    assert len(lines) == 1, lines
    return lines[0]


def test_real_review_without_marker_is_unreadable():
    assert verdict(FIXTURE.read_text()) is None


def test_prompt_instructs_one_marker_bound_to_the_event_head(tmp_path):
    line = instructed_marker(prompt(tmp_path))
    assert line == '<!-- claude-review-verdict:v1 {"head":"' + EXPRESSION + '","merge":true} -->'


def test_marker_as_instructed_makes_the_real_review_readable(tmp_path):
    line = instructed_marker(prompt(tmp_path)).replace(EXPRESSION, HEAD)
    body = FIXTURE.read_text().rstrip("\n") + "\n\n" + line + "\n"
    assert verdict(body) == {"head": HEAD, "merge": True}
    blocking = body.replace('"merge":true', '"merge":false')
    assert verdict(blocking) == {"head": HEAD, "merge": False}
    assert verdict(body + line + "\n") is None  # two markers are ambiguous

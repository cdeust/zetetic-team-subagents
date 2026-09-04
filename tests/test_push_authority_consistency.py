"""Tests for HC-ZETETIC-002 (executable-agent-handoff-contract): the push
instruction, once literally contradictory across three sources
(scripts/generate-spine.py's generated zetetic-spine text said "push, and
hand back immediately"; agents/engineer.md's own <worktree> section said
"do NOT push"; rules/agent-reference/worktree-protocol.md said push
authority is delegation-controlled), must now defer to a single source of
truth: the delegation contract's `push_authority` field
(schemas/delegation-contract.schema.yaml), surfaced as the
`DELEGATION_PUSH_AUTHORITY` environment variable by scripts/spawn-agent.sh.

This does not re-run the full HC-ZETETIC-002 cross-host behavioral matrix
(Claude vs. Codex adapters, recorder remote, tool-call audit) — that
requires the reproduction protocol's isolated repository + recorder remote
infrastructure, out of this test suite's scope. It verifies the concrete,
falsifiable defect named in the dossier's "Observed condition": no agent
.md file states an unconditional push directive that contradicts another
source.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The two previously-contradictory absolute phrasings. Neither should exist
# anywhere in agents/*.md or agents/genius/*.md after the fix — both are
# now conditioned on push_authority.
ABSOLUTE_DO_NOT_PUSH = re.compile(r"do NOT push\b(?!.*push_authority)")
ABSOLUTE_ALWAYS_PUSH = re.compile(r"push, and hand back \*\*immediately\*\*")


def _all_agent_files() -> list[Path]:
    return sorted((ROOT / "agents").glob("*.md")) + sorted((ROOT / "agents" / "genius").glob("*.md"))


def test_no_absolute_do_not_push_directive() -> None:
    offenders = []
    for path in _all_agent_files():
        text = path.read_text(encoding="utf-8")
        if ABSOLUTE_DO_NOT_PUSH.search(text):
            offenders.append(str(path))
    assert offenders == [], f"absolute 'do NOT push' survives in: {offenders}"


def test_no_absolute_always_push_directive() -> None:
    offenders = []
    for path in _all_agent_files():
        text = path.read_text(encoding="utf-8")
        if ABSOLUTE_ALWAYS_PUSH.search(text):
            offenders.append(str(path))
    assert offenders == [], f"absolute 'push, and hand back immediately' survives in: {offenders}"


def test_worktree_capable_agents_reference_push_authority() -> None:
    """Every agent with an inline <worktree> section must condition its
    push instruction on push_authority (the delegation contract field) or
    DELEGATION_PUSH_AUTHORITY (its runtime surfacing) — not an unconditional
    directive of either polarity."""
    checked = 0
    for path in _all_agent_files():
        text = path.read_text(encoding="utf-8")
        if "<worktree>" not in text:
            continue
        worktree_section = text.split("<worktree>", 1)[1].split("</worktree>", 1)[0]
        if "push" not in worktree_section.lower():
            continue
        checked += 1
        assert "push_authority" in worktree_section or "DELEGATION_PUSH_AUTHORITY" in worktree_section, (
            f"{path}: <worktree> mentions push without referencing push_authority"
        )
    assert checked > 0, "no worktree-capable agent with a push-mentioning <worktree> section was found"


def test_orchestrator_model_and_token_budget_agree() -> None:
    """HC-ZETETIC-002: orchestrator.md's frontmatter selected `fable` while
    its token-budget prose said Opus. Both must now name the same model."""
    text = (ROOT / "agents" / "orchestrator.md").read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    assert re.search(r"^model:\s*fable\s*$", frontmatter, re.MULTILINE)
    token_budget_section = text.split("<token-budget>", 1)[1].split("</token-budget>", 1)[0]
    assert "Fable" in token_budget_section
    assert "Opus" not in token_budget_section.split("\n")[0]


def test_ux_designer_declares_tools_its_required_procedure_uses() -> None:
    """HC-ZETETIC-002: ux-designer's declared tools omitted Bash/Edit/Write
    although its required memory + worktree procedure invokes memory-tool.sh
    (Bash) and produces design-spec files (Write/Edit). Every tool its
    <memory> and <worktree> sections require by name must be in the
    frontmatter tools: list."""
    text = (ROOT / "agents" / "ux-designer.md").read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    tools_line = next(line for line in frontmatter.splitlines() if line.startswith("tools:"))
    for required_tool in ("Bash", "Edit", "Write", "Read"):
        assert required_tool in tools_line, f"ux-designer tools: missing {required_tool}"

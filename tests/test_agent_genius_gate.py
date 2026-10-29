"""hooks/pre-agent-genius-gate.py: every Agent call applies a genius pattern.

The hook is run as a subprocess, the way Claude Code runs it: event JSON on
stdin, a PreToolUse decision on stdout. The four core cases are the owner's
acceptance list: it denies a missing GENIUS line, denies a removed base agent
type, denies an unknown genius name, and allows a valid call.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "pre-agent-genius-gate.py"
ROUTES = json.loads((REPO / "rules" / "agent-routes.json").read_text())
REMOVED = ("advisor architect code-reviewer data-scientist dba devops-engineer engineer "
           "experiment-runner frontend-engineer git-historian latex-engineer memory-writer "
           "mlops orchestrator paper-writer professor refactorer research-scientist "
           "reviewer-academic security-auditor simplifier test-engineer ux-designer").split()


def run_gate(subagent_type="general-purpose", prompt="", description="", **extra):
    """extra: tool (default Agent) and mode (ZETETIC_AGENT_GATE value)."""
    tool, mode = extra.get("tool", "Agent"), extra.get("mode")
    tool_input = {"prompt": prompt, "description": description}
    if subagent_type is not None:
        tool_input["subagent_type"] = subagent_type
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    env = dict(os.environ)
    env.pop("ZETETIC_AGENT_GATE", None)
    if mode:
        env["ZETETIC_AGENT_GATE"] = mode
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                          text=True, capture_output=True, env=env, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def verdict(out):
    spec = out.get("hookSpecificOutput", {})
    return spec.get("permissionDecision"), spec.get("permissionDecisionReason", "")


# ── the four acceptance cases ────────────────────────────────────────────────

def test_denies_a_missing_genius_line():
    decision, reason = verdict(run_gate(prompt="Fix the failing retry test in client.py",
                                        description="fix a bug"))
    assert decision == "deny"
    assert "GENIUS:" in reason and "no genius pattern" in reason


@pytest.mark.parametrize("name", REMOVED)
def test_denies_a_removed_base_agent_type(name):
    for subagent_type in (name, f"zetetic-team-subagents:{name}"):
        decision, reason = verdict(run_gate(subagent_type, "GENIUS: popper\ndo the thing"))
        assert decision == "deny", subagent_type
        assert "was removed" in reason and "built-in" in reason


def test_denies_an_unknown_genius_name():
    decision, reason = verdict(run_gate(prompt="GENIUS: feynmann\nreview the diff"))
    assert decision == "deny"
    assert "unknown genius" in reason and "feynman" in reason, "suggests the close match"


def test_allows_a_valid_call():
    for prompt in ("GENIUS: popper\nReview the diff.",
                   "Intro line\nGENIUS: dijkstra, liskov\nImplement the parser."):
        assert run_gate(prompt=prompt) == {}
    assert run_gate("Explore", "GENIUS: borges\nFind callers of load().") == {}
    assert run_gate("Plan", "  GENIUS: polya\nPlan the migration.") == {}
    assert run_gate(None, "GENIUS: wu\nno subagent_type defaults to general-purpose") == {}


# ── the rest of the contract ─────────────────────────────────────────────────

def test_denies_more_than_two_geniuses():
    decision, reason = verdict(run_gate(prompt="GENIUS: popper, feynman, curie\nx"))
    assert decision == "deny" and "1 or 2" in reason


def test_denies_an_empty_genius_line():
    decision, _ = verdict(run_gate(prompt="GENIUS:   \nx"))
    assert decision == "deny"


def test_denies_a_genius_used_as_a_subagent_type_and_names_the_right_one():
    decision, reason = verdict(run_gate("popper", "GENIUS: popper\nx"))
    assert decision == "deny" and "general-purpose" in reason and "GENIUS: popper" in reason


def test_denial_suggests_geniuses_from_the_routing_table_for_the_task():
    _, reason = verdict(run_gate(prompt="Review this pull request diff for bugs"))
    assert "popper, feynman" in reason and "code review" in reason
    _, reason = verdict(run_gate(prompt="Profile the slow query and cut latency"))
    assert "knuth, curie" in reason
    _, reason = verdict(run_gate(prompt="zzz qqq"))
    assert "popper, feynman" in reason, "falls back to the epistemic generalists"


def test_removed_type_denial_names_the_builtin_and_the_geniuses_of_its_route():
    _, reason = verdict(run_gate("architect", "x"))
    assert "`Plan`" in reason and "simon, alexander" in reason


def test_other_plugins_namespaced_types_and_system_types_are_not_gated():
    assert run_gate("understand-anything:file-analyzer", "scan these files") == {}
    assert run_gate("context-guard:memory-writer", "persist the stub") == {}
    assert run_gate("statusline-setup", "configure") == {}
    assert run_gate("claude-code-guide", "how do hooks work?") == {}


def test_a_zetetic_namespaced_unknown_type_is_denied():
    decision, _ = verdict(run_gate("zetetic-team-subagents:whatever", "GENIUS: popper\nx"))
    assert decision == "deny"


def test_task_tool_alias_is_gated_and_other_tools_are_not():
    assert verdict(run_gate(prompt="no marker", tool="Task"))[0] == "deny"
    assert run_gate(prompt="no marker", tool="Bash") == {}


def test_marker_must_be_a_line_of_its_own():
    decision, _ = verdict(run_gate(prompt="remember to add GENIUS: popper somewhere"))
    assert decision == "deny"


def test_observe_mode_allows_with_context_and_off_disables():
    out = run_gate(prompt="no marker", mode="observe")
    assert "permissionDecision" not in out["hookSpecificOutput"]
    assert "observe only" in out["hookSpecificOutput"]["additionalContext"]
    assert run_gate(prompt="no marker", mode="off") == {}


def test_enforce_is_the_default_mode():
    assert verdict(run_gate(prompt="no marker"))[0] == "deny"


@pytest.mark.parametrize("raw", ["", "not json", "[1]", "null"])
def test_unparseable_input_is_allowed(raw):
    proc = subprocess.run([sys.executable, str(HOOK)], input=raw, text=True,
                          capture_output=True, timeout=30)
    assert proc.returncode == 0 and proc.stdout.strip() == ""


# ── the data and the registration the gate relies on ─────────────────────────

def test_every_route_targets_a_builtin_type_and_existing_geniuses():
    genius = {p.stem for p in (REPO / "agents" / "genius").glob("*.md")}
    for route in ROUTES["routes"]:
        assert route["subagent_type"] in ROUTES["builtin_types"], route
        assert 1 <= len(route["geniuses"]) <= 2, route
        assert set(route["geniuses"]) <= genius, route
        assert route["keywords"], route
    assert set(ROUTES["fallback_geniuses"]) <= genius


def test_every_removed_agent_is_either_routed_or_listed_as_unreplaced():
    replaced = {r["replaces"] for r in ROUTES["routes"] if r["replaces"]}
    unreplaced = {"latex-engineer", "memory-writer", "orchestrator", "advisor"}
    assert replaced | unreplaced == set(REMOVED)
    assert not replaced & unreplaced


def test_the_removed_agent_files_are_gone_and_only_genius_remain():
    assert [p.name for p in (REPO / "agents").iterdir()] == ["genius"]


def test_the_hook_is_registered_on_the_agent_tool():
    hooks = json.loads((REPO / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
    gate = [h for h in hooks if "pre-agent-genius-gate.py" in json.dumps(h)]
    assert len(gate) == 1 and gate[0]["matcher"] == "Agent|Task"

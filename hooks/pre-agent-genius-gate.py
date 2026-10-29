#!/usr/bin/env python3
"""pre-agent-genius-gate.py — PreToolUse hook on the Agent (Task) tool.

Owner decision 2026-10-21: delegated agents are Claude Code's built-in agents,
and each MUST apply the reasoning pattern of one or two genius agents chosen
for the task. Prose cannot make that mandatory; this hook does, by denying the
Agent call.

Two checks, on every Agent call:

  1. subagent_type. A removed team-role agent (engineer, architect, ...), or a
     genius agent used as a subagent_type, is denied with the built-in type to
     use instead (rules/agent-routes.json). Built-in types, system types and
     other plugins' namespaced types (`plugin:agent`) pass this check.
  2. GENIUS marker. The prompt must carry a line

         GENIUS: <name>[, <name>]

     naming one or two files in agents/genius/<name>.md. A missing line, more
     than two names, or an unknown name is denied, with geniuses suggested from
     the routing table. Other plugins' namespaced types and the system types
     (`claude-code-guide`, `statusline-setup`) are exempt from this check: they
     are not delegations of reasoning work.

Mode (env ZETETIC_AGENT_GATE): `enforce` (default) denies; `observe` allows and
attaches the reason as context; `off` disables. The default is enforce.

Output: a PreToolUse JSON decision on stdout, exit 0. Anything that is not an
Agent call, or is unparseable, is allowed (a gate must never wedge the session).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENIUS_DIR = ROOT / "agents" / "genius"
ROUTES_PATH = ROOT / "rules" / "agent-routes.json"
OWN_PLUGIN = "zetetic-team-subagents"
AGENT_TOOLS = {"Agent", "Task"}
MAX_GENIUSES = 2  # source: owner decision 2026-10-21, "1 or 2 genius agents"
MARKER_RE = re.compile(r"^[ \t]*GENIUS:[ \t]*(.+?)[ \t]*$", re.M)
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")  # source: agents/genius/*.md file stems
# The 23 team-role agents removed on 2026-10-21 (agents/*.md). Kept as data so a
# stale caller gets a pointer, not a mystery.
REMOVED = frozenset(
    "advisor architect code-reviewer data-scientist dba devops-engineer engineer "
    "experiment-runner frontend-engineer git-historian latex-engineer memory-writer "
    "mlops orchestrator paper-writer professor refactorer research-scientist "
    "reviewer-academic security-auditor simplifier test-engineer ux-designer".split()
)


def load_routes() -> dict:
    try:
        return json.loads(ROUTES_PATH.read_text(encoding="utf-8"))  # source: rules/agent-routes.json
    except (OSError, ValueError):
        return {"builtin_types": ["general-purpose", "Explore", "Plan", "claude"],
                "system_types": ["claude-code-guide", "statusline-setup"],
                "routes": [], "fallback_geniuses": ["popper", "feynman"]}


def genius_names(directory: Path = GENIUS_DIR) -> set[str]:
    try:
        return {p.stem for p in directory.glob("*.md") if p.stem not in ("INDEX", "ROUTING")}
    except OSError:
        return set()


def split_type(subagent_type: str) -> tuple[str, str]:
    """('plugin', 'agent') for `plugin:agent`, ('', 'agent') otherwise."""
    if ":" in subagent_type:
        plugin, _, agent = subagent_type.partition(":")
        return plugin, agent
    return "", subagent_type


def best_route(text: str, routes: dict) -> dict | None:
    """The route whose keywords occur most often in `text`, or None."""
    text = text.lower()
    scored = [(sum(k in text for k in r["keywords"]), i, r)
              for i, r in enumerate(routes.get("routes", []))]
    scored = [s for s in scored if s[0] > 0]
    # most keyword hits wins; the earlier route breaks a tie (list order = priority)
    return max(scored, key=lambda s: (s[0], -s[1]))[2] if scored else None


def suggestion(text: str, routes: dict) -> str:
    route = best_route(text, routes)
    geniuses = route["geniuses"] if route else routes.get("fallback_geniuses", [])
    where = f" (task class: {route['task_class']})" if route else ""
    return f"GENIUS: {', '.join(geniuses)}{where}"


def check_type(subagent_type: str, routes: dict, geniuses: set[str]) -> str | None:
    plugin, agent = split_type(subagent_type)
    if plugin not in ("", OWN_PLUGIN, "zetetic"):
        return None  # another plugin's agent
    if agent in REMOVED:
        route = next((r for r in routes.get("routes", []) if r.get("replaces") == agent), None)
        use = route["subagent_type"] if route else "general-purpose"
        pair = f" with `GENIUS: {', '.join(route['geniuses'])}`" if route else " with a GENIUS line"
        return (f"subagent_type `{subagent_type}` was removed (owner decision 2026-10-21: only "
                f"the genius reasoning agents are kept). Use the built-in `{use}`{pair} in the "
                f"prompt. Routes: rules/agent-routes.json.")
    if agent in geniuses:
        return (f"`{subagent_type}` is a reasoning pattern, not a subagent type. Use the "
                f"built-in `general-purpose` and add `GENIUS: {agent}` to the prompt.")
    if plugin == OWN_PLUGIN:
        return (f"`{subagent_type}` is not an agent of this plugin. Use a built-in type "
                f"(general-purpose, Explore, Plan) with a GENIUS line.")
    return None


def parse_marker(prompt: str) -> list[str] | None:
    """Names from every `GENIUS:` line, or None when there is no such line."""
    lines = MARKER_RE.findall(prompt or "")
    if not lines:
        return None
    names = []
    for line in lines:
        names += [n.strip().strip("`*").lower() for n in line.split(",") if n.strip()]
    return names


def check_marker(prompt: str, text: str, routes: dict, geniuses: set[str]) -> str | None:
    names = parse_marker(prompt)
    hint = suggestion(text, routes)
    if names is None:
        return ("the prompt carries no genius pattern. Every delegation must apply the "
                "reasoning pattern of 1 or 2 genius agents: add a line `GENIUS: <name>[, <name>]` "
                f"and embed or point to agents/genius/<name>.md. Suggested for this task: {hint}")
    if not names or len(set(names)) > MAX_GENIUSES:
        return (f"the GENIUS line must name 1 or {MAX_GENIUSES} geniuses, found "
                f"{len(set(names))}. Suggested for this task: {hint}")
    bad = [n for n in dict.fromkeys(names) if not NAME_RE.match(n) or (geniuses and n not in geniuses)]
    if bad:
        return (f"unknown genius {_describe_unknown(bad, geniuses)}: no agents/genius/<name>.md. "
                f"Suggested for this task: {hint}")
    return None


def _describe_unknown(bad: list[str], geniuses: set[str]) -> str:
    """`name` (did you mean a, b?) for each unknown name."""
    parts = []
    for name in bad:
        close = difflib.get_close_matches(name, sorted(geniuses), n=2)
        parts.append(f"`{name}`" + (f" (did you mean {', '.join(close)}?)" if close else ""))
    return "; ".join(parts)


def decide(event: dict, routes: dict | None = None, geniuses: set[str] | None = None) -> str | None:
    """The denial reason for an Agent call, or None to allow."""
    if event.get("tool_name") not in AGENT_TOOLS:
        return None
    args = event.get("tool_input") or {}
    if not isinstance(args, dict):
        return None
    routes = routes if routes is not None else load_routes()
    geniuses = geniuses if geniuses is not None else genius_names()
    subagent_type = str(args.get("subagent_type") or "general-purpose")
    reason = check_type(subagent_type, routes, geniuses)
    if reason:
        return reason
    plugin, agent = split_type(subagent_type)
    if plugin not in ("", OWN_PLUGIN, "zetetic") or agent in routes.get("system_types", []):
        return None  # exempt from the GENIUS requirement
    prompt = str(args.get("prompt") or "")
    return check_marker(prompt, f"{args.get('description') or ''}\n{prompt}", routes, geniuses)


def emit(mode: str, reason: str | None) -> dict:
    if not reason:
        return {}
    message = f"Genius gate: {reason}"
    if mode == "observe":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "additionalContext": f"[observe only] {message}"}}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": message}}


def main() -> int:
    mode = os.environ.get("ZETETIC_AGENT_GATE", "enforce").strip().lower()
    if mode == "off":
        return 0
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0
    out = emit(mode, decide(event))
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

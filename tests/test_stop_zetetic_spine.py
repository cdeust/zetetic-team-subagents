"""Unit tests for hooks/stop-zetetic-spine.py's tool-shape patterns.

EVIDENCE_RE decides whether the session showed spine evidence (a recall/search
beat) before a claim-producing edit. It matches MCP tool names literally, and an
MCP tool's name is derived by the host as
`mcp__plugin_<plugin-name>_<mcp-server-key>__<tool>` — so a plugin RENAME
silently invalidates every literal here: the pattern stops matching, the hook
sees no evidence, and it blocks (or, symmetrically, a stale literal that can
never appear makes that arm dead). Cortex renamed its plugin `cortex` ->
`hypermnesia-mcp` in 4.15.0, which is exactly this failure. The literals are
pinned here so the next rename fails a test instead of degrading a guard.

The module is loaded by path rather than imported, for the same reason as
test_context_guard.py: hyphenated filename, hooks/ is not a package.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "stop-zetetic-spine.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("stop_zetetic_spine", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


spine = _load_hook()


def _tool_use(name: str) -> str:
    """A transcript fragment as the hook sees it — a JSON tool_use record."""
    return '{"type": "tool_use", "name": "%s", "input": {}}' % name


# ── EVIDENCE_RE — the memory/web beats that count as spine evidence ───────────

CURRENT_MEMORY_TOOLS = [
    "mcp__plugin_hypermnesia-mcp_cortex__recall",
    "mcp__plugin_hypermnesia-mcp_cortex__unified_search",
    "mcp__plugin_hypermnesia-mcp_cortex__navigate_memory",
]


@pytest.mark.parametrize("tool", CURRENT_MEMORY_TOOLS)
def test_evidence_re_matches_current_memory_tool_names(tool):
    assert spine.EVIDENCE_RE.search(_tool_use(tool))


@pytest.mark.parametrize("tool", ["WebSearch", "WebFetch"])
def test_evidence_re_matches_web_evidence_tools(tool):
    assert spine.EVIDENCE_RE.search(_tool_use(tool))


@pytest.mark.parametrize("tool", CURRENT_MEMORY_TOOLS)
def test_evidence_re_rejects_pre_rename_cortex_prefix(tool):
    """The 4.14.x prefix must not linger: it can never appear in a transcript.

    A pattern that still accepted it would keep a dead arm alive and hide the
    fact that the live literals were never updated.
    """
    stale = tool.replace("mcp__plugin_hypermnesia-mcp_cortex__",
                         "mcp__plugin_cortex_cortex__")
    assert not spine.EVIDENCE_RE.search(_tool_use(stale))


def test_evidence_re_ignores_an_unrelated_tool():
    assert not spine.EVIDENCE_RE.search(_tool_use("Read"))


def test_evidence_re_tolerates_json_whitespace():
    fragment = '{"name"  :   "mcp__plugin_hypermnesia-mcp_cortex__recall"}'
    assert spine.EVIDENCE_RE.search(fragment)


def test_remember_is_not_evidence():
    """A write is not a recall — remember must not satisfy the spine."""
    assert not spine.EVIDENCE_RE.search(
        _tool_use("mcp__plugin_hypermnesia-mcp_cortex__remember"))


# ── CHANGE_RE — the claim/state-producing calls the spine guards ──────────────

@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
def test_change_re_matches_state_producing_tools(tool):
    assert spine.CHANGE_RE.search(_tool_use(tool))


@pytest.mark.parametrize("tool", ["Read", "Grep", "WebSearch"])
def test_change_re_ignores_read_only_tools(tool):
    assert not spine.CHANGE_RE.search(_tool_use(tool))


# ── MEMORY_CMD_RE — the shell-side memory beat ────────────────────────────────

@pytest.mark.parametrize("cmd", ["memory-tool.sh view", "memory-tool.sh  search"])
def test_memory_cmd_re_matches_read_subcommands(cmd):
    assert spine.MEMORY_CMD_RE.search(cmd)


def test_memory_cmd_re_ignores_write_subcommand():
    assert not spine.MEMORY_CMD_RE.search("memory-tool.sh append 'note'")

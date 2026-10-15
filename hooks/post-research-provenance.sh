#!/usr/bin/env bash
# post-research-provenance.sh — Append URL/query to active provenance file after research tool calls
# Fires after WebFetch/WebSearch and the crawl4ai MCP research tools (q, url, urls). Lightweight (< 1s). Silent no-op if no active provenance.
#
# claude.ai Science binding slot: claude.ai Science is a beta desktop app not yet
# exposed as a named MCP tool (rules/agent-reference/research-resources.md). When it
# is, add its real mcp__… tool name to the WebFetch|WebSearch PostToolUse matcher in
# hooks/hooks.json AND .claude-plugin/plugin.json so this hook fires for it. The body
# below already labels a science-review tool call as "verified" (vs "consulted") by
# tool_name pattern, so provenance distinguishes verification from mere consultation
# the moment the matcher is widened. Do NOT invent the tool name before it exists.
set -euo pipefail

# Path resolution: CLAUDE_PLUGIN_ROOT → script-relative → git root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}"
TOOLS="${PLUGIN_ROOT}/tools"
[[ ! -d "$TOOLS" ]] && TOOLS="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/tools"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RESEARCH_DIR="$REPO_ROOT/research"

# Guard: provenance-manager must exist
[[ ! -x "$TOOLS/provenance-manager.sh" ]] && exit 0

# Read hook context from stdin
HOOK_INPUT=""
if ! [ -t 0 ]; then
  # Portable bounded stdin read. macOS ships NO 'timeout'/'gtimeout'; its
  # absence must NOT zero out the payload (that silently disables the hook — the
  # root cause of audit finding R1). Use the bound if present, else plain cat.
  _ZT="$(command -v timeout || command -v gtimeout || true)"
  if [ -n "$_ZT" ]; then
    HOOK_INPUT="$("$_ZT" 3 cat 2>/dev/null || true)"
  else
    HOOK_INPUT="$(cat 2>/dev/null || true)"
  fi
fi

# Guard: check for active research session
PROVENANCE_FILE=""
if [[ -f "$RESEARCH_DIR/NOTEBOOK.md" ]]; then
  # Find the most recent .provenance.md in the research directory
  PROVENANCE_FILE="$(find "$RESEARCH_DIR" -maxdepth 2 -name '*.provenance.md' -type f -print0 \
    | xargs -0 ls -t 2>/dev/null | head -1 || true)"
fi

# Also check for standalone .provenance.md in repo root
if [[ -z "$PROVENANCE_FILE" && -f "$REPO_ROOT/.provenance.md" ]]; then
  PROVENANCE_FILE="$REPO_ROOT/.provenance.md"
fi

# Guard: no active provenance file — silent no-op
[[ -z "$PROVENANCE_FILE" ]] && exit 0

# Extract URL or query from hook stdin context
if command -v jq &>/dev/null; then
  TOOL_NAME=$(echo "$HOOK_INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null || echo "unknown")
  SOURCE=$(echo "$HOOK_INPUT" | jq -r '.tool_input.url // .tool_input.query // .tool_input.q // (.tool_input.urls // empty | join(" "))' 2>/dev/null || echo "")
else
  TOOL_NAME=$(echo "$HOOK_INPUT" | grep -oE '"tool_name":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"tool_name":\s*"//' | sed 's/"$//' || echo "unknown")
  SOURCE=$(echo "$HOOK_INPUT" | grep -oE '"url":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"url":\s*"//' | sed 's/"$//' || echo "")
  [[ -z "$SOURCE" ]] && SOURCE=$(echo "$HOOK_INPUT" | grep -oE '"query":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"query":\s*"//' | sed 's/"$//' || echo "")
  [[ -z "$SOURCE" ]] && SOURCE=$(echo "$HOOK_INPUT" | grep -oE '"q":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"q":\s*"//' | sed 's/"$//' || echo "")
fi
[[ -z "$SOURCE" ]] && exit 0

# claude.ai Science is a verification/audit engine, not a discovery search — a hit
# is a VERIFIED claim, not merely a consulted source. Label it distinctly by
# tool_name pattern (case-insensitive 'science'). Forward-compatible: harmless until
# the matcher routes the real mcp__… tool name (see header binding slot).
STATUS="consulted"
case "$(printf '%s' "$TOOL_NAME" | tr '[:upper:]' '[:lower:]')" in
  *science*) STATUS="verified (claude.ai Science)" ;;
esac

TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# Append to provenance via the manager
"$TOOLS/provenance-manager.sh" append \
  --file "$PROVENANCE_FILE" \
  --source "$SOURCE" \
  --tool "$TOOL_NAME" \
  --status "$STATUS" \
  --timestamp "$TIMESTAMP" 2>/dev/null || {
  # Fallback: direct append if manager fails
  echo "| $TIMESTAMP | $TOOL_NAME | $SOURCE | $STATUS |" >> "$PROVENANCE_FILE" || true
}

exit 0

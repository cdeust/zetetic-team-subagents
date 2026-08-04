#!/usr/bin/env bash
# shape-router.sh — Route a problem to genius agents by matching problem shapes
#
# Usage:
#   tools/shape-router.sh "<problem description or shape keyword>"
#
# Searches INDEX.md for matching shapes and outputs the agent(s) + key moves.
# Exit codes: 0 match found, 1 no match

set -euo pipefail

# Resolve agent directory: env var → ~/.claude/agents → plugin-relative → git root
_resolve_agents_dir() {
  local d
  d="${ZETETIC_AGENTS:-}"
  [[ -n "$d" && -d "$d/genius" ]] && { echo "$d"; return; }
  d="$HOME/.claude/agents"
  [[ -d "$d/genius" ]] && { echo "$d"; return; }
  d="$(cd "$(dirname "$0")/.." && pwd)/agents"
  [[ -d "$d/genius" ]] && { echo "$d"; return; }
  d="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/agents"
  echo "$d"
}

AGENTS_DIR="$(_resolve_agents_dir)"
INDEX="$AGENTS_DIR/genius/INDEX.md"

QUERY="${1:-}"
[[ -z "$QUERY" ]] && { echo "usage: $0 \"<problem description or keyword>\"" >&2; exit 1; }

# A missing index is an install fault, not an absent match: reporting it as
# "no matching shapes" would send the caller hunting for better keywords.
[[ -r "$INDEX" ]] || { echo "shape-router: index not readable: $INDEX" >&2; exit 2; }

# `|| true` is required, not defensive: under `set -euo pipefail` a grep that
# matches nothing fails the pipeline, and the failing status of a command
# substitution propagates to the assignment, killing the script. Without it
# every no-match query exits 1 silently and the fallback below is unreachable.
matches=$(grep -i "$QUERY" "$INDEX" | grep -E '^\| \*\*' | head -10 || true)

if [[ -z "$matches" ]]; then
  # Try broader search
  matches=$(grep -i "$QUERY" "$INDEX" | grep -E '^\|' | grep -v '^\| Shape' | head -10 || true)
fi

if [[ -z "$matches" ]]; then
  echo "No matching shapes found for: $QUERY"
  echo "Try broader keywords or check agents/genius/INDEX.md directly."
  exit 1
fi

echo "Matching shapes for: $QUERY"
echo ""
echo "$matches"
echo ""
echo "Consult agents/genius/INDEX.md for full shape descriptions and agent details."

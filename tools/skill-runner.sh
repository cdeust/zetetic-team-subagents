#!/usr/bin/env bash
# skill-runner.sh — Resolve and display a skill's procedure for Claude to follow
#
# Usage:
#   tools/skill-runner.sh <skill-name>
#
# Searches skills/ recursively for <name>.md, prints its procedure and zetetic gates.
#
# Model-tier escalation policy (agent-to-skill migration, Phase 1): this
# runner has no way to introspect the model tier of the CALLING session --
# it is a bash script with no visibility into the Claude process invoking it.
# So "detect the caller's tier and compare" is not implementable here. Instead
# it compares each agent named in the skill's `agents:` frontmatter against a
# fixed baseline tier (sonnet: the most common team-agent model, 16/23 in
# agents/*.md, measured 2026-09-04 -- see tools/tests/skill-model-tier-policy).
# An agent whose own `model:` exceeds that baseline (opus, fable) is a
# deliberate capability escalation the skill's author chose -- inlining its
# procedure at the caller's tier would silently drop that upgrade with no
# indication anything was lost. When one is found, a banner is printed before
# the procedure body naming it; the caller must spawn it as a real subagent
# via the Agent tool, not inline it.
#
# Exit codes: 0 found, 1 not found

set -euo pipefail

# Ordinal ranking of model tiers, cheapest to most capable/expensive.
# source: ~/.claude/rules/agent-reference/effort-calibration.md model catalog
# (Anthropic claude-api reference, cached 2026-06-24): Haiku 4.5 $1/$5,
# Sonnet 5 $3/$15, Opus 5 $5/$25, Fable 5 $10/$50 per MTok.
declare -A MODEL_TIER_RANK=( [haiku]=0 [sonnet]=1 [opus]=2 [fable]=3 )

# Baseline caller tier used for the escalation comparison above. Overridable
# for a caller known to run at a different default (e.g. an all-opus fleet).
BASELINE_MODEL="${ZETETIC_SKILL_BASELINE_MODEL:-sonnet}"

# Resolve a plugin-relative content directory (skills/, agents/): env var →
# ~/.claude/<dirname> → plugin-relative → git root. Shared by the skills-dir
# and agents-dir resolvers below since both ship side by side in this
# plugin's layout and are looked up by the same precedence.
_resolve_plugin_dir() {
  local env_value="$1" dirname="$2" d
  d="$env_value"
  [[ -n "$d" && -d "$d" ]] && { echo "$d"; return; }
  d="$HOME/.claude/$dirname"
  [[ -d "$d" ]] && { echo "$d"; return; }
  d="$(cd "$(dirname "$0")/.." && pwd)/$dirname"
  [[ -d "$d" ]] && { echo "$d"; return; }
  d="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/$dirname"
  echo "$d"
}

_resolve_skills_dir() { _resolve_plugin_dir "${ZETETIC_SKILLS:-}" "skills"; }
_resolve_agents_dir() { _resolve_plugin_dir "${ZETETIC_AGENTS:-}" "agents"; }

# Precondition: skill_file is a readable path to a skill Markdown file whose
# frontmatter, if it declares `agents:`, uses block-list style
# (`agents:\n  - x\n  - y`) -- the only style used across skills/**/*.md
# (verified: no `agents: [...]` inline form exists in this repo, 2026-09-04).
# Postcondition: prints one agent name per line, in declaration order; prints
# nothing if the skill has no `agents:` field.
_frontmatter_agents() {
  local skill_file="$1"
  awk '
    /^agents:[[:space:]]*$/ { in_agents=1; next }
    in_agents && /^[[:space:]]*-[[:space:]]*/ { sub(/^[[:space:]]*-[[:space:]]*/, ""); print; next }
    in_agents { in_agents=0 }
  ' "$skill_file"
}

# Precondition: agents_dir is the resolved agents/ directory; name is an
# agent's bare name (no path, no .md).
# Postcondition: prints the agent's declared `model:` value if a definition
# is found under agents_dir/<name>.md or agents_dir/genius/<name>.md; prints
# nothing (not an error) if no definition is found -- an unresolvable agent
# name is not this runner's failure mode to raise, since a stale skill
# reference is caught by frontmatter-validator, not by this display path.
_agent_model() {
  local agents_dir="$1" name="$2" path
  for path in "$agents_dir/$name.md" "$agents_dir/genius/$name.md"; do
    [[ -f "$path" ]] || continue
    awk -F': *' '/^model:/ { print $2; exit }' "$path"
    return
  done
}

# Precondition: model is a non-empty tier name.
# Postcondition: returns success iff model's rank strictly exceeds
# BASELINE_MODEL's rank. An unrecognized model name never escalates (ranks
# default to unset, so the comparison short-circuits false) -- silence over
# a false-positive banner on a typo the frontmatter validator should catch
# instead.
_is_escalation() {
  local model="$1" baseline_rank model_rank
  baseline_rank="${MODEL_TIER_RANK[$BASELINE_MODEL]:-1}"
  model_rank="${MODEL_TIER_RANK[$model]:-}"
  [[ -n "$model_rank" ]] && (( model_rank > baseline_rank ))
}

SKILLS_DIR="$(_resolve_skills_dir)"
AGENTS_DIR="$(_resolve_agents_dir)"

NAME="${1:-}"
[[ -z "$NAME" ]] && { echo "usage: $0 <skill-name>" >&2; exit 1; }

# Search for the skill file
SKILL_FILE=$(find "$SKILLS_DIR" -name "${NAME}.md" -not -name "_*" 2>/dev/null | head -1)

if [[ -z "$SKILL_FILE" ]]; then
  echo "Skill not found: $NAME" >&2
  echo "" >&2
  echo "Available skills:" >&2
  find "$SKILLS_DIR" -name "*.md" -not -name "_*" -exec basename {} .md \; | sort | sed 's/^/  /' >&2
  exit 1
fi

echo "=== Skill: $NAME ==="
echo "File: $SKILL_FILE"
echo ""

# Model-tier escalation banner: printed before the procedure body so it
# cannot be missed or scrolled past silently.
escalations=()
while IFS= read -r agent_name; do
  [[ -z "$agent_name" ]] && continue
  model="$(_agent_model "$AGENTS_DIR" "$agent_name")"
  [[ -z "$model" ]] && continue
  if _is_escalation "$model"; then
    escalations+=("$agent_name ($model)")
  fi
done < <(_frontmatter_agents "$SKILL_FILE")

if [[ "${#escalations[@]}" -gt 0 ]]; then
  echo "!!! MODEL-TIER ESCALATION REQUIRED !!!"
  echo "This skill names an agent above the baseline tier ($BASELINE_MODEL):"
  for e in "${escalations[@]}"; do
    echo "  - $e"
  done
  echo "Spawn each one as a real subagent via the Agent tool. Do NOT inline"
  echo "its procedure at the caller's own tier -- that silently drops the"
  echo "capability upgrade its model: field declares."
  echo ""
fi

# Extract and display key sections
awk '
/^---$/ { fm++; next }
fm < 2 { next }
fm >= 2 { print }
' "$SKILL_FILE"

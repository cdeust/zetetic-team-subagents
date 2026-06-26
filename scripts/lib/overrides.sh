# lib/overrides.sh — per-agent model + effort override resolution.
# Sourced by setup.sh. Relies on these globals/functions from the caller:
#   MODEL_CONFIG, warn(), ok()   (defined before this file is sourced)
# Cross-platform: pure bash + python3 (probed via command -v); no OS-specific calls.

# ── Agent override resolution (model + effort) ─────────────────────────
# Reads ~/.claude/zetetic-agent-models.json and resolves model + effort per agent.
# Config schema (backward compatible):
#   { "agents": {
#       "engineer": "sonnet",                                 # shorthand: model only
#       "architect": { "model": "opus", "effort": "high" },    # full: model + effort
#       "refactorer": { "effort": "low" }                      # effort only (keeps frontmatter model)
#     },
#     "patterns": [
#       { "glob": "genius/*", "model": "sonnet" },             # shorthand
#       { "glob": "genius/*", "model": "sonnet", "effort": "medium" }  # full
#     ] }
# Precedence: exact match > first glob match > default from frontmatter
# Lines stored as: "name=model|effort" where model or effort may be empty.
OVERRIDES_LOADED=false
OVERRIDES_AGENTS=""
OVERRIDES_PATTERNS=""

load_overrides() {
  [[ "$OVERRIDES_LOADED" == true ]] && return
  OVERRIDES_LOADED=true
  [[ ! -f "$MODEL_CONFIG" ]] && return
  command -v python3 &>/dev/null || { warn "python3 required for overrides — skipping"; return; }

  if ! python3 -c "import json; json.load(open('$MODEL_CONFIG'))" 2>/dev/null; then
    warn "Invalid JSON in $MODEL_CONFIG — skipping overrides"
    return
  fi

  OVERRIDES_AGENTS=$(python3 -c "
import json
d = json.load(open('$MODEL_CONFIG'))
for name, v in d.get('agents', {}).items():
    if isinstance(v, str):
        print(f'{name}={v}|')
    elif isinstance(v, dict):
        print(f'{name}={v.get(\"model\",\"\")}|{v.get(\"effort\",\"\")}')
" 2>/dev/null || true)

  OVERRIDES_PATTERNS=$(python3 -c "
import json
d = json.load(open('$MODEL_CONFIG'))
for p in d.get('patterns', []):
    print(f\"{p['glob']}={p.get('model','')}|{p.get('effort','')}\")
" 2>/dev/null || true)

  local ac pc
  ac=$(echo "$OVERRIDES_AGENTS" | grep -c '=' 2>/dev/null || echo "0")
  pc=$(echo "$OVERRIDES_PATTERNS" | grep -c '=' 2>/dev/null || echo "0")
  [[ "$ac" -gt 0 || "$pc" -gt 0 ]] && ok "Overrides loaded: $ac agents, $pc patterns"
}

# Returns "model|effort" (either may be empty = keep default).
resolve_override() {
  local agent_name="$1"
  [[ -z "$OVERRIDES_AGENTS" && -z "$OVERRIDES_PATTERNS" ]] && { echo "|"; return; }

  # Exact match
  local exact
  exact=$(echo "$OVERRIDES_AGENTS" | grep "^${agent_name}=" 2>/dev/null | head -1 | cut -d= -f2-)
  [[ -n "$exact" ]] && { echo "$exact"; return; }

  # Glob patterns — first match wins
  while IFS= read -r pattern_line; do
    [[ -z "$pattern_line" ]] && continue
    local glob_pattern="${pattern_line%%=*}"
    local glob_rest="${pattern_line#*=}"
    # shellcheck disable=SC2254
    case "$agent_name" in
      $glob_pattern) echo "$glob_rest"; return ;;
    esac
  done <<< "$OVERRIDES_PATTERNS"

  echo "|"
}

# Back-compat alias (older callers expect just model)
load_model_overrides() { load_overrides; }
resolve_model() {
  local ov; ov="$(resolve_override "$1")"
  local model="${ov%%|*}"
  [[ -n "$model" ]] && echo "$model" || echo "$2"
}

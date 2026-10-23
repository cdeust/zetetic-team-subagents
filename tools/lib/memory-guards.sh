# shellcheck shell=bash
# shellcheck disable=SC2154  # globals assigned by tools/memory-tool.sh before sourcing
# memory-guards.sh — registry/ACL, path resolution, audit and write guards of
# memory-tool.sh. Sourced, never executed. Expects the globals set at the top of
# memory-tool.sh: MEMORY_ROOT, MEMORY_AGENT_ID, MEMORY_REGISTRY, AUDIT_LOG,
# MEMORY_MAX_FILE_KB and _script_dir.

# ─── helpers ─────────────────────────────────────────────────────────────────

die() { echo "memory-tool: $*" >&2; exit 2; }

# ─── registry / ACL ──────────────────────────────────────────────────────────
# Returns one of: allow | deny. Verbatim rules from scope-registry.json.
# Usage: acl_check <scope> <access: read|write>
# Falls back to defaults{} block if scope not listed.
# If strict_unknown_scope=true and scope missing, denies all writes.
acl_check() {
  local scope="$1" access="$2"
  [[ -n "${MEMORY_NO_ACL:-}" ]] && { echo allow; return 0; }
  if [[ ! -f "$MEMORY_REGISTRY" ]]; then
    # No registry present → permissive (first-run convenience).
    echo allow; return 0
  fi
  python3 "$_script_dir/lib/memory_acl.py" check "$MEMORY_REGISTRY" "$scope" "$access" "$MEMORY_AGENT_ID"
}

# Per-scope file size cap from registry; falls back to MEMORY_MAX_FILE_KB env.
# Usage: scope_max_kb <scope> → prints integer KB.
scope_max_kb() {
  local scope="$1"
  if [[ ! -f "$MEMORY_REGISTRY" ]]; then
    echo "$MEMORY_MAX_FILE_KB"; return 0
  fi
  python3 - "$MEMORY_REGISTRY" "$scope" "$MEMORY_MAX_FILE_KB" <<'PY'
import json, sys
reg_path, scope, fallback = sys.argv[1:4]
with open(reg_path) as f:
    reg = json.load(f)
entry = reg.get("scopes", {}).get(scope) or reg.get("defaults", {})
print(entry.get("max_file_kb", int(fallback)))
PY
}

# Emit ACL denial verbatim (agent-facing; audit logged by caller).
acl_deny() {
  local scope="$1" access="$2"
  echo "Error: agent '$MEMORY_AGENT_ID' is not permitted to $access scope '/memories/$scope'"
}

# Deny-and-exit when the agent may not <access> the scope: prints the verbatim
# denial, audits it, exits 1. Usage: _acl_guard <scope> <read|write> <cmd> <audit_vpath>
_acl_guard() {
  local scope="$1" access="$2" cmd="$3" audit_vpath="$4"
  if [[ "$(acl_check "$scope" "$access")" == "deny" ]]; then
    acl_deny "$scope" "$access"
    audit "$cmd" "$audit_vpath" 0 acl_denied
    exit 1
  fi
}

# Resolve a user-facing /memories path to an absolute FS path.
# Usage: resolve_path <vpath> <out_var_name>
#   - on success: sets the named variable, returns 0
#   - on failure: prints Anthropic-verbatim error to stdout, returns 1
# Uses an out-variable (not command substitution) so error messages are
# visible to the user instead of being swallowed by $(...).
resolve_path() {
  local vpath="$1" __out_var="$2"
  # Must start with /memories exactly (either the bare root or /memories/...).
  if [[ "$vpath" != "/memories" && "$vpath" != /memories/* ]]; then
    echo "Error: path must begin with /memories"
    return 1
  fi
  # Reject obvious traversal patterns before any filesystem operation.
  case "$vpath" in
    *'/../'*|*'/./'*|*'/..'|*'/.'|*'..\\'*|*'%2e%2e'*|*'%2E%2E'*)
      echo "Error: path must begin with /memories"
      return 1 ;;
  esac
  local rel=""
  [[ "$vpath" == /memories/* ]] && rel="${vpath#/memories/}"
  local target="$MEMORY_ROOT${rel:+/$rel}"
  # Bare root (/memories) is always valid — it maps to MEMORY_ROOT itself,
  # which is created at tool startup. Skip parent check in this case.
  if [[ "$target" != "$MEMORY_ROOT" ]]; then
    # For non-root paths, canonicalize the existing parent and verify it
    # stays inside MEMORY_ROOT. This defeats symlink escapes. Parent is NOT
    # auto-created here — that happens in the command handler after validation.
    local parent; parent="$(dirname -- "$target")"
    if [[ -d "$parent" ]]; then
      local real_parent; real_parent="$(cd "$parent" && pwd -P)"
      local real_root; real_root="$(cd "$MEMORY_ROOT" && pwd -P)"
      case "$real_parent" in
        "$real_root"|"$real_root"/*) : ;;
        *) echo "Error: path must begin with /memories"; return 1 ;;
      esac
    fi
  fi
  printf -v "$__out_var" '%s' "$target"
}

# Ensure the parent directory of a target path exists. Called only after
# resolve_path has validated the target is inside MEMORY_ROOT.
ensure_parent() {
  local target="$1"
  mkdir -p -- "$(dirname -- "$target")"
}

# Virtual path for user-facing messages (keeps /memories prefix stable).
vpath() { printf '%s' "$1"; }

# Scope = first path segment under /memories ("_root" for the bare root).
scope_of() {
  local vpath="$1"
  local rel="${vpath#/memories/}"
  local scope="${rel%%/*}"
  [[ -n "$scope" && "$scope" != "$vpath" ]] || scope="_root"
  printf '%s' "$scope"
}

# Atomic write: write to .tmp then rename. Caller has already held the lock.
atomic_write() {
  local target="$1" content="$2"
  local tmp="$target.tmp.$$"
  printf '%s' "$content" > "$tmp"
  # Flush this file, not every filesystem while holding the scope lock.
  # Source: https://docs.python.org/3/library/os.html#os.fsync
  python3 - "$tmp" <<'PY'
import os
import sys

with open(sys.argv[1], "r+b") as file:
    os.fsync(file.fileno())
PY
  mv -f -- "$tmp" "$target"
}

size_check() {
  local bytes="$1" path="$2" scope="$3"
  local max_kb; max_kb="$(scope_max_kb "$scope")"
  local max=$((max_kb * 1024))
  if (( bytes > max )); then
    echo "Error: file $(vpath "$path") exceeds max size of ${max_kb}KB"
    exit 1
  fi
}

audit() {
  [[ -n "${MEMORY_NO_AUDIT:-}" ]] && return 0
  local cmd="$1" vpath="$2" bytes="${3:-0}" result="${4:-ok}"
  local sha="${5:-}"
  mkdir -p -- "$(dirname -- "$AUDIT_LOG")"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\t%s\t%s\t%s\t%s\t%d\t%s\t%s\n' \
    "$ts" "$MEMORY_AGENT_ID" "$(scope_of "$vpath")" "$cmd" "$vpath" "$bytes" "$sha" "$result" \
    >> "$AUDIT_LOG"
}

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 | awk '{print $1}'
  else sha256sum | awk '{print $1}'; fi
}

# R5 — frontmatter contract: .md memory files must carry a description: line
# in YAML frontmatter (the retrieval cue that makes two-tier loading work).
# Usage: _desc_gate <content> <cmd> <vpath>   (exits 1 on violation)
_desc_gate() {
  local content="$1" cmd="$2" vpath="$3"
  [[ -n "${MEMORY_NO_DESC_CHECK:-}" ]] && return 0
  [[ "$vpath" != *.md ]] && return 0
  if printf '%s' "$content" | awk 'NR==1 && $0!="---" {exit 1}
      NR>1 && $0=="---" {exit found?0:1}
      /^description:[[:space:]]*[^[:space:]]/ {found=1}
      END {exit found?0:1}'; then
    return 0
  fi
  audit "$cmd" "$vpath" 0 desc_missing
  cat <<'EOF'
Error: memory .md files require YAML frontmatter with a description: line (the retrieval cue). Begin the file with:
---
description: "<one-line summary used to decide relevance during recall>"
---
then the content. (MEMORY_NO_DESC_CHECK=1 disables this check — tests only.)
EOF
  exit 1
}

# R6 — compare-and-swap guard for read-modify-write across invocations.
# Usage: _cas_gate <real> <expected_sha> <cmd> <vpath>   (exits 1 on mismatch)
_cas_gate() {
  local real="$1" expected="$2" cmd="$3" vpath="$4"
  [[ -z "$expected" ]] && return 0
  local actual; actual=$(sha256_of < "$real")
  if [[ "$actual" != "$expected" ]]; then
    audit "$cmd" "$vpath" 0 cas_mismatch
    echo "Error: compare-and-swap failed for $vpath — expected sha256 $expected, current is $actual. The file changed since you read it; re-read it (view / sha) and retry with the current sha."
    exit 1
  fi
}

# Human-readable size like 4.0K / 1.5K / 2.0M (matches Anthropic view format).
human_size() {
  local bytes="$1"
  awk -v b="$bytes" 'BEGIN{
    if (b < 1024) printf "%dB", b;
    else if (b < 1024*1024) printf "%.1fK", b/1024;
    else printf "%.1fM", b/(1024*1024);
  }'
}

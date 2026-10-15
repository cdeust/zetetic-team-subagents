#!/usr/bin/env bash
# memory-tool.sh — Local backend implementing the memory_20250818 contract
#
# Contract: memory/contract.md (source of truth, binding)
# Spec reference: platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
#
# Usage:
#   memory-tool.sh view        <path> [view_range_start view_range_end]
#   memory-tool.sh create      <path> <file_text>
#   memory-tool.sh str_replace <path> <old_str> <new_str> [expected_sha]
#   memory-tool.sh insert      <path> <insert_line> <insert_text>
#   memory-tool.sh rethink     <path> <file_text> [expected_sha]
#                                                   — atomic whole-file rewrite of an
#                                                     EXISTING file (create for new ones)
#   memory-tool.sh sha         <path>               — sha256 of current content (CAS token)
#   memory-tool.sh delete      <path>
#   memory-tool.sh rename      <old_path> <new_path>
#
# Conflict-aware writes (lost-update protection for shared scopes): pass the
# sha256 obtained from `sha <path>` (or a prior write's audit line) as the
# optional [expected_sha]; the write is rejected if the file changed since.
#
# Frontmatter contract: every .md memory file MUST begin with YAML frontmatter
# carrying a `description:` line — it is the retrieval cue for two-tier loading.
# Enforced on create/rethink. (MEMORY_NO_DESC_CHECK=1 disables — tests only.)
#   memory-tool.sh search      <query> [--scope <name>] [--limit N] [--regex]
#   memory-tool.sh scopes                           — list scopes + sizes (no content)
#   memory-tool.sh preamble                         — print Anthropic system-prompt preamble
#   memory-tool.sh sync-status                      — depth and oldest age of replica queue
#   memory-tool.sh drain-sync [--limit N]           — list pending replica jobs (JSONL)
#   memory-tool.sh commit-sync <job_id>             — mark job as successfully replicated
#   memory-tool.sh release-sync <job_id>            — return a claimed job to the queue
#   memory-tool.sh ttl-sweep [--dry-run]            — delete files older than scope TTL
#   memory-tool.sh audit [--since <iso8601>]        — tail audit log + summary + anomalies
#
# All paths MUST begin with /memories and are resolved under MEMORY_ROOT.
#
# Note: `search` is a deterministic full-text grep over scope files; it is
# NOT semantic similarity. Semantic recall is a separate MCP surface
# (cortex:recall) invoked by the agent directly — never aliased here.
#
# Env:
#   MEMORY_ROOT        (default: $HOME/.claude/memories)
#   MEMORY_AGENT_ID    (default: unknown)   — recorded in audit log + ACL check
#   MEMORY_REGISTRY    (default: $MEMORY_ROOT/.registry.json, or the repo seed)
#   MEMORY_MAX_FILE_KB (default: 100)       — hard per-file byte cap (fallback)
#   MEMORY_NO_AUDIT    (default: unset)     — disable audit log (tests only)
#   MEMORY_NO_ACL      (default: unset)     — disable ACL enforcement (tests only)
#
# Exit codes: 0 success; 1 contract error (message on stdout, verbatim per spec); 2 fatal (stderr).

# shellcheck disable=SC2034  # MEMORY_MAX_LINES, AUDIT_LOG, PENDING_SYNC_DIR are read by the sourced modules
set -euo pipefail

MEMORY_ROOT="${MEMORY_ROOT:-$HOME/.claude/memories}"
MEMORY_AGENT_ID="${MEMORY_AGENT_ID:-unknown}"
MEMORY_MAX_FILE_KB="${MEMORY_MAX_FILE_KB:-100}"
MEMORY_MAX_LINES=999999
AUDIT_LOG="$MEMORY_ROOT/.audit.log"
LOCK_DIR="$MEMORY_ROOT/.locks"
PENDING_SYNC_DIR="$MEMORY_ROOT/.pending-sync"

# Registry lookup order: env override → per-user installed → repo seed.
_script_dir="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
_repo_seed="$_script_dir/../memory/scope-registry.json"
MEMORY_REGISTRY="${MEMORY_REGISTRY:-$MEMORY_ROOT/.registry.json}"
if [[ ! -f "$MEMORY_REGISTRY" && -f "$_repo_seed" ]]; then
  MEMORY_REGISTRY="$_repo_seed"
fi

# The implementation lives in sourced modules; every one expects the globals
# above and defines functions only.
# shellcheck source=lib/memory-guards.sh
source "$_script_dir/lib/memory-guards.sh"
# shellcheck source=lib/memory-lock.sh
source "$_script_dir/lib/memory-lock.sh"
# shellcheck source=lib/memory-pii.sh
source "$_script_dir/lib/memory-pii.sh"
# shellcheck source=lib/memory-write-verbs.sh
source "$_script_dir/lib/memory-write-verbs.sh"
# shellcheck source=lib/memory-read-verbs.sh
source "$_script_dir/lib/memory-read-verbs.sh"
# shellcheck source=lib/memory-sync.sh
source "$_script_dir/lib/memory-sync.sh"
# shellcheck source=lib/memory-admin.sh
source "$_script_dir/lib/memory-admin.sh"

# ─── dispatch ────────────────────────────────────────────────────────────────

mkdir -p "$MEMORY_ROOT" "$LOCK_DIR"

cmd="${1:-}"; shift || true
case "$cmd" in
  view)        cmd_view        "${1:?path}" "${2:-}" "${3:-}" ;;
  create)      cmd_create      "${1:?path}" "${2:?file_text}" ;;
  str_replace) cmd_str_replace "${1:?path}" "${2:?old_str}" "${3:?new_str}" "${4:-}" ;;
  insert)      cmd_insert      "${1:?path}" "${2:?insert_line}" "${3:?insert_text}" ;;
  rethink)     cmd_rethink     "${1:?path}" "${2:?file_text}" "${3:-}" ;;
  sha)         cmd_sha         "${1:?path}" ;;
  delete)      cmd_delete      "${1:?path}" ;;
  rename)      cmd_rename      "${1:?old_path}" "${2:?new_path}" ;;
  search)      cmd_search      "$@" ;;
  scopes)      cmd_scopes ;;
  preamble)    cmd_preamble ;;
  sync-status) cmd_sync_status ;;
  drain-sync)  cmd_drain_sync "$@" ;;
  commit-sync) cmd_commit_sync "${1:?job_id}" ;;
  release-sync) cmd_release_sync "${1:?job_id}" ;;
  ttl-sweep)   cmd_ttl_sweep   "$@" ;;
  audit)       cmd_audit       "$@" ;;
  -h|--help|"") awk 'NR > 1 { if (/^#( |$)/) { sub(/^# ?/, ""); print } else exit }' "$0" ;;
  *) die "unknown command: $cmd (expected: view|create|str_replace|insert|rethink|sha|delete|rename|search|scopes|preamble|sync-status|drain-sync|commit-sync|release-sync|ttl-sweep|audit)" ;;
esac

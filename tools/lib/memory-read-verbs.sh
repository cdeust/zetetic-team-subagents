# shellcheck shell=bash
# shellcheck disable=SC2154  # globals assigned by tools/memory-tool.sh before sourcing
# memory-read-verbs.sh — view / sha / scopes / preamble / search of
# memory-tool.sh. Sourced, never executed.

# Directory listing: depth-2, sizes, excluding dotfiles and node_modules.
# Usage: _view_directory <real> <vpath>
_view_directory() {
  local real="$1" vpath="$2"
  echo "Here're the files and directories up to 2 levels deep in $vpath, excluding hidden items and node_modules:"
  local root_size; root_size=$(human_size "$(du -sk "$real" 2>/dev/null | awk '{print $1*1024}')")
  printf '%s\t%s\n' "$root_size" "$vpath"
  # Build listing with find, 2 levels deep, exclude hidden + node_modules.
  find "$real" -mindepth 1 -maxdepth 2 \
    \( -name '.*' -o -name 'node_modules' \) -prune -o -print 2>/dev/null \
    | sort \
    | while IFS= read -r entry; do
        [[ -z "$entry" ]] && continue
        local rel="${entry#$real/}"
        local display="$vpath/$rel"
        local bytes
        if [[ -d "$entry" ]]; then
          bytes=$(du -sk "$entry" 2>/dev/null | awk '{print $1*1024}')
        else
          bytes=$(wc -c < "$entry" 2>/dev/null || echo 0)
        fi
        printf '%s\t%s\n' "$(human_size "$bytes")" "$display"
      done
}

cmd_view() {
  local vpath="$1" range_start="${2:-}" range_end="${3:-}"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  _acl_guard "$scope" read "view" "$vpath"
  if [[ ! -e "$real" ]]; then
    echo "The path $vpath does not exist. Please provide a valid path."
    exit 1
  fi
  if [[ -d "$real" ]]; then
    _view_directory "$real" "$vpath"
    audit "view" "$vpath" 0 ok
    return 0
  fi

  # File view
  local total_lines; total_lines=$(awk 'END{print NR}' "$real")
  if (( total_lines > MEMORY_MAX_LINES )); then
    echo "File $vpath exceeds maximum line limit of 999,999 lines."
    exit 1
  fi
  echo "Here's the content of $vpath with line numbers:"
  local start=1 end="$total_lines"
  if [[ -n "$range_start" ]]; then start="$range_start"; fi
  if [[ -n "$range_end" ]]; then end="$range_end"; fi
  awk -v s="$start" -v e="$end" 'NR>=s && NR<=e { printf "%6d\t%s\n", NR, $0 }' "$real"
  audit "view" "$vpath" "$(wc -c < "$real")" ok
}

# R6 — print the CAS token (sha256 of current content) for a file.
cmd_sha() {
  local vpath="$1"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  _acl_guard "$scope" read "sha" "$vpath"
  if [[ ! -f "$real" ]]; then
    echo "Error: The path $vpath does not exist. Please provide a valid path."
    audit "sha" "$vpath" 0 missing
    exit 1
  fi
  sha256_of < "$real"
  audit "sha" "$vpath" "$(wc -c < "$real")" ok
}

cmd_scopes() {
  # Per-scope summary: name, file count, total bytes, access role of current agent.
  # No file contents. Safe to auto-inject at spawn.
  # Emptiness test by glob rather than `ls | grep` (SC2010): a plain * already
  # skips dotfiles, which is what the old `ls -A ... | grep -v '^\.'` pipeline
  # was doing, and it survives scope names containing whitespace or newlines.
  local entry has_entry=0
  for entry in "$MEMORY_ROOT"/*; do
    if [[ -e "$entry" || -L "$entry" ]]; then has_entry=1; break; fi
  done
  if [[ ! -d "$MEMORY_ROOT" ]] || [[ "$has_entry" -eq 0 ]]; then
    echo "(memory is empty — use 'memory-tool.sh create /memories/<scope>/<file> <text>' to start)"
    return 0
  fi
  printf '%-20s %8s %8s  %s\n' "SCOPE" "FILES" "BYTES" "ACCESS"
  # One python process computes every scope's counts and access (see
  # lib/memory_acl.py); the glob loop only fixes the listing order.
  local -a dirs=() scopes=()
  local d scope
  for d in "$MEMORY_ROOT"/*/; do
    [[ -d "$d" ]] || continue
    scope="$(basename -- "$d")"
    [[ "$scope" == "_"* ]] && continue
    [[ "$scope" == .* ]] && continue
    dirs+=("$d"); scopes+=("$scope")
  done
  [[ "${#dirs[@]}" -eq 0 ]] && return 0
  local registry="$MEMORY_REGISTRY"
  if [[ -n "${MEMORY_NO_ACL:-}" || ! -f "$MEMORY_REGISTRY" ]]; then registry=""; fi
  local stats i=0 files bytes access
  stats="$(python3 "$_script_dir/lib/memory_acl.py" scopes "$registry" "$MEMORY_AGENT_ID" "${dirs[@]}")"
  while IFS=$'\t' read -r files bytes access; do
    printf '%-20s %8s %8s  %s\n' "/memories/${scopes[$i]}" "$files" "$(human_size "${bytes:-0}")" "$access"
    i=$((i + 1))
  done <<<"$stats"
}

cmd_preamble() {
  # Emit the Anthropic memory-tool system-prompt preamble verbatim, so agent
  # definitions can include it at spawn. Matches the spec at
  # platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool.
  cat <<'EOF'
IMPORTANT: ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE.
MEMORY PROTOCOL:
1. Use the `view` command of your `memory` tool to check for earlier progress.
2. ... (work on the task) ...
     - As you make progress, record status / progress / thoughts etc in your memory.
ASSUME INTERRUPTION: Your context window might be reset at any moment, so you risk losing any progress that is not recorded in your memory directory.

Local extension: use `search <query>` for deterministic full-text retrieval
across scopes; use `cortex:recall` (MCP) for semantic similarity.
Memory lives under /memories/<scope>/<file>. Scope ACL is enforced — write
attempts outside your declared scope are rejected. Quarantine memories
(/memories/quarantine/) are NEVER auto-loaded.
EOF
}

# Parses the search arguments into the caller's locals query, scope_filter,
# limit and mode (bash locals are dynamically scoped).
_search_parse_args() {
  while (( $# )); do
    case "$1" in
      --scope) scope_filter="$2"; shift 2 ;;
      --limit) limit="$2"; shift 2 ;;
      --regex) mode="regex"; shift ;;
      --) shift; query="$*"; break ;;
      *) [[ -z "$query" ]] && query="$1" || query="$query $1"; shift ;;
    esac
  done
}

# Prints the raw grep/rg matches of <query> under <root>.
# Usage: _search_grep <query> <root> <limit> <fixed|regex>
_search_grep() {
  local query="$1" search_root="$2" limit="$3" mode="$4"
  # Pick the best available grepper.
  local grepper=()
  if command -v rg >/dev/null 2>&1; then
    grepper=(rg --no-heading --line-number --color=never --max-count="$limit")
    [[ "$mode" == "fixed" ]] && grepper+=(--fixed-strings)
  else
    grepper=(grep -r -n --color=never)
    [[ "$mode" == "fixed" ]] && grepper+=(-F) || grepper+=(-E)
  fi

  # Exclude control files and locks.
  local excludes=("--exclude-dir=.locks" "--exclude=.audit.log" "--exclude=.registry.json")
  if [[ "${grepper[0]}" == "rg" ]]; then
    excludes=("--glob=!.locks/**" "--glob=!.audit.log" "--glob=!.registry.json")
  fi
  "${grepper[@]}" "${excludes[@]}" -- "$query" "$search_root" 2>/dev/null || true
}

# Rewrites absolute FS paths back to /memories/... virtual paths and enforces
# the per-file read ACL (a match inside an unreadable scope must not leak).
# Prints at most <limit> "<vpath>:<rest>" lines. Usage: _search_visible <raw> <limit>
_search_visible() {
  local raw_matches="$1" limit="$2"
  local hits=0
  local real_root; real_root="$(cd "$MEMORY_ROOT" && pwd -P)"
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local path="${line%%:*}"
    local rest="${line#*:}"
    # Canonicalize path and convert to /memories/...
    local canon; canon="$(cd "$(dirname -- "$path")" 2>/dev/null && pwd -P)/$(basename -- "$path")" || continue
    case "$canon" in
      "$real_root"/*) : ;;
      *) continue ;;
    esac
    local vp="/memories${canon#$real_root}"
    local scope; scope="$(scope_of "$vp")"
    [[ "$(acl_check "$scope" read)" == "allow" ]] || continue
    printf '%s\n' "${vp}:${rest}"
    hits=$((hits + 1))
    (( hits >= limit )) && break
  done <<< "$raw_matches"
  return 0
}

cmd_search() {
  # Deterministic full-text search. Returns <vpath>:<line>:<snippet> per match.
  # Respects readers ACL: files in scopes the agent cannot read are skipped.
  local query="" scope_filter="" limit=50
  local mode="fixed"   # fixed = literal string; regex = extended regex
  _search_parse_args "$@"
  if [[ -z "$query" ]]; then
    echo "Error: search requires a query string"
    exit 1
  fi

  # Determine search root.
  local search_root="$MEMORY_ROOT"
  if [[ -n "$scope_filter" ]]; then
    local scope_real="$MEMORY_ROOT/$scope_filter"
    if [[ ! -d "$scope_real" ]]; then
      echo "The path /memories/$scope_filter does not exist. Please provide a valid path."
      exit 1
    fi
    _acl_guard "$scope_filter" read "search" "/memories/$scope_filter"
    search_root="$scope_real"
  fi

  local where="/memories${scope_filter:+/$scope_filter}"
  local raw_matches; raw_matches=$(_search_grep "$query" "$search_root" "$limit" "$mode")
  if [[ -z "$raw_matches" ]]; then
    echo "No matches for query in $where."
    audit "search" "$where" 0 no_match
    return 0
  fi

  local match_out; match_out=$(_search_visible "$raw_matches" "$limit")
  if [[ -z "$match_out" ]]; then
    echo "No matches for query in $where."
    audit "search" "$where" 0 acl_filtered
    return 0
  fi
  printf '%s\n' "$match_out"
  audit "search" "$where" "$(printf '%s\n' "$match_out" | wc -l | tr -d ' ')" ok
}

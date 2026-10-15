# shellcheck shell=bash
# shellcheck disable=SC2154  # globals assigned by tools/memory-tool.sh before sourcing
# memory-pii.sh — PII / secret scan of memory-tool.sh. Sourced, never executed.
# Expects MEMORY_ROOT, _script_dir and audit from memory-guards.sh.

# ─── PII / secret scan (contract §7.2) ───────────────────────────────────────
# Env:
#   MEMORY_PII_SCAN_DISABLE=1  — bypass entirely (test/emergency)
#   MEMORY_PII_STRICT=1        — also block low-confidence classes (email, phone)
# On scanner error: prints "pii_scan_error" (caller allows write — not a DoS vector).
# INVARIANT: matched bytes are NEVER written to any file or log — only rule IDs.
#
# Performance architecture (profile-driven, 2026-04-24):
#   Profiling showed Python cold-start = 37 ms; scan logic = 1.3 ms on 10 KB.
#   Solution: pii-daemon.py (persistent Python process) listens on a Unix-domain
#   socket.  _pii_scan_pipe sends one JSON request via `nc -U` (~4.6 ms median).
#   Cold-start is paid once at daemon launch, not per write.
#   Fallback: if the daemon is unavailable, fall back to the original per-call
#   python3 subprocess so correctness is never sacrificed for performance.
#   Source: memory/pii-profile.md

# _pii_daemon_sock — path to the Unix socket for the running daemon (if any).
# Co-located with MEMORY_ROOT so each root gets its own daemon.
_pii_daemon_sock() {
  printf '%s' "$MEMORY_ROOT/.pii-daemon.sock"
}
_pii_daemon_pid_file() {
  printf '%s' "$MEMORY_ROOT/.pii-daemon.sock.pid"
}

# _pii_daemon_ensure — start the daemon if its socket is absent or its PID is dead.
# Returns 0 if the daemon is ready (socket exists), 1 if it could not be started.
_pii_daemon_ensure() {
  local _tool_dir="$_script_dir"
  local daemon_py="$_tool_dir/../memory/pii-daemon.py"
  local rules_file="$_tool_dir/../memory/pii-rules.json"
  local sock; sock="$(_pii_daemon_sock)"
  local pid_file; pid_file="$(_pii_daemon_pid_file)"

  if [[ ! -f "$daemon_py" || ! -f "$rules_file" ]]; then return 1; fi

  # Check if daemon is already running: socket exists AND pid file contains a
  # live PID.  If the PID is dead (SIGKILL etc.) we clean up and restart.
  if [[ -S "$sock" && -f "$pid_file" ]]; then
    local saved_pid; saved_pid="$(cat "$pid_file" 2>/dev/null)"
    if [[ -n "$saved_pid" ]] && kill -0 "$saved_pid" 2>/dev/null; then
      return 0  # daemon is live
    fi
    # Stale socket — clean up before restarting.
    rm -f "$sock" "$pid_file"
  fi

  # Start daemon in background, daemonised from this shell's process group so
  # it outlives the memory-tool.sh invocation.
  # MEMORY_ROOT must be exported for the daemon to find rules via $MEMORY_ROOT
  # if it ever needs it; currently the rules path is passed as argv[1].
  export MEMORY_ROOT
  python3 "$daemon_py" "$rules_file" "$sock" </dev/null >/dev/null 2>/dev/null &
  disown $! 2>/dev/null || true

  # Wait up to 1 s for the socket to appear (daemon startup is ~30 ms).
  local i=0
  while (( i < 20 )); do
    [[ -S "$sock" ]] && return 0
    sleep 0.05
    i=$((i + 1))
  done
  return 1  # daemon failed to start in time; caller falls back
}

# _pii_scan_via_daemon — send content to the running daemon, return its response.
# Returns 0 and prints result; returns 1 if the daemon is unreachable.
#
# WHY sed-based JSON encoding (not python3):
#   Spawning python3 for encoding costs ~32 ms (cold-start) — negating the
#   daemon's benefit.  sed is a C process that starts in ~2 ms.  The chars that
#   require JSON escaping in practice are backslash, double-quote, and newline.
#   sed handles all three via three substitution expressions plus the N-loop
#   accumulate-and-replace trick for newlines.  Control chars (0x00–0x1F) are
#   rare in memory entries; if an unencoded control char slips through, the
#   daemon's json.loads raises, returns "pii_scan_error", and the write is
#   allowed (fail-open per §7.2 contract) — not a correctness violation.
#
# CORRECTNESS invariant: incorrect encoding → pii_scan_error → write allowed.
# The correctness direction is: false allow (never false block).
_pii_scan_via_daemon() {
  local content="$1"
  local sock; sock="$(_pii_daemon_sock)"
  local strict="false"
  [[ "${MEMORY_PII_STRICT:-0}" == "1" ]] && strict="true"

  # Encode the content string for JSON embedding.
  # Substitution order matters: backslash must be escaped first to avoid
  # double-escaping the backslashes inserted by later substitutions.
  # Complexity: O(N) in content length.  sed processes the whole content in one
  # pass per substitution; combined with :a;N;$!ba (accumulate all lines into
  # the pattern space) the total work is O(4N).
  local encoded
  encoded=$(printf '%s' "$content" \
    | sed -e 's/\\/\\\\/g' \
          -e 's/"/\\"/g' \
          -e 's/	/\\t/g' \
          -e ':a;N;$!ba;s/\n/\\n/g' \
    2>/dev/null) || return 1

  # Send the JSON request to the daemon; read one response line.
  local response
  response=$(printf '{"content":"%s","strict":%s}\n' "$encoded" "$strict" \
    | nc -U "$sock" 2>/dev/null) || return 1
  [[ -n "$response" ]] || return 1
  printf '%s' "$response"
  return 0
}

# Internal: reads content from stdin, emits "pass" | "blocked:<rule_id>" | "pii_scan_error".
# Primary path: persistent daemon via Unix socket (avoids Python cold-start per call).
# Fallback path: original per-call python3 subprocess (used if daemon unavailable).
_pii_scan_pipe() {
  local _tool_dir="$_script_dir"
  local scanner_py="$_tool_dir/../memory/pii-scanner.py"
  local rules_file="$_tool_dir/../memory/pii-rules.json"
  if [[ ! -f "$scanner_py" || ! -f "$rules_file" ]]; then printf 'pii_scan_error'; return 0; fi
  if [[ -n "${MEMORY_PII_SCAN_DISABLE:-}" ]]; then printf 'pii_scan_disabled'; return 0; fi

  # Read stdin into a variable (content is already in memory in the caller,
  # but _pii_scan_pipe receives it via pipe from _pii_gate).
  local content; content="$(cat)"

  # Primary path: daemon.
  if _pii_daemon_ensure 2>/dev/null; then
    local daemon_result
    daemon_result="$(_pii_scan_via_daemon "$content" 2>/dev/null)"
    if [[ -n "$daemon_result" ]]; then
      printf '%s' "$daemon_result"
      return 0
    fi
    # Daemon returned empty — fall through to subprocess fallback.
  fi

  # Fallback path: original per-call subprocess (preserves all contract
  # semantics if daemon is unavailable or returns garbage).
  printf '%s' "$content" | python3 "$scanner_py" "$rules_file" "${MEMORY_PII_STRICT:-0}" 2>/dev/null \
    || { printf 'pii_scan_error'; return 0; }
}

# Apply PII gate to new content before any write.
# Usage: _pii_gate <content> <cmd> <vpath> <bytes>
# Exits 1 with user-facing error on block; returns 0 on pass or scanner error.
_pii_gate() {
  local content="$1" cmd="$2" vpath="$3" bytes="$4"
  local result; result="$(printf '%s' "$content" | _pii_scan_pipe)"
  case "$result" in
    pass|pii_scan_disabled) return 0 ;;
    pii_scan_error)
      audit "$cmd" "$vpath" "$bytes" "pii_scan_error"
      return 0
      ;;
    blocked:*)
      local rule_id="${result#blocked:}"
      audit "$cmd" "$vpath" "$bytes" "pii_blocked:${rule_id}"
      echo "Error: write blocked by PII/secret scanner (matched rule: ${rule_id}). Remove sensitive content before writing."
      exit 1
      ;;
  esac
}

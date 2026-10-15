# shellcheck shell=bash
# session-sections.sh — the boot sections of session-start.sh, one function each.
# Sourced by hooks/lib/run_sections.py, which runs every section in its own
# process group under a hard time budget; nothing here needs its own time-box.
# Expects TOOLS, REPO_ROOT and the colour variables exported by session-start.sh.

# Plugin currency (issue #52). Silent when current and warn-only: a boot check
# that can fail a session is a check that gets disabled.
section_currency() {
  [[ -x "$TOOLS/plugin-version-check.sh" ]] || return 0
  local report
  report="$("$TOOLS/plugin-version-check.sh" 2>/dev/null || true)"
  if [[ -n "$report" ]]; then
    echo -e "${WHITE}${BOLD}  ◆ Plugin Currency${RESET}"
    echo "$report" | sed 's/^/  /'
    echo ""
  fi
}

section_books() {
  echo -e "${WHITE}${BOLD}  ◆ Difficulty Books${RESET}"
  "$TOOLS/difficulty-book-manager.sh" status 2>/dev/null || echo "  (none)"
  echo ""
}

# Memory directory: scopes listing only. No content injection (Taleb: avoid
# scope-wide auto-load; agents call `view` explicitly on names they need).
section_memory() {
  [[ -x "$TOOLS/memory-tool.sh" ]] || return 0
  local sync_line
  echo -e "${WHITE}${BOLD}  ◆ Memory Scopes${RESET}"
  MEMORY_AGENT_ID="${MEMORY_AGENT_ID:-_user}" "$TOOLS/memory-tool.sh" scopes 2>/dev/null \
    | sed 's/^/  /' || echo "  (memory-tool unavailable)"
  # Show Cortex replica queue depth if non-empty — reminds agent to drain.
  sync_line="$(MEMORY_AGENT_ID="${MEMORY_AGENT_ID:-_user}" "$TOOLS/memory-tool.sh" sync-status 2>/dev/null | head -1 || true)"
  if [[ "$sync_line" == *"pending"* && "$sync_line" != "queue: 0 pending,"* && "$sync_line" != "queue: empty"* ]]; then
    echo ""
    echo -e "${SUBTLE}  Cortex replica ${sync_line} — run /session:memory-sync to drain.${RESET}"
  fi
  echo ""
  echo -e "${SUBTLE}  Memory protocol: call \`view /memories/<scope>/<file>\` to read; never rely on prior context.${RESET}"
  echo ""
}

section_worktrees() {
  echo -e "${WHITE}${BOLD}  ◆ Agent Worktrees${RESET}"
  "$TOOLS/worktree-manager.sh" list 2>/dev/null || echo "  (none)"
  echo ""
  echo -e "${WHITE}${BOLD}  ◆ Worktree Sweep${RESET}"
  if [[ -x "$TOOLS/worktree-manager.sh" ]]; then
    # No --fetch at boot (no network). Scoped to REPO_ROOT only (issue #33):
    # the no-args form sweeps every sibling repo. Warn-only, never blocks.
    "$TOOLS/worktree-manager.sh" sweep "$REPO_ROOT" 2>/dev/null | sed 's/^/  /' || true
  else
    echo "  (worktree-manager unavailable)"
  fi
  echo ""
}

section_symlinks() {
  echo -e "${WHITE}${BOLD}  ◆ Dev Symlink Montage${RESET}"
  if [[ -x "$TOOLS/dev-symlink-doctor.sh" ]]; then
    "$TOOLS/dev-symlink-doctor.sh" 2>/dev/null | sed 's/^/  /' || true
  else
    echo "  (dev-symlink-doctor unavailable)"
  fi
  echo ""
}

section_cache() {
  echo -e "${WHITE}${BOLD}  ◆ Session Cache${RESET}"
  "$TOOLS/session-store.sh" load 2>/dev/null || echo "  (no cached session)"
  echo ""
}

# shellcheck shell=bash
# lib/state.sh — every state file the plugin owns lives under ~/.claude/zetetic/.
# Sourced by setup.sh. Relies on these globals/functions from the caller:
#   CLAUDE_DIR, STATE_DIR, DRY_RUN, PLUGIN_SERVED, manifest_lines (array),
#   step/ok/warn/info.
# Cross-platform: pure bash + cmp/mv; no OS-specific calls.
#
# Why (issue #136, measured 2026-09-10): setup.sh and the tools wrote their
# state flat into ~/.claude (.zetetic-manifest, .zetetic-version,
# zetetic-agent-models.json, worktree-sweep-audit.log, dev-symlink.map,
# dev-symlink.versions, plus the GOA Phase 0 labelling workspaces) and the
# root of ~/.claude held 324 entries. Owner ruling the same day: what a
# plugin leaves on disk is managed by the plugin and readable at a glance.
# A flat install is moved here once (mv, never cp, so the root entries
# disappear); a re-run finds nothing to move and is a no-op.

# Legacy root name -> name under STATE_DIR, one line per entry the plugin
# ever left at the root. The two directories are the GOA Phase 0 labelling
# workspaces docs/goa-phase0/PROTOCOL.md placed there; no script writes them.
# .zetetic-manifest.json was written by the v2.0/v2.1 installer (removed in
# e73213f) and has no reader today; it is moved, not deleted, because it is
# the only record of what that installer copied.
# source: issue #136 inventory of the owner's ~/.claude root, 2026-09-10.
STATE_MIGRATIONS=(
  ".zetetic-manifest|manifest"
  ".zetetic-manifest.json|manifest.json"
  ".zetetic-version|version"
  "zetetic-agent-models.json|agent-models.json"
  "worktree-sweep-audit.log|worktree-sweep-audit.log"
  "dev-symlink.map|dev-symlink.map"
  "dev-symlink.versions|dev-symlink.versions"
  "goa-phase0|goa-phase0"
  "goa-design|goa-design"
)
STATE_MOVED=0

# Moves one legacy root entry into STATE_DIR. Never overwrites: when both
# exist and differ, the audit log is appended (it is append-only by
# contract) and anything else is kept in both places with a warning.
_migrate_one() {
  local old="$1" new="$2" name
  name="$(basename "$old")"
  [[ -e "$old" ]] || return 0
  if [[ ! -e "$new" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
      info "Would move $name -> zetetic/$(basename "$new")"
    else
      mv "$old" "$new" && ok "Moved $name -> zetetic/$(basename "$new")"
    fi
    STATE_MOVED=$((STATE_MOVED + 1))
    return 0
  fi
  if [[ -f "$old" && -f "$new" ]] && cmp -s "$old" "$new"; then
    [[ "$DRY_RUN" == true ]] && { info "Would remove $name (identical copy already in zetetic/)"; return 0; }
    rm -f "$old" && ok "Removed $name (identical copy already in zetetic/)"
    return 0
  fi
  if [[ "$name" == "worktree-sweep-audit.log" && -f "$old" && -f "$new" ]]; then
    [[ "$DRY_RUN" == true ]] && { info "Would append $name to zetetic/$name"; return 0; }
    cat "$old" >> "$new" && rm -f "$old" && ok "Appended $name to zetetic/$name"
    return 0
  fi
  warn "Kept both: $old differs from $new (merge by hand, nothing was overwritten)"
}

# Moves every legacy root entry into STATE_DIR. Idempotent: a second run
# finds nothing at the root and reports so.
migrate_flat_state() {
  step "State layout"
  STATE_MOVED=0
  [[ "$DRY_RUN" == true ]] || mkdir -p "$STATE_DIR"
  local pair old bak
  for pair in "${STATE_MIGRATIONS[@]}"; do
    _migrate_one "${CLAUDE_DIR}/${pair%%|*}" "${STATE_DIR}/${pair#*|}"
  done
  for bak in "${CLAUDE_DIR}"/dev-symlink.map.bak-*; do
    [[ -e "$bak" ]] || continue
    _migrate_one "$bak" "${STATE_DIR}/$(basename "$bak")"
  done
  if [[ "$STATE_MOVED" -gt 0 ]]; then
    ok "$STATE_MOVED entries moved from the root of ~/.claude into ~/.claude/zetetic/"
  else
    ok "Plugin state lives under ~/.claude/zetetic/ (nothing flat at the root)"
  fi
}

# Prints the legacy names still present at the root, one per line.
legacy_state_at_root() {
  local pair old
  for pair in "${STATE_MIGRATIONS[@]}"; do
    old="${CLAUDE_DIR}/${pair%%|*}"
    [[ -e "$old" ]] && echo "$old"
  done
  for old in "${CLAUDE_DIR}"/dev-symlink.map.bak-*; do
    [[ -e "$old" ]] && echo "$old"
  done
  return 0
}

# One line per entry of STATE_DIR: name, then size in lines (file) or
# entries (directory).
_print_state_entries() {
  local entry name n found=false
  for entry in "$STATE_DIR"/* "$STATE_DIR"/.[!.]*; do
    [[ -e "$entry" ]] || continue
    found=true
    name="$(basename "$entry")"
    if [[ -d "$entry" ]]; then
      n="$(find "$entry" -mindepth 1 2>/dev/null | wc -l | tr -d ' ')"
      printf '    %-32s %s entries\n' "$name/" "$n"
    else
      n="$(wc -l < "$entry" | tr -d ' ')"
      printf '    %-32s %s lines\n' "$name" "$n"
    fi
  done
  [[ "$found" == true ]] || info "  (empty)"
}

# One line per staged tree with the number of files the manifest tracks in it.
_print_staged_trees() {
  local tree n entry
  for tree in agents skills commands hooks tools reference; do
    n=0
    # shellcheck disable=SC2154  # manifest_lines is filled by lib/staging.sh
    for entry in "${manifest_lines[@]}"; do
      [[ "${entry#*  }" == "$tree/"* ]] && n=$((n + 1))
    done
    if [[ "$n" -eq 0 && "$PLUGIN_SERVED" == true && ( "$tree" == agents || "$tree" == skills ) ]]; then
      printf '    ~/.claude/%-22s served by the marketplace plugin, not copied\n' "$tree/"
    elif [[ "$n" -gt 0 ]]; then
      printf '    ~/.claude/%-22s %s files\n' "$tree/" "$n"
    fi
  done
}

# The closing report: what the plugin put where, readable at a glance.
print_layout() {
  step "Layout"
  info "Plugin state, ~/.claude/zetetic/:"
  _print_state_entries
  echo ""
  info "Staged trees (Claude Code conventions, tracked in zetetic/manifest):"
  _print_staged_trees
  local leftover
  leftover="$(legacy_state_at_root)"
  [[ -z "$leftover" ]] || warn "Still at the root of ~/.claude (see the State layout step above):"$'\n'"$leftover"
}

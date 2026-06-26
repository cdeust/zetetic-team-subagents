# lib/actions.sh — uninstall + configure actions for setup.sh.
# Sourced by setup.sh. Relies on these globals/functions from the caller:
#   MANIFEST, VERSION_FILE, MODEL_CONFIG, CLAUDE_DIR, PLUGIN_ROOT, DRY_RUN,
#   BACKUP_SUFFIX, colors (GREEN/CYAN/NC), step/ok/warn/info, sha_cmd().
# Cross-platform: pure bash + python3 (probed); no OS-specific calls.

# ── Uninstall ──────────────────────────────────────────────────────────
UNINSTALL_REMOVED=0
UNINSTALL_SKIPPED=0

# Remove manifest-tracked files, preserving user-modified ones.
_uninstall_remove_tracked() {
  UNINSTALL_REMOVED=0
  UNINSTALL_SKIPPED=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local expected_hash="${line%%  *}"
    local rel_path="${line#*  }"
    local target="${CLAUDE_DIR}/${rel_path}"
    [[ ! -f "$target" ]] && continue

    # Skip user-modified files
    local current_hash; current_hash="$(sha_cmd "$target")"
    if [[ "$expected_hash" != "no-checksum" && "$current_hash" != "$expected_hash" ]]; then
      if [[ "$DRY_RUN" == true ]]; then
        info "Would keep (user-modified): $rel_path"
      else
        warn "Keeping user-modified: $rel_path"
        UNINSTALL_SKIPPED=$((UNINSTALL_SKIPPED + 1))
      fi
      continue
    fi

    if [[ "$DRY_RUN" == true ]]; then
      info "Would remove: $rel_path"
    else
      rm "$target"
    fi
    UNINSTALL_REMOVED=$((UNINSTALL_REMOVED + 1))
  done < "$MANIFEST"
}

# Clean empty dirs, restore backups, strip hooks from plugin.json, drop state.
_uninstall_cleanup() {
  [[ "$DRY_RUN" == false ]] || return
  find "${CLAUDE_DIR}/agents/genius" -type d -empty -delete 2>/dev/null || true
  for subdir in skills commands hooks tools rules; do
    find "${CLAUDE_DIR}/${subdir}" -mindepth 1 -type d -empty -delete 2>/dev/null || true
  done

  # Restore backups
  local restored=0
  while IFS= read -r backup; do
    [[ -z "$backup" ]] && continue
    local original="${backup%${BACKUP_SUFFIX}}"
    mv "$backup" "$original" && restored=$((restored + 1))
  done < <(find "$CLAUDE_DIR" -name "*${BACKUP_SUFFIX}" -type f 2>/dev/null)
  [[ "$restored" -gt 0 ]] && ok "Restored $restored user-modified files from backup"

  # Remove hooks from plugin.json
  local plugin_json="$PLUGIN_ROOT/.claude-plugin/plugin.json"
  if [[ -f "$plugin_json" ]] && command -v python3 &>/dev/null && grep -q '"hooks"' "$plugin_json"; then
    python3 -c "
import json
with open('$plugin_json') as f: d = json.load(f)
d.pop('hooks', None)
with open('$plugin_json', 'w') as f: json.dump(d, f, indent=2); f.write('\n')
" 2>/dev/null && ok "Removed hooks from plugin.json" || warn "Could not clean plugin.json"
  fi

  rm -f "$MANIFEST" "$VERSION_FILE"
}

do_uninstall() {
  step "Uninstalling Zetetic Team Subagents"

  if [[ ! -f "$MANIFEST" ]]; then
    warn "No manifest found — nothing to uninstall"
    warn "If files remain, remove manually from ~/.claude/agents/, skills/, commands/"
    return
  fi

  _uninstall_remove_tracked
  _uninstall_cleanup

  ok "Removed $UNINSTALL_REMOVED files"
  [[ "$UNINSTALL_SKIPPED" -gt 0 ]] && ok "Kept $UNINSTALL_SKIPPED user-modified files"
  echo ""
  echo -e "${GREEN}Uninstall complete.${NC} Restart Claude Code to deactivate."
}

# ── Configure (model overrides) ────────────────────────────────────────
# Write the default override config template to $MODEL_CONFIG.
_write_model_config() {
  cat > "$MODEL_CONFIG" <<'CONF'
{
  "//": "Zetetic Agent Overrides (model + effort) — survives plugin updates",
  "//models": "opus (most capable), sonnet (balanced), haiku (fastest/cheapest)",
  "//effort": "low (terse procedural), medium (balanced), high (deep reasoning), max (opus 4.6 only)",
  "//schema": "string value = model shorthand; object value = {model?, effort?}. Either field may be omitted to keep the frontmatter default.",
  "//precedence": "per-call > this config > agent frontmatter default",

  "patterns": [
    { "glob": "genius/*", "model": "sonnet" }
  ],

  "agents": {
    "refactorer":        { "model": "haiku",  "effort": "low"    },
    "latex-engineer":    { "model": "haiku",  "effort": "low"    },

    "engineer":          { "model": "sonnet", "effort": "medium" },
    "code-reviewer":     { "model": "sonnet", "effort": "medium" },
    "test-engineer":     { "model": "sonnet", "effort": "medium" },
    "frontend-engineer": { "model": "sonnet", "effort": "medium" },
    "dba":               { "model": "sonnet", "effort": "medium" },
    "devops-engineer":   { "model": "sonnet", "effort": "medium" },
    "data-scientist":    { "model": "sonnet", "effort": "medium" },
    "experiment-runner": { "model": "sonnet", "effort": "medium" },
    "mlops":             { "model": "sonnet", "effort": "medium" },
    "ux-designer":       { "model": "sonnet", "effort": "medium" },
    "professor":         { "model": "sonnet", "effort": "medium" },

    "architect":          { "model": "opus", "effort": "high" },
    "orchestrator":       { "model": "opus", "effort": "medium" },
    "security-auditor":   { "model": "opus", "effort": "high" },
    "research-scientist": { "model": "opus", "effort": "high" },
    "paper-writer":       { "model": "opus", "effort": "high" },
    "reviewer-academic":  { "model": "opus", "effort": "high" }
  }
}
CONF
}

# Print the post-creation help text for the override config.
_print_config_help() {
  echo ""
  echo "  Default config (model + effort):"
  echo "    - refactorer, latex-engineer          → haiku  + low     (mechanical)"
  echo "    - most team agents                     → sonnet + medium  (balanced)"
  echo "    - architect, security, research roles  → opus   + high    (deep)"
  echo "    - 97 genius agents                     → sonnet (effort kept from frontmatter:"
  echo "                                              deep-reasoning geniuses default to high,"
  echo "                                              procedural geniuses default to medium)"
  echo ""
  echo -e "  Edit to customize, then run ${CYAN}$0 update${NC} to apply."
  echo "  Config is yours — plugin updates leave it untouched."
  echo ""
  echo "  Schema notes:"
  echo "    - String value ('sonnet') = model shorthand; effort unchanged"
  echo "    - Object value { model, effort } = set either or both"
  echo "    - Omit a field to keep the frontmatter default"
}

do_configure() {
  step "Agent override configuration (model + effort)"

  if [[ -f "$MODEL_CONFIG" ]]; then
    info "Existing config: $MODEL_CONFIG"
    echo ""
    cat "$MODEL_CONFIG"
    echo ""
    echo -e "  Edit this file directly, then run ${CYAN}$0 update${NC} to apply."
    echo "  To reset: rm $MODEL_CONFIG && $0 configure"
    return
  fi

  _write_model_config
  ok "Created $MODEL_CONFIG"
  _print_config_help
}

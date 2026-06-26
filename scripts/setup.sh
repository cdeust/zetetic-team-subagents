#!/usr/bin/env bash
# setup.sh — Install zetetic-team-subagents into ~/.claude/
#
# Copies agents, skills, and commands to the Claude Code user directory.
# Merges hooks into plugin.json, applies per-agent model overrides, checks
# external dependencies, tracks installed files via manifest for idempotent
# updates and clean uninstall.
#
# Usage:
#   bash scripts/setup.sh [install|update|uninstall|configure] [--dry-run] [--verbose]

set -euo pipefail

# ── Path resolution ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}"
CLAUDE_DIR="${HOME}/.claude"
MANIFEST="${CLAUDE_DIR}/.zetetic-manifest"
VERSION_FILE="${CLAUDE_DIR}/.zetetic-version"
MODEL_CONFIG="${CLAUDE_DIR}/zetetic-agent-models.json"
BACKUP_SUFFIX=".zetetic-backup"

# ── Colors ─────────────────────────────────────────────────────────────
TEAL="\033[1;38;2;127;187;179m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
WHITE="\033[38;2;224;224;224m"
BOLD="\033[1m"
NC="\033[0m"

ok()   { echo -e "  ${GREEN}[ok]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[!!]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; exit 1; }
info() { echo -e "  $1"; }
step() { echo ""; echo -e "${TEAL}───${NC} ${WHITE}${BOLD}$1${NC} ${TEAL}───${NC}"; }

# ── Sourced modules (lib/) ─────────────────────────────────────────────
# Behavior-preserving split for coding-standards §4 (file/function size).
# shellcheck source=/dev/null
for _mod in overrides staging actions; do source "$SCRIPT_DIR/lib/${_mod}.sh"; done

# ── Flag parsing ───────────────────────────────────────────────────────
ACTION="install"
DRY_RUN=false
VERBOSE=false

ARGS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=true ;;
    --verbose)   VERBOSE=true ;;
    --uninstall) ACTION="uninstall" ;;
    -h|--help)
      sed -n '2,/^$/s/^# \?//p' "$0"
      exit 0 ;;
    *) ARGS+=("$arg") ;;
  esac
done
[[ ${#ARGS[@]} -gt 0 ]] && ACTION="${ARGS[0]}"

[[ "$VERBOSE" == true ]] && set -x

# ── Helpers ────────────────────────────────────────────────────────────
sha_cmd() {
  if command -v shasum &>/dev/null; then
    shasum -a 256 "$1" | cut -d' ' -f1
  elif command -v sha256sum &>/dev/null; then
    sha256sum "$1" | cut -d' ' -f1
  else
    echo "no-checksum"
  fi
}

read_version() {
  local pjson="$PLUGIN_ROOT/.claude-plugin/plugin.json"
  [[ ! -f "$pjson" ]] && pjson="$PLUGIN_ROOT/plugin.json"
  [[ ! -f "$pjson" ]] && { echo "unknown"; return; }
  if command -v jq &>/dev/null; then
    jq -r '.version // "unknown"' "$pjson"
  else
    grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$pjson" | head -1 | sed 's/.*"\([^"]*\)"/\1/'
  fi
}

# ── Install dispatch guards ────────────────────────────────────────────
case "$ACTION" in
  uninstall)  do_uninstall; exit 0 ;;
  configure)  do_configure; exit 0 ;;
  install|update) ;;
  *) echo "usage: $0 [install|update|uninstall|configure] [--dry-run] [--verbose]" >&2; exit 2 ;;
esac

# ── Banner ─────────────────────────────────────────────────────────────
PLUGIN_VERSION="$(read_version)"

echo ""
echo -e "${TEAL}  ███████╗███████╗████████╗███████╗████████╗██╗ ██████╗${NC}"
echo -e "${TEAL}  ╚══███╔╝██╔════╝╚══██╔══╝██╔════╝╚══██╔══╝██║██╔════╝${NC}"
echo -e "${TEAL}    ███╔╝ █████╗     ██║   █████╗     ██║   ██║██║     ${NC}"
echo -e "${TEAL}   ███╔╝  ██╔══╝     ██║   ██╔══╝     ██║   ██║██║     ${NC}"
echo -e "${TEAL}  ███████╗███████╗   ██║   ███████╗   ██║   ██║╚██████╗${NC}"
echo -e "${TEAL}  ╚══════╝╚══════╝   ╚═╝   ╚══════╝   ╚═╝   ╚═╝ ╚═════╝${NC}"
echo ""
echo -e "  ${WHITE}${BOLD}Setup v${PLUGIN_VERSION}${NC}"
echo ""

# ── Prerequisites ──────────────────────────────────────────────────────
step "Prerequisites"

[[ -d "$CLAUDE_DIR" ]] || fail "~/.claude/ does not exist. Is Claude Code installed?"
[[ -w "$CLAUDE_DIR" ]] || fail "~/.claude/ is not writable"
ok "Claude Code directory exists"

# ── Version gate ───────────────────────────────────────────────────────
step "Version check"

if [[ -f "$VERSION_FILE" ]]; then
  INSTALLED_VERSION="$(cat "$VERSION_FILE")"
  if [[ "$INSTALLED_VERSION" == "$PLUGIN_VERSION" ]]; then
    ok "Version $PLUGIN_VERSION already installed — reinstalling"
  elif [[ "$INSTALLED_VERSION" > "$PLUGIN_VERSION" ]]; then
    warn "Downgrade detected: $INSTALLED_VERSION → $PLUGIN_VERSION"
  else
    ok "Upgrading: $INSTALLED_VERSION → $PLUGIN_VERSION"
  fi
else
  ok "Fresh install: $PLUGIN_VERSION"
fi

# ── Load model overrides ───────────────────────────────────────────────
step "Model overrides"
load_model_overrides
[[ "$OVERRIDES_LOADED" == true && -z "$OVERRIDES_AGENTS$OVERRIDES_PATTERNS" ]] && \
  info "No overrides — using agent frontmatter defaults (run '$0 configure' to customize)"

# ── Stage files to temp directory (atomic copy) ────────────────────────
step "Staging"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

manifest_lines=()
count_agents=0
count_genius=0
count_skills=0
count_commands=0
count_hooks=0
count_tools=0
count_rules=0
count_overridden=0

stage_tree "$PLUGIN_ROOT/agents"   "agents"   true  _n; count_agents=$_n
# Count genius agents separately for reporting
count_genius=$(find "$STAGING/agents/genius" -name "*.md" -not -name "INDEX.md" 2>/dev/null | wc -l | tr -d ' ')
count_agents=$((count_agents - count_genius))

stage_tree "$PLUGIN_ROOT/skills"   "skills"   false _n; count_skills=$_n
stage_tree "$PLUGIN_ROOT/commands" "commands" false _n; count_commands=$_n
stage_tree "$PLUGIN_ROOT/hooks"    "hooks"    false _n; count_hooks=$_n
stage_tree "$PLUGIN_ROOT/tools"    "tools"    false _n; count_tools=$_n
stage_tree "$PLUGIN_ROOT/rules"    "rules"    false _n; count_rules=$_n

ok "Staged: $count_agents team + $count_genius genius agents, $count_skills skills, $count_commands commands, $count_hooks hooks, $count_tools tools, $count_rules rules"
[[ "$count_overridden" -gt 0 ]] && ok "Applied $count_overridden model overrides"

if [[ "$DRY_RUN" == true ]]; then
  echo ""
  echo -e "${YELLOW}Dry run — would install ${#manifest_lines[@]} files to $CLAUDE_DIR${NC}"
  exit 0
fi

# ── Install from staging (backup user-modified files) ──────────────────
step "Installing"

backed_up=0 copied=0 failed=0
for entry in "${manifest_lines[@]}"; do
  rel_path="${entry#*  }"
  target="${CLAUDE_DIR}/${rel_path}"
  target_dir="$(dirname "$target")"
  mkdir -p "$target_dir"

  # Back up user-modified files before overwriting
  if [[ -f "$target" && -f "$MANIFEST" ]]; then
    old_hash=$(grep "  ${rel_path}$" "$MANIFEST" 2>/dev/null | head -1 | cut -d' ' -f1 || true)
    if [[ -n "$old_hash" && "$old_hash" != "no-checksum" ]]; then
      current_hash="$(sha_cmd "$target")"
      if [[ "$current_hash" != "$old_hash" ]]; then
        cp "$target" "${target}${BACKUP_SUFFIX}"
        backed_up=$((backed_up + 1))
      fi
    fi
  fi

  if cp "$STAGING/$rel_path" "$target" 2>/dev/null; then
    copied=$((copied + 1))
    # Preserve executable bit on .sh files
    [[ "$rel_path" == *.sh ]] && chmod +x "$target"
  else
    warn "Failed to copy: $rel_path"
    failed=$((failed + 1))
  fi
done

ok "Copied $copied files to $CLAUDE_DIR"
[[ "$backed_up" -gt 0 ]] && ok "Backed up $backed_up user-modified files (*.zetetic-backup)"
[[ "$failed" -gt 0 ]] && warn "$failed files failed to copy"

# ── Merge hooks into plugin.json (Cortex-style) ────────────────────────
step "Hooks → plugin.json"

plugin_json="$PLUGIN_ROOT/.claude-plugin/plugin.json"
hooks_json="$PLUGIN_ROOT/hooks/hooks.json"

if [[ ! -f "$plugin_json" ]]; then
  warn ".claude-plugin/plugin.json not found — skipping hook merge"
elif [[ ! -f "$hooks_json" ]]; then
  warn "hooks/hooks.json not found — skipping hook merge"
elif ! command -v python3 &>/dev/null; then
  warn "python3 not found — skipping hook merge"
else
  # Content-equality re-sync (hooks.json is authoritative):
  #   - 0 = plugin.json hooks already match hooks.json (timeouts stripped) → skip
  #   - 1 = drift detected (or hooks absent) → re-merge
  #   - 2 = parse/IO error → exit 2 (fail-open: leave plugin.json untouched)
  # This makes hooks.json the single source of truth and prevents merge drift.
  in_sync=$(python3 -c "
import json, sys
try:
    with open('$plugin_json') as f: plugin = json.load(f)
    with open('$hooks_json') as f: hooks_data = json.load(f)
    authoritative = hooks_data.get('hooks', {})
    existing = plugin.get('hooks', {})
    # Strip merge-injected 'timeout' fields from plugin hooks before comparing.
    stripped = {}
    for event, entries in existing.items():
        new_entries = []
        for entry in entries:
            new_entry = {k: v for k, v in entry.items() if k != 'hooks'}
            new_entry['hooks'] = [
                {k: v for k, v in h.items() if k != 'timeout'}
                for h in entry.get('hooks', [])
            ]
            new_entries.append(new_entry)
        stripped[event] = new_entries
    print('0' if stripped == authoritative else '1')
except Exception:
    print('2')
" 2>/dev/null || echo "2")

  if [[ "$in_sync" == "0" ]]; then
    ok "Hooks in plugin.json match hooks.json (source of truth) — skipping"
  elif [[ "$in_sync" == "2" ]]; then
    warn "Could not parse plugin.json/hooks.json — leaving plugin.json untouched"
  else
    cp "$plugin_json" "${plugin_json}.bak.$$"
    if python3 -c "
import json
with open('$plugin_json') as f: plugin = json.load(f)
with open('$hooks_json') as f: hooks_data = json.load(f)
# hooks.json already uses correct nested schema; just add timeouts where missing
plugin_hooks = {}
for event, entries in hooks_data.get('hooks', {}).items():
    for entry in entries:
        for h in entry.get('hooks', []):
            if 'timeout' not in h:
                h['timeout'] = 10 if event in ('SessionStart', 'Stop', 'SessionEnd') else 5
    plugin_hooks[event] = entries
plugin['hooks'] = plugin_hooks
with open('$plugin_json', 'w') as f: json.dump(plugin, f, indent=2); f.write('\n')
print(sum(len(v) for v in plugin_hooks.values()))
" 2>/dev/null; then
      rm -f "${plugin_json}.bak.$$"
      ok "Re-synced hooks into plugin.json from hooks.json (source of truth)"
    else
      mv "${plugin_json}.bak.$$" "$plugin_json"
      warn "Hook re-sync failed — plugin.json restored"
    fi
  fi
fi

# ── Remove orphans from previous installs ──────────────────────────────
step "Orphan cleanup"

orphan_count=0
if [[ -f "$MANIFEST" ]]; then
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    old_path="${line#*  }"
    found=false
    for entry in "${manifest_lines[@]}"; do
      if [[ "${entry#*  }" == "$old_path" ]]; then found=true; break; fi
    done
    if [[ "$found" == false ]]; then
      target="${CLAUDE_DIR}/${old_path}"
      [[ -f "$target" ]] && rm "$target" && orphan_count=$((orphan_count + 1))
    fi
  done < "$MANIFEST"
fi

if [[ "$orphan_count" -gt 0 ]]; then
  ok "Removed $orphan_count orphaned files from previous install"
  find "${CLAUDE_DIR}/agents/genius" -type d -empty -delete 2>/dev/null || true
  for subdir in skills commands hooks tools; do
    find "${CLAUDE_DIR}/${subdir}" -mindepth 1 -type d -empty -delete 2>/dev/null || true
  done
else
  ok "No orphans found"
fi

# ── Write manifest and version ─────────────────────────────────────────
step "Manifest"

if printf '%s\n' "${manifest_lines[@]}" > "$MANIFEST" 2>/dev/null; then
  ok "Manifest written (${#manifest_lines[@]} files tracked)"
else
  warn "Failed to write manifest — uninstall will not work"
fi

if echo "$PLUGIN_VERSION" > "$VERSION_FILE" 2>/dev/null; then
  ok "Version $PLUGIN_VERSION recorded"
else
  warn "Failed to write version file"
fi

# ── Dependency checks (optional) ───────────────────────────────────────
step "Dependencies (optional)"

check_dep() {
  local name="$1" cmd="$2" hint="$3" required="${4:-no}"
  if command -v "$cmd" &>/dev/null; then
    ok "$name"
  elif [[ "$required" == "yes" ]]; then
    fail "$name not found. Install: $hint"
  else
    warn "$name not found (optional). Install: $hint"
  fi
}

check_py_dep() {
  local name="$1" module="$2" hint="$3"
  python3 -c "import $module" 2>/dev/null && ok "$name" || warn "$name not found (optional). Install: $hint"
}

# python3 needs special handling: on Windows, `command -v python3` resolves to
# the Microsoft Store stub (in PATH, but exits non-zero and runs nothing). A
# plain command-v check reports a false "ok". Probe by actually executing it,
# and point Windows users at the `py -3` launcher the hooks fall back to.
check_python3() {
  if command -v python3 &>/dev/null && python3 -c '' &>/dev/null; then
    ok "python3"
  elif command -v py &>/dev/null && py -3 -c '' &>/dev/null; then
    warn "python3 not runnable, but 'py -3' works — Python hooks will use it (run-python.sh)."
  else
    fail "No working Python 3 found. Install from python.org (Windows: ensure 'py -3' works
       and disable the Microsoft Store python/python3 execution aliases)."
  fi
}

check_dep "jq"       "jq"       "brew install jq"                           "yes"
check_dep "git"      "git"      "brew install git / xcode-select --install" "yes"
check_python3
check_dep "Docker"   "docker"   "brew install --cask docker"
check_dep "fswatch"  "fswatch"  "brew install fswatch"
check_dep "entr"     "entr"     "brew install entr"
check_dep "Pandoc"   "pandoc"   "brew install pandoc"
check_dep "pdflatex" "pdflatex" "brew install --cask mactex-no-gui"
check_dep "py-spy"   "py-spy"   "pip install py-spy"
check_py_dep "mlx-lm" "mlx_lm" "pip install mlx-lm"

# ── Self-test ──────────────────────────────────────────────────────────
step "Verification"

genius_count=$(find "$CLAUDE_DIR/agents/genius" -name "*.md" -not -name "INDEX.md" 2>/dev/null | wc -l | tr -d ' ')
[[ "$genius_count" -ge 90 ]] && ok "Genius agents accessible ($genius_count agents)" || warn "Expected ~97 genius agents, found $genius_count"

team_count=$(find "$CLAUDE_DIR/agents" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
ok "Team agents installed ($team_count)"

skill_count=$(find "$CLAUDE_DIR/skills" -name "*.md" -not -name "_*" 2>/dev/null | wc -l | tr -d ' ')
ok "Skills installed ($skill_count)"

cmd_count=$(find "$CLAUDE_DIR/commands" -name "*.md" -not -name "_*" 2>/dev/null | wc -l | tr -d ' ')
ok "Commands installed ($cmd_count)"

rules_count=$(find "$CLAUDE_DIR/rules" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
ok "Rules installed ($rules_count)"

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Zetetic Team Subagents v${PLUGIN_VERSION} setup complete!${NC}"
echo ""
echo "  $count_agents team + $count_genius genius agents → ~/.claude/agents/"
echo "  $count_skills skills                              → ~/.claude/skills/"
echo "  $count_commands commands                            → ~/.claude/commands/"
echo "  $count_hooks hooks                                → ~/.claude/hooks/"
echo "  $count_tools tools                                → ~/.claude/tools/"
echo "  $count_rules rules                                → ~/.claude/rules/"
[[ "$count_overridden" -gt 0 ]] && echo "  $count_overridden model overrides applied from ~/.claude/zetetic-agent-models.json"
echo ""
echo "  Next steps:"
echo "    1. Restart Claude Code to activate"
echo -e "    2. Configure models:  ${CYAN}$0 configure${NC}"
echo -e "    3. Update:            ${CYAN}$0 update${NC}"
echo -e "    4. Uninstall:         ${CYAN}$0 uninstall${NC}"
echo ""

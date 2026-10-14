#!/usr/bin/env bash
# session-start.sh — Load context at session start
set -euo pipefail

# Path resolution: CLAUDE_PLUGIN_ROOT → script-relative → git root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}"
TOOLS="${PLUGIN_ROOT}/tools"
[[ ! -d "$TOOLS" ]] && TOOLS="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/tools"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# --- Seed shared context-threshold config (consumed by stop-context-guard.py
# and the session-optimizer statusline). Idempotent: never overwrites an
# existing file, so user edits to thresholds survive plugin updates. ---
CTXGUARD_CONFIG="${HOME}/.claude/ctxguard-thresholds.json"
if [[ ! -f "$CTXGUARD_CONFIG" && -f "${PLUGIN_ROOT}/hooks/ctxguard-thresholds.json" ]]; then
  cp "${PLUGIN_ROOT}/hooks/ctxguard-thresholds.json" "$CTXGUARD_CONFIG" 2>/dev/null || true
fi

# --- Colors (true color RGB — readable on dark backgrounds) ---
TEAL="\033[1;38;2;207;110;57m"  # #cf6e39 — DS --accent (terracotta) oklch(64% 0.14 47) · scripted oklch->srgb
WHITE="\033[38;2;224;224;224m"
LIGHT="\033[38;2;190;195;190m"
SUBTLE="\033[38;2;150;160;155m"
BOLD="\033[1m"
RESET="\033[0m"

# --- Portable time-box: prefer coreutils timeout/gtimeout, else a background
# watchdog. Never lets a hook subcommand hang session start. ---
run_timeboxed() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@"
  else
    "$@" &
    local pid=$!
    # The watchdog must not inherit the caller's stdout: a pipe reader
    # (`| sed`, `$(...)`) would otherwise wait for its `sleep` to expire and
    # every timeboxed stage would cost its full budget.
    ( exec >/dev/null 2>&1; sleep "$secs" & wait $!; kill -9 "$pid" ) >/dev/null 2>&1 &
    local watchdog=$!
    wait "$pid" 2>/dev/null
    local rc=$?
    pkill -P "$watchdog" 2>/dev/null
    kill "$watchdog" 2>/dev/null
    wait "$watchdog" 2>/dev/null
    return "$rc"
  fi
}

# --- Banner ---
echo ""
echo -e "${TEAL}  ███████╗███████╗████████╗███████╗████████╗██╗ ██████╗${RESET}"
echo -e "${TEAL}  ╚══███╔╝██╔════╝╚══██╔══╝██╔════╝╚══██╔══╝██║██╔════╝${RESET}"
echo -e "${TEAL}    ███╔╝ █████╗     ██║   █████╗     ██║   ██║██║     ${RESET}"
echo -e "${TEAL}   ███╔╝  ██╔══╝     ██║   ██╔══╝     ██║   ██║██║     ${RESET}"
echo -e "${TEAL}  ███████╗███████╗   ██║   ███████╗   ██║   ██║╚██████╗${RESET}"
echo -e "${TEAL}  ╚══════╝╚══════╝   ╚═╝   ╚══════╝   ╚═╝   ╚═╝ ╚═════╝${RESET}"
echo ""
echo -e "${WHITE}${BOLD}  A G E N T S${RESET}"
echo ""
echo -e "${WHITE}  97 reasoning patterns  ·  63 skills  ·  14 hooks  ·  17 tools${RESET}"
echo ""
echo -e "${LIGHT}  Pearl ── Peirce ── Feynman ── Toulmin ── Cochrane${RESET}"
echo -e "${SUBTLE}  causal    abductive  integrity   argument   evidence${RESET}"
echo -e "${SUBTLE}  graphs    hypotheses checks      structure  synthesis${RESET}"
echo ""
echo -e "${LIGHT}  every claim cites its source · every commit is checked${RESET}"
echo -e "${LIGHT}  every agent says \"I don't know\" when it doesn't${RESET}"
echo ""
printf "%65s\n" "powered by" | sed "s/.*/${TEAL}&${RESET}/"
printf "%65s\n" "ai-architect.tools" | sed "s/.*/${TEAL}&${RESET}/"
echo ""

# --- Status ---
echo -e "${WHITE}${BOLD}  ◆ Repository${RESET}"
echo "  Branch: $(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo 'unknown')"
echo "  Uncommitted: $(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ') files"
echo "  Last commit: $(git -C "$REPO_ROOT" log --oneline -1 2>/dev/null || echo 'none')"
echo ""

# --- Plugin currency (issue #52). Three values: what is installed, what the
# marketplace PINS, what the repo has RELEASED. `installed < pin` is a user
# update; `pin < released` means the release was never delivered and is fixed in
# the marketplace-owning repo. Silent when current — this only speaks when
# something is actually stale. Time-boxed and warn-only: a boot check that can
# fail a session is a check that gets disabled. ---
if [[ -x "$TOOLS/plugin-version-check.sh" ]]; then
  version_report="$(run_timeboxed 8 "$TOOLS/plugin-version-check.sh" 2>/dev/null || true)"
  if [[ -n "$version_report" ]]; then
    echo -e "${WHITE}${BOLD}  ◆ Plugin Currency${RESET}"
    echo "$version_report" | sed 's/^/  /'
    echo ""
  fi
fi

echo -e "${WHITE}${BOLD}  ◆ Difficulty Books${RESET}"
"$TOOLS/difficulty-book-manager.sh" status 2>/dev/null || echo "  (none)"
echo ""

# ── Memory directory: scopes listing only. No content injection (Taleb: avoid
# scope-wide auto-load; agents call `view` explicitly on names they need).
if [[ -x "$TOOLS/memory-tool.sh" ]]; then
  echo -e "${WHITE}${BOLD}  ◆ Memory Scopes${RESET}"
  MEMORY_AGENT_ID="${MEMORY_AGENT_ID:-_user}" "$TOOLS/memory-tool.sh" scopes 2>/dev/null \
    | sed 's/^/  /' || echo "  (memory-tool unavailable)"
  # Show Cortex replica queue depth if non-empty — reminds agent to drain.
  sync_line="$(MEMORY_AGENT_ID="${MEMORY_AGENT_ID:-_user}" "$TOOLS/memory-tool.sh" sync-status 2>/dev/null | head -1)"
  if [[ "$sync_line" == *"pending"* && "$sync_line" != "queue: 0 pending,"* && "$sync_line" != "queue: empty"* ]]; then
    echo ""
    echo -e "${SUBTLE}  Cortex replica ${sync_line} — run /session:memory-sync to drain.${RESET}"
  fi
  echo ""
  echo -e "${SUBTLE}  Memory protocol: call \`view /memories/<scope>/<file>\` to read; never rely on prior context.${RESET}"
  echo ""
fi

echo -e "${WHITE}${BOLD}  ◆ Agent Worktrees${RESET}"
"$TOOLS/worktree-manager.sh" list 2>/dev/null || echo "  (none)"
echo ""

echo -e "${WHITE}${BOLD}  ◆ Worktree Sweep${RESET}"
if [[ -x "$TOOLS/worktree-manager.sh" ]]; then
  # No --fetch at boot (no network); merged-check relies on refs already
  # fetched from a prior `git fetch`. Warn-only — never blocks startup.
  #
  # Scoped to REPO_ROOT only (issue #33 fix). The no-args form of `sweep`
  # auto-discovers and sweeps EVERY sibling git repo under REPO_ROOT's
  # parent directory — which meant any Claude Code session started in ANY
  # sibling project on this machine would reach into and remove worktrees
  # belonging to a completely unrelated repo (this one included), widening
  # the removal race far beyond what a single repo's own boot should touch.
  # Deliberate cross-repo hygiene sweeps remain available via the explicit
  # multi-repo form: `tools/worktree-manager.sh sweep --fetch <repo...>`.
  run_timeboxed 15 "$TOOLS/worktree-manager.sh" sweep "$REPO_ROOT" 2>/dev/null | sed 's/^/  /' || true
else
  echo "  (worktree-manager unavailable)"
fi
echo ""

echo -e "${WHITE}${BOLD}  ◆ Dev Symlink Montage${RESET}"
if [[ -x "$TOOLS/dev-symlink-doctor.sh" ]]; then
  run_timeboxed 10 "$TOOLS/dev-symlink-doctor.sh" 2>/dev/null | sed 's/^/  /' || true
else
  echo "  (dev-symlink-doctor unavailable)"
fi
echo ""

echo -e "${WHITE}${BOLD}  ◆ Session Cache${RESET}"
"$TOOLS/session-store.sh" load 2>/dev/null || echo "  (no cached session)"
echo ""

echo -e "${LIGHT}  Reminder: call query_methodology for cognitive profile, recall for Cortex context.${RESET}"

exit 0

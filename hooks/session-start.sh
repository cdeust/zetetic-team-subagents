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

# --- Boot sections run in parallel under one hard budget, joined in the
# original order (hooks/lib/run_sections.py; sections in hooks/lib/session-sections.sh).
# The slowest section, not the sum, sets the startup time (measured 2026-10-14:
# 11.6 s sequential). A section still running at the budget is killed with its
# whole process group, so a hung tool cannot hold session start. worktree list
# and sweep stay in one section because sweep removes worktrees that list reads.
# source: 8 s = the 10 s hook timeout of hooks.json minus ~2 s for the banner,
# git status and the runner's own start. ---
SECTION_BUDGET_S=8
export TOOLS REPO_ROOT TEAL WHITE LIGHT SUBTLE BOLD RESET
ZETETIC_PYTHON_MISSING_NOTICE="  zetetic boot sections not run" \
  "$PLUGIN_ROOT/hooks/run-python.sh" "$SCRIPT_DIR/lib/run_sections.py" \
  "$SCRIPT_DIR/lib/session-sections.sh" "$SECTION_BUDGET_S" \
  currency books memory worktrees symlinks cache </dev/null || true

echo -e "${LIGHT}  Reminder: call query_methodology for cognitive profile, recall for Cortex context.${RESET}"

exit 0

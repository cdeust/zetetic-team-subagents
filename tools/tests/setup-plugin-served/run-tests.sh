#!/usr/bin/env bash
# Regression tests for scripts/setup.sh's plugin-served guard (2026-09-08).
# When the marketplace plugin is installed, Claude Code already lists every
# agent and skill from the plugin cache; a second copy under ~/.claude/ made
# each of them appear twice in every session's prelude (about 28K tokens for
# the agent listing alone, measured on the owner's machine). setup.sh must
# stage 0 agents and 0 skills in that case and still stage them for a
# standalone install. --dry-run stops right after staging, so the test never
# writes to a real ~/.claude: HOME points at a throwaway directory.
set -euo pipefail
cd "$(dirname "$0")"
SETUP="${SETUP_SH:-$(cd ../../.. && pwd)/scripts/setup.sh}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail=0
check() { # <label> <expected-regex> <output>
  if grep -qE "$2" <<<"$3"; then echo "  ok   $1"; else echo "  FAIL $1: expected /$2/"; echo "$3" | grep -E 'Staged:|plugin present' || true; fail=1; fi
}

# Case 1: plugin registered -> nothing staged for agents/skills.
mkdir -p "$TMP/home1/.claude/plugins"
echo '{"version":2,"plugins":{"zetetic-team-subagents@zetetic-marketplace":[{"scope":"user"}]}}' > "$TMP/home1/.claude/plugins/installed_plugins.json"
out1="$(HOME="$TMP/home1" bash "$SETUP" install --dry-run 2>&1 || true)"
check "plugin registered: agents and skills not staged" 'Staged: 0 team \+ 0 genius agents, 0 skills' "$out1"
check "plugin registered: says so"                       'served by it' "$out1"
check "plugin registered: commands still staged"        'Staged: .*, [1-9][0-9]* commands' "$out1"

# Case 2: no plugin -> standalone install stages everything.
mkdir -p "$TMP/home2/.claude"
out2="$(HOME="$TMP/home2" bash "$SETUP" install --dry-run 2>&1 || true)"
check "standalone: team agents staged"   'Staged: [1-9][0-9]* team \+' "$out2"
check "standalone: genius agents staged" '\+ [1-9][0-9]* genius agents' "$out2"
check "standalone: skills staged"        'agents, [1-9][0-9]* skills' "$out2"

# Case 3: with the plugin served, the tools must still find its agents and
# skills: ~/.claude/agents holds only personal agents (no genius/), the
# plugin's trees live at the registry's installPath.
LIB="$(cd ../../.. && pwd)/tools/lib/plugin-content-dir.sh"
mkdir -p "$TMP/home3/.claude/agents" "$TMP/home3/.claude/skills/mine" "$TMP/plug/agents/genius" "$TMP/plug/skills/writing"
touch "$TMP/home3/.claude/agents/dispatch.md" "$TMP/home3/.claude/skills/mine/SKILL.md" "$TMP/plug/agents/genius/curie.md" "$TMP/plug/skills/_index.md"
mkdir -p "$TMP/home3/.claude/plugins"
printf '{"version":2,"plugins":{"zetetic-team-subagents@zetetic-marketplace":[{"scope":"user","installPath":"%s"}]}}' "$TMP/plug" > "$TMP/home3/.claude/plugins/installed_plugins.json"
res_a="$(HOME="$TMP/home3" bash -c "source '$LIB'; resolve_plugin_content_dir '' agents genius '$TMP/home3/.claude'")"
res_s="$(HOME="$TMP/home3" bash -c "source '$LIB'; resolve_plugin_content_dir '' skills _index.md '$TMP/home3/.claude'")"
check "plugin served: agents resolve to the install path" "^$TMP/plug/agents\$" "$res_a"
check "plugin served: skills resolve to the install path" "^$TMP/plug/skills\$" "$res_s"
res_o="$(HOME="$TMP/home3" bash -c "source '$LIB'; resolve_plugin_content_dir '$TMP/plug/agents' agents genius '/nonexistent'")"
check "explicit override still wins" "^$TMP/plug/agents\$" "$res_o"
# No registry, no jq path: the newest cache directory is the fallback.
mkdir -p "$TMP/home4/.claude/plugins/cache/zetetic-marketplace/zetetic-team-subagents/9.9.9/agents/genius"
res_c="$(HOME="$TMP/home4" bash -c "source '$LIB'; resolve_plugin_content_dir '' agents genius '/nonexistent'")"
check "no registry: newest cache dir is the fallback" "9.9.9/agents\$" "$res_c"

exit "$fail"

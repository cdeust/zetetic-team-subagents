# shellcheck shell=bash
# lib/plugin-content-dir.sh — one resolver for the plugin's content directories
# (agents/, skills/), sourced by the tools that read them (agent-catalog,
# genius-invoker, shape-router, skill-runner). Pure bash + jq when present.
#
# Why one resolver (2026-09-08, PR #131): each tool carried its own copy of
# "env var > ~/.claude/<dir> > tool-relative > git root". That order silently
# broke the moment setup.sh stopped copying agents and skills into ~/.claude/
# for plugin-served installs: the tools fell through to the git root of
# whatever directory the caller stood in. The marketplace install path is a
# first-class location now, read from Claude Code's own registry.
#
# resolve_plugin_content_dir <override> <dirname> <marker> <tool_root>
#   override  : explicit path from an env var (ZETETIC_AGENTS / ZETETIC_SKILLS);
#               honoured whenever it is a directory
#   dirname   : agents | skills
#   marker    : an entry only the plugin-shipped tree carries (agents: the
#               `genius` directory; skills: `_index.md`), so a user-level
#               ~/.claude/agents holding two personal agents is not mistaken
#               for the plugin's 120
#   tool_root : what the calling tool treats as its plugin root
#               ($(dirname "$0")/..): the plugin cache when run from there,
#               ~/.claude when run from the installed copy
# Precedence: override > ~/.claude/<dirname> > tool_root/<dirname> > the
# marketplace install path > git root/<dirname> (a dev checkout).

_plugin_content_has_marker() { [[ -d "$1" && -e "$1/$2" ]]; }

# The plugin's install path: installed_plugins.json is authoritative (it is
# what Claude Code loads); the newest cache directory is the fallback when the
# registry is absent or jq is not installed.
zetetic_plugin_install_path() {
  local reg="$HOME/.claude/plugins/installed_plugins.json" p
  if [[ -f "$reg" ]] && command -v jq >/dev/null 2>&1; then
    p="$(jq -r '.plugins | to_entries[] | select(.key | startswith("zetetic-team-subagents@")) | .value[0].installPath // empty' "$reg" 2>/dev/null | head -1)"
    [[ -n "$p" && -d "$p" ]] && { echo "$p"; return 0; }
  fi
  p="$(ls -td "$HOME"/.claude/plugins/cache/*/zetetic-team-subagents/*/ 2>/dev/null | head -1)"
  [[ -n "$p" ]] && { echo "${p%/}"; return 0; }
  return 1
}

resolve_plugin_content_dir() {
  local override="$1" dirname="$2" marker="$3" tool_root="$4" d
  [[ -n "$override" && -d "$override" ]] && { echo "$override"; return; }
  for d in "$HOME/.claude/$dirname" "$tool_root/$dirname"; do
    _plugin_content_has_marker "$d" "$marker" && { echo "$d"; return; }
  done
  if d="$(zetetic_plugin_install_path)" && _plugin_content_has_marker "$d/$dirname" "$marker"; then
    echo "$d/$dirname"; return
  fi
  echo "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/$dirname"
}

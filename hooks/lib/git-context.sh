#!/usr/bin/env bash
# Shared repository resolver for advisory git PostToolUse hooks.

zt_resolve_repo_root() {
  local hook_input="$1" bash_cmd="$2"
  local event_dir="" command_dir="" base_dir="$PWD" candidate root py parser

  if command -v jq &>/dev/null; then
    event_dir=$(printf '%s' "$hook_input" | jq -r \
      '.tool_input.workdir // .tool_input.cwd // .cwd // empty' 2>/dev/null || true)
  fi
  [[ -n "$event_dir" ]] && base_dir="$event_dir"

  # Preserve the gate for `git -C <repo> commit` from a non-repository host
  # cwd.  shlex handles quoted paths without evaluating the command.  If no
  # Python interpreter is available, the event cwd/PWD probes remain a safe
  # fail-open fallback.
  py="$(command -v python3 || command -v python || true)"
  parser="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/git-command-cwd.py"
  if [[ -n "$py" && -f "$parser" ]]; then
    command_dir=$("$py" "$parser" "$bash_cmd" "$base_dir" 2>/dev/null || true)
  fi

  for candidate in "$command_dir" "$event_dir" "$PWD"; do
    [[ -n "$candidate" && -d "$candidate" ]] || continue
    if root=$(git -C "$candidate" rev-parse --show-toplevel 2>/dev/null); then
      printf '%s\n' "$root"
      return 0
    fi
  done
  return 1
}

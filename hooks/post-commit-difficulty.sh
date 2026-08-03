#!/usr/bin/env bash
# post-commit-difficulty.sh — After commit, check if difficulty books need updating
# Advisory PostToolUse hooks must fail open.  In particular, the hook process
# may start outside the repository even when the completed command used
# ``git -C`` or supplied its own tool workdir.
set -uo pipefail

# Command guard: only fire after git commit (matcher: "Bash" fires on ALL Bash calls)
HOOK_INPUT=""
if ! [ -t 0 ]; then
  # Portable bounded stdin read. macOS ships NO 'timeout'/'gtimeout'; its
  # absence must NOT zero out the payload (that silently disables the hook — the
  # root cause of audit finding R1). Use the bound if present, else plain cat.
  _ZT="$(command -v timeout || command -v gtimeout || true)"
  if [ -n "$_ZT" ]; then
    HOOK_INPUT="$("$_ZT" 3 cat 2>/dev/null || true)"
  else
    HOOK_INPUT="$(cat 2>/dev/null || true)"
  fi
fi
if command -v jq &>/dev/null; then
  BASH_CMD=$(echo "$HOOK_INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")
else
  BASH_CMD=$(echo "$HOOK_INPUT" | grep -oE '"command":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"command":\s*"//' | sed 's/"$//' || echo "")
fi
# Match the git SUBCOMMAND at a command position, not the substring 'git commit'
# anywhere on the line (which false-fires on echo/quoted/--grep= corpora — audit
# A7). 'git' must be at line-start or right after a shell separator (; & | ( {),
# then optional global flags (each a -token possibly followed by one non-flag
# arg, e.g. -C /path or -c k=v), then the verb 'commit'/'push' as a whole word
# NOT followed by '-' (so commit-tree / commit-graph are excluded).
GIT_VERB_RE='(^|[;&|({])[[:space:]]*((sudo|command|env)[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*([^[:space:];&|({]*/)?git[[:space:]]+(-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?[[:space:]]+)*(commit|push)([[:space:];&|)<>]|$)'
if ! printf '%s\n' "$BASH_CMD" | grep -qE "$GIT_VERB_RE" 2>/dev/null; then exit 0; fi

HOOK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/git-context.sh
source "$HOOK_DIR/lib/git-context.sh"
if ! REPO_ROOT="$(zt_resolve_repo_root "$HOOK_INPUT" "$BASH_CMD")"; then
  exit 0
fi
DB_DIR="$REPO_ROOT/tasks"

[[ ! -d "$DB_DIR" ]] && exit 0

# Get files in the last commit
COMMITTED=$(git -C "$REPO_ROOT" diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null || true)
[[ -z "$COMMITTED" ]] && exit 0

# Check if any difficulty book references the committed files' directories
for db in "$DB_DIR"/difficulty-book-*.md; do
  [[ ! -f "$db" ]] && continue
  bname="$(basename "$db" .md | sed 's/difficulty-book-//')"
  # If any committed file's path appears in the difficulty book, notify.
  # Use grep -F (fixed strings): the relative path / basename are DATA, never a
  # pattern — interpolating them into a BRE (audit A8) let a root-level file's
  # dirname '.' match any char, firing "Consider updating" unconditionally.
  while IFS= read -r cf; do
    [[ -z "$cf" ]] && continue
    cdir="$(dirname "$cf")"
    cbase="$(basename "$cf")"
    # Complete basename minus only the FINAL extension (sed 's/\..*//' wrongly
    # stripped at the first dot: foo.test.ts -> foo). Keep the full name if
    # stripping would empty it (e.g. dotfiles like .gitignore).
    cstem="${cbase%.*}"
    [[ -z "$cstem" ]] && cstem="$cbase"
    # Skip the dirname check for root-level files (dirname == '.').
    if { [[ "$cdir" != "." ]] && grep -qiF "$cdir" "$db" 2>/dev/null; } \
       || { [[ -n "$cstem" ]] && grep -qiF "$cstem" "$db" 2>/dev/null; }; then
      echo "NOTE: Commit touches area tracked by difficulty book '$bname'. Consider updating." >&2
      break
    fi
  done <<< "$COMMITTED"
done

exit 0

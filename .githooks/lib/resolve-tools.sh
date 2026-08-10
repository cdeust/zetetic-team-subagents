#!/usr/bin/env bash
# .githooks/lib/resolve-tools.sh — shared tool-resolution for native git
# hooks. Sourced by .githooks/pre-commit and .githooks/commit-msg; not
# executed directly.
#
# Why this exists: core.hooksPath can point at THIS repo's .githooks/ from
# any other repo's clone (verified in a scratch clone 2026-08-10 — an
# absolute, out-of-repo core.hooksPath works, and `git rev-parse
# --show-toplevel` still resolves to the COMMITTING repo, not this one).
# That makes zetetic-team-subagents/.githooks a shared enforcement engine
# for repos that never vendor tools/deletion-gate.sh, tools/zetetic-checker.sh
# or tools/craftsmanship-checker.sh themselves. Before this file, the two
# hook scripts derived their tools directory from `git rev-parse
# --show-toplevel` alone — correct only when the committing repo IS the one
# carrying the tools, i.e. only ever true for this repo's own clone. Every
# other repo hit the executability check, printed a WARNING, and exited 0:
# the gate was global in name only (see PR that added this file).
#
# PLUGIN_ROOT is derived from THIS FILE's own on-disk location (two levels
# up: lib/ -> .githooks/ -> repo root), never from the committing repo — a
# file physically living inside the plugin clone always resolves to the
# plugin clone no matter which repo's core.hooksPath named it.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# resolve_tool <name> — prints the path to an executable tools/<name>,
# preferring the committing repo's own copy (a repo may vendor and override
# the shared one) and falling back to this plugin clone's copy. Prints
# nothing and returns 1 if neither exists.
resolve_tool() {
  local name="$1"
  local local_path="$REPO_ROOT/tools/$name"
  local shared_path="$PLUGIN_ROOT/tools/$name"
  if [[ -x "$local_path" ]]; then
    printf '%s\n' "$local_path"
    return 0
  fi
  if [[ -x "$shared_path" ]]; then
    printf '%s\n' "$shared_path"
    return 0
  fi
  return 1
}

# require_tool <name> — like resolve_tool, but treats a miss as an
# infrastructure fault, not a "this repo legitimately has no gate" signal,
# and blocks (git pre-commit/commit-msg: any non-zero exit blocks).
#
# Why block instead of the old warn-and-allow: a repo that was never wired
# never reaches this code at all — core.hooksPath is unset, so git does not
# invoke a hook file that isn't configured, and nothing runs, warns, or
# blocks. This function only executes once core.hooksPath already points
# HERE. Under the shared install (tools/install-git-hooks.sh), tools/<name>
# is a sibling of this very file inside the same repo clone and moves with
# it — the only way resolve_tool fails at that point is a corrupted or
# partially-checked-out plugin clone (wrong CWD, detached submodule, moved
# directory). That is "I could not tell", never "not covered", and a git
# hook silently no-op'ing on "could not tell" is the exact failure this
# layer exists to close (see this repo's #109/#110). Fail closed.
require_tool() {
  local name="$1"
  local path
  if path="$(resolve_tool "$name")"; then
    printf '%s\n' "$path"
    return 0
  fi
  echo "BLOCKED: neither $REPO_ROOT/tools/$name nor $PLUGIN_ROOT/tools/$name is executable." >&2
  echo "This hook IS wired (core.hooksPath points here) but its engine is missing." >&2
  echo "The shared plugin clone at:" >&2
  echo "  $PLUGIN_ROOT" >&2
  echo "looks corrupted, partially checked out, or moved. Fix the clone, or repoint" >&2
  echo "core.hooksPath (git config --unset core.hooksPath removes this repo's wiring" >&2
  echo "entirely — that is the legitimate way to opt a repo out, not a silent skip here)." >&2
  return 1
}

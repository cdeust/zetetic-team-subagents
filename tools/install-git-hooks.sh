#!/usr/bin/env bash
# install-git-hooks.sh — point a repo's core.hooksPath at THIS repo's
# .githooks/ (this repo's own clone, always, by absolute path — including
# for this repo's own clone; see rationale below). Idempotent: prints
# "unchanged" on a second run against the same target with no config write.
#
# Usage:
#   tools/install-git-hooks.sh                  # wire the repo at $PWD
#   tools/install-git-hooks.sh --repo <path>     # wire a specific repo
#   tools/install-git-hooks.sh --all             # wire this repo plus every
#                                                 # repo listed in
#                                                 # tools/git-hooks-fleet.txt
#
# What "wiring" gets a target repo: .githooks/pre-commit and
# .githooks/commit-msg both fire on every `git commit` in that repo from now
# on. Neither is vendored into the target — both resolve tools/deletion-gate.sh,
# tools/zetetic-checker.sh and tools/craftsmanship-checker.sh from THIS clone
# at commit time (.githooks/lib/resolve-tools.sh), preferring a local copy in
# the target repo if one exists. core.hooksPath is per-clone LOCAL git config
# (.git/config) — it is never committed, so cloning any of the five repos
# fresh starts UNWIRED; this script (or --all) must be re-run in every fresh
# clone. Shipping .githooks/ in a repo changes nothing on its own — that gap
# is the whole reason this script exists rather than a README instruction.
#
# Why absolute, always, even when the target IS this repo: one code path,
# tested once, beats a special case for "am I the plugin repo". Confirmed
# working in a scratch clone 2026-08-10: an out-of-repo, absolute
# core.hooksPath fires correctly, and `git rev-parse --show-toplevel` inside
# the hook still resolves to the COMMITTING repo, not this one.
#
# Interaction with a repo that wants its own, different hooks: core.hooksPath
# names exactly one hooks directory per repo — a repo cannot run both this
# shared .githooks/pre-commit AND a hook file of its own under the same hook
# name. A repo that needs genuinely different hook LOGIC (not just a
# different engine) should vendor its own .githooks/ and point
# core.hooksPath there directly; it can still source
# .githooks/lib/resolve-tools.sh from this clone if it wants the same
# tools/-resolution behavior. None of the five repos this script wires need
# that today — plain wiring at this repo's .githooks/ is sufficient.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$PLUGIN_ROOT/.githooks"
FLEET_FILE="$PLUGIN_ROOT/tools/git-hooks-fleet.txt"

if [[ ! -d "$HOOKS_DIR" ]]; then
  echo "ERROR: $HOOKS_DIR not found — this script must run from inside the plugin clone." >&2
  exit 1
fi
chmod +x "$HOOKS_DIR"/pre-commit "$HOOKS_DIR"/commit-msg "$HOOKS_DIR"/lib/*.sh 2>/dev/null || true

# wire_one <path> — set core.hooksPath for the repo containing <path> to
# HOOKS_DIR (absolute). Reports "wired" (changed) or "unchanged" (already
# correct) and never fails the whole run on one bad target.
wire_one() {
  local input="$1"
  local target
  if ! target="$(cd "$input" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)"; then
    echo "SKIPPED: $input is not a git repository (or does not exist)." >&2
    return 1
  fi
  local prev
  prev="$(git -C "$target" config --get core.hooksPath 2>/dev/null || true)"
  if [[ "$prev" == "$HOOKS_DIR" ]]; then
    echo "unchanged: $target (core.hooksPath already -> $HOOKS_DIR)"
    return 0
  fi
  git -C "$target" config core.hooksPath "$HOOKS_DIR"
  echo "wired:     $target (core.hooksPath: ${prev:-<unset>} -> $HOOKS_DIR)"
}

MODE="single"
TARGET="$PWD"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all) MODE="all"; shift ;;
    --repo)
      TARGET="${2:?--repo requires a path}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Usage: $0 [--repo <path> | --all]" >&2
      exit 2
      ;;
  esac
done

if [[ "$MODE" == "all" ]]; then
  if [[ ! -f "$FLEET_FILE" ]]; then
    echo "ERROR: $FLEET_FILE not found." >&2
    exit 1
  fi
  status=0
  wire_one "$PLUGIN_ROOT" || status=1
  PARENT="$(dirname "$PLUGIN_ROOT")"
  while IFS= read -r name; do
    [[ -z "$name" || "$name" == \#* ]] && continue
    wire_one "$PARENT/$name" || status=1
  done < "$FLEET_FILE"
  exit "$status"
else
  wire_one "$TARGET"
fi

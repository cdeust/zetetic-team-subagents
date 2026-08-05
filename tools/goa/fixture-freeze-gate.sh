#!/usr/bin/env bash
# goa-fixture-freeze-gate.sh — CI HARD GATE wrapper for
# tools/goa/fixture_freeze_gate.py: external_testbase_v*.json is append-only
# once committed. See that module's docstring for the comparison contract.
#
# No "|| echo" — a real violation exits non-zero and fails the job.
set -euo pipefail

# SELF_DIR resolves the gate SCRIPT's own directory (its Python sibling lives
# right next to it — see the matching comment in no-raw-text-gate.sh);
# TARGET_REPO_ROOT is what the gate inspects, which defaults to the caller's
# cwd repo (CI's checkout) but may be overridden via --repo-root, e.g. from a
# test harness pointing at a temp repo.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PR_BASE_SHA="${PR_BASE_SHA:-}"
ARGS=("$@")
if [[ ! " ${ARGS[*]} " == *" --repo-root "* ]]; then
  TARGET_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  ARGS+=(--repo-root "$TARGET_REPO_ROOT")
fi
if [[ -n "${PR_BASE_SHA}" && ! " ${ARGS[*]} " == *" --pr-base-sha "* ]]; then
  ARGS+=(--pr-base-sha "${PR_BASE_SHA}")
fi
exec python3 "$SELF_DIR/fixture_freeze_gate.py" "${ARGS[@]}"

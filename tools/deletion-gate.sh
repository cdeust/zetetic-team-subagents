#!/usr/bin/env bash
# deletion-gate.sh — makes "delete it instead of fixing it" mechanically
# impossible to merge silently (see tools/deletion_gate.py for the mechanism
# and the incident, cdeust/cortex-viz commit 45d4a80, that this closes).
#
# Usage:
#   tools/deletion-gate.sh --commit <sha> [--repo <path>] [--message-file <path>]
#   tools/deletion-gate.sh --base <ref> --head <ref> [--repo <path>]
#   tools/deletion-gate.sh --staged --message-file <path> [--repo <path>]
#
# Exit codes: 0 pass, 1 block (a removed top-level definition has surviving
# callers, or has none and no substantive Retired-Because: trailer), 2 usage
# or git error.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$REPO_ROOT/tools/deletion_gate.py" "$@"

#!/usr/bin/env bash
# Shared gate implementation; no full-plugin research bookkeeping.
set -euo pipefail
exec bash "$(dirname "$0")/gates-pre-commit.sh"

#!/usr/bin/env bash
# source: https://github.com/cdeust/zetetic-team-subagents/tree/6fa8cc5deeeb63d65b767f2e9d79486858eb710b
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
case "${1:-}" in
  setup)
    python -m pip install --disable-pip-version-check --require-hashes -r requirements-dev.lock
    for command in jq rg go cargo npm; do command -v "$command"; done
    ;;
  unit)
    python -m coverage run -m pytest -q
    python -m coverage report
    ;;
  regression|e2e|environment|installation)
    python .github/ci/suites.py "$1"
    ;;
  release-version)
    python -c 'import json; print("tag=v"+json.load(open(".claude-plugin/plugin.json"))["version"])'
    ;;
  *) echo 'Usage: run.sh setup|unit|regression|e2e|environment|installation|release-version' >&2; exit 2 ;;
esac

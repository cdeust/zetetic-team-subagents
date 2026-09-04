#!/usr/bin/env bash
# discoverability-baseline — regression suite for
# tools/tests/discoverability-baseline/score_routing.py's pure
# precision_recall math and the committed labeled_prompts.json corpus.
#
# This does NOT invoke the `claude` CLI (no network, no API key needed in
# CI): route_with_claude is a live-scoring function exercised only by a
# manual run of score_routing.py itself (see
# tools/bench-agent-cost/README.md, Phase 3 of the staged-rolling-shannon
# plan). What CI gates here is the scoring math staying correct and the
# corpus staying well-formed -- both of which the pytest suite at
# tests/test_discoverability_baseline.py verifies via `python3 -m pytest`.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TEST_FILE="$REPO_ROOT/tests/test_discoverability_baseline.py"

PY="$(command -v python3 || command -v python)"
if [[ -z "$PY" ]]; then
  echo "FAIL no python3/python interpreter found" >&2
  exit 1
fi

if ! "$PY" -c "import pytest" 2>/dev/null; then
  echo "FAIL pytest not importable by $PY -- run 'uv sync' or install requirements-dev.lock" >&2
  exit 1
fi

"$PY" -m pytest "$TEST_FILE" -q
result=$?

echo ""
if [[ $result -eq 0 ]]; then
  echo "discoverability-baseline result: pytest suite passed"
else
  echo "discoverability-baseline result: pytest suite FAILED" >&2
fi
exit $result

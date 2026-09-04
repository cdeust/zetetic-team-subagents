#!/usr/bin/env bash
# discoverability-baseline — regression suite for
# tools/tests/discoverability-baseline/score_routing.py's pure
# precision_recall math and the committed labeled_prompts.json corpus.
#
# Self-contained: stdlib python3 only, no pytest. The "Tools Regression
# Suite" CI job that runs every tools/tests/*/run-tests.sh installs no
# Python dependencies (unlike the separate "Python Suite + Coverage Gate"
# job, which already runs tests/test_discoverability_baseline.py's fuller
# pytest suite under a uv-managed venv) -- a suite here that imports
# pytest fails closed on that job with no dependency installed, which is
# exactly what happened the first time this file assumed pytest was
# importable by the system python3 (fixed after reproducing the CI
# failure directly, not by inspection).
#
# This does NOT invoke the `claude` CLI (no network, no API key needed):
# route_with_claude is a live-scoring function exercised only by a manual
# run of score_routing.py itself (see tools/bench-agent-cost/README.md,
# Phase 3 of the staged-rolling-shannon plan).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
MODULE="$REPO_ROOT/tools/tests/discoverability-baseline/score_routing.py"
CORPUS="$REPO_ROOT/tools/tests/discoverability-baseline/labeled_prompts.json"

PY="$(command -v python3 || command -v python)"
if [[ -z "$PY" ]]; then
  echo "FAIL no python3/python interpreter found" >&2
  exit 1
fi

"$PY" - "$MODULE" "$CORPUS" <<'PYEOF'
import importlib.util
import json
import sys

module_path, corpus_path = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("score_routing", module_path)
score_routing = importlib.util.module_from_spec(spec)
# dataclasses' field-type resolution looks the module up in sys.modules by
# __module__ name, so it must be registered before exec_module runs.
sys.modules["score_routing"] = score_routing
spec.loader.exec_module(score_routing)

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        print(f"  ok   {name}")
        passed += 1
    else:
        print(f"  FAIL {name}", file=sys.stderr)
        failed += 1


shape_ids = ["boundary-design", "causal-audit", "none"]

# T1: perfect predictions score 1.0 accuracy and 1.0 precision/recall.
labels = {"p1": "boundary-design", "p2": "causal-audit", "p3": "none"}
report = score_routing.precision_recall(dict(labels), labels, shape_ids)
check("T1 perfect predictions -> accuracy 1.0", report["accuracy"] == 1.0)
check("T1 perfect predictions -> precision 1.0", report["per_shape"]["boundary-design"]["precision"] == 1.0)

# T2: a false positive lowers precision but not recall of the true shape.
labels = {"p1": "boundary-design", "p2": "none"}
predictions = {"p1": "boundary-design", "p2": "boundary-design"}
report = score_routing.precision_recall(predictions, labels, shape_ids)
bd = report["per_shape"]["boundary-design"]
check("T2 false positive: tp/fp/fn correct", (bd["tp"], bd["fp"], bd["fn"]) == (1, 1, 0))
check("T2 false positive: precision=0.5, recall=1.0", bd["precision"] == 0.5 and bd["recall"] == 1.0)

# T3: a false negative lowers recall but not precision.
labels = {"p1": "boundary-design", "p2": "boundary-design"}
predictions = {"p1": "boundary-design", "p2": "none"}
report = score_routing.precision_recall(predictions, labels, shape_ids)
bd = report["per_shape"]["boundary-design"]
check("T3 false negative: precision=1.0, recall=0.5", bd["precision"] == 1.0 and bd["recall"] == 0.5)

# T4: a shape with zero true/predicted instances reports None, not 0.0.
labels = {"p1": "none"}
report = score_routing.precision_recall({"p1": "none"}, labels, shape_ids)
untested = report["per_shape"]["boundary-design"]
check("T4 untested shape reports precision=None", untested["precision"] is None)
check("T4 untested shape reports recall=None", untested["recall"] is None)

# T5: build_router_prompt includes the table text, ids, and the request.
prompt = score_routing.build_router_prompt("TABLE TEXT", "fix the bug", ["a", "b", "none"])
check("T5 prompt includes routing table text", "TABLE TEXT" in prompt)
check("T5 prompt includes the request text", "fix the bug" in prompt)
check("T5 prompt includes the valid id list", "a, b, none" in prompt)

# T6: the committed corpus is well-formed (structural sanity, not content).
corpus = json.loads(open(corpus_path, encoding="utf-8").read())
check("T6 corpus has >= 20 prompts", len(corpus["prompts"]) >= 20)
valid_shapes = set(corpus["shape_ids"])
check("T6 every prompt label is a declared shape id",
      all(p["label"] in valid_shapes for p in corpus["prompts"]))
check("T6 'none' label is represented",
      any(p["label"] == "none" for p in corpus["prompts"]))
ids = [p["id"] for p in corpus["prompts"]]
check("T6 prompt ids are unique", len(ids) == len(set(ids)))

print("")
print(f"discoverability-baseline: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PYEOF

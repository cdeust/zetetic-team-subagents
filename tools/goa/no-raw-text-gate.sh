#!/usr/bin/env bash
# goa-no-raw-text-gate.sh — CI HARD GATE wrapper for
# tools/goa/ci_no_raw_corpus_text.py. See that module's docstring for the two
# checks it runs (fixture schema + raw-dump-name/size sweep).
#
# No "|| echo" — a real violation exits non-zero and fails the job. That exact
# defect (ci.yml swallowing a gate's failure) was the reason this task named it
# as a thing to never repeat.
set -euo pipefail

# Resolved from THIS script's own directory (its Python sibling lives right
# next to it), not the caller's cwd: a caller may invoke the gate with
# --repo-root pointed at a DIFFERENT (e.g. temporary test) repo, and
# `git rev-parse` in the caller's cwd would then find the wrong tree entirely
# (observed while writing tools/tests/goa-no-raw-text-gate).
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SELF_DIR/ci_no_raw_corpus_text.py" "$@"

#!/usr/bin/env bash
# Regression suite — tools/goa/fixture-freeze-gate.sh (tools/goa/fixture_freeze_gate.py).
#
# Asserts:
#   T1 fixture unchanged between base and HEAD -> exit 0
#   T2 new case_id appended, existing rows untouched -> exit 0
#   T3 existing row's content changed -> exit 1
#   T4 existing case_id removed -> exit 1
#   T5 fixture newly added at HEAD (absent at base) -> exit 0 (nothing to freeze against)
#   T6 manifest.row_count regresses -> exit 1
set -uo pipefail

GATE="$(cd "$(dirname "$0")/../../.." && pwd)/tools/goa/fixture-freeze-gate.sh"
PASS=0; FAIL=0
run_case() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS: $name"; PASS=$((PASS+1)); else echo "FAIL: $name"; FAIL=$((FAIL+1)); fi
}
run_case_fail() {
  local name="$1"; shift
  if ! "$@" >/dev/null 2>&1; then echo "PASS: $name"; PASS=$((PASS+1)); else echo "FAIL: $name"; FAIL=$((FAIL+1)); fi
}

fresh_repo() {
  tmp=$(mktemp -d)
  cd "$tmp" || exit 1
  git init -q .
  git config user.email test@example.com
  git config user.name test
}

base_fixture() {
  cat > external_testbase_v1.json <<'EOF'
{"manifest": {"row_count": 1}, "rows": [{"case_id": "abc123", "shape": "causal-audit", "source_id": "se-42", "license": "CC BY-SA 4.0", "features": {"char_count": 10}}]}
EOF
}

# T1 unchanged
fresh_repo
base_fixture
git add -A && git commit -q -m base
run_case "T1 unchanged: exit 0" "$GATE" --repo-root "$tmp" --pr-base-sha HEAD
cd /; rm -rf "$tmp"

# T2 append
fresh_repo
base_fixture
git add -A && git commit -q -m base
base_sha=$(git rev-parse HEAD)
cat > external_testbase_v1.json <<'EOF'
{"manifest": {"row_count": 2}, "rows": [{"case_id": "abc123", "shape": "causal-audit", "source_id": "se-42", "license": "CC BY-SA 4.0", "features": {"char_count": 10}}, {"case_id": "def456", "shape": "estimation", "source_id": "se-99", "license": "CC BY-SA 4.0", "features": {"char_count": 20}}]}
EOF
git add -A && git commit -q -m append
run_case "T2 pure append: exit 0" "$GATE" --repo-root "$tmp" --pr-base-sha "$base_sha"
cd /; rm -rf "$tmp"

# T3 modified existing row
fresh_repo
base_fixture
git add -A && git commit -q -m base
base_sha=$(git rev-parse HEAD)
cat > external_testbase_v1.json <<'EOF'
{"manifest": {"row_count": 1}, "rows": [{"case_id": "abc123", "shape": "estimation", "source_id": "se-42", "license": "CC BY-SA 4.0", "features": {"char_count": 10}}]}
EOF
git add -A && git commit -q -m modify
run_case_fail "T3 modified row: exit 1" "$GATE" --repo-root "$tmp" --pr-base-sha "$base_sha"
cd /; rm -rf "$tmp"

# T4 removed row
fresh_repo
base_fixture
git add -A && git commit -q -m base
base_sha=$(git rev-parse HEAD)
cat > external_testbase_v1.json <<'EOF'
{"manifest": {"row_count": 0}, "rows": []}
EOF
git add -A && git commit -q -m remove
run_case_fail "T4 removed row: exit 1" "$GATE" --repo-root "$tmp" --pr-base-sha "$base_sha"
cd /; rm -rf "$tmp"

# T5 newly added file
fresh_repo
printf 'unrelated\n' > README.md
git add -A && git commit -q -m base
base_sha=$(git rev-parse HEAD)
base_fixture
git add -A && git commit -q -m new-fixture
run_case "T5 fixture newly added: exit 0" "$GATE" --repo-root "$tmp" --pr-base-sha "$base_sha"
cd /; rm -rf "$tmp"

# T6 row_count regression only (rows identical, manifest lies)
fresh_repo
base_fixture
git add -A && git commit -q -m base
base_sha=$(git rev-parse HEAD)
cat > external_testbase_v1.json <<'EOF'
{"manifest": {"row_count": 0}, "rows": [{"case_id": "abc123", "shape": "causal-audit", "source_id": "se-42", "license": "CC BY-SA 4.0", "features": {"char_count": 10}}]}
EOF
git add -A && git commit -q -m lie
run_case_fail "T6 manifest row_count regressed: exit 1" "$GATE" --repo-root "$tmp" --pr-base-sha "$base_sha"
cd /; rm -rf "$tmp"

echo "goa-fixture-freeze-gate regression: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

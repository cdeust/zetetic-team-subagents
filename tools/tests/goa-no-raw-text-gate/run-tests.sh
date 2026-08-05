#!/usr/bin/env bash
# Regression suite — tools/goa/no-raw-text-gate.sh (tools/goa/ci_no_raw_corpus_text.py).
#
# Asserts:
#   T1 clean fixture (references + features only) -> exit 0
#   T2 fixture row carrying a forbidden raw-text field -> exit 1
#   T3 fixture row missing source_id/license -> exit 1
#   T4 tracked file matching a raw-dump name pattern, not marked synthetic -> exit 1
#   T5 tiny file marked .synthetic. under the size cap -> exit 0 (allowed)
#   T6 oversized file marked .synthetic. over the size cap -> exit 1
#   T7 no fixture/dump-like files tracked at all -> exit 0
set -uo pipefail

GATE="$(cd "$(dirname "$0")/../../.." && pwd)/tools/goa/no-raw-text-gate.sh"
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

# T1 clean fixture
fresh_repo
cat > external_testbase_v1.json <<'EOF'
{"manifest": {"row_count": 1}, "rows": [{"case_id": "abc123", "shape": "causal-audit", "source_id": "se-42", "license": "CC BY-SA 4.0", "features": {"char_count": 10}}]}
EOF
git add -A && git commit -q -m t1
run_case "T1 clean fixture: exit 0" "$GATE" --repo-root "$tmp"
cd /; rm -rf "$tmp"

# T2 forbidden raw-text field
fresh_repo
cat > external_testbase_v1.json <<'EOF'
{"manifest": {"row_count": 1}, "rows": [{"case_id": "abc123", "source_id": "se-42", "license": "CC BY-SA 4.0", "text": "How do I configure my router?"}]}
EOF
git add -A && git commit -q -m t2
run_case_fail "T2 raw text field: exit 1" "$GATE" --repo-root "$tmp"
cd /; rm -rf "$tmp"

# T3 missing source_id/license
fresh_repo
cat > external_testbase_v1.json <<'EOF'
{"manifest": {"row_count": 1}, "rows": [{"case_id": "abc123", "features": {"char_count": 10}}]}
EOF
git add -A && git commit -q -m t3
run_case_fail "T3 missing source_id/license: exit 1" "$GATE" --repo-root "$tmp"
cd /; rm -rf "$tmp"

# T4 raw-dump-named file, not marked synthetic
fresh_repo
mkdir -p some/site.stackexchange.com
printf '<row Id="1" PostTypeId="1" Body="x"/>\n' > some/site.stackexchange.com/Posts.xml
git add -A && git commit -q -m t4
run_case_fail "T4 unmarked Posts.xml tracked: exit 1" "$GATE" --repo-root "$tmp"
cd /; rm -rf "$tmp"

# T5 tiny synthetic fixture under cap
fresh_repo
mkdir -p tests/fixtures/goa/synthetic
printf '<row Id="1" PostTypeId="1" Body="x" Tags="&lt;causality&gt;"/>\n' > "tests/fixtures/goa/synthetic/Posts.xml"
git add -A && git commit -q -m t5
run_case "T5 tiny marked-synthetic Posts.xml: exit 0" "$GATE" --repo-root "$tmp"
cd /; rm -rf "$tmp"

# T6 oversized synthetic fixture over cap
fresh_repo
mkdir -p tests/fixtures/goa/synthetic
python3 -c "print('<row Id=\"1\" PostTypeId=\"1\" Body=\"' + ('x' * 9000) + '\"/>')" > "tests/fixtures/goa/synthetic/Posts.xml"
git add -A && git commit -q -m t6
run_case_fail "T6 oversized marked-synthetic fixture: exit 1" "$GATE" --repo-root "$tmp"
cd /; rm -rf "$tmp"

# T7 nothing to check
fresh_repo
printf 'hello\n' > README.md
git add -A && git commit -q -m t7
run_case "T7 no fixture/dump files: exit 0" "$GATE" --repo-root "$tmp"
cd /; rm -rf "$tmp"

echo "goa-no-raw-text-gate regression: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

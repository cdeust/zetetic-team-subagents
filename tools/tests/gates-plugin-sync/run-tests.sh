#!/usr/bin/env bash
# gates-plugin-sync — drift guard for the zetetic-gates micro-plugin.
#
# The micro-plugin at plugins/zetetic-gates/ ships COPIES of the enforcement
# engine (a marketplace plugin only ships files under its own directory, so it
# cannot reference ../../tools at install time). Copies drift silently; this
# suite fails CI the moment a canonical gate file and its plugin copy diverge,
# forcing every gate change to update both.
#
# plugins/zetetic-gates/hooks/pre-commit-zetetic.sh is deliberately NOT in the
# byte-identical set: it is an adaptation (drops the full plugin's repo-specific
# difficulty-book and routing-table steps). It gets syntax + contract checks.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
GATES="$REPO_ROOT/plugins/zetetic-gates"

pass=0
fail=0

ok()   { echo "  ok   $1"; pass=$((pass + 1)); }
bad()  { echo "  FAIL $1" >&2; fail=$((fail + 1)); }

check_identical() {
  local canonical="$1" copy="$2"
  if [[ ! -f "$REPO_ROOT/$canonical" ]]; then
    bad "$canonical: canonical file missing"
    return
  fi
  if [[ ! -f "$GATES/$copy" ]]; then
    bad "plugins/zetetic-gates/$copy: plugin copy missing"
    return
  fi
  if cmp -s "$REPO_ROOT/$canonical" "$GATES/$copy"; then
    ok "$canonical == plugins/zetetic-gates/$copy"
  else
    bad "$canonical drifted from plugins/zetetic-gates/$copy — re-copy the canonical file"
  fi
}

# Byte-identical set: canonical path -> plugin-relative copy path.
check_identical "tools/zetetic-checker.sh"            "tools/zetetic-checker.sh"
check_identical "tools/craftsmanship-checker.sh"      "tools/craftsmanship-checker.sh"
check_identical "tools/lib/craftsmanship-detectors.sh" "tools/lib/craftsmanship-detectors.sh"
check_identical "hooks/pre-tool-secret-shield.py"     "hooks/pre-tool-secret-shield.py"
check_identical "hooks/run-python.sh"                 "hooks/run-python.sh"
check_identical ".craftsmanship.conf.example"         ".craftsmanship.conf.example"

# Adapted hook: must exist and parse.
if bash -n "$GATES/hooks/pre-commit-zetetic.sh" 2>/dev/null; then
  ok "hooks/pre-commit-zetetic.sh (adapted) parses"
else
  bad "hooks/pre-commit-zetetic.sh (adapted) missing or has syntax errors"
fi

# Plugin manifest: valid JSON with the fields the marketplace requires.
MANIFEST="$GATES/.claude-plugin/plugin.json"
if command -v jq >/dev/null 2>&1; then
  if jq -e '.name == "zetetic-gates" and (.version | length > 0) and .hooks == "./hooks/gates.json"' "$MANIFEST" >/dev/null 2>&1; then
    ok "plugin.json valid (name, version, shared hook manifest)"
  else
    bad "plugin.json invalid or missing required fields"
  fi
else
  echo "  skip plugin.json check (jq not installed)"
fi

python3 "$REPO_ROOT/scripts/sync-gates.py" --check

# Marketplace registration: the micro-plugin must be listed at the root.
if command -v jq >/dev/null 2>&1; then
  if jq -e '.plugins[] | select(.name == "zetetic-gates")' "$REPO_ROOT/.claude-plugin/marketplace.json" >/dev/null 2>&1; then
    ok "zetetic-gates registered in .claude-plugin/marketplace.json"
  else
    bad "zetetic-gates missing from .claude-plugin/marketplace.json"
  fi
fi

echo ""
echo "gates-plugin-sync result: $pass passed, $fail failed"
if [[ $fail -gt 0 ]]; then
  echo "gates-plugin-sync FAILED" >&2
  exit 1
fi
echo "gates-plugin-sync PASSED"

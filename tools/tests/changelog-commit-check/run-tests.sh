#!/usr/bin/env bash
# Regression suite for tools/changelog-commit-check.sh (v2.37.0 postmortem:
# CHANGELOG.md silently stopped tracking 14 of 30 post-release commits).
#
# The gate's whole value is that it FAILS closed when a feat:/fix:/sec:/perf:
# commit since the latest tag has no PR-number citation in CHANGELOG.md's
# unreleased content, and it must NOT fire on docs:/chore: commits or on
# commits already cited. Builds a throwaway git repository per case (the
# checker walks real `git tag`/`git log`, so it cannot be pointed at fixture
# text alone) and never touches this repo's own history or CHANGELOG.md.

set -uo pipefail   # NOT -e: several cases expect the checker to exit non-zero.

SUITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SUITE_DIR/../../.." && pwd)"
CHECKER="$REPO_ROOT/tools/changelog-commit-check.sh"

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }

# make_repo: a fresh git repo with an initial commit, tag v1.0.0, and a
# CHANGELOG.md containing only that tag's section (nothing unreleased yet).
make_repo() {
  local dir="$1"
  git init -q "$dir"
  (
    cd "$dir" || exit 1
    git config user.email test@example.com
    git config user.name Test
    cat > CHANGELOG.md <<'EOF'
# Changelog

## [Unreleased]

## [1.0.0]: initial release

### Added
- Initial release.
EOF
    git add CHANGELOG.md
    git commit -q -m "chore: initial release"
    git tag v1.0.0
  )
}

commit() {
  local dir="$1" subject="$2"
  (cd "$dir" && git commit -q --allow-empty -m "$subject")
}

run_checker() {
  local dir="$1"
  CCC_REPO_ROOT="$dir" bash "$CHECKER"
}

# ── Case 1: a feat: commit with no CHANGELOG entry at all must fail closed ──
d1="$(mktemp -d)"
make_repo "$d1"
commit "$d1" "feat(x): add a new capability (#42)"
out="$(run_checker "$d1" 2>&1)"; rc=$?
if [[ $rc -eq 1 ]] && grep -q '#42' <<<"$out" && grep -qi 'DRIFT' <<<"$out"; then
  ok "uncited feat: commit fails closed and names the exact PR"
else
  bad "uncited feat: commit did not fail as expected (rc=$rc): $out"
fi
rm -rf "$d1"

# ── Case 2: the same feat: commit, cited in CHANGELOG.md, must pass ─────────
d2="$(mktemp -d)"
make_repo "$d2"
commit "$d2" "feat(x): add a new capability (#42)"
(cd "$d2" && sed -i.bak 's/## \[Unreleased\]/## [Unreleased]\n\n### Added\n- New capability. (#42)/' CHANGELOG.md && git add CHANGELOG.md && git commit -q -m "docs(changelog): cite #42")
out="$(run_checker "$d2" 2>&1)"; rc=$?
if [[ $rc -eq 0 ]] && grep -qi 'PASSED' <<<"$out"; then
  ok "cited feat: commit passes"
else
  bad "cited feat: commit did not pass (rc=$rc): $out"
fi
rm -rf "$d2"

# ── Case 3: a docs: commit with no entry must NOT be required ──────────────
d3="$(mktemp -d)"
make_repo "$d3"
commit "$d3" "docs: reword the README intro (#43)"
out="$(run_checker "$d3" 2>&1)"; rc=$?
if [[ $rc -eq 0 ]] && grep -qi 'PASSED' <<<"$out"; then
  ok "uncited docs: commit is not required and the gate passes"
else
  bad "docs: commit was wrongly required (rc=$rc): $out"
fi
rm -rf "$d3"

# ── Case 4: a chore: commit with no entry must NOT be required ─────────────
d4="$(mktemp -d)"
make_repo "$d4"
commit "$d4" "chore(deps): bump a dependency (#44)"
out="$(run_checker "$d4" 2>&1)"; rc=$?
if [[ $rc -eq 0 ]] && grep -qi 'PASSED' <<<"$out"; then
  ok "uncited chore: commit is not required and the gate passes"
else
  bad "chore: commit was wrongly required (rc=$rc): $out"
fi
rm -rf "$d4"

# ── Case 5: a fix: commit with no (#NNN) in its own subject is unverifiable,
# and unverifiable fails closed rather than skipping. ─────────────────────
d5="$(mktemp -d)"
make_repo "$d5"
commit "$d5" "fix: correct a typo with no PR reference"
out="$(run_checker "$d5" 2>&1)"; rc=$?
if [[ $rc -eq 1 ]] && grep -qi 'DRIFT' <<<"$out"; then
  ok "fix: commit with no (#NNN) fails closed instead of being skipped"
else
  bad "fix: commit with no (#NNN) did not fail closed (rc=$rc): $out"
fi
rm -rf "$d5"

# ── Case 6: no tag in the repository at all must fail closed, not skip ─────
d6="$(mktemp -d)"
git init -q "$d6"
(cd "$d6" && git config user.email test@example.com && git config user.name Test && printf '# Changelog\n' > CHANGELOG.md && git add CHANGELOG.md && git commit -q -m "chore: init")
out="$(run_checker "$d6" 2>&1)"; rc=$?
if [[ $rc -eq 1 ]] && grep -qi 'no vX.Y.Z tag' <<<"$out"; then
  ok "no tag in the repository fails closed"
else
  bad "missing-tag case did not fail as expected (rc=$rc): $out"
fi
rm -rf "$d6"

# ── Case 7: sec: commits are required exactly like feat:/fix: ──────────────
d7="$(mktemp -d)"
make_repo "$d7"
commit "$d7" "sec(ci): pin a dependency by hash (#45)"
out="$(run_checker "$d7" 2>&1)"; rc=$?
if [[ $rc -eq 1 ]] && grep -q '#45' <<<"$out"; then
  ok "sec: commit is required like feat:/fix: and fails closed when uncited"
else
  bad "sec: commit was not required (rc=$rc): $out"
fi
rm -rf "$d7"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]

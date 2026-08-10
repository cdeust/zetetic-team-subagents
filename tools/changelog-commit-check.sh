#!/usr/bin/env bash
# changelog-commit-check.sh — every feat:/fix:/sec:/perf: commit since the
# latest release tag must be represented in CHANGELOG.md's not-yet-released
# content, cited by its own PR number.
#
# Why (release v2.37.0 postmortem): CHANGELOG.md's `## [Unreleased]` section
# stopped being updated after PR #89 landed. 14 of the 30 commits that
# followed v2.36.0 never got an entry, including three feat: PRs and four
# fix: PRs — one of them a security fix (hash-pinning a dependency install
# against a code-scanning alert). Nothing measured the gap, so it was silent
# until a release was cut by hand and the drift was counted. This measures it.
#
# The check: every commit since the latest `vX.Y.Z` tag whose conventional-
# commit type is feat, fix, sec or perf (a change a plugin USER can observe —
# a capability, a defect, an exposure, a regression) must have its own PR
# number, as it appears in the commit subject's trailing `(#NNN)`, cited
# literally as `#NNN` somewhere in CHANGELOG.md above that tag's own section
# header. docs:/chore:/ci:/test:/refactor: commits are not required (this
# repo does not itemize every doc tweak or dependency bump; several already
# ride along inside a combined bullet with no number at all, which is fine —
# they are not the class this gate exists to catch).
#
# FAIL CLOSED, deliberately, on every "cannot verify" path: no tag found, no
# section header for that tag, and a required commit with no `(#NNN)` in its
# own subject to check against are all exit 1, not a skip. A gate that lets
# an unmeasurable commit through silently is the exact failure mode this gate
# exists to close (§ the redaction/doc-count gates already fail this way).
#
# Usage:
#   bash tools/changelog-commit-check.sh
#
# Test injection point (used by tools/tests/changelog-commit-check): set
# CCC_REPO_ROOT to point the check at a throwaway fixture repository instead
# of the one this script lives in.
#
# Exit: 0 when every feat/fix/sec/perf commit since the latest tag is cited
# in CHANGELOG.md's unreleased content; 1 when any is missing or unverifiable;
# 2 on a usage/environment error (not a git repo, CHANGELOG.md missing).

set -uo pipefail

REPO_ROOT="${CCC_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_ROOT" || { echo "FATAL: cannot cd to repo root $REPO_ROOT" >&2; exit 2; }

CHANGELOG="CHANGELOG.md"
[[ -f "$CHANGELOG" ]] || { echo "FATAL: $CHANGELOG not found." >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "FATAL: not a git repository." >&2; exit 2; }

# ── Locate the latest release tag ───────────────────────────────────────
# Sorted by version, not by date: a backdated or out-of-order tag push must
# not silently widen or narrow the audited commit range.
latest_tag="$(git tag --list 'v*' --sort=-v:refname | head -n1)"
if [[ -z "$latest_tag" ]]; then
  echo "FAILED: no vX.Y.Z tag found; cannot bound the commit range to audit." >&2
  exit 1
fi
tag_version="${latest_tag#v}"

# ── Locate that tag's own section header, and the region above it ──────
# Everything strictly above "## [<tag_version>]" is not-yet-released:
# Unreleased plus any version section still awaiting a tag (e.g. the one
# this same PR is cutting). A missing header is unverifiable, not a pass —
# it is exactly the "changelog section vs. tag" invariant this repo already
# audits in the other direction.
header="## [${tag_version}]"
if ! grep -qF "$header" "$CHANGELOG"; then
  echo "FAILED: no '$header' section header in $CHANGELOG for the latest tag $latest_tag." >&2
  exit 1
fi
unreleased_region="$(awk -v marker="$header" 'index($0, marker) == 1 { exit } { print }' "$CHANGELOG")"

# ── Walk commits since the tag, filter to user-visible types ───────────
missing=0
checked=0
while IFS='|' read -r sha subject; do
  [[ -z "$sha" ]] && continue
  type="$(printf '%s' "$subject" | sed -E 's/^([A-Za-z]+)(\([^)]*\))?!?:.*/\1/')"
  case "$type" in
    feat|fix|sec|perf) : ;;
    *) continue ;;
  esac
  checked=$((checked + 1))

  pr="$(printf '%s' "$subject" | grep -oE '\(#[0-9]+\)' | tail -n1)"
  if [[ -z "$pr" ]]; then
    echo "DRIFT: ${sha:0:9} ($type) has no (#NNN) in its own subject, cannot verify changelog coverage: $subject" >&2
    missing=$((missing + 1))
    continue
  fi
  pr_number="${pr//[()#]/}"

  if ! grep -qF "#${pr_number}" <<<"$unreleased_region"; then
    echo "DRIFT: ${sha:0:9} $pr ($type) not cited in ${CHANGELOG}'s unreleased content: $subject" >&2
    missing=$((missing + 1))
  fi
done < <(git log "${latest_tag}..HEAD" --no-merges --format='%H|%s')

if [[ "$missing" -gt 0 ]]; then
  echo "FAILED: $missing of $checked feat/fix/sec/perf commit(s) since $latest_tag are not represented in $CHANGELOG." >&2
  exit 1
fi

echo "changelog-commit-check: $checked feat/fix/sec/perf commit(s) since $latest_tag checked, 0 missing."
echo "PASSED: every user-visible commit since $latest_tag is represented in $CHANGELOG."

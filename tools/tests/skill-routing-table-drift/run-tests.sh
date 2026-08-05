#!/usr/bin/env bash
# skill-routing-table-drift — regression suite for
# scripts/generate-skill-routing-table.py's --check anti-drift gate.
#
# GOA-DESIGN.md Phase 1 codegen note (lines 56-57/85-86): the shape-to-skill
# mapping is generated from each skill's `shapes:` frontmatter, not hand-wired.
# This suite proves the generator's --check mode actually catches drift
# between that frontmatter and the committed rules/skill-routing-table.md,
# using a synthetic temp repo (never the real tree) per the disk-exhaustion
# lesson recorded for goa-fixture-freeze-gate (worktree/temp-repo discipline,
# 2026-08-04) — everything under $tmp is created fresh and removed after each
# case, and the real worktree's own generated table is checked in T5 without
# ever being mutated.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
GEN="$REPO_ROOT/scripts/generate-skill-routing-table.py"

PASS=0; FAIL=0
ok()  { echo "  ok   $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL $1" >&2; FAIL=$((FAIL+1)); }

write_skill() {
  # write_skill <dir> <name> <shapes-csv> <description>
  local dir="$1" name="$2" shapes="$3" desc="$4"
  mkdir -p "$dir/skills/$name"
  cat > "$dir/skills/$name/SKILL.md" <<EOF
---
name: $name
shapes: [$shapes]
description: >
  $desc
---

# ${name}
EOF
}

fresh_repo() {
  tmp=$(mktemp -d)
  mkdir -p "$tmp/rules"
  write_skill "$tmp" alpha-shape "alpha-shape" "First synthetic shape for the drift suite."
  write_skill "$tmp" beta-shape  "beta-shape"  "Second synthetic shape for the drift suite."
}

# T1: fresh repo, table not yet generated -> --check fails (file absent)
fresh_repo
if ! python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T1 ungenerated table: --check exits 1"
else
  bad "T1 ungenerated table: --check exited 0, expected 1"
fi
rm -rf "$tmp"

# T2: fresh repo, table generated -> --check passes
fresh_repo
python3 "$GEN" --repo-root "$tmp" >/dev/null
if python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T2 freshly generated table: --check exits 0"
else
  bad "T2 freshly generated table: --check exited nonzero, expected 0"
fi
rm -rf "$tmp"

# T3: deliberate drift — edit a skill's shapes: frontmatter AFTER generating
# the table, without regenerating -> --check must fail.
fresh_repo
python3 "$GEN" --repo-root "$tmp" >/dev/null
sed -i.bak 's/shapes: \[alpha-shape\]/shapes: [alpha-shape, alpha-shape-alias]/' \
  "$tmp/skills/alpha-shape/SKILL.md"
rm -f "$tmp/skills/alpha-shape/SKILL.md.bak"
if ! python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T3 deliberate drift (shapes: changed, table stale): --check exits 1"
else
  bad "T3 deliberate drift: --check exited 0, expected 1"
fi

# T3-restore: regenerate from the drifted frontmatter -> --check passes again,
# proving the gate is a real drift detector, not a fixed fail.
python3 "$GEN" --repo-root "$tmp" >/dev/null
if python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T3-restore regenerated after drift: --check exits 0"
else
  bad "T3-restore regenerated after drift: --check exited nonzero, expected 0"
fi
rm -rf "$tmp"

# T4: description drift (frontmatter description edited, table not
# regenerated) -> --check must fail too, not just on shapes: changes.
fresh_repo
python3 "$GEN" --repo-root "$tmp" >/dev/null
sed -i.bak 's/First synthetic shape for the drift suite\./First synthetic shape, EDITED, for the drift suite./' \
  "$tmp/skills/alpha-shape/SKILL.md"
rm -f "$tmp/skills/alpha-shape/SKILL.md.bak"
if ! python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T4 description drift: --check exits 1"
else
  bad "T4 description drift: --check exited 0, expected 1"
fi
rm -rf "$tmp"

# T5: the real worktree's checked-in artifact must already be up to date —
# read-only, never mutates the real tree.
if python3 "$GEN" --check --repo-root "$REPO_ROOT" >/dev/null 2>&1; then
  ok "T5 real worktree rules/skill-routing-table.md: --check exits 0"
else
  bad "T5 real worktree rules/skill-routing-table.md: --check exited nonzero (regenerate it)"
fi

echo ""
echo "skill-routing-table-drift result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

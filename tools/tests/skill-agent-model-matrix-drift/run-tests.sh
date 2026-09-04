#!/usr/bin/env bash
# skill-agent-model-matrix-drift — regression suite for
# scripts/generate-skill-agent-model-matrix.py's --check anti-drift gate.
#
# Mirrors tools/tests/skill-routing-table-drift's shape: the matrix is a
# generated artifact (docs/skill-agent-model-matrix.md), never hand-edited,
# so a --check mode has to actually detect when a skill's `agents:`
# frontmatter or an agent's `model:` field moves without the doc being
# regenerated. Everything under $tmp is a synthetic fixture repo, removed
# after each case; the real worktree's own committed doc is checked in T4
# without ever being mutated.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
GEN="$REPO_ROOT/scripts/generate-skill-agent-model-matrix.py"

PASS=0; FAIL=0
ok()  { echo "  ok   $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL $1" >&2; FAIL=$((FAIL+1)); }

write_agent() {
  local dir="$1" name="$2" model="$3"
  mkdir -p "$dir/agents"
  cat > "$dir/agents/$name.md" <<EOF
---
name: $name
model: $model
---

# ${name}
EOF
}

write_skill() {
  local dir="$1" name="$2" agent="$3"
  mkdir -p "$dir/skills"
  cat > "$dir/skills/$name.md" <<EOF
---
name: $name
agents:
  - $agent
shapes: []
---

# ${name}
EOF
}

fresh_repo() {
  tmp=$(mktemp -d)
  write_agent "$tmp" opus-agent opus
  write_skill "$tmp" alpha-skill opus-agent
}

# T1: fresh repo, matrix not yet generated -> --check fails (file absent)
fresh_repo
if ! python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T1 ungenerated matrix: --check exits 1"
else
  bad "T1 ungenerated matrix: --check exited 0, expected 1"
fi
rm -rf "$tmp"

# T2: fresh repo, matrix generated -> --check passes
fresh_repo
python3 "$GEN" --repo-root "$tmp" >/dev/null
if python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T2 freshly generated matrix: --check exits 0"
else
  bad "T2 freshly generated matrix: --check exited nonzero, expected 0"
fi
rm -rf "$tmp"

# T3: deliberate drift -- an agent's model: tier changes after generating,
# without regenerating -> --check must fail.
fresh_repo
python3 "$GEN" --repo-root "$tmp" >/dev/null
sed -i.bak 's/model: opus/model: haiku/' "$tmp/agents/opus-agent.md"
rm -f "$tmp/agents/opus-agent.md.bak"
if ! python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T3 deliberate drift (model: changed, matrix stale): --check exits 1"
else
  bad "T3 deliberate drift: --check exited 0, expected 1"
fi
# T3-restore: regenerate from the drifted state -> --check passes again.
python3 "$GEN" --repo-root "$tmp" >/dev/null
if python3 "$GEN" --check --repo-root "$tmp" >/dev/null 2>&1; then
  ok "T3-restore regenerated after drift: --check exits 0"
else
  bad "T3-restore regenerated after drift: --check exited nonzero, expected 0"
fi
rm -rf "$tmp"

# T4: the real worktree's checked-in artifact must already be up to date --
# read-only, never mutates the real tree.
if python3 "$GEN" --check --repo-root "$REPO_ROOT" >/dev/null 2>&1; then
  ok "T4 real worktree docs/skill-agent-model-matrix.md: --check exits 0"
else
  bad "T4 real worktree docs/skill-agent-model-matrix.md: --check exited nonzero (regenerate it)"
fi

echo ""
echo "skill-agent-model-matrix-drift result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

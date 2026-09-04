#!/usr/bin/env bash
# skill-model-tier-policy — regression suite for tools/skill-runner.sh's
# model-tier escalation banner.
#
# Why this exists (agent-to-skill migration plan, Phase 1): skill-runner.sh
# resolves a skill and prints its Markdown body verbatim, with no mechanism
# to honor a referenced agent's `model:` frontmatter -- a skill whose
# `agents:` list names an opus-tier agent (e.g. skills/engineering/review.md
# -> architect, model: opus) silently loses that capability upgrade when run
# inline at whatever tier the calling session happens to be. This suite
# proves the runner's escalation banner fires exactly when it should: for an
# agent above the baseline tier, and never for one at or below it -- a test
# that only covers the positive case would let a "banner on everything"
# implementation pass just as easily as a correct one.
#
# Fixtures are built fresh under a synthetic temp repo per case (never the
# real tree), following the disk-exhaustion / worktree-discipline lesson
# recorded for goa-fixture-freeze-gate and used by
# tools/tests/skill-routing-table-drift.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUNNER="$REPO_ROOT/tools/skill-runner.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL $1" >&2; FAIL=$((FAIL+1)); }

BANNER="MODEL-TIER ESCALATION REQUIRED"

# write_agent <dir> <name> <model>
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

# write_skill <dir> <name> <agents-yaml-block>
write_skill() {
  local dir="$1" name="$2" agents_block="$3"
  mkdir -p "$dir/skills"
  {
    echo "---"
    echo "name: $name"
    echo "agents:"
    printf '%s\n' "$agents_block"
    echo "shapes: []"
    echo "---"
    echo ""
    echo "# ${name}"
    echo ""
    echo "## Procedure"
    echo "1. Do the thing."
  } > "$dir/skills/$name.md"
}

fresh_repo() {
  tmp=$(mktemp -d)
  write_agent "$tmp" opus-agent opus
  write_agent "$tmp" sonnet-agent sonnet
  write_agent "$tmp" fable-agent fable
  write_agent "$tmp" haiku-agent haiku
  write_skill "$tmp" escalating-skill $'  - opus-agent\n  - sonnet-agent'
  write_skill "$tmp" non-escalating-skill $'  - sonnet-agent\n  - haiku-agent'
  write_skill "$tmp" fable-escalating-skill $'  - fable-agent'
}

run_runner() {
  # run_runner <tmp> <skill-name>
  local tmp="$1" name="$2"
  ZETETIC_SKILLS="$tmp/skills" ZETETIC_AGENTS="$tmp/agents" bash "$RUNNER" "$name" 2>&1
}

# T1: a skill naming an opus-tier agent (above sonnet baseline) -> banner fires.
fresh_repo
out="$(run_runner "$tmp" escalating-skill)"
if grep -q "$BANNER" <<<"$out" && grep -q "opus-agent" <<<"$out"; then
  ok "T1 opus-tier agent: banner fires and names the agent"
else
  bad "T1 opus-tier agent: banner did not fire as expected"
fi
rm -rf "$tmp"

# T2 (negative case): a skill naming only sonnet/haiku agents (at or below
# baseline) -> no banner. This is the case a "banner on everything"
# implementation would fail.
fresh_repo
out="$(run_runner "$tmp" non-escalating-skill)"
if ! grep -q "$BANNER" <<<"$out"; then
  ok "T2 sonnet/haiku-only agents: no banner"
else
  bad "T2 sonnet/haiku-only agents: banner fired, expected none"
fi
rm -rf "$tmp"

# T3: fable-tier agent also escalates against the sonnet baseline (the
# ordering is by rank, not a hardcoded "opus only" check).
fresh_repo
out="$(run_runner "$tmp" fable-escalating-skill)"
if grep -q "$BANNER" <<<"$out" && grep -q "fable-agent" <<<"$out"; then
  ok "T3 fable-tier agent: banner fires and names the agent"
else
  bad "T3 fable-tier agent: banner did not fire for fable tier"
fi
rm -rf "$tmp"

# T4: baseline is configurable, not hardcoded to sonnet. With the baseline
# raised to opus, an opus-tier agent no longer escalates.
fresh_repo
out="$(ZETETIC_SKILL_BASELINE_MODEL=opus run_runner "$tmp" escalating-skill)"
if ! grep -q "$BANNER" <<<"$out"; then
  ok "T4 baseline raised to opus: opus-tier agent no longer escalates"
else
  bad "T4 baseline raised to opus: banner still fired, expected none"
fi
rm -rf "$tmp"

# T5: the banner prints before the procedure body, not after -- a caller
# reading top-down must see it before following the procedure.
fresh_repo
out="$(run_runner "$tmp" escalating-skill)"
banner_line="$(grep -n "$BANNER" <<<"$out" | head -1 | cut -d: -f1)"
procedure_line="$(grep -n "^## Procedure" <<<"$out" | head -1 | cut -d: -f1)"
if [[ -n "$banner_line" && -n "$procedure_line" && "$banner_line" -lt "$procedure_line" ]]; then
  ok "T5 banner precedes procedure body"
else
  bad "T5 banner did not precede procedure body (banner_line=$banner_line procedure_line=$procedure_line)"
fi
rm -rf "$tmp"

# T6: real-worktree sanity check, deterministic against THIS checkout's own
# skills/ and agents/ (not whatever happens to be installed at
# ~/.claude/skills on the machine running the suite) --
# skills/engineering/review.md names architect (opus) and must escalate.
out="$(ZETETIC_SKILLS="$REPO_ROOT/skills" ZETETIC_AGENTS="$REPO_ROOT/agents" bash "$RUNNER" review 2>&1)"
if grep -q "$BANNER" <<<"$out" && grep -q "architect" <<<"$out"; then
  ok "T6 real skills/engineering/review.md: escalation banner names architect"
else
  bad "T6 real skills/engineering/review.md: expected escalation banner naming architect"
fi

# T7: real-worktree negative sanity check --
# skills/research/literature-review.md names only research-scientist
# (sonnet) and must not escalate.
out="$(ZETETIC_SKILLS="$REPO_ROOT/skills" ZETETIC_AGENTS="$REPO_ROOT/agents" bash "$RUNNER" literature-review 2>&1)"
if ! grep -q "$BANNER" <<<"$out"; then
  ok "T7 real skills/research/literature-review.md: no escalation banner"
else
  bad "T7 real skills/research/literature-review.md: banner fired, expected none"
fi

echo ""
echo "skill-model-tier-policy result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

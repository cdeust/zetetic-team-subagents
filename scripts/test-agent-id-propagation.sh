#!/usr/bin/env bash
# test-agent-id-propagation.sh — Verify MEMORY_AGENT_ID is correctly set at
# every agent-spawn call path.
#
# Tests:
#   P1  Genius agent path:  spawn-agent.sh curie     → MEMORY_AGENT_ID=curie
#   P2  Genius agent path:  spawn-agent.sh feynman   → MEMORY_AGENT_ID=feynman
#   P3  Parent session fans out to curie:
#         parent MEMORY_AGENT_ID=feynman, spawns curie
#         → child MEMORY_AGENT_ID=curie (NOT feynman, NOT unknown)
#
# Invariants tested:
#   - MEMORY_AGENT_ID must equal the agent slug (basename of agent file without .md)
#   - MEMORY_AGENT_ID must not be "unknown"
#   - MEMORY_AGENT_ID must not be the parent's id when the parent is a different agent

set -euo pipefail

REPO="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
SPAWN="$REPO/scripts/spawn-agent.sh"

TMP="$(mktemp -d)"
# source: 2026-09-17 cleanup regression, tests/test_agent_id_cleanup.py.
# Every fixture repository and spawned worktree is owned by this directory.
trap 'rm -rf -- "$TMP"' EXIT

PASS_COUNT=0
FAIL_COUNT=0

pass() { printf "  \033[32mPASS\033[0m  %s\n" "$1"; (( PASS_COUNT++ )) || true; }
fail() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; (( FAIL_COUNT++ )) || true; }

# Helper: create a throwaway git repo, seeded with the given agent's
# definition file (so delegation-contract validation can resolve it), and
# return its path.
make_target_repo() {
  local t="$TMP/target-$1"
  local agent="$2"
  mkdir -p "$t/agents" "$t/agents/genius"
  if [[ -f "$REPO/agents/$agent.md" ]]; then
    cp "$REPO/agents/$agent.md" "$t/agents/$agent.md"
  elif [[ -f "$REPO/agents/genius/$agent.md" ]]; then
    cp "$REPO/agents/genius/$agent.md" "$t/agents/genius/$agent.md"
  fi
  git -C "$t" init -q -b main
  git -C "$t" add -A
  git -C "$t" commit -q -m init
  echo "$t"
}

# Helper: write a minimal valid delegation contract for the given agent
# against the given target repo, and return its path.
make_contract() {
  local t="$1" agent="$2"
  local c="$t.contract.json"
  cat >"$c" <<JSON
{
  "schema_version": "1.0.0",
  "agent": "$agent",
  "target_repo": "$t",
  "owned_paths": ["src/**"],
  "excluded_paths": [],
  "worktree_policy": "required",
  "push_authority": "forbidden",
  "handback_artifacts": ["branch_name", "commit_sha"],
  "acceptance_oracle": {"type": "test", "criterion": "smoke"},
  "model": "sonnet",
  "tool_grant": ["Read"],
  "checkpoint_policy": {"threshold_tokens": 180000, "scope": "$agent"}
}
JSON
  echo "$c"
}

# Helper: install a claude shim that records its MEMORY_AGENT_ID.
install_shim() {
  local shim_dir="$1" env_record="$2"
  mkdir -p "$shim_dir"
  cat >"$shim_dir/claude" <<EOF
#!/usr/bin/env bash
echo "\${MEMORY_AGENT_ID:-}" > "$env_record"
exit 0
EOF
  chmod +x "$shim_dir/claude"
}

# ── P1: Genius agent (curie) ─────────────────────────────────────────────────
echo "P1: genius agent path (curie)"
TARGET="$(make_target_repo team curie)"
CONTRACT="$(make_contract "$TARGET" curie)"
SHIM="$TMP/shim-p1/bin"; ENV_REC="$TMP/shim-p1/env.txt"
install_shim "$SHIM" "$ENV_REC"
( cd "$TARGET"; PATH="$SHIM:$PATH" "$SPAWN" --contract "$CONTRACT" curie "dummy task" >/dev/null )
RECORDED="$(cat "$ENV_REC" 2>/dev/null || echo '')"
[[ "$RECORDED" == "curie" ]]  && pass "MEMORY_AGENT_ID=curie" \
                                  || fail "expected 'curie', got '$RECORDED'"
[[ "$RECORDED" != "unknown" ]]   && pass "not 'unknown'" \
                                  || fail "MEMORY_AGENT_ID is 'unknown'"

# ── P2: Genius agent (feynman) ────────────────────────────────────────────────
echo "P2: genius agent path (feynman)"
TARGET="$(make_target_repo genius feynman)"
CONTRACT="$(make_contract "$TARGET" feynman)"
SHIM="$TMP/shim-p2/bin"; ENV_REC="$TMP/shim-p2/env.txt"
install_shim "$SHIM" "$ENV_REC"
( cd "$TARGET"; PATH="$SHIM:$PATH" "$SPAWN" --contract "$CONTRACT" feynman "dummy task" >/dev/null )
RECORDED="$(cat "$ENV_REC" 2>/dev/null || echo '')"
[[ "$RECORDED" == "feynman" ]]   && pass "MEMORY_AGENT_ID=feynman" \
                                  || fail "expected 'feynman', got '$RECORDED'"
[[ "$RECORDED" != "unknown" ]]   && pass "not 'unknown'" \
                                  || fail "MEMORY_AGENT_ID is 'unknown'"

# ── P3: Parent session fans out to curie ────────────────────────────────────
# Precondition: parent process has MEMORY_AGENT_ID=feynman.
# Postcondition: the spawned curie process sees MEMORY_AGENT_ID=curie, NOT feynman.
echo "P3: a parent agent fans out to curie (parent id must not leak)"
TARGET="$(make_target_repo fanout curie)"
CONTRACT="$(make_contract "$TARGET" curie)"
SHIM="$TMP/shim-p3/bin"; ENV_REC="$TMP/shim-p3/env.txt"
install_shim "$SHIM" "$ENV_REC"
( cd "$TARGET"; export MEMORY_AGENT_ID="feynman"; PATH="$SHIM:$PATH" "$SPAWN" --contract "$CONTRACT" curie "dummy task" >/dev/null )
RECORDED="$(cat "$ENV_REC" 2>/dev/null || echo '')"
[[ "$RECORDED" == "curie" ]]       && pass "MEMORY_AGENT_ID=curie (overrides parent feynman)" \
                                       || fail "expected 'curie', got '$RECORDED'"
[[ "$RECORDED" != "feynman" ]]   && pass "parent slug 'feynman' did not leak" \
                                       || fail "child inherited parent's MEMORY_AGENT_ID=feynman"
[[ "$RECORDED" != "unknown" ]]        && pass "not 'unknown'" \
                                       || fail "MEMORY_AGENT_ID is 'unknown'"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
[[ "$FAIL_COUNT" -eq 0 ]] || exit 1

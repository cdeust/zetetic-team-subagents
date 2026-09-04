#!/usr/bin/env bash
# Basic test for spawn-agent.sh.
#
# Verifies, without hitting the Anthropic API:
#   1. missing argument fails with exit 2
#   2. missing/invalid delegation contract is denied BEFORE any worktree,
#      branch, or process mutation (HC-ZETETIC-004 fail-closed precondition)
#   3. unknown agent name (via a valid contract naming an unresolvable agent)
#      is denied with no worktree created
#   4. frontmatter stripping produces a non-empty body that excludes YAML keys
#   5. a VALID contract launches: worktree + branch created, claude invoked
#      with the expected flags, MEMORY_AGENT_ID propagated
#
# Strategy: shim `claude` on PATH with a recorder that dumps its argv to a file
# and exits 0. The real CLI is never called.

set -euo pipefail

REPO="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
SPAWN="$REPO/scripts/spawn-agent.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; [[ -n "${TARGET:-}" ]] && git -C "$TARGET" worktree list --porcelain 2>/dev/null | awk "/^worktree/ {print \$2}" | grep -v "^$TARGET\$" | xargs -I{} git -C "$TARGET" worktree remove --force {} 2>/dev/null || true; rm -rf "${TARGET:-}" "${TARGET:-}"-*' EXIT

pass() { printf "  \033[32mok\033[0m   %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m %s\n" "$1"; exit 1; }

worktree_count() {
  git -C "$TARGET" worktree list --porcelain 2>/dev/null | grep -c '^worktree' || true
}

# ---- Test 1: missing arg -----------------------------------------------------
echo "test: missing agent name exits 2"
set +e
"$SPAWN" --contract /nonexistent >/dev/null 2>&1
rc=$?
set -e
[[ $rc -eq 2 ]] && pass "exit 2" || fail "expected 2, got $rc"

# ---- Set up a throwaway target repo used by the remaining tests -------------
TARGET="$TMP/target-repo"
mkdir -p "$TARGET/agents"
git -C "$TARGET" init -q -b main
cp "$REPO/agents/engineer.md" "$TARGET/agents/engineer.md"
git -C "$TARGET" add -A
git -C "$TARGET" commit -q -m init

SHIM_DIR="$TMP/bin"
mkdir -p "$SHIM_DIR"
RECORD="$TMP/claude-argv.txt"
ENV_RECORD="$TMP/claude-env.txt"
cat >"$SHIM_DIR/claude" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" > "$RECORD"
echo "\${MEMORY_AGENT_ID:-}" > "$ENV_RECORD"
exit 0
EOF
chmod +x "$SHIM_DIR/claude"

VALID_CONTRACT="$TMP/valid-contract.json"
cat >"$VALID_CONTRACT" <<JSON
{
  "schema_version": "1.0.0",
  "agent": "engineer",
  "target_repo": "$TARGET",
  "owned_paths": ["src/**"],
  "excluded_paths": [],
  "worktree_policy": "required",
  "push_authority": "forbidden",
  "handback_artifacts": ["branch_name", "commit_sha"],
  "acceptance_oracle": {"type": "test", "criterion": "pytest tests/ -q exits 0"},
  "model": "sonnet",
  "tool_grant": ["Read", "Edit", "Bash"],
  "checkpoint_policy": {"threshold_tokens": 180000, "scope": "engineer"}
}
JSON

# ---- Test 2: no contract supplied -> denied, no worktree created ------------
echo "test: no contract supplied is denied before any mutation"
BEFORE="$(worktree_count)"
set +e
( cd "$TARGET" && PATH="$SHIM_DIR:$PATH" "$SPAWN" engineer "task" >/dev/null 2>&1 )
rc=$?
set -e
[[ $rc -ne 0 ]] || fail "expected non-zero exit with no contract, got 0"
[[ "$(worktree_count)" == "$BEFORE" ]] || fail "worktree was created despite missing contract"
pass "no contract -> deny, worktree count unchanged ($BEFORE)"

# ---- Test 3: unknown agent (valid contract, unresolvable agent name) -------
echo "test: unknown agent is denied, no worktree created"
UNKNOWN_CONTRACT="$TMP/unknown-agent-contract.json"
sed 's/"agent": "engineer"/"agent": "no-such-agent-xyz"/' "$VALID_CONTRACT" > "$UNKNOWN_CONTRACT"
BEFORE="$(worktree_count)"
set +e
( cd "$TARGET" && PATH="$SHIM_DIR:$PATH" "$SPAWN" --contract "$UNKNOWN_CONTRACT" no-such-agent-xyz "task" >/dev/null 2>&1 )
rc=$?
set -e
[[ $rc -ne 0 ]] || fail "expected non-zero exit for unknown agent, got 0"
[[ "$(worktree_count)" == "$BEFORE" ]] || fail "worktree was created despite unknown agent"
pass "unknown agent -> deny, worktree count unchanged ($BEFORE)"

# ---- Test 3b: schema-invalid contract is denied WITH an auditable reason ---
# Regression test for the `set -e` trap: `VAR="$(cmd)"` as a bare statement
# under `set -e` exits the script on `cmd`'s non-zero status AT the
# assignment line, before a subsequent `VAR_RC=$?; if [[ $VAR_RC -ne 0 ]];
# then echo ...` ever runs — so the exit code was already correct (1) but
# the "deny: ..." reason was silently swallowed. This asserts on stderr
# CONTENT, not just the exit code, so that regression cannot come back quiet.
echo "test: schema-invalid contract denies WITH a reason on stderr (not silently)"
INVALID_CONTRACT="$TMP/invalid-contract.json"
python3 - "$VALID_CONTRACT" "$INVALID_CONTRACT" <<'PY'
import json, sys
contract = json.load(open(sys.argv[1]))
del contract["push_authority"]  # schema-invalid: missing required field
json.dump(contract, open(sys.argv[2], "w"))
PY
BEFORE="$(worktree_count)"
set +e
DENY_OUTPUT="$( cd "$TARGET" && PATH="$SHIM_DIR:$PATH" "$SPAWN" --contract "$INVALID_CONTRACT" engineer "task" 2>&1 )"
rc=$?
set -e
[[ $rc -ne 0 ]] || fail "expected non-zero exit for schema-invalid contract, got 0"
[[ "$(worktree_count)" == "$BEFORE" ]] || fail "worktree was created despite schema-invalid contract"
grep -q "deny: delegation contract rejected" <<<"$DENY_OUTPUT" || fail "deny reason missing from stderr (set -e swallowed it): got: $DENY_OUTPUT"
grep -q "missing_required_field" <<<"$DENY_OUTPUT" || fail "validator's specific reason missing from stderr: got: $DENY_OUTPUT"
pass "deny reason present on stderr, worktree count unchanged ($BEFORE)"

# ---- Test 4: frontmatter stripping -------------------------------------------
echo "test: frontmatter stripping"
BODY="$(awk 'BEGIN{f=0} /^---$/{f++; next} f>=2{print}' "$REPO/agents/engineer.md")"
[[ -n "$BODY" ]]                                    || fail "body empty"
grep -q "^name: engineer" <<<"$BODY"                && fail "body still contains YAML 'name:'"
grep -q "You are the procedure" <<<"$BODY"           || fail "body missing identity text"
pass "frontmatter removed, identity preserved ($(wc -l <<<"$BODY" | tr -d ' ') lines)"

# ---- Test 5: end-to-end with a valid contract + claude shim -----------------
echo "test: worktree creation + claude invocation (shimmed, valid contract)"
(
  cd "$TARGET"
  PATH="$SHIM_DIR:$PATH" "$SPAWN" --contract "$VALID_CONTRACT" engineer "hello task" >/dev/null
)

[[ -f "$RECORD" ]] || fail "claude shim was not invoked"

# Check the recorded args.
grep -qx -- "--permission-mode"    "$RECORD" || fail "missing --permission-mode"
grep -qx -- "bypassPermissions"    "$RECORD" || fail "missing bypassPermissions value"
grep -qx -- "--append-system-prompt" "$RECORD" || fail "missing --append-system-prompt"
grep -qx -- "-p"                   "$RECORD" || fail "missing -p"
grep -qx -- "hello task"           "$RECORD" || fail "missing task string"
pass "claude invoked with correct flags"

# Verify MEMORY_AGENT_ID was exported into the shim environment.
[[ -f "$ENV_RECORD" ]] || fail "MEMORY_AGENT_ID env record not written by shim"
RECORDED_ID="$(cat "$ENV_RECORD")"
[[ "$RECORDED_ID" == "engineer" ]] || fail "MEMORY_AGENT_ID expected 'engineer', got '$RECORDED_ID'"
pass "MEMORY_AGENT_ID=engineer reached the spawned process"

# Verify worktree + branch were created.
WT="$(git -C "$TARGET" worktree list --porcelain | awk '/^worktree/ {print $2}' | grep -v "^$TARGET\$" | head -1)"
[[ -n "$WT" && -d "$WT" ]] || fail "worktree not created"
BR="$(git -C "$TARGET" branch --list 'agent/engineer/*' | head -1 | tr -d ' *')"
[[ -n "$BR" ]] || fail "agent branch not created"
pass "worktree=$WT branch=$BR"

# Verify the active-contract lock was released after the (shimmed) agent exited.
[[ -d "$TARGET/.claude/delegation-locks" ]] && [[ -n "$(ls -A "$TARGET/.claude/delegation-locks" 2>/dev/null)" ]] && fail "delegation lock not released after exit"
pass "delegation lock released on exit"

echo
echo "all tests passed"

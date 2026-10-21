#!/usr/bin/env bash
# test-memory-e2e.sh — End-to-end integration test for the memory loop.
#
# Proves the full agent memory loop works across all invariants defined in
# memory/contract.md and scope-registry.json.
#
# Usage: bash scripts/test-memory-e2e.sh
# Exit code = number of failed invariants.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TOOL="$REPO_ROOT/tools/memory-tool.sh"
REGISTRY="$REPO_ROOT/memory/scope-registry.json"

export MEMORY_ROOT="/tmp/memtest-e2e-$$"
export MEMORY_REGISTRY="$REGISTRY"
MT_SYNC_ENABLED=0   # set to 1 only in I7 to test queue durability

PASS=0
FAIL=0

trap 'rm -rf "$MEMORY_ROOT"' EXIT

# ── helpers ───────────────────────────────────────────────────────────────────

pass() { echo "PASS  I${1}: ${2}"; PASS=$((PASS + 1)); }
fail() {
  echo "FAIL  I${1}: ${2}"
  echo "      stdout: $(echo "$3" | head -5 | sed 's/^/        /')"
  echo "      stderr: $(echo "$4" | head -5 | sed 's/^/        /')"
  FAIL=$((FAIL + 1))
}

mt() {
  # mt <agent_id> -- <args...>
  # MT_SYNC_ENABLED=1 forces sync ON (for I7); otherwise sync is disabled.
  local agent="$1"; shift
  shift  # consume --
  if [[ "${MT_SYNC_ENABLED:-0}" == "1" ]]; then
    env MEMORY_AGENT_ID="$agent" MEMORY_ROOT="$MEMORY_ROOT" \
      MEMORY_REGISTRY="$REGISTRY" \
      "$TOOL" "$@"
  else
    env MEMORY_AGENT_ID="$agent" MEMORY_ROOT="$MEMORY_ROOT" \
      MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 \
      "$TOOL" "$@"
  fi
}

# Wrap content in the mandatory description frontmatter (memory/contract.md §3.6:
# every .md memory file begins with a description: retrieval cue; the desc gate
# rejects bare content). Denial-path tests stay bare — ACL fires before the gate.
fm() { printf -- '---\ndescription: "e2e test fixture"\n---\n%s' "$1"; }

# ── I1: own-scope write is durable across a fresh shell ──────────────────────
test_i1() {
  local content="decision: use postgres"
  local out; out=$(mt engineer -- create /memories/engineer/decision-1.md "$(fm "$content")" 2>&1) || true
  local exit_code=$?

  if [[ $exit_code -ne 0 ]] || ! echo "$out" | grep -q "File created successfully"; then
    fail 1 "create own scope failed" "$out" ""
    return
  fi

  # Simulate fresh shell: new subshell with same MEMORY_ROOT (mt provides env)
  local view_out
  view_out=$(mt engineer -- view /memories/engineer/decision-1.md 2>&1)

  if echo "$view_out" | grep -q "$content"; then
    pass 1 "own-scope write durable across session boundary"
  else
    fail 1 "durable read failed; content not found" "$view_out" ""
  fi
}

# ── I2: strict_unknown_scope denies writes to unregistered scopes ─────────────
test_i2() {
  local out; out=$(mt _user -- create /memories/zzz-unknown/foo.md "data" 2>&1)
  local exit_code=$?

  local expected="Error: agent '_user' is not permitted to write scope '/memories/zzz-unknown'"
  if [[ $exit_code -eq 1 ]] && echo "$out" | grep -qF "$expected"; then
    pass 2 "strict_unknown_scope denies write to unregistered scope"
  else
    fail 2 "expected ACL error on unknown scope (exit=$exit_code)" "$out" ""
  fi
}

# ── I3: cross-agent ACL denial is real ───────────────────────────────────────
test_i3() {
  local out; out=$(mt architect -- create /memories/engineer/sneaky.md "stolen" 2>&1)
  local exit_code=$?

  local expected="Error: agent 'architect' is not permitted to write scope '/memories/engineer'"
  if [[ $exit_code -eq 1 ]] && echo "$out" | grep -qF "$expected"; then
    pass 3 "cross-agent write correctly denied"
  else
    fail 3 "expected cross-agent ACL denial (exit=$exit_code)" "$out" ""
  fi
}

# ── I4: genius agents share scope; cross-genius write logged as policy gap ───
test_i4() {
  # feynman writes under own subpath — allowed
  local out1; out1=$(mt feynman -- create /memories/genius/feynman/lesson.md "$(fm "feynman lesson")" 2>&1)
  local e1=$?

  # pearl writes under feynman subpath — also allowed by ACL (owners=*)
  local out2; out2=$(mt pearl -- create /memories/genius/feynman/stolen.md "$(fm "pearl wrote here")" 2>&1)
  local e2=$?

  if [[ $e1 -ne 0 ]] || ! echo "$out1" | grep -q "File created successfully"; then
    fail 4 "feynman write to genius/feynman failed" "$out1" ""
    return
  fi
  if [[ $e2 -ne 0 ]] || ! echo "$out2" | grep -q "File created successfully"; then
    fail 4 "pearl write to genius/feynman failed (should be allowed by ACL)" "$out2" ""
    return
  fi

  # Both writes exist — verify audit log has both
  local audit_out; audit_out=$(mt _user -- audit 2>&1)
  local feynman_logged; feynman_logged=$(echo "$audit_out" | grep "feynman" | grep "genius" | wc -l | tr -d ' ')
  local pearl_logged;   pearl_logged=$(echo "$audit_out"   | grep "pearl"   | grep "genius" | wc -l | tr -d ' ')

  if [[ "$feynman_logged" -ge 1 && "$pearl_logged" -ge 1 ]]; then
    echo "      POLICY NOTE I4: cross-genius write by 'pearl' to genius/feynman is ACL-permitted but violates slug convention — curator should review audit."
    pass 4 "genius scope writes both auditable; cross-slug write detectable by curator"
  else
    fail 4 "audit did not surface both genius writes (feynman=$feynman_logged pearl=$pearl_logged)" "$audit_out" ""
  fi
}

# ── I5: quarantine — any agent writes, only curator reads ────────────────────
test_i5() {
  # engineer writes to quarantine — owners=* so allowed
  local out1; out1=$(mt engineer -- create /memories/quarantine/pr-123-summary.md "$(fm "summary")" 2>&1)
  local e1=$?
  if [[ $e1 -ne 0 ]] || ! echo "$out1" | grep -q "File created successfully"; then
    fail 5 "engineer write to quarantine failed (should be allowed)" "$out1" ""
    return
  fi

  # engineer tries to VIEW quarantine — readers=[_user, _curator] → denied
  local out2; out2=$(mt engineer -- view /memories/quarantine/pr-123-summary.md 2>&1)
  local e2=$?
  local expected_deny="Error: agent 'engineer' is not permitted to read scope '/memories/quarantine'"
  if [[ $e2 -ne 1 ]] || ! echo "$out2" | grep -qF "$expected_deny"; then
    fail 5 "engineer read quarantine should be denied (exit=$e2)" "$out2" ""
    return
  fi

  # _user views quarantine — should succeed
  local out3; out3=$(mt _user -- view /memories/quarantine/pr-123-summary.md 2>&1)
  local e3=$?
  if [[ $e3 -eq 0 ]] && echo "$out3" | grep -q "summary"; then
    pass 5 "quarantine: engineer write allowed, engineer read denied, _user read allowed"
  else
    fail 5 "_user read quarantine failed (exit=$e3)" "$out3" ""
  fi
}

# ── I6: TTL sweep deletes expired files and nothing else ─────────────────────
test_i6() {
  # Create two session files
  mt _user -- create /memories/session/old.md "$(fm "old content")" >/dev/null 2>&1
  mt _user -- create /memories/session/new.md "$(fm "new content")" >/dev/null 2>&1

  # Forcibly backdate old.md to 2 days ago (session TTL=1 day)
  local old_path="$MEMORY_ROOT/session/old.md"
  python3 -c "
import os, time
two_days_ago = time.time() - (2 * 86400)
os.utime('$old_path', (two_days_ago, two_days_ago))
"

  local sweep_out; sweep_out=$(mt _user -- ttl-sweep 2>&1)
  local sweep_exit=$?

  local old_exists=0; [[ -f "$old_path" ]] && old_exists=1
  local new_path="$MEMORY_ROOT/session/new.md"
  local new_exists=0; [[ -f "$new_path" ]] && new_exists=1

  local audit_out; audit_out=$(mt _user -- audit 2>&1)
  local ttl_entries; ttl_entries=$(echo "$audit_out" | grep "ttl_expire" | wc -l | tr -d ' ')

  if [[ $sweep_exit -eq 0 && $old_exists -eq 0 && $new_exists -eq 1 && "$ttl_entries" -ge 1 ]]; then
    pass 6 "TTL sweep expired old.md, preserved new.md, audit has ttl_expire entry"
  else
    fail 6 "TTL sweep incorrect (old_exists=$old_exists new_exists=$new_exists ttl_entries=$ttl_entries exit=$sweep_exit)" "$sweep_out" "$audit_out"
  fi
}

# ── I7: queue drain is durable across fake failure ───────────────────────────
test_i7() {
  # Temporarily enable sync so enqueue_sync runs
  MT_SYNC_ENABLED=1

  mt engineer -- create /memories/engineer/sync-test.md "$(fm "sync content")" >/dev/null 2>&1

  # Drain — get job id (mt now exports correct env)
  local drained; drained=$(mt engineer -- drain-sync --limit 1 2>&1)
  local job_id; job_id=$(echo "$drained" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])" 2>/dev/null || true)

  if [[ -z "$job_id" ]]; then
    MT_SYNC_ENABLED=0
    fail 7 "drain-sync returned no job id" "$drained" ""
    return
  fi

  # Simulate failure: release back to queue
  mt engineer -- release-sync "$job_id" >/dev/null 2>&1

  # Re-drain — job must reappear
  local drained2; drained2=$(mt engineer -- drain-sync --limit 1 2>&1)
  local job_id2; job_id2=$(echo "$drained2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])" 2>/dev/null || true)

  if [[ -z "$job_id2" || "$job_id2" != "$job_id" ]]; then
    MT_SYNC_ENABLED=0
    fail 7 "job did not reappear after release (id2=$job_id2)" "$drained2" ""
    return
  fi

  # Commit — job gone
  mt engineer -- commit-sync "$job_id" >/dev/null 2>&1

  # Drain again — must be empty
  local drained3; drained3=$(mt engineer -- drain-sync --limit 1 2>&1)

  MT_SYNC_ENABLED=0

  if [[ -z "$(echo "$drained3" | tr -d '[:space:]')" ]]; then
    pass 7 "queue drain is durable: release requeues, commit removes, second drain empty"
  else
    fail 7 "queue not empty after commit" "$drained3" ""
  fi
}

# ── I8: path traversal rejected before any FS touch ──────────────────────────
test_i8() {
  local errors=0

  # Case 1: classic traversal
  local out1; out1=$(mt _user -- view "/memories/../etc/passwd" 2>&1); local e1=$?
  if [[ $e1 -ne 1 ]] || ! echo "$out1" | grep -qF "Error: path must begin with /memories"; then
    echo "      SUBCASE FAIL: ../etc/passwd (exit=$e1): $out1"
    errors=$((errors + 1))
  fi

  # Case 2: dot segment
  local out2; out2=$(mt _user -- view "/memories/./session/x" 2>&1); local e2=$?
  if [[ $e2 -ne 1 ]] || ! echo "$out2" | grep -qF "Error: path must begin with /memories"; then
    echo "      SUBCASE FAIL: ./session/x (exit=$e2): $out2"
    errors=$((errors + 1))
  fi

  # Case 3: wrong root prefix
  local out3; out3=$(mt _user -- view "/memoriesX/foo" 2>&1); local e3=$?
  if [[ $e3 -ne 1 ]] || ! echo "$out3" | grep -qF "Error: path must begin with /memories"; then
    echo "      SUBCASE FAIL: /memoriesX/foo (exit=$e3): $out3"
    errors=$((errors + 1))
  fi

  if [[ $errors -eq 0 ]]; then
    pass 8 "all three path traversal variants rejected before FS touch"
  else
    fail 8 "$errors/3 traversal subcases not rejected correctly" "" ""
  fi
}

# ── I9: audit anomaly detection on 6 consecutive acl_denied ──────────────────
test_i9() {
  # Generate 6 consecutive acl_denied from architect hitting engineer scope
  for i in $(seq 1 6); do
    mt architect -- create "/memories/engineer/probe-$i.md" "x" >/dev/null 2>&1 || true
  done

  local audit_out; audit_out=$(mt _user -- audit 2>&1)

  if echo "$audit_out" | grep -q "\[ANOMALY\]" && \
     echo "$audit_out" | grep -q "architect" && \
     echo "$audit_out" | grep -q "acl_denied"; then
    pass 9 "audit surfaces anomaly after 5+ consecutive acl_denied from same agent"
  else
    fail 9 "audit did not flag anomaly for architect's repeated denials" "$audit_out" ""
  fi
}

# ── I10: lessons scope — engineer denied, orchestrator (curator) allowed ──────
test_i10() {
  # engineer create → denied
  local out1; out1=$(mt engineer -- create /memories/lessons/foo.md "eng lesson" 2>&1)
  local e1=$?
  local expected_deny="Error: agent 'engineer' is not permitted to write scope '/memories/lessons'"
  if [[ $e1 -ne 1 ]] || ! echo "$out1" | grep -qF "$expected_deny"; then
    fail 10 "engineer write to lessons should be denied (exit=$e1)" "$out1" ""
    return
  fi

  # orchestrator create → allowed (curator_agents includes orchestrator)
  local out2; out2=$(mt orchestrator -- create /memories/lessons/foo.md "$(fm "orch lesson")" 2>&1)
  local e2=$?
  if [[ $e2 -ne 0 ]] || ! echo "$out2" | grep -q "File created successfully"; then
    fail 10 "orchestrator write to lessons failed (exit=$e2)" "$out2" ""
    return
  fi

  # Both results visible in audit
  local audit_out; audit_out=$(mt _user -- audit 2>&1)
  local eng_denied;  eng_denied=$(echo "$audit_out"  | grep "engineer"    | grep "acl_denied" | grep "lessons" | wc -l | tr -d ' ')
  local orch_ok;     orch_ok=$(echo "$audit_out"     | grep "orchestrator" | grep " ok "      | grep "lessons" | wc -l | tr -d ' ')

  if [[ "$eng_denied" -ge 1 && "$orch_ok" -ge 1 ]]; then
    pass 10 "lessons scope: engineer denied, orchestrator allowed, both in audit"
  else
    fail 10 "audit entries missing (eng_denied=$eng_denied orch_ok=$orch_ok)" "$audit_out" ""
  fi
}

# ── I11: desc gate — bare .md content rejected with desc_missing audit ───────
test_i11() {
  local out; out=$(mt engineer -- create /memories/engineer/bare.md "no frontmatter here" 2>&1)
  local e=$?
  local audit_out; audit_out=$(mt engineer -- audit 2>&1)
  local gate_entries; gate_entries=$(echo "$audit_out" | grep -c "desc_missing" || true)

  if [[ $e -ne 0 ]] && echo "$out" | grep -q "require YAML frontmatter" && [[ "$gate_entries" -ge 1 ]]; then
    pass 11 "desc gate rejects bare .md content and audits desc_missing"
  else
    fail 11 "desc gate did not fire (exit=$e gate_entries=$gate_entries)" "$out" ""
  fi
}

# ── I12: `_user` has a registered home scope (issue #31) ─────────────────────
# The checkpoint protocol (token-budget.md, hooks/stop-context-guard.py,
# the checkpoint protocol's "primary path") defaults MEMORY_AGENT_ID to `_user` for
# the top-level interactive session and prescribes writing its own checkpoint
# to /memories/_user/checkpoint.md — the same own-scope pattern every team
# agent gets (I1). Unlike team agents, `_user` had no `_user` entry in
# scope-registry.json, so strict_unknown_scope (I2) denied it unconditionally.
# This must succeed exactly like I1 does for `engineer`.
test_i12() {
  local content="checkpoint: session at 42% context"
  local out; out=$(mt _user -- create /memories/_user/checkpoint.md "$(fm "$content")" 2>&1)
  local exit_code=$?

  if [[ $exit_code -ne 0 ]] || ! echo "$out" | grep -q "File created successfully"; then
    fail 12 "_user create own scope failed (exit=$exit_code)" "$out" ""
    return
  fi

  local rethink_out
  rethink_out=$(mt _user -- rethink /memories/_user/checkpoint.md "$(fm "checkpoint: session at 60% context")" 2>&1)
  local rethink_exit=$?

  if [[ $rethink_exit -ne 0 ]] || ! echo "$rethink_out" | grep -q "File rewritten successfully"; then
    fail 12 "_user rethink own scope failed (exit=$rethink_exit)" "$rethink_out" ""
    return
  fi

  # Cross-agent isolation must still hold: engineer must NOT be able to write
  # into _user's scope (own-scope grant is not a backdoor to a shared scope).
  local cross_out; cross_out=$(mt engineer -- create /memories/_user/sneaky.md "$(fm "stolen")" 2>&1)
  local cross_exit=$?
  local expected_deny="Error: agent 'engineer' is not permitted to write scope '/memories/_user'"

  if [[ $cross_exit -eq 1 ]] && echo "$cross_out" | grep -qF "$expected_deny"; then
    pass 12 "_user own-scope write/rethink durable; cross-agent write into _user still denied"
  else
    fail 12 "expected cross-agent denial into _user scope (exit=$cross_exit)" "$cross_out" ""
  fi
}

# ── main runner ───────────────────────────────────────────────────────────────

echo "=== Memory E2E Integration Test ==="
echo "MEMORY_ROOT    : $MEMORY_ROOT"
echo "MEMORY_REGISTRY: $MEMORY_REGISTRY"
echo "TOOL           : $TOOL"
echo ""

test_i1
test_i2
test_i3
test_i4
test_i5
test_i6
test_i7
test_i8
test_i9
test_i10
test_i11
test_i12

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
exit "$FAIL"

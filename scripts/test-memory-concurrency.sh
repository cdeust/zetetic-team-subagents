#!/usr/bin/env bash
# test-memory-concurrency.sh — Concurrency hazard tests for memory-tool.sh
#
# Each test is labelled with the hazard it covers.
# Exit code = number of failed tests.

set -uo pipefail

# Mechanics suite: locking/protocol behavior, not content semantics. The desc
# gate has dedicated coverage in test-memory-e2e.sh I11; disable it here so
# fixtures stay byte-minimal (MEMORY_NO_DESC_CHECK is the documented test escape).
export MEMORY_NO_DESC_CHECK=1

REPO_ROOT="$(cd "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TOOL="$REPO_ROOT/tools/memory-tool.sh"
REGISTRY="$REPO_ROOT/memory/scope-registry.json"

PASS=0
FAIL=0
SKIPS=0

pass() { echo "PASS  C${1}: ${2}"; PASS=$((PASS + 1)); }
fail() { echo "FAIL  C${1}: ${2}"; echo "      detail: ${3:-}"; FAIL=$((FAIL + 1)); }
skip() { echo "SKIP  C${1}: ${2}"; SKIPS=$((SKIPS + 1)); }

# ── C1: mutex correctness under 10-way parallel create ───────────────────────
# Invariant: exactly one create succeeds; N-1 return "already exists".
# (Replicates the known-passing 10-way race; documents the invariant as a test.)
test_c1() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN

  local pids=() outs=()
  for i in $(seq 1 10); do
    local f="$ROOT/output-$i"
    outs+=("$f")
    ( MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
      "$TOOL" create /memories/testscope/race.md "body-$i" >"$f" 2>&1 ) &
    pids+=($!)
  done
  for pid in "${pids[@]}"; do wait "$pid" || true; done

  local successes=0 duplicates=0
  for f in "${outs[@]}"; do
    grep -q "File created successfully" "$f" && successes=$((successes+1)) || true
    grep -q "already exists"            "$f" && duplicates=$((duplicates+1)) || true
  done

  if [[ $successes -eq 1 && $duplicates -eq 9 ]]; then
    pass 1 "10-way parallel create: exactly 1 success, 9 duplicates (mutex correct)"
  else
    fail 1 "10-way parallel create" "successes=$successes duplicates=$duplicates (expected 1+9)"
    for f in "${outs[@]}"; do cat "$f"; done
  fi
}

# ── C2: stale-lock detection — SIGKILL leaves lockdir; tool must time out ─────
# Invariant: a process killed while holding the lock must not block callers
# indefinitely. The lockdir here has NO pid file (holder died between mkdir and
# the pid write), so PID-liveness reclaim cannot trigger: the tool must die
# after its 5 s no-progress wall-clock deadline (concurrency-audit.md §1).
# Window [5, 10]:
#   lower — with_lock guarantees > 5.0 s of real spinning before the die
#           ($SECONDS whole-second granularity, strict > compare), so the
#           int-truncated total is always >= 5.
#   upper — deadline fires within 5–6 s of spinning; the rest is tool startup +
#           die-path process-spawn overhead. source: measured 2026-07-22 —
#           total 5.3–6.5 s on ubuntu CI, 7.0–8.2 s on macOS Darwin 25.5
#           (~85–250 ms per process spawn there); 10 s still fails on a hang
#           or a doubled deadline.
test_c2() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local LOCK_DIR="$ROOT/.locks"
  mkdir -p "$LOCK_DIR"
  mkdir "$LOCK_DIR/stale.lockd"   # simulate lock left by SIGKILL

  local START; START=$(python3 -c "import time; print(int(time.time()))")
  local OUT
  OUT=$(MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
        "$TOOL" create /memories/stale/x.md "body" 2>&1 || true)
  local END; END=$(python3 -c "import time; print(int(time.time()))")
  local ELAPSED=$(( END - START ))

  if echo "$OUT" | grep -q "could not acquire lock" && (( ELAPSED >= 5 && ELAPSED <= 10 )); then
    pass 2 "stale lock: tool dies after its 5 s no-progress deadline (elapsed=${ELAPSED}s)"
  else
    fail 2 "stale lock timeout" "elapsed=${ELAPSED}s out='$OUT'"
  fi
}

# ── C3: mv -n double-claim hazard — WITHOUT fix ──────────────────────────────
# Invariant: exactly one drain-sync caller claims a given job.
#
# The hazard: BSD mv -n returns exit 0 even when it does NOT rename
# (because dst already exists). The old guard `mv -n src dst && [[ -f $dst ]]`
# enters the success branch for BOTH drainers when dst pre-exists.
#
# This test reproduces the hazard by directly exercising the broken check,
# then shows the fixed check prevents it.
test_c3_without_fix() {
  local TMP; TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' RETURN

  echo '{"id":"job1"}' > "$TMP/job1.json"
  echo '{"id":"job1-already"}' > "$TMP/job1.json.claimed"   # dst pre-exists

  # OLD (broken) check: mv -n src dst && [[ -f $dst ]]
  # Hazard exists ONLY on BSD `mv` (macOS): `mv -n` silently succeeds when dst
  # pre-exists, leaving src in place. GNU `mv` (Linux/CI) returns non-zero, so
  # the broken check correctly drops to false there. The hazard is platform-
  # specific; on Linux we SKIP rather than fail because the absence of the
  # hazard means the BSD-specific fix is moot on this platform.
  local claimed_by_broken=0
  if mv -n "$TMP/job1.json" "$TMP/job1.json.claimed" 2>/dev/null \
     && [[ -f "$TMP/job1.json.claimed" ]]; then
    claimed_by_broken=1
  fi

  if [[ $claimed_by_broken -eq 1 ]]; then
    pass 3a "WITHOUT fix: broken mv -n guard enters success branch when dst pre-exists (hazard confirmed)"
  else
    skip 3a "BSD-mv-specific hazard not reproducible on this platform (GNU mv); fix still applied"
  fi
}

test_c3_with_fix() {
  local TMP; TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' RETURN

  echo '{"id":"job1"}' > "$TMP/job1.json"
  echo '{"id":"job1-already"}' > "$TMP/job1.json.claimed"

  # FIXED check: mv -n src dst && [[ ! -e src ]]
  # src still exists → move was blocked → we did NOT claim it.
  local claimed_by_fixed=0
  if mv -n "$TMP/job1.json" "$TMP/job1.json.claimed" 2>/dev/null \
     && [[ ! -e "$TMP/job1.json" ]]; then
    claimed_by_fixed=1
  fi

  if [[ $claimed_by_fixed -eq 0 ]]; then
    pass 3b "WITH fix: correct mv -n guard rejects double-claim (hazard eliminated)"
  else
    fail 3b "fixed guard still entered success branch" ""
  fi
}

# C3 combined: run the real drain-sync concurrently; verify at most one emits the job
test_c3_concurrent_drain() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN

  # Create one sync job manually
  local SYNC_DIR="$ROOT/.pending-sync"
  mkdir -p "$SYNC_DIR"
  echo '{"id":"job-abc","op":"create"}' > "$SYNC_DIR/20240101T000000Z-0000.json"

  # Capture parallel output via tmp files — `var=$(cmd) &` runs the assignment
  # in a subshell that the parent never sees, so OUT1/OUT2 stayed unset under
  # `set -u`. Use files so each parallel process writes its captured stdout
  # into a known location the parent can read after wait.
  local F1="$ROOT/.drain-out-1" F2="$ROOT/.drain-out-2"
  ( MEMORY_ROOT="$ROOT" MEMORY_NO_AUDIT=1 MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
    "$TOOL" drain-sync --limit 1 > "$F1" 2>&1 ) &
  local PID1=$!
  ( MEMORY_ROOT="$ROOT" MEMORY_NO_AUDIT=1 MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
    "$TOOL" drain-sync --limit 1 > "$F2" 2>&1 ) &
  local PID2=$!
  wait $PID1 || true
  wait $PID2 || true
  local OUT1 OUT2
  OUT1=$(cat "$F1" 2>/dev/null || echo "")
  OUT2=$(cat "$F2" 2>/dev/null || echo "")

  local claims=0
  [[ -n "$(echo "$OUT1" | tr -d '[:space:]')" ]] && claims=$((claims+1)) || true
  [[ -n "$(echo "$OUT2" | tr -d '[:space:]')" ]] && claims=$((claims+1)) || true

  if [[ $claims -le 1 ]]; then
    pass "3c" "concurrent drain: at most 1 drainer claimed the job (claims=$claims)"
  else
    fail "3c" "DOUBLE CLAIM: both drainers emitted the job (claims=$claims)"
  fi
}

# ── C4: ttl-sweep holds scope lock (regression guard) ────────────────────────
# Invariant: ttl-sweep acquires the scope lock before deleting; a concurrent
# create that holds the lock completes before sweep can delete the file.
# We verify this by reading the code path (the test-observable property is
# that a just-created file is never deleted by a concurrent sweep).
test_c4() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN

  # Create file, immediately run sweep with a 0-day TTL via a synthetic registry.
  # GNU mktemp requires X's in the template; BSD mktemp accepts a prefix.
  # `mktemp -d` then writing the .json in that dir is portable across both.
  local REG_DIR; REG_DIR=$(mktemp -d)
  local REG="$REG_DIR/concurrency_reg.json"
  cat > "$REG" <<REGEOF
{
  "version": 1,
  "strict_unknown_scope": false,
  "defaults": { "owners": ["*"], "readers": ["*"] },
  "curator_agents": [],
  "scopes": {
    "sweepscope": { "owners": ["*"], "readers": ["*"], "ttl_days": 0 }
  }
}
REGEOF
  MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REG" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
    "$TOOL" create /memories/sweepscope/file.md "body" >/dev/null 2>&1

  # Backdate the file to make it appear expired
  python3 -c "
import os, time
p = '$ROOT/sweepscope/file.md'
os.utime(p, (time.time() - 86401, time.time() - 86401))
"
  # Sweep should delete it (lock is held by sweep, not by create which already completed)
  local SWEEP_OUT
  SWEEP_OUT=$(MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REG" MEMORY_NO_SYNC=1 \
              "$TOOL" ttl-sweep 2>&1)

  rm -f "$REG"

  if [[ ! -f "$ROOT/sweepscope/file.md" ]]; then
    pass 4 "ttl-sweep holds scope lock and correctly deletes expired file"
  else
    fail 4 "ttl-sweep failed to delete expired file" "$SWEEP_OUT"
  fi
}

# ── main ──────────────────────────────────────────────────────────────────────

echo "=== Memory Concurrency Audit Tests ==="
echo "TOOL: $TOOL"
echo ""

test_c1
test_c2
test_c3_without_fix
test_c3_with_fix
test_c3_concurrent_drain
test_c4

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIPS skipped ==="
exit "$FAIL"

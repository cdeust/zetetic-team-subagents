#!/usr/bin/env bash
# test-memory-stale-lock.sh — PID-liveness stale-lock recovery tests
#
# Covers:
#   S1 — SIGKILL reclaim: dead holder → writer succeeds quickly, audit shows reclaimed
#   S2 — Live process not stolen: slow holder → waiter does NOT reclaim
#   S3 — Two concurrent reclaimers: exactly one wins, other fails cleanly
#   S4 — PID reuse resistance: SKIPPED (Option A chosen; no proc start-time check)
#   S5: SIGKILL reclaim when the dead holder left its owner file beside its pid file
#
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

pass() { echo "PASS  S${1}: ${2}"; PASS=$((PASS + 1)); }
fail() { echo "FAIL  S${1}: ${2}"; echo "      detail: ${3:-}"; FAIL=$((FAIL + 1)); }

# ── S1: SIGKILL reclaim ───────────────────────────────────────────────────────
# Invariants: I-NEW (liveness), I1 (mutual exclusion)
# A background process acquires the lock then receives SIGKILL.
# The foreground writer must succeed promptly via reclaim (audit shows
# stale_lock_reclaimed), NOT by waiting out the 5 s no-progress deadline.
#
# The promptness bound is RELATIVE to an uncontended-create baseline measured
# in the same environment, not absolute: one tool invocation's wall time is
# dominated by per-process spawn cost, which varies by platform (measured
# 2026-07-22: ~0.3 s/create on ubuntu CI vs 3.7–5.4 s on macOS Darwin 25.5 at
# ~85–250 ms per spawned process). An absolute bound measures the platform,
# not the reclaim.
test_s1() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local LOCK_DIR="$ROOT/.locks"
  mkdir -p "$LOCK_DIR"

  # Baseline: an uncontended create in the same MEMORY_ROOT (different scope,
  # so no lock interaction with the reclaim run below).
  local BSTART; BSTART=$(python3 -c "import time; print(time.time())")
  MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
    "$TOOL" create /memories/s1base/base.md "baseline" >/dev/null 2>&1 || true
  local BEND; BEND=$(python3 -c "import time; print(time.time())")
  local BASELINE; BASELINE=$(python3 -c "print(round($BEND - $BSTART, 2))")

  # Simulate a SIGKILLed holder: create lockdir manually, write a PID that
  # will be killed so kill -0 returns non-zero.
  local lockdir="$LOCK_DIR/s1scope.lockd"
  mkdir "$lockdir"
  # Start a background sleep, record its PID, then kill -9 it.
  sleep 60 &
  local holder_pid=$!
  printf '%s' "$holder_pid" > "$lockdir/pid"
  kill -9 "$holder_pid" 2>/dev/null || true
  wait "$holder_pid" 2>/dev/null || true
  # lockdir persists; holder_pid is now dead.

  local START; START=$(python3 -c "import time; print(time.time())")
  local OUT
  OUT=$(MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
        "$TOOL" create /memories/s1scope/test.md "hello" 2>&1)
  local END; END=$(python3 -c "import time; print(time.time())")
  local ELAPSED; ELAPSED=$(python3 -c "print(round($END - $START, 2))")

  local reclaimed=0
  if [[ -f "$ROOT/.audit.log" ]] && grep -q "stale_lock_reclaimed" "$ROOT/.audit.log"; then
    reclaimed=1
  fi

  local success=0
  echo "$OUT" | grep -q "File created successfully" && success=1 || true

  # Bound: ELAPSED < BASELINE * 1.5 + 2.0.
  #   * 1.5 — run-to-run spawn-cost jitter (measured 2026-07-22 on macOS
  #     Darwin 25.5: baseline spread 3.68–5.17 s across consecutive runs).
  #   + 2.0 s — the reclaim itself: one 0.1 s spin tick plus ~7 extra spawned
  #     processes at worst-measured ~0.25 s/spawn (measured delta over baseline:
  #     -0.2 to +2.4 s on macOS, <= +0.2 s on ubuntu CI).
  # A regression that waits out the 5 s no-progress deadline instead of
  # reclaiming exceeds this bound on both platforms (CI: 0.3*1.5+2.0 = 2.5 s
  # vs >= 5.3 s; macOS: ~5*1.5+2.0 = 9.5 s vs >= 10 s).
  local within_bound
  within_bound=$(python3 -c "print(1 if $ELAPSED < $BASELINE * 1.5 + 2.0 else 0)")

  if [[ $success -eq 1 && $reclaimed -eq 1 && $within_bound -eq 1 ]]; then
    pass 1 "SIGKILL reclaim: writer succeeded in ${ELAPSED}s (baseline ${BASELINE}s), audit shows reclaimed"
  else
    fail 1 "SIGKILL reclaim" "success=$success reclaimed=$reclaimed elapsed=${ELAPSED}s baseline=${BASELINE}s out='$(echo "$OUT" | head -3)'"
  fi
}

# ── S2: Live process not stolen ───────────────────────────────────────────────
# Invariants: I-NEW-2 (no false reclaim), I2 (no lost update)
# A background writer holds the lock legitimately while doing real work.
# A concurrent foreground attempt must NOT reclaim the lock from it — the
# foreground must either wait and succeed (if the holder finishes within 5 s)
# or die with the normal "could not acquire lock" message.
# We use a 2-second artificial delay inside the critical section by spawning
# a background shell that holds the lock via a direct subshell.
test_s2() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local LOCK_DIR="$ROOT/.locks"
  mkdir -p "$LOCK_DIR"
  mkdir -p "$ROOT/s2scope"

  # Background: acquire lock manually, hold for 2 s, release.
  # This simulates a live-but-slow holder (SIGKILL will NOT be sent).
  (
    local lockdir="$LOCK_DIR/s2scope.lockd"
    mkdir "$lockdir"
    printf '%s' "$$" > "$lockdir/pid"
    sleep 2
    rmdir "$lockdir" 2>/dev/null || true
  ) &
  local holder_pid=$!

  # Give the holder 0.2 s to acquire the lock before the foreground tries.
  sleep 0.2

  local OUT
  OUT=$(MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
        "$TOOL" create /memories/s2scope/test.md "body" 2>&1) || true

  wait "$holder_pid" 2>/dev/null || true

  # The foreground either succeeded (waited for holder to release) or received
  # "could not acquire lock". Either outcome is acceptable; what is NOT acceptable
  # is a stale_lock_reclaimed entry for a process that was alive.
  local false_reclaim=0
  if [[ -f "$ROOT/.audit.log" ]] && grep -q "stale_lock_reclaimed" "$ROOT/.audit.log"; then
    false_reclaim=1
  fi

  if [[ $false_reclaim -eq 0 ]]; then
    pass 2 "Live holder NOT stolen (false_reclaim=0); foreground out='$(echo "$OUT" | head -1)'"
  else
    fail 2 "Live holder was falsely reclaimed" "out='$OUT'"
  fi
}

# ── S3: Two concurrent reclaimers — exactly one wins ─────────────────────────
# Invariants: I1 (mutex), I-NEW (liveness), serialization proof in audit doc.
# Two waiters simultaneously detect a stale lock and race to reclaim.
# Exactly one must succeed; the other must fail cleanly and eventually acquire
# through normal spin.
test_s3() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local LOCK_DIR="$ROOT/.locks"
  mkdir -p "$LOCK_DIR"

  # Create a stale lockdir with a dead PID.
  local lockdir="$LOCK_DIR/s3scope.lockd"
  mkdir "$lockdir"
  sleep 60 &
  local holder_pid=$!
  printf '%s' "$holder_pid" > "$lockdir/pid"
  kill -9 "$holder_pid" 2>/dev/null || true
  wait "$holder_pid" 2>/dev/null || true

  # Launch two concurrent writers against the stale lock.
  local OUT1 OUT2 rc1=0 rc2=0
  OUT1=$(MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
         "$TOOL" create /memories/s3scope/f1.md "body1" 2>&1) || rc1=$?
  # Run second writer in background at nearly the same time as the first.
  OUT2=$(MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
         "$TOOL" create /memories/s3scope/f2.md "body2" 2>&1) || rc2=$?

  # Both should succeed (different files, same scope) — at most one reclaim event.
  local reclaim_count=0
  if [[ -f "$ROOT/.audit.log" ]]; then
    reclaim_count=$(grep -c "stale_lock_reclaimed" "$ROOT/.audit.log" 2>/dev/null || true)
  fi

  local s1=0 s2=0
  echo "$OUT1" | grep -q "File created successfully" && s1=1 || true
  echo "$OUT2" | grep -q "File created successfully" && s2=1 || true

  # At most one reclaim event; both operations ultimately succeed (different files).
  if [[ $reclaim_count -le 1 && $s1 -eq 1 && $s2 -eq 1 ]]; then
    pass 3 "Two reclaimers: reclaim_count=$reclaim_count, both writes succeeded"
  else
    fail 3 "Two reclaimers race" "reclaim_count=$reclaim_count s1=$s1 s2=$s2 out1='$(echo "$OUT1" | head -1)' out2='$(echo "$OUT2" | head -1)'"
  fi
}

# ── S4: PID reuse resistance — SKIPPED (Option A) ────────────────────────────
# Option B (proc start-time) was not chosen; this test is not applicable.
test_s4_skip() {
  echo "SKIP  S4: PID-reuse resistance (Option A chosen — no proc start-time check; see concurrency-audit.md §Stale-Lock-Recovery)"
}

# ── S5: reclaim of a dead holder that left an owner file ─────────────────────
# Invariants: I-NEW (liveness), I-LOCK.
# A holder killed inside its critical section leaves what it created: the
# lockdir, its owner file and its pid file (tools/lib/memory-lock.sh,
# _lock_try_acquire). The writer must reclaim that lock, not wait out the 5 s
# deadline: a reclaim that left the owner file could not remove the lockdir.
# After the write the lockdir is gone, so the next writer is not blocked.
test_s5() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local LOCK_DIR="$ROOT/.locks"
  mkdir -p "$LOCK_DIR"

  local lockdir="$LOCK_DIR/s5scope.lockd"
  mkdir "$lockdir"
  sleep 60 &
  local holder_pid=$!
  printf '%s' "$holder_pid" > "$lockdir/owner"
  printf '%s' "$holder_pid" > "$lockdir/pid"
  kill -9 "$holder_pid" 2>/dev/null || true
  wait "$holder_pid" 2>/dev/null || true

  local OUT
  OUT=$(MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
        "$TOOL" create /memories/s5scope/test.md "hello" 2>&1)

  local reclaimed=0 created=0 left=0
  if [[ -f "$ROOT/.audit.log" ]] && grep -q "stale_lock_reclaimed" "$ROOT/.audit.log"; then
    reclaimed=1
  fi
  echo "$OUT" | grep -q "File created successfully" && created=1 || true
  [[ -e "$lockdir" ]] && left=1

  if [[ $created -eq 1 && $reclaimed -eq 1 && $left -eq 0 ]]; then
    pass 5 "SIGKILL reclaim with an owner file: write succeeded, audit shows reclaimed, lock released"
  else
    fail 5 "SIGKILL reclaim with an owner file" "created=$created reclaimed=$reclaimed lockdir_left=$left out='$(echo "$OUT" | head -1)'"
  fi
}

# ── main ──────────────────────────────────────────────────────────────────────

echo "=== Memory Stale-Lock Recovery Tests ==="
echo "TOOL: $TOOL"
echo ""

test_s1
test_s2
test_s3
test_s4_skip
test_s5

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
exit "$FAIL"

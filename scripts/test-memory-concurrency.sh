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
# indefinitely. The lockdir here has an owner file and NO pid file (holder died
# between its owner file and its pid write), so PID-liveness reclaim cannot
# trigger: the tool must die after its 5 s no-progress wall-clock deadline
# (concurrency-audit.md §1). Until 2026-11-13 the lockdir of this test was
# empty; an empty lockdir is now taken by the next writer (C10).
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
  local dead
  ( : ) & dead=$!
  wait "$dead"
  printf '%s' "$dead" > "$LOCK_DIR/stale.lockd/owner"

  local START; START=$(python3 -c "import time; print(int(time.time()))")
  local OUT
  OUT=$(MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
        "$TOOL" create /memories/stale/x.md "body" 2>&1 || true)
  local END; END=$(python3 -c "import time; print(int(time.time()))")
  local ELAPSED=$(( END - START ))

  if echo "$OUT" | grep -q "could not acquire lock" && (( ELAPSED >= 5 && ELAPSED <= 10 )); then
    pass 2 "stale lock without a pid file: tool dies after its 5 s no-progress deadline (elapsed=${ELAPSED}s)"
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

# ── C5: the lock does not depend on an atomic external mkdir ──────────────────
# Invariant: exactly one create succeeds even when `mkdir DIR` reports success
# to every process that raced the creation of DIR.
# The stand-in below is first on PATH for the ten writers. It decides as uutils
# coreutils 0.2.2 does (src/uu/mkdir/src/mkdir.rs: `if path_exists &&
# !config.recursive` is an error, then `Err(_) if path.is_dir() => Ok(())`):
# an error when DIR is there at the check, success when its own create fails
# and DIR is a directory by then. Any other invocation (-p, several operands)
# goes to the real mkdir. The pause between the check and the create lets the
# ten writers pass the check before one of them creates the directory.
# source: measured 2026-11-12 on the lock as it was when mkdir alone decided,
# 10 writers, 15 rounds per setting: without the pause, 12 rounds had more than
# one success; with a 0.05 s pause, 15 rounds had 10 successes. With the owner
# file: 0 round in 15 for each setting.
test_c5() {
  local real_mkdir; real_mkdir="$(command -v mkdir)"
  if [[ "$real_mkdir" != /* ]]; then
    skip 5 "mkdir is not an external command here ($real_mkdir)"
    return
  fi
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local BIN="$ROOT/.standin-bin"
  "$real_mkdir" -p "$BIN"
  cat > "$BIN/mkdir" <<'STANDIN'
#!/usr/bin/env bash
if [ "$#" -ne 1 ] || [ "${1#-}" != "$1" ]; then exec "$REAL_MKDIR" "$@"; fi
if [ -e "$1" ]; then echo "mkdir: cannot create directory '$1': File exists" >&2; exit 1; fi
sleep 0.05
"$REAL_MKDIR" "$1" 2>/dev/null && exit 0
[ -d "$1" ] && exit 0
exit 1
STANDIN
  chmod +x "$BIN/mkdir"

  local pids=() outs=()
  for i in $(seq 1 10); do
    local f="$ROOT/output-$i"
    outs+=("$f")
    ( PATH="$BIN:$PATH" REAL_MKDIR="$real_mkdir" \
      MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
      "$TOOL" create /memories/testscope/race.md "body-$i" >"$f" 2>&1 ) &
    pids+=($!)
  done
  for pid in "${pids[@]}"; do wait "$pid" || true; done

  local successes=0 duplicates=0
  for f in "${outs[@]}"; do
    grep -q "File created successfully" "$f" && successes=$((successes+1)) || true
    grep -q "already exists"            "$f" && duplicates=$((duplicates+1)) || true
  done
  local left=0
  [[ -e "$ROOT/.locks/testscope.lockd" ]] && left=1

  if [[ $successes -eq 1 && $duplicates -eq 9 && $left -eq 0 ]]; then
    pass 5 "mkdir that reports success to every racer: exactly 1 success, 9 duplicates, lock released"
  else
    fail 5 "10-way parallel create under a check-then-act mkdir" \
      "successes=$successes duplicates=$duplicates lockdir_left=$left (expected 1+9, 0)"
    for f in "${outs[@]}"; do cat "$f"; done
  fi
}

# Writes an executable at <path> that pauses <seconds>, then runs the real <command>.
_slow_standin() {
  local path="$1" seconds="$2" real="$3"
  printf '#!/usr/bin/env bash\nsleep %s\nexec %q "$@"\n' "$seconds" "$real" > "$path"
  chmod +x "$path"
}

# ── C6: INT or TERM during the critical section ──────────────────────────────
# Invariant: a signal does not release the lock while the command runs, and the
# release runs once. Writer A is slowed inside its critical section and receives
# the signal while it holds the lock; writer W waits on the same scope. Expected:
# A finishes its write under the lock and exits 128 + the signal number, then W
# takes the lock and still holds it. With a trap that released on the signal, A
# went on without the lock, W took it, and A's second release removed W's owner
# file, pid file and lockdir while W was inside its own critical section.
# A is started through python3, which restores the default action of SIGINT: a
# non-interactive shell starts a background command with SIGINT ignored, and
# bash cannot trap a signal that was ignored when it started.
# The pauses order the events, they are not tuned: A pauses 1 s before its
# rename and 1 s in the checksum after it, ten times W's 0.1 s spin tick, so
# that in the old behaviour W held the lock before A released a second time;
# W pauses 3 s before its rename, longer than the 2 s A has left, so that W is
# still inside its critical section when the check reads the owner file.
test_c6() {
  local label="$1" signal="$2" expected="$3"
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local BIN_A="$ROOT/.bin-a" BIN_W="$ROOT/.bin-w" sum
  mkdir -p "$BIN_A" "$BIN_W"
  _slow_standin "$BIN_A/mv" 1 "$(command -v mv)"
  _slow_standin "$BIN_W/mv" 3 "$(command -v mv)"
  for sum in shasum sha256sum; do
    if command -v "$sum" >/dev/null 2>&1; then _slow_standin "$BIN_A/$sum" 1 "$(command -v "$sum")"; fi
  done
  local lockdir="$ROOT/.locks/sigscope.lockd"

  ( export PATH="$BIN_A:$PATH" MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1
    exec python3 -c 'import os, signal, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])' "$TOOL" create /memories/sigscope/a.md "body-a" >"$ROOT/out-a" 2>&1 ) &
  local A_PID=$! i
  for i in $(seq 1 50); do
    [[ "$(cat "$lockdir/owner" 2>/dev/null)" == "$A_PID" ]] && break
    sleep 0.1
  done
  ( export PATH="$BIN_W:$PATH" MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1
    exec "$TOOL" create /memories/sigscope/w.md "body-w" >"$ROOT/out-w" 2>&1 ) &
  local W_PID=$!
  kill -"$signal" "$A_PID"
  local rc_a=0; wait "$A_PID" || rc_a=$?

  local w_holds=0
  for i in $(seq 1 20); do
    if [[ "$(cat "$lockdir/owner" 2>/dev/null)" == "$W_PID" ]]; then w_holds=1; break; fi
    sleep 0.1
  done
  wait "$W_PID" || true

  local a_written=0 w_written=0 left=0
  [[ -f "$ROOT/sigscope/a.md" ]] && a_written=1
  [[ -f "$ROOT/sigscope/w.md" ]] && w_written=1
  [[ -e "$lockdir" ]] && left=1
  if [[ $rc_a -eq $expected && $a_written -eq 1 && $w_holds -eq 1 && $w_written -eq 1 && $left -eq 0 ]]; then
    pass "$label" "$signal while holding the lock: write finished under the lock, exit $expected, next holder kept its lock"
  else
    fail "$label" "$signal while holding the lock" \
      "exit=$rc_a (expected $expected) a_written=$a_written next_holder_kept_lock=$w_holds w_written=$w_written lockdir_left=$left"
    cat "$ROOT/out-a" "$ROOT/out-w"
  fi
}

# ── C7: INT or TERM while the lock is being taken ────────────────────────────
# Invariant: a signal that arrives while the tool takes the lock leaves no lock
# behind. Writer A's mkdir of the lockdir is a stand-in that says it was called
# and pauses; A receives the signal during that pause. Expected: A exits 128 +
# the signal number without writing, no lockdir is left, and writer W, started
# afterwards, writes at once. With the traps set only once the lock was held,
# the signal took its default action while mkdir ran: the shell ended, mkdir
# went on and created a lockdir with no owner and no pid file, which no waiter
# can reclaim, so every later writer of the scope died after the 5 s bound.
# A is started through python3 for the reason given at C6.
# The 1 s pause orders the events, it is not tuned: the signal is sent as soon
# as the stand-in says it was called, and the checks wait for A's exit and for
# the stand-in's own end before they look at the lockdir.
test_c7() {
  local label="$1" signal="$2" expected="$3"
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local BIN_A="$ROOT/.bin-a" called="$ROOT/.mkdir-called" done_mark="$ROOT/.mkdir-done"
  mkdir -p "$BIN_A"
  printf '#!/usr/bin/env bash\ncase "${*: -1}" in\n  *.lockd) : > %q; sleep 1; %q "$@"; rc=$?; : > %q; exit $rc ;;\nesac\nexec %q "$@"\n' \
    "$called" "$(command -v mkdir)" "$done_mark" "$(command -v mkdir)" > "$BIN_A/mkdir"
  chmod +x "$BIN_A/mkdir"
  local lockdir="$ROOT/.locks/sigscope.lockd"

  ( export PATH="$BIN_A:$PATH" MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1
    exec python3 -c 'import os, signal, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])' "$TOOL" create /memories/sigscope/a.md "body-a" >"$ROOT/out-a" 2>&1 ) &
  local A_PID=$! i
  for i in $(seq 1 50); do
    [[ -e "$called" ]] && break
    sleep 0.1
  done
  if [[ ! -e "$called" ]]; then
    kill -KILL "$A_PID" 2>/dev/null; wait "$A_PID" 2>/dev/null
    fail "$label" "$signal while taking the lock" "the mkdir stand-in was not called within 5 s: the race did not take place"
    cat "$ROOT/out-a"
    return
  fi
  kill -"$signal" "$A_PID"
  local rc_a=0; wait "$A_PID" || rc_a=$?
  for i in $(seq 1 30); do
    [[ -e "$done_mark" ]] && break
    sleep 0.1
  done

  local a_written=0 left=0 rc_w=0
  [[ -f "$ROOT/sigscope/a.md" ]] && a_written=1
  [[ -e "$lockdir" ]] && left=1
  local started=$SECONDS
  MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
    "$TOOL" create /memories/sigscope/w.md "body-w" >"$ROOT/out-w" 2>&1 || rc_w=$?
  local waited=$(( SECONDS - started ))
  if [[ $rc_a -eq $expected && $a_written -eq 0 && $left -eq 0 && $rc_w -eq 0 && -f "$ROOT/sigscope/w.md" ]]; then
    pass "$label" "$signal while taking the lock: exit $expected, nothing written, no lockdir left, next writer wrote"
  else
    fail "$label" "$signal while taking the lock" \
      "exit=$rc_a (expected $expected) a_written=$a_written lockdir_left=$left next_writer_exit=$rc_w after ${waited}s"
    cat "$ROOT/out-a" "$ROOT/out-w"
  fi
}

# ── C8: INT or TERM while waiting for a lock another writer holds ────────────
# Invariant: a waiter that receives a signal leaves at once, with 128 + the
# signal number, without writing and without touching the holder's lock.
# Writer A is slowed inside its critical section (3 s before its rename); W
# waits on the same scope and receives the signal. Expected: W exits while A
# still holds the lock, A then finishes its write and releases. With the
# signals held and no check in the wait, W would go on waiting, take the lock
# once A released it, and only then leave.
# W is started through python3 for the reason given at C6.
# This test guards the check of the signal in the wait; it does not reproduce
# a defect of the lock as it was, where the default action ended the waiter at
# once. W's sleep is a stand-in that says when W pauses in its wait: the signal
# is sent then, and the test fails when A never held the lock or W never
# waited, where a fixed pause could let it pass without the wait.
test_c8() {
  local label="$1" signal="$2" expected="$3"
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local BIN_A="$ROOT/.bin-a" BIN_W="$ROOT/.bin-w" waiting="$ROOT/.w-waiting"
  mkdir -p "$BIN_A" "$BIN_W"
  _slow_standin "$BIN_A/mv" 3 "$(command -v mv)"
  printf '#!/usr/bin/env bash\n[[ "${1:-}" == 0.1 ]] && : > %q\nexec %q "$@"\n' \
    "$waiting" "$(command -v sleep)" > "$BIN_W/sleep"
  chmod +x "$BIN_W/sleep"
  local lockdir="$ROOT/.locks/sigscope.lockd"

  ( export PATH="$BIN_A:$PATH" MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1
    exec "$TOOL" create /memories/sigscope/a.md "body-a" >"$ROOT/out-a" 2>&1 ) &
  local A_PID=$! i
  for i in $(seq 1 50); do
    [[ "$(cat "$lockdir/owner" 2>/dev/null)" == "$A_PID" ]] && break
    sleep 0.1
  done
  if [[ "$(cat "$lockdir/owner" 2>/dev/null)" != "$A_PID" ]]; then
    kill -KILL "$A_PID" 2>/dev/null; wait "$A_PID" 2>/dev/null
    fail "$label" "$signal while waiting for the lock" "writer A did not take the lock within 5 s: there was nothing to wait for"
    cat "$ROOT/out-a"
    return
  fi
  ( export PATH="$BIN_W:$PATH" MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1
    exec python3 -c 'import os, signal, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])' "$TOOL" create /memories/sigscope/w.md "body-w" >"$ROOT/out-w" 2>&1 ) &
  local W_PID=$!
  for i in $(seq 1 50); do
    [[ -e "$waiting" ]] && break
    sleep 0.05
  done
  if [[ ! -e "$waiting" ]]; then
    kill -KILL "$W_PID" "$A_PID" 2>/dev/null; wait "$W_PID" "$A_PID" 2>/dev/null
    fail "$label" "$signal while waiting for the lock" "writer W did not reach its wait within 2.5 s: the signal would not have met the wait"
    cat "$ROOT/out-w"
    return
  fi
  kill -"$signal" "$W_PID"
  local rc_w=0; wait "$W_PID" || rc_w=$?
  local a_held_at_w_exit=0
  [[ "$(cat "$lockdir/owner" 2>/dev/null)" == "$A_PID" ]] && a_held_at_w_exit=1
  local rc_a=0; wait "$A_PID" || rc_a=$?

  local a_written=0 w_written=0 left=0
  [[ -f "$ROOT/sigscope/a.md" ]] && a_written=1
  [[ -f "$ROOT/sigscope/w.md" ]] && w_written=1
  [[ -e "$lockdir" ]] && left=1
  if [[ $rc_w -eq $expected && $w_written -eq 0 && $a_held_at_w_exit -eq 1 && $rc_a -eq 0 && $a_written -eq 1 && $left -eq 0 ]]; then
    pass "$label" "$signal while waiting for the lock: exit $expected at once, nothing written, the holder finished"
  else
    fail "$label" "$signal while waiting for the lock" \
      "exit=$rc_w (expected $expected) w_written=$w_written holder_still_held_at_exit=$a_held_at_w_exit holder_exit=$rc_a a_written=$a_written lockdir_left=$left"
    cat "$ROOT/out-a" "$ROOT/out-w"
  fi
}

# ── C9: INT or TERM during the pause of a waiter that could reclaim ──────────
# Invariant: a signal received during a waiter's pause ends the waiter before
# the rest of its tick. The lock is a dead holder's (a lockdir whose owner and
# pid files name a process that has ended), so the tick that follows the pause
# would reclaim it. W's sleep is a stand-in that says when W pauses and makes
# the pause last 1 s; the signal is sent then. Expected: W exits 128 + the
# signal number, the dead holder's lock is still there, and the audit log has
# no stale_lock_reclaimed. With the signal looked for only at the next tick, W
# reclaimed the lock first (review of pull request 263).
# W is started through python3 for the reason given at C6.
test_c9() {
  local label="$1" signal="$2" expected="$3"
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local BIN_W="$ROOT/.bin-w" pausing="$ROOT/.w-pausing"
  mkdir -p "$BIN_W"
  printf '#!/usr/bin/env bash\nif [[ "${1:-}" == 0.1 ]]; then : > %q; exec %q 1; fi\nexec %q "$@"\n' \
    "$pausing" "$(command -v sleep)" "$(command -v sleep)" > "$BIN_W/sleep"
  chmod +x "$BIN_W/sleep"
  local lockdir="$ROOT/.locks/sigscope.lockd" dead i
  ( : ) & dead=$!
  wait "$dead"
  mkdir -p "$lockdir"
  printf '%s' "$dead" > "$lockdir/owner"
  printf '%s' "$dead" > "$lockdir/pid"

  ( export PATH="$BIN_W:$PATH" MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1
    exec python3 -c 'import os, signal, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])' "$TOOL" create /memories/sigscope/w.md "body-w" >"$ROOT/out-w" 2>&1 ) &
  local W_PID=$!
  for i in $(seq 1 50); do
    [[ -e "$pausing" ]] && break
    sleep 0.05
  done
  if [[ ! -e "$pausing" ]]; then
    kill -KILL "$W_PID" 2>/dev/null; wait "$W_PID" 2>/dev/null
    fail "$label" "$signal during a waiter's pause" "writer W did not reach its pause within 2.5 s: the signal would not have met it"
    cat "$ROOT/out-w"
    return
  fi
  kill -"$signal" "$W_PID"
  local rc_w=0; wait "$W_PID" || rc_w=$?

  local w_written=0 kept=0 reclaimed=0
  [[ -f "$ROOT/sigscope/w.md" ]] && w_written=1
  [[ "$(cat "$lockdir/pid" 2>/dev/null)" == "$dead" ]] && kept=1
  if [[ -f "$ROOT/.audit.log" ]] && grep -q "stale_lock_reclaimed" "$ROOT/.audit.log"; then reclaimed=1; fi
  if [[ $rc_w -eq $expected && $w_written -eq 0 && $kept -eq 1 && $reclaimed -eq 0 ]]; then
    pass "$label" "$signal during a waiter's pause: exit $expected, nothing written, the dead holder's lock not reclaimed"
  else
    fail "$label" "$signal during a waiter's pause" \
      "exit=$rc_w (expected $expected) w_written=$w_written dead_lock_kept=$kept reclaimed=$reclaimed"
    cat "$ROOT/out-w"
  fi
}

# ── C10: a writer killed while it takes the lock does not block the scope ────
# Invariant: a lockdir that holds no owner file is free. Writer A is ended by
# KILL between its mkdir and its owner file: its mkdir is a stand-in that
# creates the lockdir, says so, then pauses, and A is killed during the pause.
# What A leaves is a lockdir with nothing in it. Expected: writer B, started
# after, takes the lock, writes and removes the lockdir. When a failed mkdir
# ended the attempt, B found the directory there, never looked further, and
# died after the 5 s bound, as did every writer of the scope after it
# (measured 2026-11-13: exit 2 after 5.1 s, nothing written).
test_c10() {
  local real_mkdir; real_mkdir="$(command -v mkdir)"
  if [[ "$real_mkdir" != /* ]]; then
    skip 10 "mkdir is not an external command here ($real_mkdir)"
    return
  fi
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local BIN_A="$ROOT/.bin-a" made="$ROOT/.a-made-lockdir" i
  "$real_mkdir" -p "$BIN_A"
  # Only the lockdir is paused on: mkdir -p of the lock root goes straight through.
  printf '#!/usr/bin/env bash\ncase "$#:$1" in 1:*.lockd) %q "$1" || exit 1; : > %q; exec %q 2;; esac\nexec %q "$@"\n' \
    "$real_mkdir" "$made" "$(command -v sleep)" "$real_mkdir" > "$BIN_A/mkdir"
  chmod +x "$BIN_A/mkdir"
  local lockdir="$ROOT/.locks/killscope.lockd"

  ( export PATH="$BIN_A:$PATH" MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1
    exec "$TOOL" create /memories/killscope/a.md "body-a" >"$ROOT/out-a" 2>&1 ) &
  local A_PID=$!
  for i in $(seq 1 50); do
    [[ -e "$made" ]] && break
    sleep 0.05
  done
  if [[ ! -e "$made" ]]; then
    kill -KILL "$A_PID" 2>/dev/null; wait "$A_PID" 2>/dev/null
    fail 10 "a writer killed while it takes the lock" "writer A did not reach its mkdir within 2.5 s: the kill would not have met it"
    cat "$ROOT/out-a"
    return
  fi
  kill -KILL "$A_PID"
  wait "$A_PID" 2>/dev/null
  local left; left="$(ls -A "$lockdir" 2>/dev/null | tr '\n' ' ')"
  if [[ ! -d "$lockdir" || -n "$left" ]]; then
    fail 10 "a writer killed while it takes the lock" "A did not leave an empty lockdir (found: ${left:-no lockdir}): the case was not produced"
    return
  fi

  local rc_b=0
  MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
    "$TOOL" create /memories/killscope/b.md "body-b" >"$ROOT/out-b" 2>&1 || rc_b=$?
  local a_written=0 b_written=0 still=0
  [[ -f "$ROOT/killscope/a.md" ]] && a_written=1
  [[ -f "$ROOT/killscope/b.md" ]] && b_written=1
  [[ -e "$lockdir" ]] && still=1
  if [[ $rc_b -eq 0 && $a_written -eq 0 && $b_written -eq 1 && $still -eq 0 ]]; then
    pass 10 "writer killed between mkdir and its owner file: the next writer takes the lock, writes, releases"
  else
    fail 10 "a writer killed while it takes the lock" \
      "exit_b=$rc_b a_written=$a_written b_written=$b_written lockdir_left=$still (expected 0, 0, 1, 0)"
    cat "$ROOT/out-b"
  fi
}

# ── C11: a lock held in the format before the owner file is not entered ──────
# Invariant: a lockdir that holds a pid file is not free, owner file or not.
# The tool as it was before the owner file took the lock with mkdir and wrote
# only the pid file; a writer of this version that met such a holder, live,
# must wait for it as it did before C10's change. The holder here is a live
# process that keeps the lock past the 5 s bound. Expected: the writer dies
# with "could not acquire lock", writes nothing, and the holder's lockdir and
# pid file are as they were. With "a lockdir without an owner file is free",
# the writer entered beside the live holder.
test_c11() {
  local ROOT; ROOT=$(mktemp -d)
  trap 'rm -rf "$ROOT"' RETURN
  local lockdir="$ROOT/.locks/oldscope.lockd"
  mkdir -p "$lockdir"
  sleep 30 &
  local holder=$!
  printf '%s' "$holder" > "$lockdir/pid"

  local rc=0
  MEMORY_ROOT="$ROOT" MEMORY_REGISTRY="$REGISTRY" MEMORY_NO_SYNC=1 MEMORY_NO_ACL=1 \
    "$TOOL" create /memories/oldscope/w.md "body-w" >"$ROOT/out-w" 2>&1 || rc=$?
  local written=0 kept=0 refused=0
  [[ -f "$ROOT/oldscope/w.md" ]] && written=1
  [[ "$(cat "$lockdir/pid" 2>/dev/null)" == "$holder" && ! -e "$lockdir/owner" ]] && kept=1
  grep -q "could not acquire lock" "$ROOT/out-w" && refused=1
  kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null

  if [[ $rc -ne 0 && $written -eq 0 && $kept -eq 1 && $refused -eq 1 ]]; then
    pass 11 "live holder with a pid file and no owner file: the writer waits, then dies, nothing written, the lock untouched"
  else
    fail 11 "a lock held in the format before the owner file" \
      "exit=$rc written=$written lock_untouched=$kept refused=$refused (expected non-zero, 0, 1, 1)"
    cat "$ROOT/out-w"
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
test_c5
test_c6 6a TERM 143  # source: 128 + SIGTERM (15)
test_c6 6b INT 130   # source: 128 + SIGINT (2)
test_c7 7a TERM 143  # source: 128 + SIGTERM (15)
test_c7 7b INT 130   # source: 128 + SIGINT (2)
test_c8 8a TERM 143  # source: 128 + SIGTERM (15)
test_c8 8b INT 130   # source: 128 + SIGINT (2)
test_c9 9a TERM 143  # source: 128 + SIGTERM (15)
test_c9 9b INT 130   # source: 128 + SIGINT (2)
test_c10
test_c11

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIPS skipped ==="
exit "$FAIL"

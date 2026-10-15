# shellcheck shell=bash
# shellcheck disable=SC2154  # globals assigned by tools/memory-tool.sh before sourcing
# memory-lock.sh — exclusive per-scope lock of memory-tool.sh. Sourced, never
# executed. Expects LOCK_DIR and the helpers die / audit from memory-guards.sh.
#
# I-LOCK (Lamport 1978 §3): at most one process executes the critical section
#   for a given scope at any instant. Source: POSIX mkdir(2) atomicity.
# I-NEW (liveness): a SIGKILL'd holder does not permanently block writers.
#   Source: kill -0 PID liveness check (POSIX kill(2), signal 0 semantics).
# I-NEW-2 (no false reclaim): a slow but live holder is NEVER stolen from.
#   Source: kill -0 returns 0 for live processes; reclaim requires confirmed death.
# Portability note: Option A (kill -0) chosen over Option B (proc start-time)
#   for portability (no /proc or `ps -o lstart` dependency). PID-reuse risk
#   is accepted: the window is narrow (holder dead + PID recycled within 100ms
#   spin tick); reclaim is an improvement over unconditional die, not a
#   guarantee of perfect safety under extreme PID-reuse churn.
# Acquisition timeout is WALL-CLOCK time WITHOUT PROGRESS, not tick-count.
# The contract is a bounded 5 s die on a stuck lock (memory/concurrency-audit.md
# §1). The previous tick-count proxy (50 ticks x sleep 0.1) diverged from
# wall-clock where per-tick process-spawn overhead is high: measured 10 s for
# the nominal 5 s on macOS Darwin 25.5 (2026-07-22, ~0.1 s spawn overhead per
# tick) vs ~5.2 s on ubuntu CI. Progress = the lock changing hands (holder PID
# in the pid file changes): each handoff resets the deadline, so N writers
# legitimately serialized behind short critical sections are not killed by the
# stuck-lock bound, while a lock that is stuck (holder never changes, or the
# lockdir has no pid file at all) still dies after 5 s.
# $SECONDS (bash 3.2+ builtin) has whole-second granularity, so a >= compare
# could fire after only timeout-1 s of real time; the strict > guarantees at
# least lock_timeout_s real seconds of spinning before the die.

# Reclaim the lock of a dead holder.
# Returns 0: we reclaimed it and now hold it (pid file written);
#         1: the holder is dead but another waiter won the reclaim (progress);
#         2: the holder is unknown or alive, nothing was touched.
# Reclaim sequence:
#   1. Remove the pid file so lockdir becomes empty (rmdir requires empty).
#   2. rmdir the now-empty lockdir atomically — only one waiter's rmdir
#      can succeed (POSIX rmdir(2) atomicity). The loser gets ENOENT.
#   3. mkdir our lock. If it fails, another waiter already re-acquired.
# Serialization guarantee: at most one rmdir(2) removes the dentry.
# happens-before witness: rmdir succeeds only after the dead holder's
# process table entry is gone; our subsequent mkdir is causally after.
_lock_reclaim_dead() {
  local lockdir="$1" scope="$2" holder_pid="$3"
  if [[ -z "$holder_pid" ]] || kill -0 "$holder_pid" 2>/dev/null; then return 2; fi
  rm -f "$lockdir/pid" 2>/dev/null || true
  if rmdir "$lockdir" 2>/dev/null; then
    audit "with_lock" "/memories/$scope" 0 "stale_lock_reclaimed"
    if mkdir "$lockdir" 2>/dev/null; then
      printf '%s' "$$" > "$lockdir/pid"
      return 0
    fi
  fi
  return 1
}

# Usage: with_lock <scope> <command> [args...]  — runs the command in this shell
# while holding the scope's lock; returns the command's status.
with_lock() {
  local scope="$1"; shift
  mkdir -p "$LOCK_DIR"
  local lockdir="$LOCK_DIR/$scope.lockd"
  local pid_file="$lockdir/pid"
  local rc=0 holder_pid reclaimed
  local lock_timeout_s=5  # source: memory/concurrency-audit.md §1 (bounded 5 s die)
  local spin_start=$SECONDS
  local last_holder=""
  while ! mkdir "$lockdir" 2>/dev/null; do
    sleep 0.1  # spin tick; source: memory/concurrency-audit.md §1 (100 ms interval)
    if [[ -f "$pid_file" ]]; then
      holder_pid=$(cat "$pid_file" 2>/dev/null || true)
      if [[ -n "$holder_pid" && "$holder_pid" != "$last_holder" ]]; then
        # The lock changed hands — progress. Reset the no-progress deadline.
        last_holder="$holder_pid"
        spin_start=$SECONDS
      fi
      reclaimed=0
      _lock_reclaim_dead "$lockdir" "$scope" "$holder_pid" || reclaimed=$?
      case "$reclaimed" in
        0) break ;;
        1) spin_start=$SECONDS; continue ;;  # progress was made, don't penalise
      esac
    fi
    (( SECONDS - spin_start > lock_timeout_s )) && die "could not acquire lock on scope '$scope' after ${lock_timeout_s}s"
  done
  # Write holder PID so waiters can check liveness.
  printf '%s' "$$" > "$pid_file"
  # Release: remove pid file first so lockdir is empty, then rmdir atomically.
  trap 'rm -f "'"$lockdir"'/pid" 2>/dev/null; rmdir "'"$lockdir"'" 2>/dev/null || true' EXIT INT TERM
  "$@"
  rc=$?
  rm -f "$lockdir/pid" 2>/dev/null || true
  rmdir "$lockdir" 2>/dev/null || true
  trap - EXIT INT TERM
  return $rc
}

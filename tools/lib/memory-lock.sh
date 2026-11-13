# shellcheck shell=bash
# shellcheck disable=SC2154  # globals assigned by tools/memory-tool.sh before sourcing
# memory-lock.sh — exclusive per-scope lock of memory-tool.sh. Sourced, never
# executed. Expects LOCK_DIR and the helpers die / audit from memory-guards.sh.
#
# I-LOCK (Lamport 1978 §3): at most one process executes the critical section
#   for a given scope at any instant. Source: POSIX open(2), O_CREAT|O_EXCL: the
#   holder is the one process that creates $lockdir/owner, and bash opens that
#   file itself under noclobber (measured 2026-11-12, bash 5.2.21, strace:
#   `openat(..., O_WRONLY|O_CREAT|O_EXCL, 0666)`). `mkdir $lockdir` only says
#   that the directory is there: an external mkdir that looks for the directory
#   and then creates it reports success to every process that raced the
#   creation (uutils coreutils 0.2.2, src/uu/mkdir/src/mkdir.rs: `Err(_) if
#   path.is_dir() => Ok(())`), and the lock must not depend on which mkdir is
#   first on PATH.
# I-NEW (liveness): a SIGKILL'd holder does not permanently block writers.
#   Source: kill -0 PID liveness check (POSIX kill(2), signal 0 semantics).
#   Not held in three cases (memory/concurrency-audit.md, Appendix: Owner
#   file without a pid file, Limits, and Appendix: Empty pid file): a holder
#   killed after it created its owner file and before it wrote its pid in
#   it; a waiter killed while it held the reclaim marker, when the dead
#   holder's owner file is still there, or when a holder is then killed
#   before one has removed that marker; an empty pid file with no owner file.
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
# lockdir has no pid file and an owner file whose process is alive or
# unknown) still dies after 5 s.
# $SECONDS (bash 3.2+ builtin) has whole-second granularity, so a >= compare
# could fire after only timeout-1 s of real time; the strict > guarantees at
# least lock_timeout_s real seconds of spinning before the die.

# Remove the owner file of a dead holder. Returns 0 when it was removed.
# This is the one step of a reclaim that two waiters must not do together: a
# waiter that removes an owner file after another has removed it removes the
# owner file a writer created in between. Only one waiter at a time holds
# $lockdir/reclaim, which bash creates with O_CREAT|O_EXCL as it does the
# owner file, and under it the owner file is removed only when its content is
# the pid found dead. While a dead holder's owner file is there no process can
# create one, and its creator cannot remove it: what is read under the marker
# is what is removed.
# A waiter killed while it holds the marker leaves it. Another waiter does not
# take it over: that is the race above, one level up. The next holder removes
# it (_lock_clear_dead_marker); when the dead holder's owner file is still
# there, there is no next holder (memory/concurrency-audit.md, Appendix: Owner
# file without a pid file, Limits).
_lock_remove_dead_owner() {
  local lockdir="$1" dead_pid="$2" removed=1
  ( set -o noclobber; printf '%s' "$$" > "$lockdir/reclaim" ) 2>/dev/null || return 1
  if [[ "$(cat "$lockdir/owner" 2>/dev/null || true)" == "$dead_pid" ]]; then
    # A holder ended between the opening of its pid file and the write of its
    # pid left that file empty, and nothing reclaimed the lockdir (issue 268).
    # Only the creator of the owner file writes the pid file beside it, so a
    # pid file here is the dead holder's. It goes first: a waiter ended
    # between the two removals leaves the owner file, which says who died; an
    # empty pid file left alone would say nothing.
    rm -f "$lockdir/pid" 2>/dev/null || true
    rm -f "$lockdir/owner" 2>/dev/null && removed=0
  fi
  rm -f "$lockdir/reclaim" 2>/dev/null || true
  return "$removed"
}

# Remove the reclaim marker of a waiter that died while it held it. Called by
# the holder of the lock only, so by one process at a time: the lock is what
# serialises this removal. A marker that names a dead process cannot be
# removed by its creator, and no waiter can create one while it is there, so
# the marker read is the marker removed. Left in place, it stops every later
# reclaim of the scope: the next holder to be killed would lock it for good.
# A marker with no content, or whose process is alive, is a waiter at work.
# This runs once, before the command. A waiter that takes the marker after
# it and is then killed leaves a marker that stays until the next holder: if
# this holder is killed too, at any point of its command, the scope is locked
# (review of pull request 267).
_lock_clear_dead_marker() {
  local lockdir="$1" marker_pid
  [[ -e "$lockdir/reclaim" ]] || return 0
  marker_pid=$(cat "$lockdir/reclaim" 2>/dev/null || true)
  [[ "$marker_pid" =~ ^[0-9]+$ ]] || return 0
  if kill -0 "$marker_pid" 2>/dev/null; then return 0; fi
  rm -f "$lockdir/reclaim" 2>/dev/null || true
}

# Reclaim a lockdir that holds an owner file and no pid, when the process the
# owner file names is dead: a holder killed between its owner file and its
# pid write (the pid file is then missing, or there and empty), or between
# the two removals of its release.
# Returns 1: the owner file was removed, the lockdir is free (progress);
#         2: nothing was touched.
# An owner file with no content yet, or whose process is alive, is a holder
# that is taking or releasing the lock, or one whose pid file a waiter claimed
# by mistake: it keeps the lock.
_lock_reclaim_unfinished() {
  local lockdir="$1" scope="$2" owner_pid
  owner_pid=$(cat "$lockdir/owner" 2>/dev/null || true)
  [[ "$owner_pid" =~ ^[0-9]+$ ]] || return 2
  if kill -0 "$owner_pid" 2>/dev/null; then return 2; fi
  _lock_remove_dead_owner "$lockdir" "$owner_pid" || return 2
  audit "with_lock" "/memories/$scope" 0 "unfinished_lock_reclaimed"
  return 1
}

# Reclaim the lock of a dead holder.
# Returns 0: we reclaimed it and now hold it (pid file written);
#         1: the holder is dead but another waiter won the reclaim (progress);
#         2: the holder is unknown or alive, nothing was touched.
# Reclaim sequence:
#   1. Remove the pid file, and the dead holder's owner file when it left one,
#      so lockdir becomes empty (rmdir requires empty).
#   2. rmdir the now-empty lockdir atomically — only one waiter's rmdir
#      can succeed (POSIX rmdir(2) atomicity). The loser gets ENOENT.
#   3. Take the lock as any waiter does (_lock_try_acquire). If that fails,
#      another waiter already re-acquired.
# Serialization guarantee: at most one rmdir(2) removes the dentry.
# happens-before witness: rmdir succeeds only after the dead holder's
# process table entry is gone; our subsequent acquisition is causally after.
_lock_reclaim_dead() {
  local lockdir="$1" scope="$2" holder_pid="$3"
  if [[ -z "$holder_pid" ]] || kill -0 "$holder_pid" 2>/dev/null; then return 2; fi
  # Claim the pid file by an atomic rename, then verify it still names the dead
  # holder: the caller read holder_pid earlier, and that holder may have released
  # and a new one taken the lock since. Deleting the pid file blind would
  # steal that live holder's lock (two creators of one file under 10-way load).
  # Whether the holder left an owner file is noted before the claim. While
  # the pid file is there no process can create an owner file (see
  # _lock_try_acquire), so an owner file seen now is the holder's. Once the
  # pid file is moved, a lockdir that had none holds nothing, and a writer may
  # create its own there: that one is not ours to remove.
  local claimed="$lockdir.reclaim.$$" claimed_pid had_owner=0
  [[ -e "$lockdir/owner" ]] && had_owner=1
  mv "$lockdir/pid" "$claimed" 2>/dev/null || return 1
  claimed_pid=$(cat "$claimed" 2>/dev/null || true)
  if [[ "$claimed_pid" != "$holder_pid" ]]; then
    # We took a newer holder's pid file. Do NOT put it back: by now that holder
    # may have released and a third process re-created the lockdir, and a stale
    # pid restored there names a dead holder, so a later waiter would reclaim
    # (rmdir) the third process's live lock. A live holder merely loses
    # crash-recovery for this one acquisition; mutual exclusion is kept.
    rm -f "$claimed" 2>/dev/null || true
    return 1
  fi
  # The pid file we claimed named the dead holder, so the owner file that was
  # beside it is the dead holder's too. A dead holder of the format before the
  # owner file left none: an owner file there now is a writer's, created after
  # our claim. Removing it took that writer's owner file from under it, which
  # lets a second holder in (review of pull request 266; C12 of
  # scripts/test-memory-concurrency.sh shows the removal). Our rmdir then
  # fails, and we wait.
  rm -f "$claimed" 2>/dev/null || true
  if (( had_owner )); then _lock_remove_dead_owner "$lockdir" "$holder_pid" || true; fi
  if rmdir "$lockdir" 2>/dev/null; then
    audit "with_lock" "/memories/$scope" 0 "stale_lock_reclaimed"
    _lock_try_acquire "$lockdir" && return 0
  fi
  return 1
}

# Test-and-set of the lock. Returns 0 when this process now holds it.
# mkdir is not the decision: see I-LOCK in the header. The decision is the
# creation of $lockdir/owner with O_CREAT|O_EXCL, which only one process can
# win. A process that loses it goes back to waiting and removes nothing: if
# its mkdir was the one that created the directory, the directory is now the
# winner's.
# The directory only has to be there, whoever made it. A writer killed
# between its mkdir and its owner file leaves a lockdir with nothing in it;
# when a failed mkdir ended the attempt, no writer took that lockdir again and
# each one died after the 5 s bound (scripts/test-memory-concurrency.sh C10).
# A lockdir that holds a pid file is not taken this way: with no owner file
# beside it, that pid file is the lock of a holder running the tool as it was
# before the owner file (scripts/test-memory-concurrency.sh C11), and liveness
# decides (_lock_reclaim_dead).
_lock_try_acquire() {
  local lockdir="$1"
  if ! mkdir "$lockdir" 2>/dev/null; then
    [[ -d "$lockdir" && ! -e "$lockdir/pid" ]] || return 1
  fi
  ( set -o noclobber; printf '%s' "$$" > "$lockdir/owner" ) 2>/dev/null || return 1
  # Holder PID, so that waiters can check liveness.
  printf '%s' "$$" > "$lockdir/pid"
}

# Release the lock this shell holds: the pid file first, then the owner file,
# then the directory. In that order a waiter can create owner only once our
# pid file is gone. Only the first call removes anything, so the EXIT trap and
# the normal path of with_lock can both call it.
_lock_release() {
  [[ -n "${_LOCK_HELD:-}" ]] || return 0
  local lockdir="$_LOCK_HELD"
  _LOCK_HELD=""
  rm -f "$lockdir/pid" "$lockdir/owner" 2>/dev/null || true
  rmdir "$lockdir" 2>/dev/null || true
}

# Wait until this shell holds the lock of <scope>: returns once
# _lock_try_acquire or a reclaim has succeeded. Leaves the tool, nothing held
# and nothing written, on a signal received while waiting, and with die after
# 5 s without progress. The signal is looked for right after the pause, before
# the rest of the tick: looked for at the next tick only, a signal let the
# tick go on to reclaim a dead holder's lock, or to end as the die of a stuck
# lock (scripts/test-memory-concurrency.sh C9). A signal received after that
# check does not stop the tick it falls in: memory/concurrency-audit.md,
# Appendix: Signals, Limits.
_lock_take() {
  local lockdir="$1" scope="$2"
  local pid_file="$lockdir/pid"
  local holder_pid reclaimed
  local lock_timeout_s=5  # source: memory/concurrency-audit.md §1 (bounded 5 s die)
  local spin_start=$SECONDS
  local last_holder=""
  while ! _lock_try_acquire "$lockdir"; do
    sleep 0.1  # spin tick; source: memory/concurrency-audit.md §1 (100 ms interval)
    # Nothing is held here: nothing is written.
    if (( _LOCK_SIGNAL )); then exit "$_LOCK_SIGNAL"; fi
    # An empty pid file names no holder: it is read as no pid file is.
    holder_pid=""
    if [[ -f "$pid_file" ]]; then holder_pid=$(cat "$pid_file" 2>/dev/null || true); fi
    if [[ -n "$holder_pid" ]]; then
      if [[ "$holder_pid" != "$last_holder" ]]; then
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
    else
      reclaimed=0
      _lock_reclaim_unfinished "$lockdir" "$scope" || reclaimed=$?
      # 1: a dead holder's owner file was removed and the lockdir is free.
      if (( reclaimed == 1 )); then spin_start=$SECONDS; continue; fi
    fi
    (( SECONDS - spin_start > lock_timeout_s )) && die "could not acquire lock on scope '$scope' after ${lock_timeout_s}s"
  done
  # The loop's status is that of the last command of its body, the deadline
  # test, which is false on every tick but the last: without this line the
  # function failed once it had waited, and errexit ended the tool, silently
  # and with the lock taken.
  return 0
}

# Usage: with_lock <scope> <command> [args...]  — runs the command in this shell
# while holding the scope's lock; returns the command's status.
#
# INT and TERM sent to this shell are held from before the lock is taken until
# the command has returned. (Sent to the whole process group, as Ctrl-C is,
# they also reach mkdir and the subshell that creates the owner file, which
# take them with their default action: memory/concurrency-audit.md, Appendix:
# Signals, Limits.) Taken with their default action while the lock was being taken,
# they ended the shell during mkdir, which went on and left a lockdir with no
# owner and no pid file: no writer took it then, and every later writer of the
# scope died after the 5 s bound (scripts/test-memory-concurrency.sh C7). Held
# while the command runs, they do not release the lock under it, and the
# release runs once: before, the trap released the lock on the signal, the
# command ran on without it, and the release ran a second time, on the next
# holder's files (C6).
with_lock() {
  local scope="$1"; shift
  _LOCK_HELD=""
  _LOCK_SIGNAL=0
  trap '_LOCK_SIGNAL=130' INT   # source: 128 + SIGINT (2), bash manual, "Exit Status"
  trap '_LOCK_SIGNAL=143' TERM  # source: 128 + SIGTERM (15), same section
  trap '_lock_release' EXIT     # the command may call exit itself (a duplicate, a die)
  mkdir -p "$LOCK_DIR"
  local lockdir="$LOCK_DIR/$scope.lockd"
  local rc=0
  _lock_take "$lockdir" "$scope"
  _LOCK_HELD="$lockdir"
  # A signal received while the lock was being taken: the command is not
  # started. The EXIT trap releases the lock this shell now holds.
  if (( _LOCK_SIGNAL )); then exit "$_LOCK_SIGNAL"; fi
  _lock_clear_dead_marker "$lockdir"
  "$@"
  rc=$?
  _lock_release
  trap - EXIT INT TERM
  # A signal received while the command ran: the tool exits with 128 + the
  # signal number, the status a shell gives a command a signal ended. A
  # command that calls exit itself (a duplicate, a die) ends the tool with
  # its own status instead: this line is not reached.
  if (( _LOCK_SIGNAL )); then exit "$_LOCK_SIGNAL"; fi
  return $rc
}

# Memory-Tool Concurrency Audit

Audit date: 2026-04-24
Tool: `tools/memory-tool.sh`
Method: static code review + reproducible process-level tests in `scripts/test-memory-concurrency.sh`

---

## Happens-Before Relationships Per Command

All write commands follow the same causal order:

```
resolve_path → acl_check → (ensure_parent) → with_lock → [[ -e check ]] → atomic_write
```

The lock is the synchronisation point: the directory `$lockdir`, held by the
one process that created `$lockdir/owner` (see Appendix: Owner file). Any event
in `with_lock` on process A causally precedes any event in `with_lock` on
process B for the same scope, because A removes its owner file before B can
create one.

---

## Question 1 — Write-lock sufficiency (SIGKILL / stale lock)

**Is the TOCTOU inside the critical section sound?**
Yes. The `[[ -e "$real" ]]` check at line 317 and `atomic_write` at line 324 are
both inside `with_lock`. The lock is held from the creation of `$lockdir/owner`
to its removal (`tools/lib/memory-lock.sh`, `_lock_try_acquire` and the release
in `with_lock`). The owner file is created with `O_CREAT|O_EXCL`, so at most one
process enters the critical section at a time. The check-then-act sequence is
serialised; there is no TOCTOU window between independent processes. Until
2026-11-12 this paragraph rested on `mkdir(2)` being atomic. The system call
is; the `mkdir` command the tool runs need not be (Appendix: Owner file).

**What if the process is killed while holding the lock?**
No handler runs on SIGKILL (signal 9): the ones `with_lock` sets for EXIT, INT
and TERM (`tools/lib/memory-lock.sh`) are not called. The lockdir
`$LOCK_DIR/$scope.lockd` persists. If the dead holder
left a pid file, waiters reclaim the lock (see §Stale-Lock-Recovery). If not,
it depends on where it was killed. Between `mkdir` and its owner file, the
lockdir is empty and the next writer takes it (Appendix: Lockdir without an
owner file). Between its owner file and its pid write, the lockdir holds an
owner file that names a dead process, which the next waiter removes
(Appendix: Owner file without a pid file). On a lock a live holder keeps,
subsequent callers spin
at 100 ms intervals until 5 s of WALL-CLOCK time pass without progress
(progress = the holder PID changing hands), then call `die` and exit 2. The
deadline is
wall-clock, not tick-count: tick duration includes per-tick process-spawn
overhead, which is platform-dependent (measured 2026-07-22: ~5 ms/spawn on
ubuntu CI vs ~85–250 ms/spawn on macOS Darwin 25.5), so a 50-tick proxy for
"5 s" ran ~10 s on macOS.

**Is that acceptable?** Yes for the current single-host deployment: a 5 s
bounded timeout prevents indefinite hang. The failure mode is loud (`die` writes
to stderr) and bounded.

**Stale-lock recovery strategy (no patch required — documented only):**
If automated recovery is ever needed, the correct approach is to record the PID
of the lock holder in a file inside `$lockdir` at acquisition time, then at spin
time check whether that PID is still alive (`kill -0 $pid`). If not, remove the
stale lockdir and retry. This is not patched here because it cannot be
demonstrated to be a currently-failing hazard — the 5 s die is the stated
contract and is tested by C2.

---

## Question 2 — Atomic rename sufficiency (cross-filesystem)

**Is there a cross-filesystem risk?**
No. Both `atomic_write` (line 207) and `enqueue_sync` (line 488) create the tmp
file with the pattern `$target.tmp.$$`, i.e. in the same directory as the target.
Same directory implies same filesystem mount. `rename(2)` is used and is atomic.

**File-line evidence:**
- Line 207: `local tmp="$target.tmp.$$"` — tmp in dirname(target).
- Line 488: `local tmp="$job_file.tmp.$$"` — tmp in dirname(job_file).
- Line 211: `mv -f -- "$tmp" "$target"` — same mount, uses rename(2).
- Line 520: `mv -f -- "$tmp" "$job_file"` — same mount, uses rename(2).

No hazard. No patch.

---

## Question 3 — Queue claim race with `mv -n` (REAL HAZARD — PATCHED)

**The hazard:**
BSD `mv -n` (macOS default) returns **exit 0** even when it performs no rename
because the destination already exists (no-clobber skip). The original guard at
line 745:

```bash
if mv -n -- "$job_file" "$claimed" 2>/dev/null && [[ -f "$claimed" ]]; then
```

`[[ -f $claimed ]]` is true whether or not THIS process moved the source.
If two drainers race, both can enter the success branch, emitting the same job
twice and allowing duplicate replication to Cortex.

**Verification:** test C3a in `scripts/test-memory-concurrency.sh` reproduces the
broken guard entering the success branch when dst pre-exists (PASS = hazard
confirmed before patch).

**The fix (line 745, `cmd_drain_sync`):**

```bash
# before
if mv -n -- "$job_file" "$claimed" 2>/dev/null && [[ -f "$claimed" ]]; then

# after
if mv -n -- "$job_file" "$claimed" 2>/dev/null && [[ ! -e "$job_file" ]]; then
```

**Invariant restored:** "A job is claimed by this process if and only if
`rename(2)` atomically removed the source." The source's absence is the
causal witness that this process performed the rename. `[[ ! -e $job_file ]]`
checks exactly this. The other drainer's `mv -n` is silently blocked (dst
exists) and its source remains; it takes the false branch.

**Source:** POSIX `rename(2)` atomicity; BSD `mv(1)` man page, `-n` flag
("Do not overwrite an existing file.").

**Tests:**
- C3a — reproduces broken guard (passes before patch to confirm hazard).
- C3b — exercises fixed guard (passes after patch to confirm fix).
- C3c — concurrent real drain-sync: at most 1 drainer emits the job.

---

## Question 4 — TTL-sweep vs concurrent create race

**Does `ttl-sweep` hold the scope lock?**
Yes. Line 815:

```bash
with_lock "$scope" _sweep_scope
```

The non-dry-run path wraps `_sweep_scope` in `with_lock`. The dry-run path
does NOT hold the lock (line 812), but dry-run makes no mutations, so
there is no correctness hazard in the dry-run case.

**Race scenario (non-dry-run):** A `create` that has completed and released its
lock on scope S happened-before any `ttl-sweep` that subsequently acquires the
lock on scope S. The sweep cannot delete the file within the same lock critical
section in which `create` wrote it, because only one lock holder executes at a
time. If the file is old enough to expire, the sweep may delete it after `create`
releases — but that is correct TTL behaviour, not a race.

No hazard. No patch.

---

## Question 5 — Audit log append atomicity

**Format (line 231):**
```
ts(20) TAB agent TAB scope TAB cmd TAB vpath TAB bytes(≤10) TAB sha(64) TAB result(≤12) LF
```

**Worst-case bound:**
```
ts=20 + 7 tabs + agent(50) + scope(50) + cmd(11) + vpath(200) + bytes(10) + sha(64) + result(12)
= 424 bytes
```

macOS `PIPE_BUF` = 512 bytes (SUSv4 minimum). The `>>` append-mode open
on a regular file combined with `O_APPEND` guarantees that writes up to
`PIPE_BUF` bytes are atomic (no interleaving). 424 < 512, so lines are
not interleaved under realistic inputs.

**Note:** `MEMORY_AGENT_ID` is user-controlled. A pathologically long agent ID
could exceed 512 bytes. However MEMORY_AGENT_ID is an internal env var set by
the tool's caller (a Claude agent or test harness), not an untrusted network
input. No patch warranted; the current design is safe for all realistic values.

---

## Summary

| # | Hazard | Verdict | Action |
|---|--------|---------|--------|
| 1 | SIGKILL stale lock | Bounded 5 s die — acceptable | Documented, no patch |
| 2 | Cross-filesystem rename | Not a hazard (tmp co-located) | No patch |
| 3 | `mv -n` double-claim | **REAL HAZARD** | **Patched** (line 745) |
| 4 | TTL-sweep vs create race | Not a hazard (lock held) | No patch |
| 5 | Audit log interleaving | Not a hazard (< PIPE_BUF) | No patch |

---

## Invariants

**I-LOCK:** At most one process executes the body of `with_lock` for a given
scope at any instant. Proof: the holder is the process that created
`$lockdir/owner`; bash opens that file with `O_CREAT|O_EXCL` under `noclobber`,
and POSIX open(2) makes the existence check and the creation one atomic step,
so exactly one caller creates it; all others spin or die after 5 s.

**I-WRITE:** For any file path P under MEMORY_ROOT, the sequence
check-then-create is serialised by I-LOCK; no two processes can both observe
P as absent and both write it.

**I-RENAME:** A write to P is atomic at the filesystem level. Readers observe
either the old content or the new content, never a partial write. Proof: both
`atomic_write` and `enqueue_sync` write to a tmp file in the same directory as
the target, then call `rename(2)` via `mv -f`.

**I-CLAIM (patched):** A sync job J is claimed by drainer D if and only if
`rename(2)` atomically moved J's source file to J's claimed file. D can verify
this by checking that the source no longer exists after `mv -n`. Two concurrent
drainers cannot both claim J because `rename(2)` is atomic and `mv -n` prevents
overwriting an existing destination — exactly one drainer's source disappears.

---

## Appendix: Stale-Lock-Recovery

Patch date: 2026-04-24  
Mechanism chosen: **Option A — `kill -0 $pid`**

### Motivation

Prior to this patch, a SIGKILL'd lock holder left `$LOCK_DIR/$scope.lockd`
on disk. The trap registered for EXIT/INT/TERM did not fire under SIGKILL.
Subsequent writers spun 50 × 100 ms = 5 s then died. That is bounded but
suboptimal: the lock is provably stale (holder PID is dead) yet callers wait
the full penalty.

### Mechanism chosen and justification

**Option A: `kill -0 $pid`** — POSIX kill(2) with signal 0 performs a
permission-only check: it returns 0 if the process exists and the caller has
permission to signal it, and returns non-zero if the process does not exist.
This is the simplest portable liveness check available in bash without external
tools.

Tradeoffs vs alternatives:

| Option | Mechanism | Portability | PID-reuse safe? | Extra deps |
|--------|-----------|-------------|-----------------|------------|
| A (chosen) | `kill -0 $pid` | POSIX, macOS + Linux | No — narrow window | None |
| B | `kill -0` + `ps -o lstart` start-time comparison | macOS + Linux, different flags | Yes | `ps`, format divergence |
| C | `flock`/`fcntl` kernel file lock | Linux native; macOS needs shim | Yes (kernel tracks owner) | `flock` binary or python3 fcntl shim |

Option B was considered but `ps -o lstart` format differs between macOS BSD ps
and GNU ps, requiring conditional parsing. The portability cost was not
justified for the narrow PID-reuse window. Option C requires a dependency (flock
binary not available on macOS without util-linux) or a python3 shim adding
~15 ms latency per spin tick — also not justified.

**PID-reuse risk accepted:** the reuse window is at most one 100 ms spin tick
between `kill -0` returning non-zero and the next `rmdir` attempt. In that
window a new unrelated process must reuse the exact PID. This is extremely
unlikely on both macOS (PIDs wrap at 99999) and Linux (default 32768) with any
reasonable process creation rate. The consequence of a false negative (treating
a live process as dead) is protected by I-NEW-2: `rmdir` on an actively held
lockdir will fail because the holder wrote its PID and holds the dir open
conceptually — but more critically, the `rmdir` is still atomic; if the
"live" new PID holder has already re-acquired (impossible while the lock is
held: since 2026-11-12 the owner file decides, see Appendix: Owner file), the
`rmdir` simply fails and we spin again.

### Sequence diagrams

**Case (a): holder alive and making progress**

```
Holder H:   mkdir lockdir → create owner (O_EXCL) → write pid → [critical section]
            → remove pid → remove owner → rmdir lockdir
Waiter W:            spin → kill -0 pid → 0 (alive) → spin → ...
                                                              → acquire after H's rmdir
```
W sees a live PID; reclaim path is skipped; I-NEW-2 preserved.

**Case (b): holder SIGKILLed**

```
Holder H:   mkdir lockdir → create owner → write pid → SIGKILL (no handler runs)
                            lockdir persists with its owner and pid files
Waiter W:   spin → kill -0 dead_pid → non-zero
            → mv pid file aside (atomic) → SUCCESS, and it names dead_pid
            → remove it and H's owner file → rmdir lockdir (atomic) → SUCCESS
            → audit: stale_lock_reclaimed
            → take the lock as any waiter: mkdir lockdir → create owner (O_EXCL)
            → write own pid → proceed
```
happens-before witness: W's `rmdir` is causally after H's death (the process
table entry is gone before `kill -0` returns non-zero).

**Case (c): two concurrent waiters racing for a stale lock**

```
Holder H:   SIGKILL'd — lockdir persists
Waiter W1:  kill -0 dead_pid → non-zero → mv pid file aside → SUCCESS
            → remove H's owner file → rmdir → SUCCESS
Waiter W2:  kill -0 dead_pid → non-zero → mv pid file aside → FAIL (W1 took it)
            → W2 falls through to normal spin
W1:         mkdir → create owner → SUCCESS → proceeds
W2:         spin → after W1 releases: mkdir → create owner → SUCCESS → proceeds
```
Serialization is guaranteed: only one rename of the pid file can succeed, and
only one `rmdir` (POSIX rename(2) and rmdir(2) are atomic on a local FS). The
waiter whose `rmdir` succeeds then takes the lock as any waiter does, by
creating the owner file; the other falls back to the spin loop. At most one
reclaimer wins per stale-lock event.

**Case (d): holder slow (e.g. 30 s write)**

```
Holder H:   mkdir lockdir → create owner → write pid → [30 s write] → release
Waiter W:   100 ms spin: each tick: kill -0 pid → 0 (alive) → continue
            After 5 s wall-clock without progress (holder pid unchanged):
            die "could not acquire lock after 5s"
```
No reclaim occurs. Caller gets the existing bounded-die behavior. The 5 s
no-progress ceiling is unchanged; I-NEW-2 is preserved. (A lock that DOES
change hands resets the deadline — N writers serialized behind short critical
sections are legitimate contention, not a stuck lock.)

**Case (e): PID reuse (holder died, unrelated process recycles the PID)**

```
Holder H (pid=1234):  SIGKILL'd — lockdir persists with pid=1234
New process N (pid=1234): unrelated process started, now owns pid 1234
Waiter W:  kill -0 1234 → 0 (N is alive!)
           → W believes lock is live → skips reclaim → spins
           → eventually die after 5 s
```
This is the accepted risk of Option A. The window for this to occur is ≤100 ms
per spin tick. In practice, PID reuse this fast requires a very high process
creation rate. The consequence is the pre-patch behavior (5 s die), not
a correctness violation — mutual exclusion is not broken, only liveness
degrades to the original bound.

### Invariants preserved

- **I1 (mutual exclusion):** the holder is the one process that creates
  `$lockdir/owner` with `O_CREAT|O_EXCL` (Appendix: Owner file; until
  2026-11-12 this line rested on the exit status of the `mkdir` command). The
  reclaim path removes the dead holder's pid and owner files, then the
  lockdir; only the winner of that `rmdir` goes on, and it takes the lock as
  any waiter does, by creating the owner file. If another waiter created it
  first, the reclaimer spins. At most one process holds the lock at any
  instant.

- **I2 (no lost update):** The check-then-act inside the critical section is
  still serialized by I1. Reclaim does not weaken this: the reclaimer enters
  the critical section only after it has created the owner file.

- **I3 (atomic observability):** `atomic_write` (rename-based) is unchanged.

- **I-NEW (liveness):** A dead holder's lock is reclaimed within the first spin
  tick after the holder's PID is confirmed dead by `kill -0`. The `stale_lock_reclaimed`
  audit entry is written as the causal witness.

- **I-NEW-2 (no false reclaim):** `kill -0` returns 0 for live processes.
  A live holder is never stolen from. The 5 s ceiling still fires for truly
  slow holders.

### Serialization proof (reclaim race)

Claim: at most one waiter reclaims a stale lock per stale-lock event.

Proof by contradiction: suppose W1 and W2 both reclaim. Both must have executed
`rmdir lockdir` successfully. But `rmdir(2)` on a directory that no longer
exists returns ENOENT. POSIX guarantees that at most one `rmdir` call removes a
given directory name from the parent — after the first, the name is gone, and
the second returns ENOENT (non-zero). Therefore both cannot succeed. QED.

---

## Appendix: Owner file

Patch date: 2026-11-12

### What failed

The `e2e` job of pull request 255 ran on the `ubuntu-26.04` runner image
(version 20261101.186.1) and C1 reported two successful creates out of ten
(run 43325391700, job 131560712296). Both successes belong to writers that
entered the critical section before the file existed, that is, at the first
acquisition, when the lockdir was not there and several `mkdir` ran at once.

The tool decided the lock with the exit status of the `mkdir` command. That
status is atomic only if the command is a plain mkdir(2). uutils coreutils
0.2.2 (`src/uu/mkdir/src/mkdir.rs`) first tests `path.exists()`, which is an
error without `-p`, then calls `std::fs::create_dir`, and maps its failure to
success when the path is a directory by then (`Err(_) if path.is_dir() =>
Ok(())`). Two processes that both pass the first test both exit 0. The main
branch of uutils guards that arm with `config.recursive` (both files read on
2026-11-12).

Not established: which `mkdir` that runner image has. The job log does not
print it. What is established is the decision table of that source, and that a
`mkdir` with that table breaks the lock as it was.

### Measure

A stand-in `mkdir` with that decision table, first on PATH, ten writers of one
file, 15 rounds per setting, GNU bash 5.2.21, 4 cores, 2026-11-12:

| Stand-in pauses between check and create | Rounds with more than one success, mkdir decides | With the owner file |
|---|---|---|
| no | 12 of 15 | 0 of 15 |
| 0.05 s | 15 of 15 (10 successes each) | 0 of 15 |

With GNU mkdir 9.4: 0 of 60 before, 0 of 30 after.

### Mechanism

`_lock_try_acquire` runs `mkdir $lockdir`, then creates `$lockdir/owner` in a
subshell under `set -o noclobber`. bash opens the file itself: measured with
strace on bash 5.2.21, `openat(..., O_WRONLY|O_CREAT|O_EXCL, 0666)`. A process
that loses that open goes back to waiting and removes nothing. It may be the
one whose `mkdir` reported success without creating anything, or the one whose
`mkdir` created the directory: the directory is then the winner's. The pid file
is written after, for the liveness check, and decides nothing.

Release removes the pid file, then the owner file, then the directory. A
verified reclaim of a dead holder removes the dead holder's owner file with
its pid file: the pid file it claimed named the dead holder, no process
creates an owner file in a lockdir that holds a pid file, and a holder
removes its pid file before its owner file, so an owner file that was beside
a dead holder's pid file is that holder's. The reclaimer notes whether there
was one before it claims the pid file, and removes none otherwise (Appendix:
Lockdir without an owner file, C12). Since 2026-11-13 it removes it under
the reclaim marker, and only when the file holds the dead holder's pid
(Appendix: Owner file without a pid file).

A waiter that claims a newer holder's pid file by mistake (Appendix:
Stale-Lock-Recovery) discards it and leaves the owner file, so that holder
keeps the lock.

### Limits

- A holder killed (KILL) between its owner file and its pid write leaves a
  lockdir with an owner file and no pid file. Until 2026-11-13 nothing
  reclaimed it: writers died after 5 s, and so did every later one, until the
  lockdir was removed by hand (measured
  2026-11-13: exit 2 after 5.5 s, nothing written, the lockdir left with its
  owner file). The next waiter now removes that owner file (Appendix: Owner
  file without a pid file, C13). Killed one step earlier, between `mkdir` and its owner file, it
  leaves an empty lockdir, which the next writer takes since 2026-11-13
  (Appendix: Lockdir without an owner file, C10). INT and TERM sent to the
  tool's shell do neither: they are held while the lock is taken (Appendix:
  Signals, C7). Sent to the whole process group, they can do both (same
  appendix, Limits).
- A process running the tool as it was before this patch, waiting on a dead
  holder of this version, takes the pid file and cannot remove the lockdir
  (the owner file is in it). It dies after 5 s. Until 2026-11-13 so did every
  later writer of either version (measured that day: the old waiter, then a
  writer of this version, both "could not acquire lock", the lockdir left
  with its owner file alone). A writer of this version now reclaims that
  lockdir (Appendix: Owner file without a pid file); writers of the earlier
  version still die on it until one does.
- Until 2026-11-13 the `trap` on INT and TERM ran the release while the command
  was still running, and the normal path ran it again when the command
  returned. See Appendix: Signals.

Tests: C5 (`scripts/test-memory-concurrency.sh`) runs the ten writers under the
stand-in; S5 (`scripts/test-memory-stale-lock.sh`) reclaims a dead holder that
left an owner file.

---

## Appendix: Signals

Patch date: 2026-11-13

### What failed

`with_lock` set one handler for EXIT, INT and TERM: the release. bash runs a
trap handler and then goes on with the script. A TERM or INT received while
the command ran therefore released the lock, the command ran to its end
without it, and the normal path released a second time. If another writer
had taken the lock in between, that second release removed its owner file,
its pid file and the lockdir while it was inside its own critical section.

Measured with C6 against the lock as it was (2026-11-13, bash 5.2.21, two
runs, same result): writer A, slowed inside its critical section, receives
TERM; writer W waits on the scope. A exits 0, and W's owner file is gone
while W is still writing.

That patch set the handlers once the lock was held. A signal received while
the lock was being taken still had its default action. Measured with C7
against the lock of that patch (2026-11-13, bash 5.2.21): writer A receives
TERM while its `mkdir` of the lockdir runs, a stand-in that pauses 1 s. The
shell ends at once with status 143, the `mkdir` goes on and creates the
lockdir, which has no owner and no pid file; the next writer of the scope
dies after 5 s, "could not acquire lock", and so would every later one. With
INT sent to the shell alone, the shell waits for `mkdir`, sees it end
normally, and goes on: the write is done and the tool exits 0.

### Mechanism

INT and TERM are held from before the lock is taken until the command
returns: the handler only records the signal. What the tool does with it
depends on where it was:

- while waiting for a lock another writer holds: it leaves once its pause of
  0.1 s is over, nothing held, nothing written (C8, C9);
- while taking the lock: it finishes taking it, does not start the command,
  and leaves; the EXIT handler releases the lock (C7);
- while the command runs: the command finishes under the lock, and the lock
  is released once, by `_lock_release` (C6).

In the three cases the tool exits with 128 + the signal number (130 for INT,
143 for TERM), the status a shell gives a command a signal ended. Two
exceptions. A command that calls `exit` itself after the signal (a duplicate,
a `die`) ends the tool with its own status; EXIT runs the release for that
case, and `_lock_release` removes nothing when no lock is held. A waiter
whose tick reaches the 5 s bound ends with the `die` of a stuck lock, exit 2,
when the signal came after that tick's check (Limits).

### Limits

- A command that never returns keeps the lock, and INT or TERM do not end it;
  KILL does, and the lock is then reclaimed by the next waiter (Appendix:
  Stale-Lock-Recovery).
- A waiter that receives a signal leaves once its pause of 0.1 s is over, not
  at once. The signal is looked for once per tick, right after the pause, so
  a signal received during the pause does not let the tick go on to reclaim a
  lock or to die as on a stuck lock (review of pull request 263, C9). One
  received after that check, while the tick reads the pid file or reclaims a
  dead holder's lock, does not stop the tick. If the tick takes the lock, the
  tool leaves without starting the command and releases the lock, with 128 +
  the signal number, and the audit log has the reclaim. If the tick is the
  one that reaches the 5 s bound, the tool ends with `die`, exit 2. Otherwise
  the signal is seen after the next pause. Read in the code (review of pull
  request 264), not measured: the window is the few commands of a tick.
- A signal sent to the whole process group (Ctrl-C, `kill -- -PGID`) also
  reaches the `mkdir` command and the subshell that creates the owner file.
  They are children: the handlers are not theirs, and the signal ends them
  with its default action. Ended after the directory or the owner file was
  created and before they returned, they leave a lockdir with no owner file,
  or with an owner file and no pid file. The first is taken by the next
  writer since 2026-11-13 (Appendix: Lockdir without an owner file). The
  second is reclaimed once the tool's shell, which the owner file names, has
  ended, unless the subshell was ended before it wrote that pid (Appendix:
  Owner file without a pid file, Limits). Found by reading the
  code in the review of pull request 263, not reproduced. What C7 shows is
  the case of a signal sent to the shell alone.
- KILL is not held. Between the owner file and the pid write it leaves a
  lockdir the next waiter reclaims (Appendix: Owner file without a pid file,
  C13); between `mkdir` and the owner file, an empty lockdir the next writer
  takes (C10).
- A signal sent to the whole process group also reaches the commands the tool
  runs inside the critical section. One of them failing ends the write as any
  failure does, with the lock released on exit.

Tests, in `scripts/test-memory-concurrency.sh`, each for TERM (a) and INT
(b): C6 while the command runs, C7 while the lock is taken, C8 while waiting
for a live holder, C9 during the pause of a waiter that could reclaim.

---

## Appendix: Lockdir without an owner file

Patch date: 2026-11-13

### What failed

`_lock_try_acquire` ended its attempt when `mkdir $lockdir` failed. A lockdir
that was there with nothing in it was therefore never taken: no owner file to
lose to, no pid file to check, and the 5 s bound for every writer of the
scope, until the lockdir was removed by hand.

Measured against the lock as it was (2026-11-13, bash 5.2.21): with an empty
lockdir in place, a writer exits 2 after 5.1 s, "could not acquire lock",
nothing written, the lockdir still there. C10 produces that lockdir the way
it happens: writer A is ended by KILL while its `mkdir`, a stand-in that
creates the lockdir and then pauses, has not returned. The writer started
after A exits 2 and writes nothing.

This is the state header invariant I-NEW excludes ("a SIGKILL'd holder does
not permanently block writers"). The reclaim of a dead holder covers a holder
that got as far as its pid file; this one did not get as far as its owner
file.

### Mechanism

The directory only has to be there. A writer whose `mkdir` fails goes on to
the owner file when the lockdir holds no pid file. The decision is unchanged:
the holder is the one process that creates `$lockdir/owner` with
`O_CREAT|O_EXCL` (Appendix: Owner file). What changed is who may try.

A lockdir that holds a pid file is not taken this way, owner file or not.
With an owner file the attempt fails at the owner file, as before. Without
one, the pid file is the lock of a holder running the tool as it was before
the owner file: it took the lock with `mkdir` and wrote only its pid. Such a
holder, live, is waited for as before (C11), and reclaimed when dead
(S1, `scripts/test-memory-stale-lock.sh`).

An empty lockdir is also what a holder leaves for an instant when it
releases (owner file removed, `rmdir` not yet done) and what a reclaimer
leaves between removing the dead holder's owner file and its `rmdir`. A
writer that creates the owner file in that instant holds the lock; the
`rmdir` of the other process fails on a lockdir that is no longer empty and
removes nothing (`_lock_release` and `_lock_reclaim_dead` both ignore that
failure, the reclaimer goes back to waiting).

A reclaimer leaves an empty lockdir at one more moment: right after it has
claimed the pid file of a dead holder of the earlier format, which left no
owner file. The first version of this patch let a writer in at that moment
and kept the reclaimer's removal of the owner file as it was, whatever the
file held: the reclaimer removed the writer's owner file. If the writer had
not yet written its pid file, the reclaimer's `rmdir` then succeeded and it
took the lock too; if it had, the lockdir was left with the writer's pid
file alone, and one mistaken claim of that pid file by a third waiter made
it empty under the writer. Found by the two reviews of pull request 266, one
of which reproduced it. The reclaimer now notes, before it claims the pid
file, whether the lockdir holds an owner file, and removes one only then.
While the pid file is there no process can create an owner file, so the one
it noted is the dead holder's; an owner file that appears after the claim is
a writer's, the reclaimer's `rmdir` fails on it, and the reclaimer waits.
C12 produces the moment with a reclaimer whose `mv` pauses after the claim:
with the removal as it was, the writer's owner file is gone when the
reclaimer reaches its `rmdir`.

Measured with the change (2026-11-13): on the empty lockdir, a writer exits 0
in 0.1 s, the file written, the lockdir removed.

### Limits

- A lockdir with an owner file and no pid file was not reclaimed by this
  patch. Removing that owner file safely needs one step that both checks
  whose it is and removes it: a waiter that reads the owner file, finds a
  dead process, and then removes it can remove the owner file of a holder
  that took the lock in between. Done the same day, with the removal
  serialised by a marker (Appendix: Owner file without a pid file).
- A live holder running the tool as it was before the owner file is not
  protected whenever its lockdir holds no pid file: between its `mkdir` and
  its pid write, and after a waiter of this version has claimed its pid file
  by mistake (the claim is discarded, Appendix: Stale-Lock-Recovery, and the
  lockdir is then empty). A writer of this version that polls then takes the
  lock beside it. It needs both versions to run on one scope at the same
  time, which happens only while a call started before an update is still
  running. Read in the code, not reproduced.
- A lockdir made by hand to keep writers out of a scope no longer does so
  when it is empty. No script of this repository does that
  (`grep -rn lockd`, 2026-11-13: the lock library and its two test suites
  only).

Tests: C10, C11 and C12 (`scripts/test-memory-concurrency.sh`). C2 of the same
suite, which timed out on an empty lockdir, then on a lockdir with an owner
file and no pid file, times out on the lock of a live holder since the patch
of the next appendix.

---

## Appendix: Owner file without a pid file

Patch date: 2026-11-13

### What failed

A lockdir that held an owner file and no pid file was never reclaimed. The
reclaim of a dead holder starts from the pid file, and there was none; the
owner file kept every writer out; each one died after the 5 s bound until the
lockdir was removed by hand. Three ways lead to that lockdir:

- a holder ended by KILL between its owner file and its pid write, or one
  whose release was cut between its two removals;
- a reclaimer ended by KILL after it claimed a dead holder's pid file and
  before it removed that holder's owner file;
- a waiter running the tool as it was before the owner file, which claims
  the pid file of a dead holder of this version and cannot remove the
  lockdir (Appendix: Owner file, Limits).

This is the second state header invariant I-NEW excludes; the first was the
empty lockdir (Appendix: Lockdir without an owner file).

### Measure

One writer (`memory-tool.sh create`) against a lockdir put in place
beforehand, bash 5.2.21, 2026-11-13. "Before" is the lock as it was after the
previous appendix (`5fd257e`).

| lockdir | before | after |
|---|---|---|
| owner file of a dead process, no pid file | exit 2 after 5.7 s, nothing written, lockdir left | exit 0 in 0.3 s, written, lockdir removed |
| owner file of a live process, no pid file | exit 2 after 6.0 s, nothing written | exit 2 after 5.4 s, nothing written (unchanged) |
| owner file with no content, no pid file | exit 2 after 6.0 s, nothing written | exit 2 after 6.0 s, nothing written (unchanged, Limits) |
| owner file of a dead process, no pid file, marker of a dead waiter | exit 2 after 6.0 s, nothing written | exit 2 after 5.9 s, nothing written (unchanged, Limits) |
| owner and pid files of a dead holder, marker of a dead waiter | exit 0 in 0.3 s, written (the file named `reclaim` meant nothing) | exit 2 after 6.0 s, nothing written (Limits) |

The last line is a state the patch creates and then keeps from lasting: see
"The marker of a dead waiter" below.

### Mechanism

The removal of a dead holder's owner file is the one step that is
serialised. A waiter removes it only while it holds a marker,
`$lockdir/reclaim`, which bash creates with `O_CREAT|O_EXCL` as it does the
owner file, and only when the owner file holds the pid of the process the
waiter found dead (`_lock_remove_dead_owner`). Both reclaims use it:

- the reclaim of a dead holder that left a pid file (`_lock_reclaim_dead`),
  which until now removed the owner file with no other waiter excluded;
- a new one, for a lockdir with an owner file and no pid file
  (`_lock_reclaim_unfinished`): when the owner file holds a pid and that pid
  names no live process, the waiter removes the owner file under the marker
  and writes `unfinished_lock_reclaimed` in the audit log. The lockdir is
  then empty, and the rule of the previous appendix lets a writer take it.

Why the marker. A waiter that reads the owner file, finds a dead process and
then removes the file acts on what it read earlier. Two waiters that read
the same dead owner file both go on to remove it; between the two removals a
writer can create its own owner file, and the second removal takes it from
under that writer. Under the marker there is one remover at a time, and what
it reads is what it removes: while a dead holder's owner file is there no
process can create an owner file, the dead holder cannot remove its own, and
a live holder's release removes only an owner file it created. A second
waiter that enters after the first has left reads no owner file, or a
writer's, whose content is not the dead pid, and removes nothing.

Three other ways were considered and not taken (decision recorded on issue
265). Moving the owner file aside before checking it leaves the lockdir
without an owner file for an instant, in which a writer creates one, and
putting the first back gives two. Writing a pid file on behalf of the dead
owner, so that the existing reclaim applies, lets two reclaimers hold a claim
on the same dead holder. Having each writer take the lock by hard-linking a
file named after its pid to `owner` gives a reclaimer a name no live holder
can have, but changes the format of the lock a second time. The decision
also said that `ln` copies where hard links are not available. The source
for that is the Cygwin mailing list, for the releases of 1999 to 2005; a
2010 message there says hard links fail on FAT. It was not measured.

An owner file whose process is alive is never removed: it is a holder that
is taking or releasing the lock, or one whose pid file a waiter claimed by
mistake (C14). An owner file with no content is not removed either: there is
no pid to check (C15). An owner file that does not hold the dead holder's
pid is not removed by the reclaim of that holder's pid file (C16; first note
of the second review of pull request 266: the guard on an owner file seen
before the claim holds only when every process runs this version).

### The marker of a dead waiter

A waiter ended by KILL while it holds the marker leaves it, and no waiter
takes a marker over: two waiters that both find the marker's process dead
and both remove the marker are the race above, one level up (C17 holds that
a marker is not taken over).

If the waiter had already removed the dead holder's owner file, the lockdir
holds the marker alone and writers take the lock as before. The marker then
stopped every later reclaim of the scope: the next holder to be killed would
have locked it for good, where the lock without a marker reclaimed it (last
line of the table, measured before the next sentence was true). So the
holder of the lock removes a marker that names a dead process, before it
runs its command (`_lock_clear_dead_marker`, C19). The lock is what
serialises that removal: one holder at a time, a dead waiter cannot remove
its marker, and no waiter can create one while it is there. A marker whose
process is alive (C20) or that has no content yet (C21) is a waiter at work
and is left.

If the waiter had not yet removed the owner file, there is no next holder:
see Limits.

### Limits

- A waiter ended by KILL after it created the marker and before it removed
  the dead holder's owner file, a span of two commands, leaves both. The scope is
  locked until the lockdir is removed by hand (fourth line of the table). The
  lock as it was had the same outcome over a wider span: a reclaimer killed
  between its claim of the pid file and its removal of the owner file left
  the owner file alone, which nothing reclaimed.
- A holder ended by KILL after it took the lock and before it removed a dead
  waiter's marker leaves its owner and pid files beside that marker, and the
  scope is locked the same way (last line of the table). It takes two
  processes killed in two spans of a few commands each.
- An owner file with no content is not reclaimed, and a marker with no
  content is not removed: their creator was ended between the creation of
  the file and the write of its pid, by KILL or by a signal sent to the whole
  process group (Appendix: Signals, Limits), and there is no pid to check.
- `kill -0` decides who is dead, as for the pid file (Appendix:
  Stale-Lock-Recovery): a pid reused by another process reads as alive, and
  the lock is then kept, not stolen. A pid reused between a waiter's check
  and its removal, by a process that takes the lock in that span, is the
  risk that appendix accepts for the pid file. A process the caller may not signal, or
  one in another pid namespace that shares the directory, reads as dead, and
  its owner file is removed while it holds the lock. The tool is used by one
  user on one host; nothing in it checks that.
- A writer running the tool as it was before this patch removes an owner
  file without the marker when it reclaims a dead holder. Two versions on one
  scope keep the race this patch removes, for as long as a call started
  before an update is still running.

Tests, in `scripts/test-memory-concurrency.sh`: C13 (reclaimed), C14 to C17
(kept out: a live owner, an owner file with no content, another process's
owner file beside a dead holder's pid file, a marker another waiter holds),
C18 (ten writers on a dead owner file: one success), C19 to C21 (the marker
after a write). S5 of `scripts/test-memory-stale-lock.sh`, unchanged, holds
the reclaim of a dead holder that left both files.

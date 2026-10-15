# Async tasks: state on disk, no waiting

Owner rule (2026-10-15): the expected way to run slow work is an async task with
state, everywhere. No timeout, wait, sleep, poll or time budget is a mechanism
for verification or correctness.

`tools/lib/tasks.py` (shell front door `tools/task.sh`) is the one module every
repo reuses. It is Python 3.9+ and stdlib only. This page is its contract: the
task record on disk is the only thing a producer (the detached worker) and its
consumers (hooks, gates, CLIs, mods) share.

## Model

A caller starts a task and gets control back at once. A detached worker runs the
command and writes the outcome into a JSON record. The record is keyed by the
input, so asking again for the same input finds the same record. Callers read
state at their next event (a hook firing, a prompt, a stop) and decide from the
state alone. Elapsed time is never an input to a decision. The module has no
`wait()` by design.

## Where the state lives

| Case | Directory |
|---|---|
| `$ZETETIC_TASKS_DIR` set | that directory (tests, unusual layouts) |
| inside a git repository | `<git-common-dir>/zetetic-tasks/`, shared by every worktree of the repo |
| not a git repository | `~/.claude/fleet/tasks/<basename>-<8 hex of the absolute path>/` |

Files inside it:

| File | Writer | Meaning |
|---|---|---|
| `<id>.json` | starter, worker, reaper | the record (below) |
| `<id>.a<N>.out` | worker | full combined stdout and stderr of attempt N, never truncated |
| `<id>.a<N>.worker.log` | worker | the worker's own stderr (tracebacks); empty on a healthy run |
| `inbox/<id>.a<N>.json` | worker, reaper | one file per failed attempt, until drained |
| `latest-<kind>.json` | starter | `{"id": ...}` of the last task of that kind started |
| `<id>.a<N>.reap`, `<id>.a<N>.requeue` | reaper, requeuer | single-winner claims (below) |

## Identity

`id = <kind>-<key>`. `kind` matches `[a-z][a-z0-9_]{0,31}` (no hyphen, so an id
parses). `key` matches `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` and is a content hash
of the input: the git tree hash for a gate, a sha of the arguments otherwise.
The caller chooses the key; the same input must give the same key.

Dedup is atomic creation of `<id>.json`. The module writes the complete record
to a private temp file and hard-links it into place: link(2) fails with EEXIST
if the id exists, and the name never exists with partial content. Of N
concurrent starters exactly one creates the record and launches the worker; the
rest read the existing record. The state directory must be on a filesystem that
supports hard links; on one that does not, `os.link` raises `OSError` and `start`
fails loudly rather than creating the record without the atomic guarantee.

A finished green record (`state: done`, `rc: 0`) for an id is the cached proof
for that input. `start` returns it with disposition `cached` and runs nothing.

## The record (schema 1)

```json
{
  "schema": 1,
  "id": "gate-3f2a...", "kind": "gate", "key": "3f2a...",
  "state": "queued | running | done | failed",
  "rc": 0, "signal": null, "reason": null,
  "attempt": 1,
  "result_excerpt": "last 2000 bytes of the output", "output_path": "/abs/path/<id>.a1.out", "output_bytes": 1234,
  "pid": 4242, "pid_token": "Thu Oct 15 15:05:43 2026", "pgid": 4242,
  "starter_pid": 4200, "starter_token": "...", "started_by": "pid:4200",
  "host": "mac-1.home",
  "created": "...Z", "started": "...Z", "finished": "...Z",
  "input": {"argv": ["..."], "cwd": "/abs/cwd"}
}
```

`done` means the command exited 0. `failed` means any other end: non-zero exit
(`rc`), killed by a signal (`signal`, and `rc` negative as in Python), the worker
interrupted (`signal` set), the command not startable (`rc` 127), or a worker
that died without writing a terminal state (`rc` null). `reason` says which.
`result_excerpt` is a convenience tail; the full output is always at
`output_path`. `created`, `started` and `finished` describe the run to a human and
are never read by any decision. `pid_token` is the process start time (`/proc` starttime on Linux, `ps` lstart on macOS),
used to tell the worker from a later process that reused its pid.

## Who writes what

Every write is a temp file in the same directory followed by `rename(2)`, so a
reader sees the old record or the new one and never a prefix.

- The starter creates the record as `queued`, spawns the worker, then rewrites
  it with the worker's `pid`. The worker is blocked on a pipe until that rewrite
  is done; closing the pipe is the go signal (EOF), so the order is an event, not
  a delay.
- Only the detached worker moves `queued` to `running` to `done` or `failed`.
  Its exit path always writes a terminal state: `try/finally` around the run, and
  handlers for SIGTERM, SIGHUP, SIGINT and SIGQUIT that forward the signal to the
  command and record `failed` with `signal`. Failures are also written to `inbox/`.
- The one exception is the reaper, below. It acts only after proving the worker dead.
- SIGKILL of the worker cannot be observed by the worker. The record stays
  `running` with a dead pid; the command it started is not killed and runs on
  unsupervised until it ends. Nothing here kills a process it did not start.

## Staleness and retry

A `queued` or `running` record is in flight while its responsible process is
alive: the worker if its pid is recorded, else the starter. Alive means
`kill(pid, 0)` succeeds, the process shows the same start-time token, and it is
not a zombie. This is an OS fact, never a clock. A process is alive, dead or
unknown, and unknown is never read as dead: where the platform cannot answer,
the call raises `LivenessUnknown` naming the platform (reading it as dead would
reap a live worker and run the command twice). The probe is `/proc/<pid>/stat`
on Linux (state is field 3, start time in clock ticks since boot is field 22,
parsed after the last `)`; no `ps` needed, so slim and busybox images work) and
`ps -o lstart,stat` on macOS only (`task_proc.py`).

`status(id)` adds `alive` to in-flight records. A dead one is `stale`.
`reap_stale` (called by `drain_inbox`) turns each stale record into `failed`
plus an inbox entry; one reaper wins per `(id, attempt)` through a claim file.
A claim records its owner; a claim whose owner is dead is retired by the next
claimer, so a crash cannot wedge a transition.

Retry is explicit and counted: `requeue` (CLI: `start ... --requeue`) moves a
`failed` or stale task to attempt N+1 and launches it. Concurrent requeuers: one
wins the claim and, after winning, re-reads the record: it launches only if the
record is still attempt N and `failed`, so a requeuer that read `failed` before
the first winner finished cannot launch attempt N+1 a second time. A green or
genuinely in-flight task is returned untouched. A failed task whose recorded
process group still holds a live process (the command outlived a SIGKILLed
worker) is refused with disposition `orphaned`: a retry would run the command
twice. Retry once that group has ended. Zombies and the worker itself do not count. `start` on a `failed` task does not retry; it returns the
failure (`disposition: failed`).

## API

| Call | Returns |
|---|---|
| `start(kind, key, argv, cwd)` | `Started(record, disposition)` at once; disposition is `started`, `cached`, `in-flight`, `stale`, `failed` or `orphaned` (requeue only) |
| `requeue(kind, key, argv, cwd)` | same, for an explicit retry |
| `status(id, cwd)` | the record (plus `alive` if in flight), or None |
| `latest(kind, key, cwd)` | the record of `<kind>-<key>`, or with key None the last task of that kind started |
| `drain_inbox(cwd)` | list of failure entries not yet delivered, after reaping dead workers |
| `reap_stale(cwd)` | records turned `failed` |
| `is_green(record)` | the cached-proof test |

The inbox is at-least-once. A drain returns every entry then unlinks it, so a
second drain returns `[]` until a new failure arrives. A drainer killed between
read and unlink redelivers; two concurrent drainers may both deliver. A failure
is never lost.

## CLI

```
tools/task.sh start KIND KEY [--requeue] [--repo D] [--cwd D] -- CMD...
tools/task.sh status ID [--repo D]
tools/task.sh latest KIND [KEY] [--repo D]
tools/task.sh inbox [--repo D]
```

`--repo` selects where the state lives (default: the current directory);
`--cwd` is where the command runs (default: `--repo`). Options go before `--`;
everything after it is the command, verbatim. Each verb prints one JSON document
and exits 0. The verdict is in the document, not in the exit code or in how long
the call took. Exit 2 is a usage error.

## How a consumer decides

Allowed means state `done` with `rc` 0 for this key. Blocked means `failed` or
never started; the message names the exact `status` line and says "started, run
again after it finishes" when it has just started it. In flight means proceed
with other work. No consumer waits for a task.

## Survival

The worker is started with `start_new_session=True` (setsid): its own session
and process group. Killing the caller's process group (as the host does at a hook
timeout) does not reach it. `tests/test_tasks_survival.py` proves this on the
machine it runs on: a hook process starts a task, the test SIGKILLs the hook's
whole process group, and only then releases the task's command. The record
reaches `done`, which a killed worker could never write. It runs through the
Python API and through `tools/task.sh`.

## Verification without time

The tests in `tests/test_tasks*.py` use no sleep, poll or timeout to decide
anything. Waits are on OS events: a process exit (kqueue `NOTE_EXIT`; a pidfd
branch exists for Linux and has not been run), a FIFO open or EOF, a thread `Event`. Atomic writes are checked at the
instant that matters (a spy on `rename(2)` and `link(2)` asserts the temp file is
whole and the target is still the old record), not by hoping a race shows up.

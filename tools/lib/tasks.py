#!/usr/bin/env python3
"""tasks.py -- start a task, read its state. There is no wait(), by design.

The model (docs/async-tasks.md): ``start`` returns at once; a detached worker
runs the command and writes the outcome into a JSON record keyed by the input;
callers read the record at their next event and never decide on elapsed time.

  start(kind, key, argv, cwd)  create-or-find the task ``<kind>-<key>``
  requeue(kind, key, argv, cwd) explicit, counted retry of a failed/stale task
  status(tid, cwd)             the record, plus the liveness fact for in-flight ones
  latest(kind, key, cwd)       the record of the most recently started task of a kind
  drain_inbox(cwd)             failures not yet seen (reaps dead workers first)
  reap_stale(cwd)              turn running-with-a-dead-pid records into ``failed``

CLI:  tasks.py start KIND KEY [--repo D] [--cwd D] [--requeue] -- ARGV...
      tasks.py status ID [--repo D] | latest KIND [KEY] [--repo D] | inbox [--repo D]
Every verb prints one JSON document on stdout and exits 0; the verdict is in
the document, never in the exit code or in how long the call took. When the
platform cannot say whether a process is alive the document is
{"disposition": "unknown", "error": "<platform/cause>"}. Exit 2 is a usage error.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from typing import NamedTuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import task_proc as proc  # noqa: E402
import task_store as store  # noqa: E402

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task_worker.py")


class Started(NamedTuple):
    record: dict
    disposition: str  # started | cached | in-flight | stale | failed | orphaned


class Job(NamedTuple):
    kind: str
    key: str
    argv: list
    cwd: str


def is_green(rec: dict | None) -> bool:
    """A finished green record: the cached proof for its key."""
    return rec is not None and rec["state"] == "done" and rec["rc"] == 0


def disposition(rec: dict) -> str:
    if is_green(rec):
        return "cached"
    if rec["state"] == "failed":
        return "failed"
    return "in-flight" if store.record_alive(rec) else "stale"


def _new_record(job: Job) -> dict:
    kind, key, argv, cwd = job
    return {"schema": store.SCHEMA, "id": store.task_id(kind, key), "kind": kind, "key": key,
            "state": "queued", "rc": None, "signal": None, "reason": None, "attempt": 1,
            "result_excerpt": "", "output_path": None, "output_bytes": 0,
            "pid": None, "pid_token": None, "pgid": None,
            "starter_pid": os.getpid(), "starter_token": proc.proc_token(os.getpid()),
            "started_by": os.environ.get("ZETETIC_TASK_STARTED_BY") or f"pid:{os.getpid()}",
            "host": socket.gethostname(), "created": store.utc_now(), "started": None, "finished": None,
            "input": {"argv": list(argv), "cwd": os.path.abspath(cwd)}}


def _launch(directory: str, rec: dict) -> dict:
    """Spawn the detached worker for ``rec`` (state queued); return the stored record.

    The worker is its own session leader (setsid), so killing the caller's
    process group does not reach it. It blocks on a pipe until this function
    has written its pid into the record; closing the write end is that signal
    (EOF), so no ordering depends on timing.
    """
    path = store.record_path(directory, rec["id"])
    gate_r, gate_w = os.pipe()
    try:
        with open(os.path.join(directory, f"{rec['id']}.a{rec['attempt']}.worker.log"), "wb") as log:
            worker = subprocess.Popen([sys.executable, WORKER, directory, rec["id"], str(rec["attempt"])],
                                      stdin=gate_r, stdout=log, stderr=log, start_new_session=True)
    except BaseException as exc:  # FAILS_ON: fork/exec of the worker failed; nothing will ever run it
        os.close(gate_w)
        os.close(gate_r)
        return _fail_unlaunched(path, rec, exc)
    os.close(gate_r)
    try:
        rec = {**rec, "pid": worker.pid, "pid_token": proc.proc_token(worker.pid),
               "output_path": store.output_path(directory, rec["id"], rec["attempt"])}
        store.atomic_write(path, rec)
    finally:
        os.close(gate_w)  # EOF: the worker may now go (even if the write above failed)
    return rec


def _fail_unlaunched(path: str, rec: dict, exc: BaseException) -> dict:
    failed = {**rec, "state": "failed", "reason": f"worker could not be spawned: {exc!r}",
              "finished": store.utc_now()}
    store.atomic_write(path, failed)
    store.inbox_put(os.path.dirname(path), failed)
    return failed


def start(kind: str, key: str, argv: list[str], cwd: str) -> Started:
    """Pre: kind/key valid (task_store), argv non-empty. Post: returns at once.

    Exactly one caller per id creates the record (hard-link create, see
    store.create_exclusive) and launches the worker; every other caller, now or
    after the task finished, gets the existing record and a disposition.
    A finished green record is the cached proof and is returned as ``cached``.
    """
    return _start(store.tasks_dir(cwd), Job(kind, key, argv, cwd))


def _start(directory: str, job: Job) -> Started:
    if not job.argv:
        raise ValueError("argv must be non-empty")
    rec = _new_record(job)
    path = store.record_path(directory, rec["id"])
    if not store.create_exclusive(path, rec):
        current = store.read_record(path)
        return Started(current, disposition(current))
    store.atomic_write(os.path.join(directory, f"latest-{job.kind}.json"), {"id": rec["id"]})
    return Started(_launch(directory, rec), "started")


def reap_stale(cwd: str) -> list[dict]:
    """Turn every queued/running record whose responsible process is dead into
    ``failed`` (+ inbox entry). Single-winner per (id, attempt) via a claim; the
    liveness proof is a pid check, never a duration. Returns the records reaped."""
    directory = store.tasks_dir(cwd)
    reaped = []
    for name in sorted(os.listdir(directory)):
        if name.startswith((".", "latest-")) or not name.endswith(".json"):
            continue
        rec = store.read_record(os.path.join(directory, name))
        if rec and rec.get("state") in ("queued", "running") and not store.record_alive(rec):
            done = _reap(directory, rec)
            if done:
                reaped.append(done)
    return reaped


def _reap(directory: str, rec: dict) -> dict | None:
    if not store.claim(directory, f"{rec['id']}.a{rec['attempt']}.reap"):
        return None
    path = store.record_path(directory, rec["id"])
    current = store.read_record(path)
    if current["attempt"] != rec["attempt"] or current["state"] in store.TERMINAL:
        return None
    excerpt, size = store.read_excerpt(store.output_path(directory, rec["id"], rec["attempt"]))
    failed = {**current, "state": "failed", "rc": None, "finished": store.utc_now(),
              "reason": "worker died without writing a terminal state (pid not alive)",
              "result_excerpt": excerpt, "output_bytes": size}
    store.atomic_write(path, failed)
    store.inbox_put(directory, failed)
    return failed


def requeue(kind: str, key: str, argv: list[str], cwd: str) -> Started:
    """Explicit retry: attempt+1 of a ``failed`` (or dead in-flight) task.

    A green or genuinely in-flight task is returned untouched, and so is a
    failed one whose process group still holds a live process (disposition
    ``orphaned``: the command outlived its killed worker; a retry would run it
    twice). Concurrent requeuers: one wins the claim for attempt N+1, the rest
    get its record.
    """
    return _requeue(store.tasks_dir(cwd), Job(kind, key, argv, cwd))


def _requeue(directory: str, job: Job) -> Started:
    tid = store.task_id(job.kind, job.key)
    path = store.record_path(directory, tid)
    current = store.read_record(path)
    if current is None:
        return _start(directory, job)
    if disposition(current) == "stale":
        _reap(directory, current)
        current = store.read_record(path)
    if current["state"] != "failed":
        return Started(current, disposition(current))
    if proc.group_alive(current.get("pgid"), current.get("pid")):
        return Started(current, "orphaned")
    return _requeue_failed(directory, job, current)


def _requeue_failed(directory: str, job: Job, seen: dict) -> Started:
    """Pre: ``seen`` is the record as read, state ``failed`` at attempt N.

    Post: attempt N+1 is launched at most once, by the claim winner, and only
    if the record is STILL attempt N and ``failed`` after the claim is won. A
    claim whose owner has exited is retired by the next claimer, so a requeuer
    that read ``failed`` before the first winner finished can win the same
    claim again; the re-read is what stops it from launching N+1 a second time.
    """
    tid, attempt = seen["id"], seen["attempt"]
    path = store.record_path(directory, tid)
    if not store.claim(directory, f"{tid}.a{attempt + 1}.requeue"):
        return Started(seen, disposition(seen))
    current = store.read_record(path)
    if current["attempt"] != attempt or current["state"] != "failed":
        return Started(current, disposition(current))
    again = _new_record(job)
    again["attempt"] = attempt + 1
    store.atomic_write(path, again)
    return Started(_launch(directory, again), "started")


def status(tid: str, cwd: str) -> dict | None:
    """The record of ``tid`` or None. In-flight records carry ``alive`` (the pid fact)."""
    rec = store.read_record(store.record_path(store.tasks_dir(cwd), tid))
    if rec is not None and rec["state"] in ("queued", "running"):
        rec = {**rec, "alive": store.record_alive(rec)}
    return rec


def latest(kind: str, key: str | None, cwd: str) -> dict | None:
    """Record of ``<kind>-<key>``, or (key None) of the last task of ``kind`` started."""
    directory = store.tasks_dir(cwd)
    if key is None:
        pointer = store.read_record(os.path.join(directory, f"latest-{kind}.json"))
        if pointer is None:
            return None
        return status(pointer["id"], cwd)
    return status(store.task_id(kind, key), cwd)


def drain_inbox(cwd: str) -> list[dict]:
    """Failures not yet delivered (dead workers are reaped into it first)."""
    reap_stale(cwd)
    return store.inbox_drain(store.tasks_dir(cwd))


# -- CLI -------------------------------------------------------------------------

def _option(args: list[str], flag: str, default: str) -> str:
    """Remove ``flag VALUE`` from args and return VALUE (or ``default``)."""
    if flag not in args:
        return default
    at = args.index(flag)
    value = args[at + 1]
    del args[at:at + 2]
    return value


def _cli_start(args: list[str], repo: str, cwd: str, again: bool) -> object:
    if len(args) < 4 or args[2] != "--":
        raise ValueError("usage: start KIND KEY [--requeue] [--repo D] [--cwd D] -- ARGV...")
    run = _requeue if again else _start
    outcome = run(store.tasks_dir(repo), Job(args[0], args[1], args[3:], cwd))
    return {"disposition": outcome.disposition, "record": outcome.record}


def _dispatch(verb: str, args: list[str], where: tuple) -> object:
    repo, cwd, again = where
    if verb == "start":
        return _cli_start(args, repo, cwd, again)
    if verb == "status" and len(args) == 1:
        return status(args[0], repo)
    if verb == "latest" and 1 <= len(args) <= 2:
        return latest(args[0], args[1] if len(args) > 1 else None, repo)
    if verb == "inbox" and not args:
        return drain_inbox(repo)
    raise ValueError(f"bad verb or arguments: {verb} {args} (start|status|latest|inbox)")


def main(argv: list[str]) -> int:
    args = list(argv)
    split = args.index("--") if "--" in args else len(args)
    head, tail = args[:split], args[split:]  # options before "--" only; the command is opaque
    repo = os.path.abspath(_option(head, "--repo", os.getcwd()))
    cwd = os.path.abspath(_option(head, "--cwd", repo))
    again = "--requeue" in head  # only before "--": the command may contain the word
    if again:
        head.remove("--requeue")
    if not head:
        sys.stderr.write(__doc__ or "")
        return 2
    try:
        print(json.dumps(_dispatch(head[0], head[1:] + tail, (repo, cwd, again))))
    except (ValueError, IndexError) as exc:
        sys.stderr.write(f"tasks.py: {exc}\n")
        return 2
    except proc.LivenessUnknown as exc:  # a verdict about the platform, not a crash: JSON, exit 0
        print(json.dumps({"disposition": "unknown", "error": str(exc)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

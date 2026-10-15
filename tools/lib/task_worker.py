"""task_worker.py -- the detached process that runs one task attempt.

Invoked only by tasks.py:  ``python3 task_worker.py <dir> <id> <attempt>``

Contract (docs/async-tasks.md):
  pre   the record <id>.json is at ``attempt``, state ``queued``; stdin is the
        start gate: the worker does nothing until it reads EOF, i.e. until the
        starter has written the worker's pid into the record.
  post  the record is terminal (``done`` iff the command exited 0, else
        ``failed``) and, on failure, an inbox entry exists. This holds on every
        exit path the process can observe: normal exit, an exception, SIGTERM /
        SIGHUP / SIGINT / SIGQUIT. SIGKILL is the one exit it cannot observe;
        the record then stays ``running`` with a dead pid, which tasks.py
        detects by liveness and turns into ``failed`` (reap_stale).
  inv   only this process writes queued->running->terminal for its attempt
        (the reaper acts only after proving this process dead).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys

import task_store as store

CAUGHT = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGQUIT)  # source: every catchable termination request; SIGKILL/SIGSTOP cannot be caught (signal(7))


class Interrupts:
    """Remembers the first caught signal and forwards it to the running command."""

    def __init__(self) -> None:
        self.number = 0
        self.child: subprocess.Popen | None = None

    def handle(self, signum: int, _frame: object) -> None:
        self.number = self.number or signum
        if self.child is not None:
            self.forward()

    def forward(self) -> None:
        try:
            self.child.send_signal(self.number)
        except ProcessLookupError:
            pass  # FAILS_ON: the command already exited; its result is read below


def _run_command(directory: str, rec: dict, interrupts: Interrupts) -> dict:
    """Run the recorded argv; return the terminal fields. Pre: rec is ``running``."""
    spec = rec["input"]
    out = store.output_path(directory, rec["id"], rec["attempt"])
    with open(out, "wb") as sink:
        try:
            child = subprocess.Popen(spec["argv"], cwd=spec["cwd"], stdin=subprocess.DEVNULL,
                                     stdout=sink, stderr=subprocess.STDOUT)
        except OSError as exc:  # FAILS_ON: argv[0] missing / not executable / cwd absent
            sink.write(f"task_worker: cannot start {spec['argv']!r}: {exc}\n".encode())
            return {"state": "failed", "rc": 127, "reason": f"cannot-start: {exc}"}
        interrupts.child = child
        if interrupts.number:
            interrupts.forward()
        code = child.wait()
    return _outcome(code, interrupts.number)


def _outcome(code: int, caught: int) -> dict:
    if caught:
        return {"state": "failed", "rc": code, "signal": caught,
                "reason": f"worker interrupted by signal {caught}"}
    if code < 0:
        return {"state": "failed", "rc": code, "signal": -code, "reason": f"command killed by signal {-code}"}
    if code != 0:
        return {"state": "failed", "rc": code, "reason": f"command exited {code}"}
    return {"state": "done", "rc": 0}


def _finish(directory: str, rec: dict, outcome: dict) -> None:
    """Write the terminal record, then the inbox entry on failure. Skips only if
    a requeue already superseded this attempt."""
    path = store.record_path(directory, rec["id"])
    current = store.read_record(path)
    if current is None or current["attempt"] != rec["attempt"]:
        return
    excerpt, size = store.read_excerpt(store.output_path(directory, rec["id"], rec["attempt"]))
    final = {**current, **outcome, "finished": store.utc_now(), "result_excerpt": excerpt, "output_bytes": size}
    store.atomic_write(path, final)
    if final["state"] == "failed":
        store.inbox_put(directory, final)


def work(directory: str, tid: str, attempt: int) -> int:
    path = store.record_path(directory, tid)
    interrupts = Interrupts()
    for sig in CAUGHT:
        signal.signal(sig, interrupts.handle)
    sys.stdin.buffer.read()  # the start gate: EOF means the starter's record write is done
    rec = store.read_record(path)
    if rec is None or rec["attempt"] != attempt or rec["state"] != "queued":
        return 3  # FAILS_ON: superseded before start; nothing of ours to finish
    rec.update(state="running", pid=os.getpid(), pid_token=store.proc_token(os.getpid()),
               pgid=os.getpgid(0), started=store.utc_now())
    store.atomic_write(path, rec)
    outcome = {"state": "failed", "rc": None, "reason": "worker exited without an outcome"}
    try:
        outcome = _run_command(directory, rec, interrupts)
    except BaseException as exc:  # FAILS_ON: any bug or late signal; the terminal state is still written
        outcome = {"state": "failed", "rc": None, "reason": f"worker error: {exc!r}"}
        raise
    finally:
        _finish(directory, rec, outcome)
    return 0


if __name__ == "__main__":
    sys.exit(work(sys.argv[1], sys.argv[2], int(sys.argv[3])))

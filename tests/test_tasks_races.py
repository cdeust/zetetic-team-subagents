"""Single-winner transitions of tools/lib/tasks.py under races: reap, requeue, orphans.

Event-synchronised only: a Barrier releases the racers together, an Event holds
the first one inside the critical section until the others have either been
refused or have arrived. Nothing here sleeps or times out.
"""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading

import pytest

from task_support import blocked_task, fire, task_store as store, tasks, wait_exit

RACERS = 4  # source: any n >= 2 races; 4 keeps the file fast


@pytest.fixture
def state(tmp_path, monkeypatch, spawning):
    monkeypatch.setenv(store.ENV_DIR, str(tmp_path / "state"))
    return tmp_path


def kill_worker(started) -> None:
    os.kill(started.record["pid"], signal.SIGKILL)
    wait_exit(started.record["pid"])


def test_concurrent_reapers_write_one_terminal_record(state, monkeypatch):
    started, hold, command = blocked_task(state, "reapers")
    try:
        race_reapers(state, monkeypatch, started)
    finally:
        fire(hold)  # release the orphaned command we started, on every path
        wait_exit(command)


def race_reapers(state, monkeypatch, started) -> None:
    kill_worker(started)
    directory = store.tasks_dir(str(state))
    path = store.record_path(directory, "unit-reapers")
    rec = store.read_record(path)
    assert rec["state"] == "running" and not store.record_alive(rec)

    terminal_writes, arrivals, outcomes = [], [], queue.Queue()
    release, lock, gate = threading.Event(), threading.Lock(), threading.Barrier(RACERS)
    real_write, real_excerpt = store.atomic_write, store.read_excerpt

    def spy_write(target, obj):
        if target == path and obj["state"] == "failed":
            terminal_writes.append(obj["attempt"])
        real_write(target, obj)

    def hold_the_first(target):  # the first to get this far waits until the others are accounted for
        with lock:
            arrivals.append(target)
            first = len(arrivals) == 1
        if first:
            release.wait()
        else:
            release.set()  # a second racer inside the section: let everyone finish
        return real_excerpt(target)

    monkeypatch.setattr(store, "atomic_write", spy_write)
    monkeypatch.setattr(store, "read_excerpt", hold_the_first)

    def reaper():
        gate.wait()
        outcomes.put(tasks._reap(directory, rec))

    threads = [threading.Thread(target=reaper) for _ in range(RACERS)]
    for thread in threads:
        thread.start()
    results = [outcomes.get() for _ in range(RACERS - 1)]  # the refused ones return without the section
    release.set()
    results.append(outcomes.get())
    for thread in threads:
        thread.join()
    assert len([r for r in results if r is not None]) == 1
    assert terminal_writes == [1]


def test_a_requeuer_that_read_failed_before_the_winner_finished_cannot_launch_again(state, monkeypatch):
    log = state / "runs.log"
    command = ["sh", "-c", f"echo run >> {log}"]
    first = tasks.start("unit", "dbl", ["false"], str(state))
    wait_exit(first.record["pid"])
    stale_view = tasks.status("unit-dbl", str(state))
    assert (stale_view["state"], stale_view["attempt"]) == ("failed", 1)

    winner = tasks.requeue("unit", "dbl", command, str(state))
    assert (winner.disposition, winner.record["attempt"]) == ("started", 2)
    wait_exit(winner.record["pid"])  # attempt 2 is over: its worker has exited

    ghost = subprocess.Popen(["true"])  # the winner was another process: its claim has a dead owner now
    wait_exit(ghost.pid)
    ghost.wait()
    claim = os.path.join(store.tasks_dir(str(state)), "unit-dbl.a2.requeue")
    os.unlink(claim)
    assert store.create_exclusive(claim, {"pid": ghost.pid, "token": None})

    real_read, served = store.read_record, []

    def stale_first(path):  # the late requeuer's first read happened before the winner moved on
        if path.endswith("unit-dbl.json") and not served:
            served.append(path)
            return stale_view
        return real_read(path)

    monkeypatch.setattr(store, "read_record", stale_first)
    late = tasks.requeue("unit", "dbl", command, str(state))
    if late.disposition == "started":
        wait_exit(late.record["pid"])  # a second worker was launched: let it finish, then fail below
    assert (late.disposition, late.record["attempt"]) == ("cached", 2)
    assert log.read_text() == "run\n"  # the command ran once for attempt 2


def test_requeue_is_refused_while_the_killed_workers_command_still_runs(state):
    started, hold, command = blocked_task(state, "orphan")
    kill_worker(started)
    try:
        refused = tasks.requeue("unit", "orphan", ["true"], str(state))
        assert (refused.disposition, refused.record["state"], refused.record["attempt"]) == ("orphaned", "failed", 1)
    finally:
        fire(hold)  # the orphan ends; its group is empty (or only a zombie) from here
        wait_exit(command)
    retry = tasks.requeue("unit", "orphan", ["true"], str(state))
    assert (retry.disposition, retry.record["attempt"]) == ("started", 2)
    wait_exit(retry.record["pid"])

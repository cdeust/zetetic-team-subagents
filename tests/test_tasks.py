"""tools/lib/tasks.py: start / status / latest / inbox / requeue and the record contract.

Event-synchronised only (docs/async-tasks.md): process exit, FIFO EOF, thread Event.
No sleep, poll or timeout decides pass or fail.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from task_support import fire, make_fifo, read_line, task_store as store, tasks, wait_exit


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv(store.ENV_DIR, str(tmp_path / "state"))
    return tmp_path


def finish(started):
    """Block until the worker of a just-started task has exited; return its record."""
    wait_exit(started.record["pid"])
    return tasks.status(started.record["id"], ".")


# -- the record contract ---------------------------------------------------------

def test_start_runs_to_done_and_records_everything(state):
    started = tasks.start("unit", "k1", ["sh", "-c", "echo hello"], str(state))
    assert started.disposition == "started"
    rec = finish(started)
    assert (rec["state"], rec["rc"], rec["attempt"]) == ("done", 0, 1)
    assert rec["result_excerpt"] == "hello\n"
    assert Path(rec["output_path"]).read_text() == "hello\n"
    assert rec["pgid"] == rec["pid"]  # a session leader: detached from the caller's group
    assert rec["input"] == {"argv": ["sh", "-c", "echo hello"], "cwd": str(state)}
    assert rec["finished"] and rec["started_by"].startswith("pid:")


def test_failure_records_rc_and_fills_the_inbox(state):
    rec = finish(tasks.start("unit", "bad", ["sh", "-c", "echo oops; exit 7"], str(state)))
    assert (rec["state"], rec["rc"]) == ("failed", 7)
    entries = tasks.drain_inbox(str(state))
    assert [(e["id"], e["rc"], e["attempt"]) for e in entries] == [("unit-bad", 7, 1)]
    assert entries[0]["result_excerpt"] == "oops\n"


def test_unstartable_command_is_failed_127_not_lost(state):
    rec = finish(tasks.start("unit", "nobin", ["/nonexistent/zz-binary"], str(state)))
    assert (rec["state"], rec["rc"]) == ("failed", 127)
    assert "cannot start" in Path(rec["output_path"]).read_text()


def test_output_is_never_truncated(state):
    rec = finish(tasks.start("unit", "big", [sys.executable, "-c", "print('x' * 99999)"], str(state)))
    assert rec["output_bytes"] == 100000 == Path(rec["output_path"]).stat().st_size
    assert len(rec["result_excerpt"]) <= store.EXCERPT_BYTES


def test_invalid_kind_key_and_argv_are_refused(state):
    for kind, key in (("Bad-Kind", "k"), ("a-b", "k"), ("unit", "../x"), ("unit", "")):
        with pytest.raises(ValueError):
            tasks.start(kind, key, ["true"], str(state))
    with pytest.raises(ValueError):
        tasks.start("unit", "k", [], str(state))


# -- dedup and the cached proof --------------------------------------------------

def test_concurrent_starts_create_one_task(state):
    hold = make_fifo(state, "hold")
    argv = ["sh", "-c", f"echo run >> {state}/runs.log; cat {hold} >/dev/null"]
    gate, results = threading.Barrier(8), []

    def starter():
        gate.wait()
        results.append(tasks.start("unit", "dup", argv, str(state)))

    threads = [threading.Thread(target=starter) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r.disposition for r in results) == ["in-flight"] * 7 + ["started"]
    assert len({r.record["id"] for r in results}) == 1
    worker = next(r.record["pid"] for r in results if r.disposition == "started")
    fire(hold)
    wait_exit(worker)
    assert (state / "runs.log").read_text() == "run\n"  # the command ran exactly once


def test_green_record_is_the_cached_proof(state):
    first = finish(tasks.start("unit", "proof", ["sh", "-c", f"echo run >> {state}/runs.log"], str(state)))
    again = tasks.start("unit", "proof", ["sh", "-c", f"echo run >> {state}/runs.log"], str(state))
    assert again.disposition == "cached" and tasks.is_green(again.record)
    assert again.record["attempt"] == first["attempt"] == 1
    assert (state / "runs.log").read_text() == "run\n"


def test_failed_record_is_not_silently_retried(state):
    finish(tasks.start("unit", "f", ["false"], str(state)))
    again = tasks.start("unit", "f", ["true"], str(state))
    assert again.disposition == "failed" and again.record["attempt"] == 1


# -- crash and stale detection ---------------------------------------------------

def blocked_task(state, key):
    """Start a task whose command announces itself, then blocks. Returns (started, hold, command_pid)."""
    hold, ready = make_fifo(state, f"{key}.hold"), make_fifo(state, f"{key}.ready")
    started = tasks.start("unit", key, ["sh", "-c", f"echo $$ > {ready}; cat {hold} >/dev/null"], str(state))
    return started, hold, int(read_line(ready))  # the line proves: running record written, command alive


def test_worker_sigkill_is_detected_by_dead_pid_and_reported(state):
    started, hold, command = blocked_task(state, "crash")
    worker = started.record["pid"]
    rec = tasks.status("unit-crash", str(state))
    assert (rec["state"], rec["alive"]) == ("running", True)
    os.kill(worker, signal.SIGKILL)
    wait_exit(worker)
    rec = tasks.status("unit-crash", str(state))
    assert (rec["state"], rec["alive"]) == ("running", False)  # the lie is visible, and it is a pid fact
    assert tasks.disposition(rec) == "stale"
    entries = tasks.drain_inbox(str(state))  # reaps first
    assert [e["id"] for e in entries] == ["unit-crash"] and "worker died" in entries[0]["reason"]
    assert tasks.status("unit-crash", str(state))["state"] == "failed"
    assert tasks.drain_inbox(str(state)) == []  # drained once, not again
    fire(hold)  # release the orphaned command we started
    wait_exit(command)


def test_worker_sigterm_writes_terminal_state_and_stops_the_command(state):
    started, _hold, command = blocked_task(state, "term")
    worker = started.record["pid"]
    os.kill(worker, signal.SIGTERM)
    wait_exit(worker)
    rec = tasks.status("unit-term", str(state))
    assert (rec["state"], rec["signal"]) == ("failed", signal.SIGTERM)
    wait_exit(command)  # the forwarded SIGTERM reached the command
    assert [e["id"] for e in tasks.drain_inbox(str(state))] == ["unit-term"]


def test_requeue_is_explicit_counted_and_single_winner(state):
    finish(tasks.start("unit", "rq", ["false"], str(state)))
    gate, results = threading.Barrier(4), []

    def requeuer():
        gate.wait()
        results.append(tasks.requeue("unit", "rq", ["sh", "-c", "echo again"], str(state)))

    threads = [threading.Thread(target=requeuer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    winners = [r for r in results if r.disposition == "started"]
    assert len(winners) == 1 and winners[0].record["attempt"] == 2
    rec = finish(winners[0])
    assert (rec["state"], rec["attempt"], rec["result_excerpt"]) == ("done", 2, "again\n")
    assert tasks.requeue("unit", "rq", ["false"], str(state)).disposition == "cached"  # green: untouched


def test_requeue_of_a_stale_task_reaps_then_retries(state):
    started, hold, command = blocked_task(state, "stale")
    os.kill(started.record["pid"], signal.SIGKILL)
    wait_exit(started.record["pid"])
    fire(hold)
    wait_exit(command)
    retry = tasks.requeue("unit", "stale", ["sh", "-c", "echo second"], str(state))
    assert (retry.disposition, retry.record["attempt"]) == ("started", 2)
    assert finish(retry)["result_excerpt"] == "second\n"


def test_a_dead_claim_owner_does_not_wedge_a_transition(state):
    ghost = subprocess.Popen(["true"])
    wait_exit(ghost.pid)
    directory = store.tasks_dir(str(state))
    store.create_exclusive(os.path.join(directory, "x.claim"), {"pid": ghost.pid, "token": None})
    assert store.claim(directory, "x.claim") is True  # retired the dead claim, won
    assert store.claim(directory, "x.claim") is False  # we are alive: a live claim holds


# -- atomic writes: the protocol, checked at the instant that matters ------------

def test_atomic_write_exposes_old_or_new_never_a_prefix(state, monkeypatch):
    path = str(state / "rec.json")
    store.atomic_write(path, {"n": 1, "pad": "a" * 100000})
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(("temp", json.loads(Path(src).read_text())["n"]))  # the temp is complete before rename
        seen.append(("old", json.loads(Path(dst).read_text())["n"]))  # the target is still the old, whole record
        real_replace(src, dst)
        seen.append(("new", json.loads(Path(dst).read_text())["n"]))

    monkeypatch.setattr(store.os, "replace", spy)
    store.atomic_write(path, {"n": 2, "pad": "b" * 100000})
    assert seen == [("temp", 2), ("old", 1), ("new", 2)]


def test_a_failed_rename_leaves_the_old_record_and_no_temp(state, monkeypatch):
    path = str(state / "rec.json")
    store.atomic_write(path, {"n": 1})

    def boom(src, dst):
        raise OSError("rename failed")

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        store.atomic_write(path, {"n": 2})
    assert json.loads(Path(path).read_text()) == {"n": 1}
    assert sorted(p.name for p in state.iterdir() if p.name.startswith(".")) == []


def test_create_exclusive_name_appears_complete(state, monkeypatch):
    path = str(state / "new.json")
    real_link, seen = os.link, []

    def spy(src, dst):
        seen.append(json.loads(Path(src).read_text()))  # complete at the instant the name is created
        real_link(src, dst)

    monkeypatch.setattr(store.os, "link", spy)
    assert store.create_exclusive(path, {"n": 1, "pad": "z" * 100000}) is True
    assert store.create_exclusive(path, {"n": 2}) is False
    assert json.loads(Path(path).read_text())["n"] == 1 and seen[0]["n"] == 1


def test_concurrent_readers_only_ever_parse_whole_records(state):
    path = str(state / "hot.json")
    store.atomic_write(path, {"n": 0, "pad": ""})
    finished, bad = threading.Event(), []

    def writer():
        for n in range(1, 200):
            store.atomic_write(path, {"n": n, "pad": "p" * (n * 500)})
        finished.set()

    def reader():
        while not finished.is_set():
            rec = store.read_record(path)
            if len(rec["pad"]) != rec["n"] * 500:
                bad.append(rec["n"])

    threads = [threading.Thread(target=reader) for _ in range(2)] + [threading.Thread(target=writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert bad == []


# -- inbox -----------------------------------------------------------------------

def test_inbox_put_is_idempotent_and_drain_is_exactly_once_sequentially(state):
    directory = store.tasks_dir(str(state))
    rec = {"id": "unit-i", "kind": "unit", "key": "i", "state": "failed", "rc": 1, "attempt": 1}
    store.inbox_put(directory, rec)
    store.inbox_put(directory, rec)
    assert [e["id"] for e in store.inbox_drain(directory)] == ["unit-i"]
    assert store.inbox_drain(directory) == []
    store.inbox_put(directory, {**rec, "attempt": 2})
    assert [e["attempt"] for e in store.inbox_drain(directory)] == [2]


# -- latest, locations, CLI ------------------------------------------------------

def test_latest_follows_the_last_started_task_of_a_kind(state):
    assert tasks.latest("unit", None, str(state)) is None
    finish(tasks.start("unit", "one", ["true"], str(state)))
    second = finish(tasks.start("unit", "two", ["true"], str(state)))
    assert tasks.latest("unit", None, str(state))["id"] == second["id"] == "unit-two"
    assert tasks.latest("unit", "one", str(state))["id"] == "unit-one"


def test_git_repo_and_its_worktrees_share_one_state_dir(tmp_path, monkeypatch):
    monkeypatch.delenv(store.ENV_DIR, raising=False)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                    "-m", "i"], cwd=repo, check=True)
    subprocess.run(["git", "worktree", "add", "-q", str(tmp_path / "wt")], cwd=repo, check=True)
    here, there = store.tasks_dir(str(repo)), store.tasks_dir(str(tmp_path / "wt"))
    assert os.path.realpath(here) == os.path.realpath(there)
    assert here.endswith(os.path.join(".git", "zetetic-tasks"))


def test_non_git_directory_uses_the_fleet_tasks_dir(tmp_path, monkeypatch):
    monkeypatch.delenv(store.ENV_DIR, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    plain = tmp_path / "plain"
    plain.mkdir()
    directory = store.tasks_dir(str(plain))
    assert directory.startswith(str(tmp_path / "home" / ".claude" / "fleet" / "tasks" / "plain-"))


def test_cli_start_status_latest_inbox_roundtrip(state):
    tool = str(Path(__file__).resolve().parents[1] / "tools" / "task.sh")
    env = {**os.environ, store.ENV_DIR: str(state / "state")}

    def cli(*args):
        done = subprocess.run([tool, *args], capture_output=True, text=True, env=env, cwd=state, check=True)
        return json.loads(done.stdout)

    out = cli("start", "unit", "cli", "--", "sh", "-c", "echo --requeue; exit 4")  # "--requeue" in the command is data
    assert out["disposition"] == "started"
    wait_exit(out["record"]["pid"])
    rec = cli("status", "unit-cli")
    assert (rec["state"], rec["rc"], rec["result_excerpt"]) == ("failed", 4, "--requeue\n")
    assert cli("latest", "unit")["id"] == "unit-cli"
    assert [e["id"] for e in cli("inbox")] == ["unit-cli"] and cli("inbox") == []
    again = cli("start", "unit", "cli", "--requeue", "--", "true")
    assert (again["disposition"], again["record"]["attempt"]) == ("started", 2)
    wait_exit(again["record"]["pid"])
    assert cli("status", "unit-cli")["state"] == "done"
    assert subprocess.run([tool, "bogus"], capture_output=True, env=env, cwd=state, check=False).returncode == 2

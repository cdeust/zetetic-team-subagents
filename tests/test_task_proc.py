"""tools/lib/task_proc.py: alive, dead or unknown (docs/async-tasks.md, "Staleness").

Event-synchronised only. The same file runs on macOS (ps backend) and Linux
(/proc backend); the pure parsers are tested on both.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from task_support import fire, make_fifo, read_line, task_proc as proc, task_store as store, wait_exit


pytestmark = pytest.mark.spawns  # leak guard applies (tests/conftest.py)


def stat_line(comm: str, state: str = "S", pgrp: int = 77, starttime: int = 9999) -> str:
    """A /proc/<pid>/stat line (proc(5)): fields 4..21 are filler, field 22 is starttime."""
    filler = ["1", str(pgrp), str(pgrp), "0", "-1", "4194560"] + ["0"] * 12  # fields 4..21
    return f"4242 ({comm}) {state} " + " ".join(filler) + f" {starttime} 0 0\n"


@pytest.mark.parametrize("comm", ["sh", "my prog", "a) S 1 1 (b", "(x)", ") ("])
def test_proc_stat_is_parsed_after_the_last_parenthesis(comm):
    stat = proc.parse_proc_stat(stat_line(comm, state="Z", pgrp=31, starttime=123456))
    assert (stat.state, stat.pgrp, stat.starttime) == ("Z", 31, "123456")


def test_a_platform_with_no_probe_is_an_error_not_a_dead_process(monkeypatch):
    monkeypatch.setattr(proc, "PLATFORM", "plan9")
    with pytest.raises(proc.LivenessUnknown, match="plan9"):
        proc.proc_info(os.getpid())
    with pytest.raises(proc.LivenessUnknown, match="plan9"):
        proc.is_alive(os.getpid(), None)


def test_darwin_without_ps_is_an_error_not_a_dead_process(monkeypatch):
    def no_ps(*_args, **_kwargs):
        raise FileNotFoundError("ps")

    monkeypatch.setattr(proc, "PLATFORM", "darwin")
    monkeypatch.setattr(proc.subprocess, "run", no_ps)
    with pytest.raises(proc.LivenessUnknown, match="ps is not installed"):
        proc.proc_info(os.getpid())


def test_an_existing_process_whose_start_time_is_unreadable_is_unknown_not_dead(monkeypatch):
    def not_ours(_pid, _sig):
        raise PermissionError

    monkeypatch.setattr(proc.os, "kill", not_ours)
    monkeypatch.setattr(proc, "proc_info", lambda _pid: None)
    with pytest.raises(proc.LivenessUnknown):
        proc.is_alive(os.getpid(), "tok")


def test_a_live_process_has_a_token_that_survives_the_probe_twice():
    me = os.getpid()
    token = proc.proc_token(me)
    assert token and proc.proc_token(me) == token
    assert proc.is_alive(me, token) is True
    assert proc.is_alive(me, None) is True


def test_a_token_mismatch_means_a_different_incarnation_not_alive():
    me = os.getpid()
    assert proc.is_alive(me, proc.proc_token(me) + "x") is False  # the pid exists; the incarnation does not
    forged = {"pid": me, "pid_token": proc.proc_token(me) + "x", "starter_pid": None}
    assert store.record_alive(forged) is False
    assert store.record_alive({**forged, "pid_token": proc.proc_token(me)}) is True


def test_an_exited_unreaped_child_is_not_alive():
    child = subprocess.Popen(["true"])
    token = proc.proc_token(child.pid)  # may already be a zombie; either way it has a token
    wait_exit(child.pid)  # exited, still unreaped: kill(pid, 0) succeeds, the state is Z
    assert proc.is_alive(child.pid, token) is False
    child.wait()
    assert proc.is_alive(child.pid, token) is False


def test_group_alive_follows_the_group_not_the_leader(tmp_path):
    hold, ready = make_fifo(tmp_path, "hold"), make_fifo(tmp_path, "ready")
    leader = subprocess.Popen(["sh", "-c", f"echo $$ > {ready}; cat {hold} >/dev/null"], start_new_session=True)
    read_line(ready)
    try:
        assert proc.group_alive(leader.pid) is True
    finally:
        fire(hold)
        leader.wait()
    assert proc.group_alive(leader.pid) is False  # every member gone (zombies do not count)
    assert proc.group_alive(None) is False


def test_the_leader_alone_is_not_an_orphan():
    leader = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE,
                              start_new_session=True)
    try:
        assert proc.group_alive(leader.pid, leader.pid) is False
        assert proc.group_alive(leader.pid) is True
    finally:
        leader.stdin.close()
        leader.wait()

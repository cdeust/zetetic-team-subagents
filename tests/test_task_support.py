"""tests/task_support.py: the helpers the process tests rely on to leave nothing behind.

`wait_group_exit` is what a teardown calls after it killed a process group. The case
pinned here is a member that the caller's kill did not reach, because it entered the
group after the signal went out: the child of a member that was inside fork() during
the kill (macOS), or a process of the session that joins the group later. The second
form is used because it can be produced on purpose, on Linux and macOS alike.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from task_support import make_fifo, task_proc as proc, wait_exit

pytestmark = pytest.mark.spawns  # leak guard applies (tests/conftest.py)

TESTS = Path(__file__).resolve().parent

# argv: ready marker joined never. The leader and its child both end blocked on `never`, a fifo
# the test keeps open: neither ever exits on its own, as the held `cat` of the gate tests.
LATE_JOINER = """
import os, sys
ready, marker, joined, never = sys.argv[1:5]
leader = os.getpid()
if os.fork() == 0:
    os.setpgid(0, 0)                      # outside the group: the first kill cannot reach it
    with open(ready, "w") as out:
        out.write(f"{os.getpid()}\\n")
    open(marker).readline()               # the test: "the kill went out"
    try:
        os.setpgid(0, leader)             # a member of the killed group that nothing has signalled
        said = "in"
    except OSError as exc:
        said = f"setpgid failed: {exc}"
    with open(joined, "w") as out:
        out.write(said + "\\n")
open(never).read()
"""

# The bound of the helper process below. It never decides a passing run: `wait_group_exit` returns
# on process exits. It exists so that a helper that waits for a process nothing signals FAILS this
# test instead of hanging the suite. source: the same bound as the other subprocess tests (30 s),
# doubled for a loaded CI runner.
HELPER_BOUND_S = 60
WAIT_IN_A_PROCESS = "import sys; sys.path.insert(0, sys.argv[1]); from task_support import wait_group_exit; wait_group_exit(int(sys.argv[2]))"


def test_wait_group_exit_ends_a_member_that_entered_the_group_after_the_callers_kill(tmp_path):
    ready, marker, joined, never = (make_fifo(tmp_path, name) for name in ("ready", "marker", "joined", "never"))
    hold = os.open(never, os.O_RDWR)  # `never` has a writer for the whole test and is never written
    leader = subprocess.Popen([sys.executable, "-c", LATE_JOINER, ready, marker, joined, never], start_new_session=True)
    late = None
    try:
        with open(ready) as said:
            late = int(said.readline())
        os.killpg(leader.pid, signal.SIGKILL)  # the caller's one kill: the leader dies, `late` is not in the group yet
        with open(marker, "w") as go:
            go.write("killed\n")
        with open(joined) as said:
            assert said.readline() == "in\n"
        assert os.getpgid(late) == leader.pid and proc.is_alive(late, None)  # precondition: a live member, never signalled
        try:
            done = subprocess.run([sys.executable, "-c", WAIT_IN_A_PROCESS, str(TESTS), str(leader.pid)],
                                  capture_output=True, text=True, timeout=HELPER_BOUND_S)
        except subprocess.TimeoutExpired:
            pytest.fail("wait_group_exit waited for a member that entered the group after the kill and that nothing signals")
        assert done.returncode == 0, done.stderr
        assert not proc.is_alive(late, None), "wait_group_exit returned while a member of the group was still running"
    finally:
        if late is not None:
            try:
                os.kill(late, signal.SIGKILL)
            except ProcessLookupError:
                pass  # the good case: wait_group_exit ended it
            wait_exit(late)
        leader.kill()
        leader.wait()
        os.close(hold)

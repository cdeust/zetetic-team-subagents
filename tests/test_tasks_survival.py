"""A task started from a process whose whole process group is then SIGKILLed keeps
running and still writes its terminal state (Claude Code kills a hook's process
group at the hook timeout; docs/async-tasks.md, "Survival").

Event-synchronised: the task command blocks on a FIFO the test releases only AFTER
the kill, so the run can only reach ``done`` if the worker survived the kill.
Process exits are awaited with kqueue/pidfd, never with a timer.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from task_support import fire, make_fifo, task_store as store, tasks, wait_exit

TOOL = str(Path(__file__).resolve().parents[1] / "tools" / "task.sh")
LIB = str(Path(__file__).resolve().parents[1] / "tools" / "lib")

# The "hook": starts a task, reports the record on stdout, then stays alive
# (blocked on stdin) the way a hook shell does until the host kills its group.
API_HOOK = (
    "import json, sys; sys.path.insert(0, sys.argv[1]); import tasks; "
    "s = tasks.start('surv', sys.argv[2], ['sh', '-c', sys.argv[3]], sys.argv[4]); "
    "print(json.dumps(s.record), flush=True); sys.stdin.read()"
)
CLI_HOOK = '"$1" start surv "$2" --cwd "$4" -- sh -c "$3" || exit 1; cat'  # a failed start ends the hook: the test reads EOF, never blocks


def hook_command(via: str, key: str, command: str, cwd: str) -> list[str]:
    if via == "api":
        return [sys.executable, "-c", API_HOOK, LIB, key, command, cwd]
    return ["sh", "-c", CLI_HOOK, "hook", TOOL, key, command, cwd]


@pytest.mark.parametrize("via", ["api", "cli"])
def test_task_survives_sigkill_of_the_callers_whole_process_group(tmp_path, monkeypatch, via):
    monkeypatch.setenv(store.ENV_DIR, str(tmp_path / "state"))
    hold = make_fifo(tmp_path, "hold")
    hook = subprocess.Popen(hook_command(via, f"{via}", f"cat {hold}; echo survived", str(tmp_path)),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, start_new_session=True)
    try:
        survive_kill(hook, via, hold, tmp_path)
    finally:
        reap_hook(hook)


def reap_hook(hook: subprocess.Popen) -> None:
    """Leave no hook behind, whatever the assertions did (the group may already be dead)."""
    try:
        os.killpg(hook.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    hook.wait()
    hook.stdin.close()
    hook.stdout.close()


def survive_kill(hook: subprocess.Popen, via: str, hold: str, tmp_path: Path) -> None:
    record = json.loads(hook.stdout.readline())  # event: start() returned while the hook is still alive
    worker = record["record"]["pid"] if via == "cli" else record["pid"]
    hook_group = os.getpgid(hook.pid)
    assert hook_group == hook.pid != os.getpgid(worker)  # precondition: the worker is outside the hook's group

    os.killpg(hook_group, signal.SIGKILL)  # what the host does at a hook timeout
    hook.wait()  # event: the hook is gone

    fire(hold)  # only now may the command finish; a killed worker could never write ``done``
    wait_exit(worker)
    rec = tasks.status(f"surv-{via}", str(tmp_path))
    assert (rec["state"], rec["rc"], rec["result_excerpt"]) == ("done", 0, "survived\n")
    assert rec["attempt"] == 1 and rec["pid"] == worker

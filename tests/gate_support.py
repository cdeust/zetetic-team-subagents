"""Helpers for the async-gate tests: a real repository, the real hooks as subprocesses, a gate check the
test can hold open and release. Nothing here sleeps, polls or times out: the test learns that a check is
running from a FIFO line it writes itself, and that a worker has finished from the worker's process exit.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from task_support import make_fifo, tasks, wait_exit

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS / "lib"))

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
                         env={**os.environ, **GIT_ENV}, stdin=subprocess.DEVNULL)
    assert out.returncode == 0, f"git {args} failed: {out.stderr}"
    return out.stdout.strip()


def payload(command: str, cwd, tool="Bash") -> dict:
    return {"session_id": "s", "cwd": str(cwd), "tool_name": tool, "tool_input": {"command": command}}


def run_hook(script: str, event, cwd, env: dict | None = None):
    raw = event if isinstance(event, str) else json.dumps(event)
    out = subprocess.run([sys.executable, "-B", str(HOOKS / script)], input=raw, cwd=str(cwd),
                         capture_output=True, text=True, env={**os.environ, **GIT_ENV, **(env or {})})
    return out.returncode, out.stdout, out.stderr


def write_config(repo: Path, checks: list, **extra) -> None:
    (repo / ".zetetic").mkdir(exist_ok=True)
    (repo / ".zetetic" / "gate.json").write_text(json.dumps({"version": 1, "checks": checks, **extra}))


class Gate:
    """A repository gated by one check that announces itself on READY, then blocks on HOLD until released.

    The test keeps both FIFOs open read-write for its whole life, so no open(2) of either ever blocks (the
    check's read open of HOLD and write open of READY find a peer at once) and READY lines are read from a
    descriptor that never sees EOF. The check opens HOLD before it says READY, so releasing it (closing the
    test's HOLD descriptor) always reaches a reader that already exists. A plain open-write-close "fire" that
    can precede the reader's open leaves the reader asleep in open(2) for ever; that is the hang this layout
    removes.
    """

    def __init__(self, tmp: Path):
        self.tmp, self.repo, self.state = tmp, tmp / "repo", tmp / "state"
        self.repo.mkdir()
        (tmp / "tmp").mkdir()  # the worker's private checkouts land here, so a SIGKILLed one cannot litter /tmp
        self.hold, self.ready = make_fifo(tmp, "hold"), make_fifo(tmp, "ready")
        self.hold_fd, self.ready_fd = os.open(self.hold, os.O_RDWR), os.open(self.ready, os.O_RDWR)
        self.mark = tmp / "mark"
        self.env = {tasks.store.ENV_DIR: str(self.state), "TMPDIR": str(tmp / "tmp")}
        git(self.repo, "init", "-q", "-b", "main")
        self.use_blocking_check()
        (self.repo / "a.txt").write_text("one\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init", "--no-verify")

    def use_blocking_check(self) -> None:
        # fd 3 is opened on HOLD BEFORE the check announces itself: once the test has seen READY, closing its own
        # HOLD descriptor is guaranteed to be seen as EOF by a reader that already exists. Announcing first and
        # opening afterwards loses the race on Linux (the reader then opens a FIFO with no writer and sleeps for ever).
        script = f"exec 3<{self.hold}; echo $$ >> {self.mark}; echo $$ > {self.ready}; exec cat <&3 >/dev/null"
        write_config(self.repo, [{"name": "hold", "argv": ["sh", "-c", script]}])

    def stage(self, text: str) -> str:
        (self.repo / "a.txt").write_text(text)
        git(self.repo, "add", "a.txt")
        return git(self.repo, "write-tree")

    def commit(self) -> str:
        git(self.repo, "commit", "-q", "-m", "x", "--no-verify")
        return git(self.repo, "rev-parse", "HEAD^{tree}")

    def hook(self, script: str, command: str):
        return run_hook(script, payload(command, self.repo), self.repo, self.env)

    def gate(self, command: str):
        return self.hook("gate-proof.py", command)

    def head_start(self, command: str = "git add a.txt"):
        return self.hook("gate-start.py", command)

    def record(self, tree: str) -> dict | None:
        """The task record of ``tree`` (the test sets ZETETIC_TASKS_DIR for itself and its subprocesses)."""
        return tasks.status(f"gate-{tree}", str(self.repo))

    def _read_ready_line(self) -> bytes:
        line = b""
        while not line.endswith(b"\n"):
            line += os.read(self.ready_fd, 1)  # blocks until the check writes; never EOF (we are a writer too)
        return line

    def await_running(self, tree: str) -> dict:
        """Block until the check of ``tree`` is executing (it said so on READY); return the record."""
        self._read_ready_line()
        return self.record(tree)

    def finish(self, tree: str) -> dict:
        """Release the held check and block until the worker exited; return the final record."""
        rec = self.record(tree)
        os.close(self.hold_fd)  # EOF for the check's cat: it exits 0
        wait_exit(rec["pid"])
        self.hold_fd = os.open(self.hold, os.O_RDWR)  # armed again, only after the previous reader is gone
        return self.record(tree)

    def _end_if_in_flight(self, path: Path) -> None:
        rec = tasks.store.read_record(str(path))
        if not (rec and rec["state"] in ("queued", "running") and tasks.store.record_alive(rec)):
            return
        try:
            os.killpg(rec["pgid"] or rec["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass  # gone between the liveness read and the kill
        wait_exit(rec["pid"])

    def close(self) -> None:
        """Teardown: end every task this test left in flight (its own processes), then wait for each worker."""
        for path in sorted(self.state.glob("gate-*.json")) if self.state.is_dir() else []:
            self._end_if_in_flight(path)
        os.close(self.hold_fd)
        os.close(self.ready_fd)

    def started(self) -> list:
        """Names of the gate task records on disk."""
        return sorted(p.name for p in self.state.glob("gate-*.json")) if self.state.is_dir() else []

    def runs(self) -> int:
        return len(self.mark.read_text().split()) if self.mark.exists() else 0

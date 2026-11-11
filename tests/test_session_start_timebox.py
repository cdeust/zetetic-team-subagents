"""A section of hooks/session-start.sh that hangs is killed with its whole process group.

Before: the shell watchdog `run_timeboxed` killed only the direct child. A tool
that spawned a grandchild left it alive holding the stdout pipe of
`$(...)` / `| sed`, so the hook never returned (and, without coreutils
`timeout`, a `sleep` watchdog cost the whole budget besides). The runner now puts
each section in its own session and kills the group at the budget.

These tests decide on events only, never on elapsed time, and a regression
FAILS them instead of hanging them:

* the section announces its pid on a fifo, and the test checks at that moment
  that the section is its own session leader (what `start_new_session` buys);
* once the runner has returned, the test releases a token that a grandchild of
  the group is blocked on. A grandchild that is still alive wakes up and writes
  `survived`; one that was sent SIGKILL can never run another instruction. The
  fifo then reaches EOF in both cases, so the verdict is the text read, not a wait.

Without the kill of the group (`proc.kill()` instead of `killpg`) the grandchild
survives and the token makes it say so; without `start_new_session` the session-
leader check fails at once. Only a runner that never returns at all (no kill of
any kind) can still wait, and the CI job timeout bounds that as infrastructure.
"""

from pathlib import Path
import io
import os
import shutil
import signal
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

import run_sections  # noqa: E402
from task_support import wait_exit  # noqa: E402

RUNNER = ROOT / "hooks" / "lib" / "run_sections.py"
BUDGET_S = 1  # source: product budget handed to the runner; short so the test is quick
LONG_BUDGET_S = 600  # source: any value no test reaches; the kill under test comes from a signal, not the budget
HANG_SECTIONS = """
section_hang() {
  exec 3>"$GROUP_FIFO"          # every process of the group inherits this writer
  echo "$$" >&3                 # the section is its session leader: pid == pgid
  ( exec 4<>"$NEVER_FIFO"; read -r -u 4; echo survived >&3 ) &   # grandchild: waits for the token
  echo partial-output
  wait
}
section_after() { echo after; }
section_leaves_child() {      # exits at once; the child keeps this section's stdout and group open
  exec 3>"$GROUP_FIFO"
  ( exec 4<>"$NEVER_FIFO"; echo up >&3; read -r -u 4; echo alive >&3 ) &
  echo main-done
}
section_gated() {             # announces itself, then exits only when the test says so
  exec 3>"$GROUP_FIFO"; echo "$$" >&3; exec 3>&-
  read -r _ < "$RELEASE_FIFO"
  echo released
}
section_fail() { echo before-fail; exit 3; }
section_slow_first() { echo first; }
"""


class Fifos:
    """The two fifos of a scenario and the token that tells survivors apart from the killed."""

    def __init__(self, tmp_path):
        self.group = tmp_path / "group"
        self.never = tmp_path / "never"
        os.mkfifo(self.group)
        os.mkfifo(self.never)
        self.env = {"GROUP_FIFO": str(self.group), "NEVER_FIFO": str(self.never)}
        self._token_fd = os.open(self.never, os.O_RDWR)  # keeps the token readable by a late opener

    def release_token(self):
        """Wake every process blocked on the never fifo; the killed cannot answer."""
        os.write(self._token_fd, b"go\n")

    def close(self):
        os.close(self._token_fd)


def _kill_own_child(pid):
    """Cleanup of a process this test started (its pid came from our own runner child)."""
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:  # FAILS_ON: already gone, which is the good case
        pass


def _assert_session_leader(pid):
    got = (os.getpgid(pid), os.getsid(pid))
    assert got == (pid, pid), f"section {pid} is not its own session leader (pgid, sid) = {got}"


def _survivors(fifos, group):
    """After the runner is done: release the token, read the group fifo to EOF."""
    fifos.release_token()
    return group.read()


def _run_in_thread(tmp_path, names, monkeypatch):
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    fifos = Fifos(tmp_path)
    for key, value in fifos.env.items():
        monkeypatch.setenv(key, value)
    out = io.BytesIO()
    runner = threading.Thread(target=run_sections.run_sections, args=(str(lib), names, BUDGET_S, out),
                              daemon=True)
    runner.start()
    return runner, out, fifos


def test_hung_section_with_a_grandchild_is_killed_as_a_group(tmp_path, monkeypatch):
    runner, out, fifos = _run_in_thread(tmp_path, ["hang", "after"], monkeypatch)
    pid = None
    try:
        with open(fifos.group, "rb") as group:  # opens when the section does
            pid = int(group.readline())
            _assert_session_leader(pid)
            runner.join()  # the runner returned: it killed what it was going to kill
            assert _survivors(fifos, group) == b"", "a process of the killed group outlived the runner"
        assert out.getvalue() == (b"partial-output\n  session-start: section hang was still running at the 1 s budget and was killed\n"
                                  b"after\n")
    finally:
        if pid is not None:
            _kill_own_child(pid)
        fifos.release_token()
        runner.join()
        fifos.close()


def test_failing_section_leaves_the_others_intact_and_the_order(tmp_path, monkeypatch):
    runner, out, fifos = _run_in_thread(tmp_path, ["fail", "slow_first", "after"], monkeypatch)
    try:
        runner.join()
        assert out.getvalue() == b"before-fail\nfirst\nafter\n"
    finally:
        fifos.close()


def _default_sigint():
    # A test run started from a background job inherits SIGINT as ignored, which
    # would make the signal test depend on how pytest was launched.
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def _popen_runner(args, env_extra, **kwargs):
    env = {**os.environ, **env_extra}
    return subprocess.Popen([sys.executable, str(RUNNER), *args], stdout=subprocess.PIPE, env=env,
                            preexec_fn=_default_sigint, **kwargs)


def test_runner_exits_zero_when_a_section_fails_or_hangs(tmp_path):
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    fifos = Fifos(tmp_path)
    proc = _popen_runner([str(lib), str(BUDGET_S), "fail", "hang", "after"], fifos.env)
    pid = None
    try:
        with open(fifos.group, "rb") as group:
            pid = int(group.readline())
            _assert_session_leader(pid)
            out = proc.stdout.read()  # EOF on the hook's own pipe: the runner exited
            assert proc.wait() == 0
            assert _survivors(fifos, group) == b"", "a process of the killed group outlived the runner"
        assert out == (b"before-fail\npartial-output\n"
                       b"  session-start: section hang was still running at the 1 s budget and was killed\nafter\n")
    finally:
        if pid is not None:
            _kill_own_child(pid)
        fifos.release_token()
        proc.stdout.close()
        proc.wait()
        fifos.close()


def test_session_start_hook_returns_when_a_tool_leaves_a_grandchild(tmp_path):
    # The 9014be4 failure end to end: plugin-version-check.sh is read through
    # `$(...)`; its grandchild kept that pipe open and the hook never returned.
    plugin = tmp_path / "plugin"
    shutil.copytree(ROOT / "hooks", plugin / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
    (plugin / "tools").mkdir()
    tool = plugin / "tools" / "plugin-version-check.sh"
    tool.write_text(
        "#!/usr/bin/env bash\n"
        'exec 3>"$GROUP_FIFO"; echo "$$" >&3\n'
        '( exec 4<>"$NEVER_FIFO"; read -r -u 4; echo survived >&3 ) &\n'
        "wait\n"
    )
    tool.chmod(0o755)
    fifos = Fifos(tmp_path)
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin), **fifos.env}
    hook = subprocess.Popen(["bash", str(plugin / "hooks" / "session-start.sh")], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=tmp_path)
    pid = None
    try:
        with open(fifos.group, "rb") as group:
            pid = int(group.readline())
            assert os.getpgid(pid) != os.getpgid(0), "the tool runs in the hook's own process group"
            out = hook.stdout.read()  # EOF on the hook's pipe: no survivor holds it
            assert hook.wait() == 0
            assert _survivors(fifos, group) == b"", "a process of the killed group outlived the hook"
        assert b"Plugin Currency" not in out  # the killed tool printed nothing
    finally:
        if pid is not None:
            _kill_own_child(pid)
        fifos.release_token()
        hook.stdout.close()
        hook.wait()
        fifos.close()


# --- the runner reports a failure of its own, with its real cause, and exits 0 ---

def _run_to_completion(args, env_extra):
    """Runner as a subprocess; returns (exit status, stdout text)."""
    proc = _popen_runner(args, env_extra)
    out = proc.stdout.read()
    proc.stdout.close()
    return proc.wait(), out.decode()


def test_missing_bash_is_reported_as_missing_bash_not_as_a_tmpdir_problem(tmp_path):
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    rc, out = _run_to_completion([str(lib), "1", "after"], {"PATH": str(empty)})
    assert rc == 0
    assert "FileNotFoundError" in out and "'bash'" in out
    assert "TMPDIR" not in out


def _popen_main_with(patch_source, args, env_extra, epilogue=""):
    """The real `main` of the runner, after `patch_source` has replaced one stdlib call.

    `epilogue` runs in the same process once `main` has returned (its return
    value is in `rc`).
    """
    wrapper = (
        "import errno, os, subprocess, sys, tempfile, threading\n"
        f"sys.path.insert(0, {str(ROOT / 'hooks' / 'lib')!r})\n"
        "import run_sections\n"
        f"{patch_source}\n"
        "rc = run_sections.main(sys.argv[1:])\n"
        f"{epilogue}\n"
        "sys.exit(rc)\n"
    )
    return subprocess.Popen([sys.executable, "-c", wrapper, *args], stdout=subprocess.PIPE,
                            env={**os.environ, **env_extra})


def test_unusable_tmpdir_is_reported_with_its_own_error(tmp_path):
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    proc = _popen_main_with(
        "def mkdtemp(*a, **k):\n    raise PermissionError(errno.EACCES, 'Permission denied')\n"
        "tempfile.mkdtemp = mkdtemp",
        [str(lib), "1", "after"], {})
    out = proc.stdout.read().decode()
    proc.stdout.close()
    assert proc.wait() == 0
    assert "PermissionError" in out and "Permission denied" in out


@pytest.mark.parametrize("args, cause", [
    (["{lib}", "not-a-number", "after"], "could not convert string to float"),
    (["{lib}"], "not enough values to unpack"),
])
def test_bad_arguments_are_reported_not_a_traceback_and_exit_zero(tmp_path, args, cause):
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    rc, out = _run_to_completion([a.format(lib=lib) for a in args], {})
    assert rc == 0
    assert "ValueError" in out and cause in out
    assert "Traceback" not in out


def test_a_failed_start_midway_reports_the_cause_and_kills_the_sections_already_started(tmp_path):
    # Fork failure on the SECOND section: the first one is already running and
    # must not be orphaned. The wrapper reads the first section's announcement
    # on the fifo, and only then makes the second Popen raise ENOMEM, so the
    # failure cannot beat the first section's own start. Once `main` has
    # returned it releases the token and reports what the group fifo yielded.
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    fifos = Fifos(tmp_path)
    proc = _popen_main_with(
        "announced, group = threading.Event(), []\n"
        "def watch():\n"
        "    group.append(open(os.environ['GROUP_FIFO'], 'rb'))\n"
        "    pid = int(group[0].readline())\n"
        "    if (os.getpgid(pid), os.getsid(pid)) != (pid, pid):\n"
        "        print('NOT-A-SESSION-LEADER')\n"
        "        os.kill(pid, 9)\n"
        "    announced.set()\n"
        "threading.Thread(target=watch, daemon=True).start()\n"
        "real, calls = subprocess.Popen, []\n"
        "def popen(*a, **k):\n"
        "    calls.append(1)\n"
        "    if len(calls) == 2:\n"
        "        announced.wait()\n"
        "        raise OSError(errno.ENOMEM, 'Cannot allocate memory')\n"
        "    return real(*a, **k)\n"
        "subprocess.Popen = popen",
        [str(lib), "1", "hang", "after"], fifos.env,
        epilogue=(
            "os.write(os.open(os.environ['NEVER_FIFO'], os.O_RDWR), b'go\\n')\n"
            "print('SURVIVORS=' + repr(group[0].read()))"
        ))
    try:
        out = proc.stdout.read().decode()
        assert proc.wait() == 0
        assert "OSError" in out and "Cannot allocate memory" in out
        assert "TMPDIR" not in out
        assert "NOT-A-SESSION-LEADER" not in out
        assert "SURVIVORS=b''" in out, "the section started before the failure was orphaned"
    finally:
        fifos.release_token()
        proc.stdout.close()
        proc.wait()
        fifos.close()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_a_signal_kills_every_live_group_removes_the_scratch_dir_and_exits_zero(tmp_path, sig):
    # What the hook timeout does to the runner: it must not leave section groups
    # behind or leak its temp directory. Event-synchronised: the signal is sent
    # once the section has announced itself; the runner's exit is its EOF.
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    fifos = Fifos(tmp_path)
    proc = _popen_runner([str(lib), str(LONG_BUDGET_S), "hang", "after"],
                         {**fifos.env, "TMPDIR": str(scratch)})
    pid = None
    try:
        with open(fifos.group, "rb") as group:
            pid = int(group.readline())
            _assert_session_leader(pid)
            proc.send_signal(sig)
            out = proc.stdout.read().decode()  # EOF: the runner is gone
            assert proc.wait() == 0
            assert sig.name in out
            assert os.listdir(scratch) == [], "the runner leaked its temp directory"
            assert _survivors(fifos, group) == b"", "a section group outlived the signalled runner"
    finally:
        if pid is not None:
            _kill_own_child(pid)
        fifos.release_token()
        proc.stdout.close()
        proc.wait()
        fifos.close()


GATED_RUNNER = """
import os, sys
sys.path.insert(0, {lib!r})
import run_sections
real_reap = run_sections._reap_live
def gated_reap(procs):
    # The handler has fired and the cleanup is starting: tell the test, then
    # hold the cleanup open until the test has delivered its second signal.
    with open(os.environ['CLEANUP_FIFO'], 'wb') as announce:
        announce.write(b'cleanup\\n')
    with open(os.environ['RELEASE_FIFO'], 'rb') as release:
        release.readline()  # data survives in the pipe: the test holds its write end open
    real_reap(procs)
run_sections._reap_live = gated_reap
sys.exit(run_sections.main(sys.argv[1:]))
"""


def test_a_second_signal_during_the_cleanup_does_not_reenter_it(tmp_path):
    # Event-synchronised: the second SIGTERM is sent while the cleanup of the
    # first is provably running (it announced itself and waits for us).
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    fifos = Fifos(tmp_path)
    cleanup, release = tmp_path / "cleanup", tmp_path / "release"
    os.mkfifo(cleanup)
    os.mkfifo(release)
    wrapper = tmp_path / "gated_runner.py"
    wrapper.write_text(GATED_RUNNER.format(lib=str(ROOT / "hooks" / "lib")))
    env = {**os.environ, **fifos.env, "CLEANUP_FIFO": str(cleanup), "RELEASE_FIFO": str(release)}
    proc = subprocess.Popen([sys.executable, str(wrapper), str(lib), str(LONG_BUDGET_S), "hang", "after"],
                            stdout=subprocess.PIPE, env=env, preexec_fn=_default_sigint)
    pid = None
    go = os.open(release, os.O_RDWR)  # held open to the end: a closed, unread FIFO discards its data
    try:
        with open(fifos.group, "rb") as group:
            pid = int(group.readline())
            proc.send_signal(signal.SIGTERM)
            with open(cleanup, "rb") as announced:
                assert announced.readline() == b"cleanup\n"
            proc.send_signal(signal.SIGTERM)  # second signal, mid-cleanup
            os.write(go, b"go\n")
            out = proc.stdout.read().decode()
            assert proc.wait() == 0, out
            assert "SIGTERM" in out
            assert _survivors(fifos, group) == b"", "the re-entered cleanup left a section group alive"
    finally:
        os.close(go)
        if pid is not None:
            _kill_own_child(pid)
        fifos.release_token()
        proc.stdout.close()
        proc.wait()
        fifos.close()


@pytest.fixture
def delivery():
    """The handler's own state, restored with the dispositions it replaces."""
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    state = run_sections._Delivery
    before = (state.interruptible, state.held)
    try:
        yield state
    finally:
        state.interruptible, state.held = before
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def test_the_handler_ignores_further_signals_once_it_has_fired(delivery):
    with pytest.raises(run_sections._Interrupted):
        with run_sections._interruptible():
            run_sections._raise_interrupted(signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
    assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN


def test_a_signal_outside_a_wait_is_held_and_raised_at_the_next_wait(delivery):
    run_sections._raise_interrupted(signal.SIGINT, None)  # outside a wait: returns, raises nothing
    assert delivery.held == "SIGINT"
    assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
    reached = []
    with pytest.raises(run_sections._Interrupted, match="SIGINT"):
        with run_sections._interruptible():
            reached.append("body")
    assert reached == [], "the wait started although a signal was already held"
    assert delivery.interruptible is False


def test_a_signal_landing_between_a_sections_fork_and_its_registration_still_kills_its_group(tmp_path):
    # The handler used to raise wherever the main thread was. Raised on the
    # instruction after the fork, it dropped the Popen object before the cleanup
    # list had it, and the section's group outlived the runner. Here the signal
    # is delivered at exactly that point: inside the Popen call of the first
    # section, once the section has announced itself on the fifo (so the kill
    # cannot beat its start). Once `main` has returned, the wrapper releases the
    # token and reports what the group fifo yielded.
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    fifos = Fifos(tmp_path)
    proc = _popen_main_with(
        "import signal\n"
        "announced, group = threading.Event(), []\n"
        "def watch():\n"
        "    group.append(open(os.environ['GROUP_FIFO'], 'rb'))\n"
        "    group[0].readline()\n"
        "    announced.set()\n"
        "threading.Thread(target=watch, daemon=True).start()\n"
        "real, calls = subprocess.Popen, []\n"
        "def popen(*a, **k):\n"
        "    child = real(*a, **k)\n"
        "    calls.append(1)\n"
        "    if len(calls) == 1:\n"
        "        announced.wait()\n"
        "        os.kill(os.getpid(), signal.SIGTERM)\n"
        "    return child\n"
        "subprocess.Popen = popen",
        [str(lib), str(LONG_BUDGET_S), "hang", "after"], fifos.env,
        epilogue=(
            "os.write(os.open(os.environ['NEVER_FIFO'], os.O_RDWR), b'go\\n')\n"
            "print('SURVIVORS=' + repr(group[0].read()))"
        ))
    try:
        out = proc.stdout.read().decode()
        assert proc.wait() == 0
        assert "interrupted by SIGTERM" in out
        assert "SURVIVORS=b''" in out, "a section forked just before the signal outlived the runner"
    finally:
        fifos.release_token()
        proc.stdout.close()
        proc.wait()
        fifos.close()


LOCK_WINDOW_PATCH = """
import signal
class Watched:
    # Stands for Popen._waitpid_lock. The signal is delivered once, right after
    # the first acquisition: where a handler that raises leaves the lock held.
    fired = False
    def __init__(self, lock):
        self.lock, self.held = lock, False
    def acquire(self, blocking=True, timeout=-1):
        if blocking and self.held:
            print('DEADLOCK: the cleanup waits on a lock the interrupted wait still holds', flush=True)
            os._exit(3)
        got = self.lock.acquire(blocking, timeout)
        if got:
            self.held = True
            if not Watched.fired:
                Watched.fired = True
                os.kill(os.getpid(), signal.SIGTERM)
        return got
    def release(self):
        self.held = False
        self.lock.release()
    def __enter__(self):
        self.acquire()
    def __exit__(self, *exc):
        self.release()
real = subprocess.Popen
def popen(*a, **k):
    child = real(*a, **k)
    child._waitpid_lock = Watched(child._waitpid_lock)
    return child
subprocess.Popen = popen
"""


def test_a_signal_landing_while_the_wait_holds_the_subprocess_lock_does_not_deadlock_the_cleanup(tmp_path):
    # Popen.wait(timeout) and Popen.poll() take `_waitpid_lock` without blocking
    # and release it in a `finally` that starts one instruction later. A handler
    # that raised in between left the lock held, and the cleanup's `proc.wait()`
    # then slept on it for ever: the runner never exited (observed once in 44
    # runs of the signal test). The signal is delivered at exactly that
    # instruction; the stand-in lock turns the sleep into exit status 3.
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    fifos = Fifos(tmp_path)
    proc = _popen_main_with(LOCK_WINDOW_PATCH, [str(lib), str(LONG_BUDGET_S), "hang", "after"], fifos.env)
    try:
        out = proc.stdout.read().decode()
        assert "DEADLOCK" not in out
        assert proc.wait() == 0
        assert "interrupted by SIGTERM" in out
    finally:
        fifos.release_token()
        proc.stdout.close()
        proc.wait()
        fifos.close()


WAKEUP_PATCH = """
import select
real_select, calls, log = select.select, [], []
def watched(r, w, x, timeout=None):
    # First wait of the runner on its wake-up pipe: say so, let the test end the
    # section, then look at the pipe without waiting. The exit of the section must
    # already have written to it (SIGCHLD); an empty pipe would make the real wait
    # last the whole budget, so it is reported and the process ends at once.
    calls.append(1)
    if len(calls) == 1:
        with open(os.environ['INSELECT_FIFO'], 'w') as said:
            said.write('in select\\n')
        open(os.environ['GO_FIFO']).readline()
        if not real_select(r, [], [], 0)[0]:
            print('NO WAKE-UP: the section exited and the wake-up pipe is empty', flush=True)
            os._exit(3)
        log.append('woken by the exit')
    return real_select(r, w, x, timeout)
select.select = watched
"""


def test_the_exit_of_a_section_wakes_the_runner_out_of_its_wait(tmp_path):
    # Every other section of this file exits before the runner reaches its wait,
    # so a wake-up pipe that no SIGCHLD writes to would cost the whole budget on
    # every boot and fail nothing. Here the section exits while the runner is in
    # its wait, and the verdict is the cause, never a duration: at the moment the
    # section is known to have exited (an OS event), the pipe the runner waits on
    # is readable, and the runner returns the section's output without killing it.
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    fifos = Fifos(tmp_path)
    names = {name: tmp_path / name for name in ("release", "inselect", "go")}
    for path in names.values():
        os.mkfifo(path)
    release = os.open(names["release"], os.O_RDWR)  # the section's read of it never blocks on open
    env = {**fifos.env, "RELEASE_FIFO": str(names["release"]), "INSELECT_FIFO": str(names["inselect"]),
           "GO_FIFO": str(names["go"])}
    proc = _popen_main_with(WAKEUP_PATCH, [str(lib), str(LONG_BUDGET_S), "gated"], env,
                            epilogue="print('SELECT_LOG=' + repr(log))")
    pid = None
    try:
        with open(fifos.group, "rb") as group:
            pid = int(group.readline())
        with open(names["inselect"]) as said:
            assert said.readline() == "in select\n"  # the runner is in its wait, the section alive
        os.write(release, b"go\n")
        wait_exit(pid)  # the section's main process has exited
        with open(names["go"], "w") as go:
            go.write("exited\n")
        out = proc.stdout.read().decode()
        assert "NO WAKE-UP" not in out
        assert proc.wait() == 0
        assert out == "released\nSELECT_LOG=['woken by the exit']\n"
    finally:
        os.close(release)
        if pid is not None:
            _kill_own_child(pid)
        proc.stdout.close()
        proc.wait()
        fifos.close()


# --- no Python: the hook says so on stdout instead of dropping the sections silently ---

def test_hook_without_python_says_so_on_stdout(tmp_path):
    # A PATH holding only what session-start.sh itself needs, no python anywhere.
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("bash", "dirname", "cp", "sed", "wc", "tr", "git"):  # bash: the hook scripts start with `env bash`
        found = shutil.which(name)
        if found:
            (tools / name).symlink_to(found)
    hook = ROOT / "hooks" / "session-start.sh"
    done = subprocess.run(
        [shutil.which("bash"), str(hook)], stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env={"PATH": str(tools), "HOME": str(tmp_path)}, cwd=tmp_path,
    )
    assert done.returncode == 0
    notice = [line for line in done.stdout.splitlines() if "boot sections not run" in line]
    assert len(notice) == 1, done.stdout
    assert "Python 3 not found" in notice[0] and "python3" in notice[0]
    assert "Reminder:" in done.stdout  # the rest of the hook still ran


def test_runner_does_not_wait_for_descendants_of_a_finished_section(tmp_path):
    """The boot report is complete when the section's MAIN process exits (2026-10-15 investigation).

    The child of `leaves_child` is alive and holds the section's stdout when the
    section's main process exits. The runner must return on the main process's
    exit, neither waiting for the child nor killing it (background work belongs
    to a detached task). Decided on events: the child says `up` while it is
    alive, the runner's pipe reaches EOF, and only then is the child released;
    a runner that waited for the child would never reach EOF (the CI job
    timeout bounds that as infrastructure), one that killed it would leave no
    `alive`.
    """
    lib = tmp_path / "sections.sh"
    lib.write_text(HANG_SECTIONS)
    fifos = Fifos(tmp_path)
    proc = _popen_runner([str(lib), str(LONG_BUDGET_S), "leaves_child", "after"], fifos.env)
    try:
        with open(fifos.group, "rb") as group:
            assert group.readline() == b"up\n"
            out = proc.stdout.read()
            assert proc.wait() == 0
            assert _survivors(fifos, group) == b"alive\n", "the runner killed the descendant of a finished section"
        assert out == b"main-done\nafter\n"
    finally:
        fifos.release_token()
        proc.stdout.close()
        proc.wait()
        fifos.close()

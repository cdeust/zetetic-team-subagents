#!/usr/bin/env python3
"""Run the boot sections of hooks/session-start.sh concurrently, each under a hard budget.

Usage: run_sections.py <sections.sh> <budget-seconds> <name> [<name> ...]

Each `section_<name>` function of <sections.sh> runs in its own bash, in its own
session (process group), with stdin on /dev/null, stderr discarded and stdout
sent to a file. When a section outlives the budget, its WHOLE group is killed,
so a hung tool's grandchildren cannot outlive it. Stdout goes to a file, not a
pipe, so a descendant that escaped the group still cannot hold this process up.

The outputs are written to stdout in the order of the names, whatever the order
in which the sections finish. A section that is killed contributes what it
wrote before the kill, then a line saying it was killed. Exit status is 0 whatever happens, in this runner itself
(not through a caller's `|| true`): a boot report must never fail the session.
A failure of the runner (bad arguments, no bash, fork or temp-dir error) and a
SIGTERM or SIGINT are reported on stdout with their real cause, after every
live section group has been killed and the scratch directory removed.
A signal never raises inside the start or the wait of a section: the handler
records it, and the wait, a select on a wake-up pipe, raises it from ordinary
code. So it can land neither between the creation of a section and its
registration for the cleanup, nor inside a subprocess call that holds a lock.

A section is complete when its own main process exits with its output written;
the runner never waits for descendants of a finished section (they hold only the
output file, not this process).

Contract:
  pre : <sections.sh> defines section_<name> for every name; budget > 0.
  post: returns only after every section process has exited or been killed
        (also when interrupted or failing); the bytes written equal the concatenation, in name order, of what each
        section wrote to stdout.
"""

import contextlib
import os
import select
import signal
import subprocess
import sys
import tempfile
import time

# set -euo pipefail: the sections were written for the errexit/pipefail of
# session-start.sh and keep that behaviour when they run in a fresh bash.
_BASH_PROGRAM = 'set -euo pipefail; source "$1"; "section_$2"'


# killpg is not atomic against a member that is inside fork() when the signal
# lands: the child joins the group only after the signal went out and survives
# it. Measured 2026-10-15 on macOS 25.6: with one pass a grandchild survived in
# 5 of 25 runs of tests/test_session_start_timebox.py, and three back-to-back
# passes still left one in 3 of 18 (a fork takes longer than the passes do).
# Passes made after the leader is reaped see every child it managed to fork.
# source: measurement above (loop outputs kept in ~/.claude/fleet/pr162/loopg.*, loopf.*)
_KILL_PASSES = 3


def _kill_group(proc):
    """SIGKILL the whole process group of `proc` (its own session leader), then reap it.

    post: `proc` is reaped; a second and third signal follow the reaping, so a
    child forked by a member during the first one does not outlive it. Stops
    early when the group is empty (ESRCH, or EPERM on macOS when only an
    unreaped leader is left). The pid cannot be reused while a member lives, so
    signalling the group after the reaping only ever reaches members.
    """
    if not hasattr(os, "killpg"):  # Windows: no process groups, the direct child is all that can be killed
        proc.kill()
        proc.wait()
        return
    for attempt in range(_KILL_PASSES):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # FAILS_ON: group already empty (ESRCH; EPERM on macOS for an unreaped leader alone): nothing to kill
            break
        if attempt == 0:
            proc.wait()  # the leader got SIGKILL: this returns as soon as it is reaped
    proc.wait()


class _Interrupted(Exception):
    """SIGTERM or SIGINT reached the runner; raised by the handler of `main`."""


class _Delivery:
    """How a SIGTERM or SIGINT reaches the runner: recorded by the handler, raised by the code that waits.

    Python runs a handler between any two bytecodes of the main thread, and one
    that raises there breaks what was running. Both breaks were measured on
    2026-11-11 with the signal test of tests/test_session_start_timebox.py:
    * raised on the instruction after the fork, it dropped the Popen object
      before the cleanup list held it and the section's group outlived the
      runner (the test failed in 8 of 30 runs of its file);
    * raised inside Popen.wait(timeout), between `_waitpid_lock.acquire(False)`
      and the `try` that releases it, it left the lock held and the cleanup's
      `proc.wait()` blocked on it for ever (1 run in 44).
    So the handler raises only while the runner writes its stdout, where no
    subprocess call is in progress; elsewhere it records the signal in `held`
    and `_exited_by` raises it between two system calls of its own.
    """

    interruptible = False  # True only inside _interruptible()
    held = None            # name of the signal recorded outside _interruptible()
    wakeup = None          # read end of the wake-up pipe; None when no handler is installed


def _raise_interrupted(signum, _frame):
    # Once fired, further SIGTERM/SIGINT are ignored: a second one must not
    # re-enter the cleanup this exception is about to start.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    name = signal.Signals(signum).name
    if not _Delivery.interruptible:
        _Delivery.held = name
        return
    raise _Interrupted(name)


@contextlib.contextmanager
def _interruptible():
    """Let a signal interrupt the body; raise at once the one held since before it.

    pre : no subprocess call is in progress in the body.
    post: outside the body a signal is recorded, never raised by the handler.
    """
    _Delivery.interruptible = True
    try:
        if _Delivery.held is not None:
            raise _Interrupted(_Delivery.held)
        yield
    finally:
        _Delivery.interruptible = False


def _ignore(_signum, _frame):
    """SIGCHLD needs a Python handler for its arrival to be written to the wake-up pipe."""


@contextlib.contextmanager
def _signals_delivered():
    """Install the handlers of `main` and the wake-up pipe `_exited_by` selects on.

    A signal with a Python handler writes one byte to the pipe on arrival
    (signal.set_wakeup_fd): a wait on it ends on a section's exit (SIGCHLD) and
    on SIGTERM or SIGINT. Windows has neither SIGCHLD nor select on a pipe: no
    pipe there, and a signal recorded during a wait is raised when it ends.
    """
    signal.signal(signal.SIGTERM, _raise_interrupted)
    signal.signal(signal.SIGINT, _raise_interrupted)
    if not hasattr(signal, "SIGCHLD"):
        yield
        return
    read_end, write_end = os.pipe()
    os.set_blocking(read_end, False)
    os.set_blocking(write_end, False)
    signal.signal(signal.SIGCHLD, _ignore)
    previous = signal.set_wakeup_fd(write_end, warn_on_full_buffer=False)
    _Delivery.wakeup = read_end
    try:
        yield
    finally:
        _Delivery.wakeup = None
        signal.set_wakeup_fd(previous)
        os.close(read_end)
        os.close(write_end)


def _raise_held():
    if _Delivery.held is not None:
        raise _Interrupted(_Delivery.held)


def _exited_by(proc, deadline):
    """Wait for the main process of `proc` until `deadline`. True iff it exited.

    Raises _Interrupted, from its own code, for a signal recorded before or
    during the wait. With the wake-up pipe the wait is a select that a child's
    exit and a signal both end; without it (library use, Windows) it is the
    plain timed wait.
    """
    while True:
        _raise_held()
        if _Delivery.wakeup is None:
            try:
                proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                _raise_held()
                return False
            _raise_held()
            return True
        if proc.poll() is not None:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if select.select([_Delivery.wakeup], [], [], remaining)[0]:
            try:
                os.read(_Delivery.wakeup, select.PIPE_BUF)  # drain; what arrived is read from poll() and `held`
            except BlockingIOError:  # FAILS_ON: nothing left to read; the loop decides from poll() and `held`
                pass


def _start(sections_file, name, sink):
    return subprocess.Popen(
        ["bash", "-c", _BASH_PROGRAM, "bash", sections_file, name],
        stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wait_or_kill(proc, deadline):
    """Wait for the section's MAIN process until `deadline`; kill its group if it is still running.

    A section is complete when its main process exits: descendants it left
    behind are never waited for (background work belongs in a detached task,
    tools/lib/tasks.py). The kill is the host-imposed safety net for a main
    process that is still running at the budget, not a completion path.
    post: returns True iff the section had to be killed.
    """
    if _exited_by(proc, deadline):
        return False
    _kill_group(proc)
    return True


def _report_killed(scratch, name, budget_s):
    """Make a safety-net kill visible in the section's own output, where the user reads it."""
    with open(os.path.join(scratch, name), "ab") as sink:
        sink.write(f"  session-start: section {name} was still running at the {budget_s:g} s budget and was killed\n".encode())


def _reap_live(procs):
    """Kill the group of every section still running, whatever made us stop."""
    for proc in procs:
        if proc.poll() is None:  # poll() reaps an exited leader, so a pid is never reused here
            _kill_group(proc)


def _start_all(sections_file, names, scratch, procs):
    """Start every section; each is appended to `procs` the moment it exists, so
    a failure on a later one leaves the earlier ones visible to the caller's cleanup."""
    for name in names:
        with open(os.path.join(scratch, name), "wb") as sink:  # the child holds its own descriptor
            procs.append(_start(sections_file, name, sink))


def _wait_all(sections, scratch, started, budget_s):
    """Wait for every (name, proc) section's main process; say so in its output when one had to be killed."""
    for name, proc in sections:
        if _wait_or_kill(proc, started + budget_s):
            _report_killed(scratch, name, budget_s)


def _write_in_order(scratch, names, out):
    for name in names:
        with open(os.path.join(scratch, name), "rb") as written:
            data = written.read()
        with _interruptible():  # a reader that stopped reading must not hold the runner past a signal
            out.write(data)
            out.flush()


def run_sections(sections_file, names, budget_s, out):
    """Run every section concurrently and write their outputs to `out` in order.

    post: on return AND on any exception (including _Interrupted) no section
    group started here is left running and the scratch directory is removed.
    """
    with tempfile.TemporaryDirectory(prefix="zetetic-start.") as scratch:
        procs = []
        try:
            started = time.monotonic()
            _start_all(sections_file, names, scratch, procs)
            _wait_all(list(zip(names, procs)), scratch, started, budget_s)
            _write_in_order(scratch, names, out)
        finally:
            _reap_live(procs)


def main(argv):
    """Always returns 0; a failure is reported on stdout with its real cause."""
    try:
        with _signals_delivered():
            sections_file, budget, *names = argv
            run_sections(sections_file, names, float(budget), sys.stdout.buffer)
    except _Interrupted as exc:  # FAILS_ON: SIGTERM or SIGINT; groups are already killed and the scratch removed by run_sections
        _report(f"  session-start: boot sections not completed: interrupted by {exc}")
    except Exception as exc:  # FAILS_ON: any other failure (bad arguments, bash missing, fork or temp-dir error); a boot report must never fail the session
        _report(f"  session-start: boot sections not completed: {type(exc).__name__}: {exc}")
    return 0


def _report(line):
    """Print `line` on stdout; if stdout itself is gone, stderr is the last visible place."""
    try:
        sys.stdout.flush()
        print(line, flush=True)
    except OSError:  # FAILS_ON: stdout closed or broken pipe
        print(line, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Put the repo root on sys.path so `import tools.acceptance_gate` resolves.

The module MUST be imported under its fully-qualified package path
(`tools.acceptance_gate`) — that is the key mutmut uses to match its trampoline
hits to mutants (rules/coding-standards.md §12). Importing it bare (as
`acceptance_gate`) makes every mutant look unreached and mutmut stops early.

Adding the repo root (parent of tools/ and tests/) works in two layouts with the
SAME code: the real repo, and mutmut's `mutants/` sandbox — mutmut copies
source_paths + also_copy preserving that sibling layout, so the path computed
from __file__ points at the MUTATED tools/acceptance_gate.py.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from leak_support import live_processes_naming
from reflection_support import (
    SESSION,
    event,
    make_transcript,
    run_hook,
    start_hook,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


# -- worktree sweep fixtures -------------------------------------------------
SWEPT_ROOTS = ("/tmp/", "/private/tmp/")  # source: tools/worktree-manager.sh sweepable_path()


@pytest.fixture
def unswept_dir():
    """A directory the sweep never treats as agent scratch, on Linux and macOS alike.

    pytest's tmp_path is /tmp/... on Linux (a swept root) but /private/var/... on macOS, so a
    "deliberate worktree" placed under tmp_path is only deliberate on macOS. /var/tmp is outside
    both swept roots on both platforms; the assert makes a wrong platform layout fail loudly.
    """
    path = tempfile.mkdtemp(prefix="sweep-deliberate-", dir="/var/tmp")
    assert not (path + "/").startswith(SWEPT_ROOTS), path
    try:
        yield Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


# -- subagent-reflection fixtures (#153) -------------------------------------
# Names are prefixed or unique in the suite (`repo` is defined locally elsewhere).
@pytest.fixture
def reflection_repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@pytest.fixture
def schedule(reflection_repo, tmp_path, monkeypatch, capsys):
    """schedule(agent_id, session): run the SubagentStop hook for one general-purpose run."""
    def _schedule(agent_id="a1b2c3", session=SESSION):
        transcript = make_transcript(tmp_path, agent_id=agent_id)
        run_hook(start_hook, event(reflection_repo, transcript, agent_id=agent_id, agent_type="general-purpose",
                                   session_id=session), monkeypatch, capsys)
    return _schedule


# -- leak guard ----------------------------------------------------------------
# Scanning every process after every test costs ~35-40 ms on macOS (about 75 s over the whole
# suite), so the guard runs only for tests that can start processes: those marked `spawns`
# (module `pytestmark` in the task, worker, memory-daemon and sweep modules) and those using
# the `spawning` fixture (the task `state` fixtures request it). CI honours the same selection.
@pytest.fixture
def spawning():
    """Marker fixture: a test using it (directly or through another fixture) can start processes."""


def _can_spawn(request) -> bool:
    return request.node.get_closest_marker("spawns") is not None or "spawning" in request.fixturenames


@pytest.fixture(autouse=True)
def no_leaked_processes(request):
    """Fail a test that can spawn and leaves a process alive whose argv names its tmp_path.

    Autouse and requested before every other fixture, so it is torn down last: it
    sees the world after the test's own teardown. The survivors are killed (a leak
    must not outlive the run that found it) and the test errors with their pids.
    """
    watched = request.getfixturevalue("tmp_path") if _can_spawn(request) else None
    yield
    if watched is None:
        return
    leaked = live_processes_naming(watched)
    for pid, _argv in leaked:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # it exited between the scan and the kill: not a leak any more
    assert not leaked, "test left processes running (killed by the guard): " + "; ".join(
        f"{pid} {argv}" for pid, argv in leaked)

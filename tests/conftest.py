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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
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
    """schedule(agent_id, session): run the SubagentStop hook for one engineer run."""
    def _schedule(agent_id="a1b2c3", session=SESSION):
        transcript = make_transcript(tmp_path, agent_id=agent_id)
        run_hook(start_hook, event(reflection_repo, transcript, agent_id=agent_id, agent_type="engineer",
                                   session_id=session), monkeypatch, capsys)
    return _schedule

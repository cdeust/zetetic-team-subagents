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
import subprocess
import sys
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

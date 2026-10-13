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
import http.server
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from reflection_support import (
    SESSION,
    _Recorder,
    event,
    make_transcript,
    run_hook,
    start_hook,
    write_hindsight_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


# -- subagent-reflection fixtures (#153) -------------------------------------
# Not autouse: the Hindsight isolation is applied by `pytestmark` in each
# test_subagent_reflection_*.py module, so no other module is affected.
# Names are prefixed or unique in the suite (`repo` is defined locally elsewhere).
@pytest.fixture
def reflection_repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@pytest.fixture
def no_real_hindsight(tmp_path, monkeypatch) :
    """Default: Hindsight config absent, so no test can reach a real server."""
    config = tmp_path / "hindsight.json"
    monkeypatch.setenv("HINDSIGHT_CONFIG", str(config))
    monkeypatch.delenv("HINDSIGHT_API_URL", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_TOKEN", raising=False)
    return config


@pytest.fixture
def hindsight_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    server.received, server.auth, server.status = [], [], 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join()
    server.server_close()


@pytest.fixture
def fire(reflection_repo, tmp_path, monkeypatch, capsys):
    """fire(cwd=None): run the SubagentStop hook for one run, return its stderr."""
    def _fire(cwd=None):
        payload = event(cwd or reflection_repo, make_transcript(tmp_path), agent_id="a1b2c3", agent_type="engineer")
        return run_hook(start_hook, payload, monkeypatch, capsys)[2]
    return _fire


@pytest.fixture
def configure(reflection_repo, no_real_hindsight):
    """configure(api_url, opt_in=None): write the Hindsight config for `repo`."""
    def _configure(api_url, opt_in=None):
        write_hindsight_config(no_real_hindsight, reflection_repo, api_url, opt_in)
    return _configure


@pytest.fixture
def schedule(reflection_repo, tmp_path, monkeypatch, capsys):
    """schedule(agent_id, session): run the SubagentStop hook for one engineer run."""
    def _schedule(agent_id="a1b2c3", session=SESSION):
        transcript = make_transcript(tmp_path, agent_id=agent_id)
        run_hook(start_hook, event(reflection_repo, transcript, agent_id=agent_id, agent_type="engineer",
                                   session_id=session), monkeypatch, capsys)
    return _schedule

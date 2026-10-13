"""Shared fixtures and helpers for the subagent-reflection tests (#153).

The hook scripts are loaded by path (hyphenated names, hooks/ is not a package)
and run in-process against a real throwaway git repository. Hindsight
"configured" is a real http.server on an ephemeral port: the socket is bound and
listening when the server object exists, so no readiness wait is needed.
"Server down" is a port that was bound and then closed: connection refused is
immediate, not a timer. Nothing here sleeps or retries.
"""
from __future__ import annotations

import http.server
import importlib.util
import io
import json
import socket
import sys
import threading
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "sess-A"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


start_hook = _load("subagent_stop_reflection", "hooks/subagent-stop-reflection.py")
stop_hook = _load("stop_reflection_gate", "hooks/stop-reflection-gate.py")
import reflection_hindsight  # noqa: E402,F401  (tools/ is put on sys.path by the hooks above)
import reflection_ledger as ledger  # noqa: E402,F401
import reflection_subagent  # noqa: E402,F401


# -- fixtures ---------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@pytest.fixture(autouse=True)
def no_real_hindsight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Default: Hindsight config absent, so no test can reach a real server."""
    config = tmp_path / "hindsight.json"
    monkeypatch.setenv("HINDSIGHT_CONFIG", str(config))
    monkeypatch.delenv("HINDSIGHT_API_URL", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_TOKEN", raising=False)
    return config


def _assistant(message_id: str, block: dict) -> str:
    return json.dumps({"type": "assistant", "message": {"id": message_id, "content": [block]}})


def make_transcript(tmp_path: Path, agent_id: str = "a1b2c3", meta: dict | None = None,
                    handback: str | None = "Done: fixed the bug in parser.py") -> Path:
    sub = tmp_path / "proj" / SESSION / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    transcript = sub / f"agent-{agent_id}.jsonl"
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "task"}}),
             _assistant("m1", {"type": "text", "text": "working on it"})]
    if handback is not None:
        lines.append(_assistant("m2", {"type": "tool_use", "name": "SubagentHandback",
                                       "input": {"message": handback}}))
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if meta is not None:
        (sub / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return transcript


def event(repo: Path, transcript: Path | None, **extra) -> dict:
    base = {"session_id": SESSION, "cwd": str(repo), "hook_event_name": "SubagentStop"}
    if transcript is not None:
        base["agent_transcript_path"] = str(transcript)
    base.update(extra)
    return base


def run_hook(module, payload: dict, monkeypatch: pytest.MonkeyPatch, capsys) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = module.main()
    out = capsys.readouterr()
    return code, out.out, out.err


def raw_rows(repo: Path) -> list[dict]:
    return ledger.read_rows(ledger.ledger_path(str(repo)))


def rows(repo: Path) -> list[dict]:
    """The ledger as a reader sees it: outcome lines merged into their pending row."""
    raw = raw_rows(repo)
    outcomes = {r["hindsight_for"]: r["hindsight"] for r in raw if "hindsight_for" in r}
    return [{**r, "hindsight": outcomes.get(r.get("agent_id"), r.get("hindsight"))} if "agent_id" in r else r
            for r in raw if "hindsight_for" not in r]


def write_hindsight_config(path: Path, repo: Path, api_url: str, opt_in: list[str] | None = None):
    path.write_text(json.dumps({
        "apiUrl": api_url, "optInOnly": True,
        "optInPaths": [str(repo)] if opt_in is None else opt_in,
        "mapPathToBank": {str(repo): "bank-x"}}), encoding="utf-8")


class _Recorder(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802  (http.server API)
        length = int(self.headers.get("Content-Length", "0"))
        self.server.received.append((self.path, json.loads(self.rfile.read(length))))
        self.server.auth.append(self.headers.get("Authorization"))
        self.send_response(self.server.status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


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


def closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def fire(repo, tmp_path, monkeypatch, capsys):
    """fire(cwd=None): run the SubagentStop hook for one run, return its stderr."""
    def _fire(cwd=None):
        payload = event(cwd or repo, make_transcript(tmp_path), agent_id="a1b2c3", agent_type="engineer")
        return run_hook(start_hook, payload, monkeypatch, capsys)[2]
    return _fire


@pytest.fixture
def configure(repo, no_real_hindsight):
    """configure(api_url, opt_in=None): write the Hindsight config for `repo`."""
    def _configure(api_url, opt_in=None):
        write_hindsight_config(no_real_hindsight, repo, api_url, opt_in)
    return _configure


def server_url(server) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"


@pytest.fixture
def schedule(repo, tmp_path, monkeypatch, capsys):
    """schedule(agent_id, session): run the SubagentStop hook for one engineer run."""
    def _schedule(agent_id="a1b2c3", session=SESSION):
        transcript = make_transcript(tmp_path, agent_id=agent_id)
        run_hook(start_hook, event(repo, transcript, agent_id=agent_id, agent_type="engineer",
                                   session_id=session), monkeypatch, capsys)
    return _schedule


def stop_event(repo: Path, **extra) -> dict:
    return {"session_id": SESSION, "cwd": str(repo), "hook_event_name": "Stop", **extra}

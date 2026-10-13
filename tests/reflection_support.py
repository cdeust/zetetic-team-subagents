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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
ledger = importlib.import_module("reflection_ledger")  # tools/ is on sys.path from the line above
gates_jsonl = importlib.import_module("gates_jsonl")
SESSION = "sess-A"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


start_hook = _load("subagent_stop_reflection", "hooks/subagent-stop-reflection.py")
stop_hook = _load("stop_reflection_gate", "hooks/stop-reflection-gate.py")




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


def run_hook(module, payload: dict, monkeypatch, capsys) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = module.main()
    out = capsys.readouterr()
    return code, out.out, out.err


def raw_rows(repo: Path) -> list[dict]:
    return gates_jsonl.read_rows(ledger.ledger_path(str(repo)))


def rows(repo: Path) -> list[dict]:
    """The ledger as a reader sees it: outcome lines merged into their pending row."""
    raw = raw_rows(repo)
    outcomes = {r["hindsight_for"]: r["hindsight"] for r in raw if "hindsight_for" in r}
    excerpts = {r["excerpt_for"]: r["excerpt"] for r in raw if "excerpt_for" in r}
    return [{**r, "hindsight": outcomes.get(r.get("agent_id"), r.get("hindsight")),
             "excerpt": excerpts.get(r.get("agent_id"), r.get("excerpt"))} if "agent_id" in r else r
            for r in raw if "hindsight_for" not in r and "excerpt_for" not in r]


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


def closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def server_url(server) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"


def stop_event(repo: Path, **extra) -> dict:
    return {"session_id": SESSION, "cwd": str(repo), "hook_event_name": "Stop", **extra}

"""Shared helpers for the per-task cycle ledger tests.

Transcripts are written in the shape Claude Code records (checked on the
owner's transcripts, see tools/cycle_evidence.py): an assistant line with one
tool_use block, then a user line with its tool_result. The hooks are loaded by
path and run in-process against a real throwaway git repository.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
SESSION = "sess-C"
RECALL = "mcp__plugin_hypermnesia-mcp_cortex__recall"
REMEMBER = "mcp__plugin_hypermnesia-mcp_cortex__remember"
CHECK = "python3 -m pytest -q tests/test_x.py"


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


open_hook = load("post_edit_cycle_open", "hooks/post-edit-cycle-open.py")
gate_hook = load("stop_cycle_gate", "hooks/stop-cycle-gate.py")


def git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    return path


def call(name: str, is_error: bool | None = False, **tool_input) -> dict:
    return {"name": name, "input": tool_input, "is_error": is_error}


def full_cycle(repo: Path, check: str = CHECK) -> list:
    """Every transcript-provable stage, in engineering-loop order."""
    return [call(RECALL, query="parser"), call("Read", file_path=str(repo / "a.py")),
            call("Edit", file_path=str(repo / "a.py")), call("Bash", command=check),
            call("Agent", subagent_type="general-purpose", description="review the diff",
                 prompt="GENIUS: popper\nreview the diff"),
            call(REMEMBER, content="lesson")]


def write_transcript(path: Path, calls: list, append: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    start = 0
    if append and path.exists():
        start = sum(1 for _ in path.open(encoding="utf-8"))
    for i, c in enumerate(calls, start):
        use = {"type": "tool_use", "id": f"tu{i}", "name": c["name"], "input": c["input"]}
        lines.append(json.dumps({"type": "assistant", "message": {"content": [use]}}))
        if c["is_error"] is not None:
            result = {"type": "tool_result", "tool_use_id": f"tu{i}", "is_error": c["is_error"]}
            lines.append(json.dumps({"type": "user", "message": {"content": [result]}}))
    with path.open("a" if append else "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def edit_event(repo: Path, file_path: str, transcript: Path, **extra) -> dict:
    return {"session_id": SESSION, "cwd": str(repo), "hook_event_name": "PostToolUse",
            "tool_name": "Edit", "tool_input": {"file_path": file_path},
            "transcript_path": str(transcript), **extra}


def stop_event(repo: Path, transcript: Path, **extra) -> dict:
    return {"session_id": SESSION, "cwd": str(repo), "hook_event_name": "Stop",
            "transcript_path": str(transcript), **extra}


def run_hook(module, payload: dict, monkeypatch, capsys) -> tuple:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = module.main()
    out = capsys.readouterr()
    return code, out.out, out.err

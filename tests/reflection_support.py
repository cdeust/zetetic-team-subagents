"""Shared fixtures and helpers for the subagent-reflection tests (#153).

The hook scripts are loaded by path (hyphenated names, hooks/ is not a package)
and run in-process against a real throwaway git repository. Nothing here
sleeps or retries.
"""
from __future__ import annotations

import importlib.util
import io
import json
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
    """The ledger as a reader sees it: excerpt lines merged into their pending row."""
    raw = raw_rows(repo)
    excerpts = {r["excerpt_for"]: r["excerpt"] for r in raw if "excerpt_for" in r}
    return [{**r, "excerpt": excerpts.get(r.get("agent_id"), r.get("excerpt"))} if "agent_id" in r else r
            for r in raw if "excerpt_for" not in r]


def stop_event(repo: Path, **extra) -> dict:
    return {"session_id": SESSION, "cwd": str(repo), "hook_event_name": "Stop", **extra}

"""The context-guard checkpoint is written by the hook, from the transcript.

Owner decision 2026-10-21: no agent writes the checkpoint. These tests feed a
sample transcript JSONL to the real hook (a subprocess, isolated HOME) and to
tools/checkpoint_summary.py, and pin three things: every measured field lands in
the checkpoint file, the hook never emits a "spawn ... subagent" instruction,
and the turn is not blocked.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "stop-context-guard.py"
sys.path.insert(0, str(REPO / "tools"))
import checkpoint_summary as cs  # noqa: E402


def _line(role, *blocks, usage=None):
    msg = {"role": role, "content": list(blocks)}
    if usage:
        msg["usage"] = usage
        msg["model"] = "claude-opus-5"
    return json.dumps({"type": role, "message": msg})


# 190k input tokens is above every model's warn band (source: hooks/stop-context-guard.py table)
def sample_transcript(path: Path) -> str:
    text = lambda s: {"type": "text", "text": s}  # noqa: E731
    use = lambda name, **inp: {"type": "tool_use", "name": name, "id": "t1", "input": inp}  # noqa: E731
    rows = [
        _line("user", text("add a retry to fetch_all in client.py")),
        _line("assistant", text("Reading the client."), use("Read", file_path="/r/client.py")),
        _line("user", {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}),
        _line("user", text("<system-reminder>harness noise</system-reminder>")),
        _line("assistant", use("Edit", file_path="/r/client.py", old_string="a", new_string="b")),
        _line("assistant", use("Write", file_path="/r/test_client.py", content="x")),
        _line("assistant", use("Bash", command="python3 -m pytest -q tests/test_client.py")),
        _line("user", {"type": "tool_result", "tool_use_id": "t2", "is_error": True,
                       "content": "FAILED tests/test_client.py::test_retry - AssertionError"}),
        _line("user", text("also cap the backoff at 5 seconds")),
        _line("assistant", use("TodoWrite", todos=[
            {"content": "cap the backoff", "status": "in_progress"},
            {"content": "write the changelog line", "status": "pending"},
            {"content": "add retry", "status": "completed"}])),
        _line("assistant", text("Retry added; backoff cap still to do."),
              usage={"input_tokens": 190_000}),
    ]
    path.write_text("\n".join(rows) + "\n")
    return str(path)


def test_summarize_measures_every_field(tmp_path):
    facts = cs.summarize(sample_transcript(tmp_path / "t.jsonl"))
    assert facts["user_requests"] == ["add a retry to fetch_all in client.py",
                                      "also cap the backoff at 5 seconds"]
    assert facts["files_touched"] == ["/r/client.py", "/r/test_client.py"]
    assert facts["commands"] == ["python3 -m pytest -q tests/test_client.py"]
    assert any("AssertionError" in e for e in facts["errors"])
    assert facts["last_assistant"] == "Retry added; backoff cap still to do."
    assert facts["open_todos"] == ["[in_progress] cap the backoff",
                                   "[pending] write the changelog line"]


def test_summarize_survives_a_missing_or_garbled_transcript(tmp_path):
    empty = {"user_requests": [], "files_touched": [], "commands": [], "errors": [],
             "last_assistant": "", "open_todos": []}
    assert cs.summarize(str(tmp_path / "absent.jsonl")) == empty
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n[1, 2]\n\n{broken")
    assert cs.summarize(str(bad)) == empty
    assert cs.summarize(None) == empty


def test_summarize_reads_only_the_tail_of_a_huge_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "MAX_BYTES", 600)
    path = tmp_path / "big.jsonl"
    old = _line("user", {"type": "text", "text": "ancient request " + "x" * 800})
    new = _line("user", {"type": "text", "text": "recent request"})
    path.write_text(old + "\n" + new + "\n")
    assert cs.summarize(str(path))["user_requests"] == ["recent request"]


def _run_hook(tmp_path, transcript):
    # The hook keeps its fired-level state in /tmp keyed by session id, so each
    # run needs a session id nobody has used (and the state file is removed).
    session = "cp-" + uuid.uuid4().hex
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home))
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    payload = {"session_id": session, "transcript_path": transcript, "cwd": str(tmp_path)}
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          text=True, capture_output=True, env=env, timeout=30)
    Path("/tmp", f"zetetic-ctxguard-{session}.json").unlink(missing_ok=True)
    return proc, home / ".claude" / "memories" / "checkpoints" / f"{session}.md"


def test_hook_writes_the_checkpoint_with_the_measured_fields(tmp_path):
    proc, checkpoint = _run_hook(tmp_path, sample_transcript(tmp_path / "t.jsonl"))
    assert proc.returncode == 0, proc.stderr
    body = checkpoint.read_text()
    for needle in ("add a retry to fetch_all in client.py",
                   "also cap the backoff at 5 seconds",
                   "/r/client.py", "/r/test_client.py",
                   "python3 -m pytest -q tests/test_client.py",
                   "AssertionError",
                   "Retry added; backoff cap still to do.",
                   "[in_progress] cap the backoff",
                   "[pending] write the changelog line"):
        assert needle in body, needle
    assert "harness noise" not in body
    assert "<to be filled" not in body


def test_hook_never_asks_the_model_to_spawn_a_subagent_and_never_blocks(tmp_path):
    proc, checkpoint = _run_hook(tmp_path, sample_transcript(tmp_path / "t.jsonl"))
    out = json.loads(proc.stdout)
    assert "decision" not in out and "reason" not in out
    message = out["systemMessage"].lower()
    assert str(checkpoint).lower() in message
    for forbidden in ("spawn", "subagent", "memory-writer", "agent tool"):
        assert forbidden not in message, forbidden
    assert "spawn" not in checkpoint.read_text().lower()


def test_hook_source_has_no_subagent_instruction():
    source = HOOK.read_text().lower()
    assert "memory-writer" not in source
    assert "subagent_type" not in source

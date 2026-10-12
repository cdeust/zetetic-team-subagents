#!/usr/bin/env python3
"""reflection_subagent.py -- identify the subagent run a SubagentStop event describes.

The SubagentStop payload (verified against session-optimizer's
subagent-tracker.py contract and the real files under
``~/.claude/projects/<proj>/<session>/subagents/``) carries session_id,
transcript_path, cwd, hook_event_name and, on recent builds, agent_id,
agent_type and agent_transcript_path. The subagent transcript is
``agent-<id>.jsonl``; beside it sits ``agent-<id>.meta.json``:
``{"agentType": ..., "description": ..., "toolUseId": ..., "spawnDepth": 1}``.

The payload shape differs between builds, so each field is resolved through an
ordered list of sources and every fallback that fired is recorded in ``notes``
(no silent substitution): the ledger row and the hook's stderr both carry them.

Pre: ``payload`` is the decoded event object.
Post: ``resolve_run`` returns a Run with a non-empty agent_id, or raises
RunUnidentified when neither an agent id nor a transcript path can be found.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List

# The handback message sits at the very end of the transcript; 1 MiB covers a
# long report plus its tool_use rows. source: hooks/stop-redaction-gate.py
# TAIL_BYTES rationale (same transcript format, same read).
TAIL_BYTES = 1024 * 1024
# A ledger row is one atomic append and a Hindsight document is one retain:
# a handback longer than this is cut, and the cut is marked in the text.
# source: operational default, a typical handback report is 2-6 KB.
MAX_EXCERPT_CHARS = 4000
UNKNOWN_TYPE = "unknown"
_AGENT_FILE = re.compile(r"^agent-(?P<id>[A-Za-z0-9_-]+)\.jsonl$")


class RunUnidentified(Exception):
    """The event names neither an agent id nor a transcript: nothing to reflect on."""


@dataclass
class Run:
    agent_id: str
    agent_type: str
    description: str
    transcript_path: str
    session_id: str
    excerpt: str
    notes: List[str] = field(default_factory=list)

    def as_row(self) -> Dict:
        return {"agent_id": self.agent_id, "agent_type": self.agent_type,
                "description": self.description, "transcript_path": self.transcript_path,
                "session_id": self.session_id, "excerpt": self.excerpt,
                "notes": list(self.notes)}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _agent_id_of(path: str) -> str:
    match = _AGENT_FILE.match(os.path.basename(path))
    return match.group("id") if match else ""


def _transcript_path(payload: Dict, agent_id: str, notes: List[str]) -> str:
    """Subagent transcript: agent_transcript_path, else transcript_path when it
    is itself an agent-<id>.jsonl, else the sibling subagents/ file derived
    from the parent transcript, else the bare transcript_path (flagged)."""
    explicit = _text(payload.get("agent_transcript_path"))
    if explicit:
        return explicit
    parent = _text(payload.get("transcript_path"))
    if parent and _agent_id_of(parent):
        return parent
    if parent and agent_id:
        stem = parent[:-len(".jsonl")] if parent.endswith(".jsonl") else parent
        derived = os.path.join(stem, "subagents", f"agent-{agent_id}.jsonl")
        if os.path.isfile(derived):
            notes.append("transcript derived from the parent transcript path and agent_id")
            return derived
    if parent:
        notes.append("subagent transcript not identified: transcript_path is not an "
                     "agent-<id>.jsonl, the parent transcript is recorded instead")
    return parent


def _read_meta(transcript: str, notes: List[str]) -> Dict:
    if not transcript.endswith(".jsonl"):
        notes.append("no transcript path, so no meta.json could be read")
        return {}
    meta_path = transcript[:-len(".jsonl")] + ".meta.json"
    try:
        with open(meta_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        notes.append(f"no meta.json beside the transcript ({meta_path})")
        return {}
    except (OSError, ValueError) as exc:
        notes.append(f"meta.json unreadable ({meta_path}): {exc.__class__.__name__}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def _tail_rows(path: str) -> List[Dict]:
    try:
        size = os.stat(path).st_size
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
            data = fh.read()
    except OSError:
        return []
    rows: List[Dict] = []
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # the first line of a seek()ed tail is usually a fragment
        if isinstance(row, dict) and row.get("type") == "assistant":
            rows.append(row)
    return rows


def _blocks(row: Dict) -> List[Dict]:
    content = (row.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _handback_message(row: Dict) -> str:
    """The message of this row's SubagentHandback tool_use ('' when it has none)."""
    for block in _blocks(row):
        if block.get("type") == "tool_use" and block.get("name") == "SubagentHandback":
            return _text((block.get("input") or {}).get("message"))
    return ""


def final_message(transcript: str) -> str:
    """The subagent's last report: the message of its last SubagentHandback
    tool_use, else the text blocks of its last assistant message ('' if none)."""
    rows = _tail_rows(transcript)
    for row in reversed(rows):
        message = _handback_message(row)
        if message:
            return message
    if not rows:
        return ""
    last_id = (rows[-1].get("message") or {}).get("id")
    texts = [b["text"] for row in rows if (row.get("message") or {}).get("id") == last_id
             for b in _blocks(row) if b.get("type") == "text" and b.get("text")]
    return "\n".join(texts).strip()


def _excerpt(payload: Dict, transcript: str, notes: List[str]) -> str:
    text = final_message(transcript)
    if not text:
        text = _text(payload.get("last_assistant_message"))
        if text:
            notes.append("final message taken from the payload's last_assistant_message")
    if not text:
        notes.append("no final message found in the transcript or the payload")
        return ""
    if len(text) > MAX_EXCERPT_CHARS:
        return text[:MAX_EXCERPT_CHARS] + f"\n[... cut at {MAX_EXCERPT_CHARS} characters]"
    return text


def resolve_run(payload: Dict) -> Run:
    notes: List[str] = []
    agent_id = _text(payload.get("agent_id"))
    transcript = _transcript_path(payload, agent_id, notes)
    if not agent_id:
        agent_id = _agent_id_of(transcript)
        if agent_id:
            notes.append("agent_id taken from the transcript file name")
    if not agent_id:
        raise RunUnidentified(
            "the event carries no agent_id and no agent-<id>.jsonl transcript path; "
            "payload keys: " + ", ".join(sorted(payload)))
    meta = _read_meta(transcript, notes)
    agent_type = _text(payload.get("agent_type"))
    if not agent_type:
        agent_type = _text(meta.get("agentType"))
        if agent_type:
            notes.append("agent_type taken from meta.json")
    if not agent_type:
        agent_type = UNKNOWN_TYPE
        notes.append("agent_type absent from the payload and from meta.json")
    description = _text(meta.get("description")) or _text(payload.get("description"))
    return Run(agent_id=agent_id, agent_type=agent_type, description=description,
               transcript_path=transcript, session_id=_text(payload.get("session_id")),
               excerpt=_excerpt(payload, transcript, notes), notes=notes)

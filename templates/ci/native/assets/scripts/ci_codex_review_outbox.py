"""Exact native security command with separate authenticated outbox control.

Source: cortex-viz PR213 comments6492065732/6492093354, native summary6489153112;
zetetic PR219 exact-only comment6491562935 and security receipt6491639753.
REST comment creation has no idempotency key. Persist posting before sending;
uncertain outcomes never resend. Hosted workers retain per-PR serialization.
"""

import json
import re
import subprocess

import ci_codex_review_request as requests
from ci_codex_reviews import EvidenceError

EXACT = "@codex security review"
MARKER = "codex-security-outbox:v1"
HEADER = "Codex security review control"
STATES = ("prepared", "posting", "submitted", "uncertain", "aborted")


def _body(target, state, command_id=None):
    data = dict(target, state=state, command_id=command_id)
    return HEADER + "\n\n<!-- " + MARKER + " " + json.dumps(data, sort_keys=True) + " -->"


def _record(row, target):
    body = row.get("body", "")
    if not body.startswith(HEADER + "\n"):
        return None
    if not requests._trusted_author(row.get("user"), target["repository"]):
        return None
    pattern = re.escape(HEADER + "\n\n<!-- " + MARKER + " ") + r"(.*?) -->"
    match = re.fullmatch(pattern, body, re.DOTALL)
    if match is None:
        raise EvidenceError("outbox_protocol")
    data = requests._json(match[1])
    if not isinstance(data, dict) or any(data.get(key) != value for key, value in target.items()):
        return None
    if not requests._trusted_actor(row, target["repository"]):
        raise EvidenceError("outbox_editor")
    if row["lastEditedAt"] is not None:
        requests._order(dict(id=row["id"], updated_at=row["lastEditedAt"]))
        editor, user = row["editor"], row["user"]
        if (editor.get("__typename") != user["type"]
                or editor.get("login", "").removesuffix("[bot]") != user["login"].removesuffix("[bot]")):
            raise EvidenceError("outbox_editor")
    requests._order(row)
    if (set(data) != set(target) | {"state", "command_id"} or data["state"] not in STATES
            or type(data["number"]) is not int):
        raise EvidenceError("outbox_protocol")
    command = data["command_id"]
    if data["state"] == "submitted":
        requests.source.positive(command)
    elif command is not None:
        raise EvidenceError("outbox_protocol")
    return row, data


def _records(rows, target):
    return [record for row in rows if (record := _record(row, target)) is not None]


def _linked(rows, record, command_id):
    control, _ = record
    matches = [row for row in rows if row["id"] == command_id]
    if len(matches) != 1:
        return False
    command = matches[0]
    return (command.get("body") == EXACT and command.get("editor") is None
            and command.get("lastEditedAt") is None
            and command.get("user") == control.get("user"))


def _existing(snapshot, target):
    active = [record for record in _records(snapshot[1], target)
              if record[1]["state"] not in ("prepared", "aborted")]
    if not active:
        return None
    if len(active) != 1:
        raise EvidenceError("outbox_ambiguous")
    record = active[0]
    row, data = record
    if data["state"] != "submitted":
        reason = "security_command_uncertain"
    elif not _linked(snapshot[1], record, data["command_id"]):
        reason = "security_command_unverified"
    else:
        reason = requests._inflight_reason(snapshot[0], row, "security_review")
    return dict(action="none", reason=reason, control_id=row["id"])


def _patch(target, control_id, state, command_id=None):
    repo = target["repository"]
    try:
        result = subprocess.run(
            ["gh", "api", "--method", "PATCH", f"repos/{repo}/issues/comments/{control_id}", "--input", "-"],
            input=json.dumps(dict(body=_body(target, state, command_id))),
            text=True, capture_output=True, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError("outbox_write") from exc
    value = requests._json(result.stdout)
    if not isinstance(value, dict) or requests.source.positive(value.get("id")) != control_id:
        raise EvidenceError("outbox_protocol")


def _snapshot(target, job_reader):
    snapshot = requests._snapshot(target["repository"], target["number"], target["sha"], job_reader)
    if snapshot is None or requests.request_kind(snapshot[0], snapshot[3]) != "security_review":
        return None
    return snapshot


def _ready(target, job_reader, control_id, state):
    snapshot = _snapshot(target, job_reader)
    if snapshot is None:
        return None
    records = _records(snapshot[1], target)
    selected = [record for record in records if record[0]["id"] == control_id]
    if len(selected) != 1 or selected[0][1]["state"] != state:
        raise EvidenceError("outbox_control")
    if any(row["id"] != control_id and data["state"] not in ("prepared", "aborted")
           for row, data in records):
        raise EvidenceError("outbox_ambiguous")
    return snapshot, selected[0]


def _sent(target, job_reader, control_id, command_id):
    snapshot = requests._snapshot(target["repository"], target["number"], target["sha"], job_reader)
    if snapshot is None:
        return False
    selected = [record for record in _records(snapshot[1], target) if record[0]["id"] == control_id]
    return len(selected) == 1 and _linked(snapshot[1], selected[0], command_id)


def _uncertain(target, control_id):
    try:
        _patch(target, control_id, "uncertain")
    except EvidenceError:
        pass  # The durable posting state already forbids another command.


def _submit(target, job_reader, control_id):
    try:
        command_id = requests._post(target["repository"], target["number"], EXACT)
    except EvidenceError as exc:
        _uncertain(target, control_id)
        raise EvidenceError("security_command_uncertain") from exc
    result = dict(action="request", kind="security_review", comment_id=command_id, control_id=control_id)
    if not _sent(target, job_reader, control_id, command_id):
        _uncertain(target, control_id)
        return dict(result, control_state="unverified")
    try:
        _patch(target, control_id, "submitted", command_id)
    except EvidenceError:
        result["control_state"] = "unrecorded"
    return result


def dispatch(target, snapshot, job_reader, dry_run=False):
    existing = _existing(snapshot, target)
    if existing is not None:
        return existing
    if dry_run:
        return dict(action="request", kind="security_review", dry_run=True)
    snapshot = _snapshot(target, job_reader)
    if snapshot is None:
        return dict(action="none")
    existing = _existing(snapshot, target)
    if existing is not None:
        return existing
    control_id = requests._post(target["repository"], target["number"], _body(target, "prepared"))
    if _ready(target, job_reader, control_id, "prepared") is None:
        _patch(target, control_id, "aborted")
        return dict(action="none", reason="head_or_proof_changed", control_id=control_id)
    _patch(target, control_id, "posting")
    if _ready(target, job_reader, control_id, "posting") is None:
        _patch(target, control_id, "aborted")
        return dict(action="none", reason="head_or_proof_changed", control_id=control_id)
    return _submit(target, job_reader, control_id)

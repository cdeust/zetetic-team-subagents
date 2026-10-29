"""Synthetic gh comment transport fixtures; no live requests are performed."""

import json
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from codex_resume_fixtures import SHA, OTHER, comment, state
from test_ci_codex_review_event_fixtures import REPO, Server, event, load


def unknown(server):
    data = state()
    data["security_review"].update(has_any_findings=None, has_unresolved_findings=None)
    server.data["comments"] = [comment(data, comment_id=9)]
    return server


EXACT = "@codex security review"
MARKER = "codex-security-outbox:v1"
OWNER = dict(login="cdeust", type="User", node_id="MDQ6VXNlcjMxNjc3Njc=")


def control_body(state="prepared", command_id=None):
    data = dict(repository=REPO, number=797, sha=SHA, kind="security_review",
                state=state, command_id=command_id)
    return "Codex security review control\n\n<!-- " + MARKER + " " + json.dumps(data, sort_keys=True) + " -->"


class OutboxHarness:
    def __init__(self, server=None):
        self.server = unknown(Server()) if server is None else server
        self.next_id = 91
        self.writes = []
        self.failure = None
        self.move_after_posting = False
        self.complete_after_posting = False

    def row(self, body, identity):
        row = comment(comment_id=identity, updated="2026-10-29T09:00:00Z")
        row.update(body=body, user=dict(OWNER))
        return row

    def write(self, command, **options):
        method, endpoint = command[3:5]
        if "/actions/jobs/" in endpoint:
            self.writes.append((method, "rerun", ""))
            return SimpleNamespace(stdout="")
        body = json.loads(options["input"])["body"]
        phase = "command" if body == EXACT else "control"
        if method == "PATCH":
            phase = json.loads(body.split(MARKER + " ", 1)[1].split(" -->", 1)[0])["state"]
        self.writes.append((method, phase, body))
        if self.failure == phase + "_before":
            raise subprocess.CalledProcessError(1, command)
        if method == "POST":
            identity = self.next_id
            self.next_id += 1
            self.server.data["comments"].append(self.row(body, identity))
        else:
            identity = int(endpoint.rsplit("/", 1)[1])
            row = next(row for row in self.server.data["comments"] if row["id"] == identity)
            row.update(body=body, editor=dict(login="cdeust", __typename="User", id=OWNER["node_id"]),
                       lastEditedAt="2026-10-29T09:00:01Z", updated_at="2026-10-29T09:00:01Z")
            if phase == "posting" and self.move_after_posting:
                self.server.data["pull"]["head"]["sha"] = OTHER
            if phase == "posting" and self.complete_after_posting:
                self.server.data["comments"][0] = comment(comment_id=9)
        if self.failure == phase + "_after":
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout=json.dumps(dict(id=identity)))

    def invoke(self):
        target = load()
        with (
            patch.dict(os.environ, {"EXPECTED_PR": "797"}),
            patch.object(target.source, "_api", side_effect=self.server),
            patch.object(target.subprocess, "run", side_effect=self.write),
        ):
            return target.coordinate("issue_comment", event(), REPO)

    def commands(self):
        return [row for row in self.server.data["comments"] if row["body"] == EXACT]

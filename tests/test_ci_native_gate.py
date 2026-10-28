"""Native merge gate: a red merge names the condition that made it red.

Source: Pipeline merge jobs of cdeust/Cortex run 40583904933 (a deliberate
"do not merge" title) and run 40548981339 (an already merged PR), both reported
as "closed, draft, held, or no longer at the tested head". Attribution of every
failed gate of 2026-10-27/28: docs/verification/native-gate-patience-20261029.md.
"""

import json
import os
from pathlib import Path
import stat
import subprocess
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "templates/ci/native"
SHA = "a" * 40
MOVED = "b" * 40


def eligibility_script():
    jobs = yaml.safe_load((NATIVE / "pipeline.yml").read_text())["jobs"]
    return next(
        item["run"]
        for item in jobs["merge"]["steps"]
        if item["name"] == "Verify live PR eligibility"
    )


def run_eligibility(tmp_path, live):
    """Run the merge job's eligibility step against a stubbed `gh pr view`."""
    stub = tmp_path / "bin/gh"
    stub.parent.mkdir(parents=True)
    stub.write_text('#!/bin/sh\ncat "$LIVE_PR"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    payload = tmp_path / "live.json"
    payload.write_text(json.dumps(live))
    env = {
        **os.environ,
        "PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}",
        "LIVE_PR": str(payload),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "PR": "7",
        "HEAD_SHA": SHA,
        "REVIEW_STATE": "success",
    }
    result = subprocess.run(
        ["bash", "-c", eligibility_script()], capture_output=True, text=True, env=env
    )
    return result.returncode, result.stdout


def pull(**changes):
    live = {"state": "OPEN", "isDraft": False, "headRefOid": SHA, "title": "fix: x"}
    return {**live, "labels": [], **changes}


@pytest.mark.parametrize(
    "changes, cause",
    [
        ({"state": "MERGED"}, "is not open (MERGED)"),
        ({"state": "CLOSED"}, "is not open (CLOSED)"),
        ({"isDraft": True}, "is a draft"),
        ({"headRefOid": MOVED}, f"head moved: tested {SHA}, live {MOVED}"),
        ({"title": "do not merge: probe"}, "is held by title"),
        ({"labels": [{"name": "Hold"}]}, "is held by label"),
    ],
)
def test_red_merge_names_the_condition_that_failed(tmp_path, changes, cause):
    assert run_eligibility(tmp_path / "ok", pull())[0] == 0  # control: same harness
    code, out = run_eligibility(tmp_path / "red", pull(**changes))
    assert code == 1
    assert f"::error::PR {cause}." in out


# Characterization of the native `resolve` job (pipeline-post-merge.yml). Green on
# origin/main by construction: they pin an invariant this change must not break.
# tests/test_ci_post_merge.py covers tools/ci_post_merge.py, which has no
# `merge pending review` branch, so the inline native resolver had no test.
RUNNERS = ("ubuntu-latest", "macos-latest", "windows-latest")
MATRIX = [f"{kind} ({runner})" for kind in ("environment", "install") for runner in RUNNERS]


def resolver(tmp_path):
    """The native resolve job's inline source, loaded as a module."""
    jobs = yaml.safe_load((NATIVE / "pipeline.yml").read_text())["jobs"]
    command = jobs["resolve"]["steps"][0]["run"]
    source = command.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    module = ModuleType("native_resolve")
    module.__file__ = str(tmp_path / "native_resolve.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def source_run(head, repository):
    return {
        "id": 9, "event": "pull_request", "status": "completed",
        "conclusion": "success", "head_branch": "topic", "run_attempt": 1,
        "head_sha": head, "path": ".github/workflows/pipeline.yml",
        "name": "Pipeline", "head_repository": {"full_name": repository},
        "pull_requests": [{"number": 7}], "actor": {"login": "owner"},
    }


def open_pull(head, repository):
    repo = {"full_name": repository}
    return {
        "number": 7, "state": "open", "draft": False, "title": "fix", "labels": [],
        "head": {"sha": head, "repo": repo}, "base": {"ref": "main", "repo": repo},
    }


def green_jobs(head, merge_job):
    names = ["contract", "unit", "regression", "e2e", "review", merge_job, *MATRIX]
    return [
        {"id": 100 + n, "name": name, "run_attempt": 1, "run_id": 9,
         "head_sha": head, "status": "completed", "conclusion": "success"}
        for n, name in enumerate(names)
    ]


class FakeGitHub:
    def __init__(self, tested, live, merge_job):
        self.calls = []
        self.run = source_run(tested, "o/r")
        self.pr = open_pull(live, "o/r")
        self.jobs = green_jobs(tested, merge_job)

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        if path.endswith("/actions/runs/9"):
            return self.run
        if path.endswith("/pulls/7"):
            return self.pr
        raise AssertionError(f"unexpected request {method} {path}")

    def records(self, path, key=None):
        self.calls.append(("GET", path))
        return iter(self.jobs)

    def merges(self):
        return [call for call in self.calls if call[0] == "PUT"]


def resolve(module, api):
    event = {"repository": {"full_name": "o/r"}, "workflow_run": dict(api.run)}
    return module.resolve(event, "o/r", api)


def test_superseded_run_does_not_trigger_merge(tmp_path):
    # The PR head moved after this run tested SHA: the new head's run decides.
    module = resolver(tmp_path)
    api = FakeGitHub(SHA, MOVED, "merge")
    with pytest.raises(module.PostMergeError, match="head advanced"):
        resolve(module, api)
    assert api.merges() == []


def test_pending_run_does_not_trigger_merge(tmp_path):
    module = resolver(tmp_path)
    api = FakeGitHub(SHA, SHA, "merge pending review")
    assert resolve(module, api)["run_tests"] == "false"
    assert api.merges() == []

"""Native post-merge resolver characterization.

The merge job is the aggregate of the test jobs of the run (owner rule 2026-10-29): it
reads no live PR state, so the eligibility-step tests that lived here are gone.
"""

import json
import re
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from test_ci_pr_safety import GH_STUB, execute
from test_ci_template import heredoc

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "templates/ci/native"
SHA = "a" * 40
MOVED = "b" * 40
MERGED = "c" * 40
@pytest.fixture(scope="module")
def jobs():
    return yaml.safe_load((NATIVE / "pipeline.yml").read_text())["jobs"]


# Characterization of the native `resolve` job (pipeline-post-merge.yml). Green on
# origin/main by construction: they pin an invariant this change must not break.
# tests/test_ci_post_merge.py covers tools/ci_post_merge.py; the inline native
# resolver is exercised here. Neither requires the review job (owner rule 2026-10-29).
RUNNERS = ("ubuntu-latest", "macos-latest", "windows-latest")
MATRIX = [f"{kind} ({runner})" for kind in ("environment", "install") for runner in RUNNERS]


def resolver(jobs, tmp_path):
    """The native resolve job's inline source, loaded as a module."""
    step = next(s for s in jobs["resolve"]["steps"] if s.get("name") == "Resolve protected merge")
    command = step["run"]
    source = heredoc(command, "python3")
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
    names = ["contract", "unit", "regression", "e2e", merge_job, *MATRIX]
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
        if method == "PUT" and path.endswith("/pulls/7/merge"):
            self.pr = {**self.pr, "merged": True, "merge_commit_sha": MERGED}
            return {"merged": True, "sha": MERGED}
        raise AssertionError(f"unexpected request {method} {path}")

    def records(self, path, key=None):
        self.calls.append(("GET", path))
        return iter(self.jobs)

    def merges(self):
        return [call for call in self.calls if call[0] == "PUT"]


def resolve(module, api):
    event = {"repository": {"full_name": "o/r"}, "workflow_run": dict(api.run)}
    return module.resolve(event, "o/r", api)


def test_superseded_run_does_not_trigger_merge(jobs, tmp_path):
    # The PR head moved after this run tested SHA: the new head's run decides.
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, MOVED, "merge")
    with pytest.raises(module.PostMergeError, match="head advanced"):
        resolve(module, api)
    assert api.merges() == []


def review_row(head, **fields):
    return {"id": 900, "name": "review", "run_attempt": 1, "run_id": 9,
            "head_sha": head, "status": "completed", "conclusion": "success", **fields}


def test_green_tests_merge(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    assert resolve(module, api)["run_tests"] == "true"
    assert len(api.merges()) == 1


@pytest.mark.parametrize("fields", [
    {"conclusion": "failure"}, {"conclusion": "cancelled"}, {"conclusion": "skipped"},
    {"status": "in_progress", "conclusion": None},
])
def test_the_review_job_never_blocks_the_native_merge(jobs, tmp_path, fields):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    api.jobs.append(review_row(SHA, **fields))
    assert resolve(module, api)["run_tests"] == "true"
    assert len(api.merges()) == 1


def test_a_native_run_without_a_review_job_merges(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    assert "review" not in [job["name"] for job in api.jobs]
    assert resolve(module, api)["run_tests"] == "true"


@pytest.mark.parametrize("name", ["contract", "unit", "regression", "e2e", "merge", *MATRIX])
def test_a_red_test_job_still_blocks_with_a_green_review(jobs, tmp_path, name):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    api.jobs.append(review_row(SHA))
    next(job for job in api.jobs if job["name"] == name)["conclusion"] = "failure"
    with pytest.raises(module.PostMergeError, match=re.escape(f"completed {name}")):
        resolve(module, api)
    assert api.merges() == []


def test_no_pending_review_machinery_remains(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge pending review")
    with pytest.raises(module.PostMergeError, match="exactly one merge job"):
        resolve(module, api)
    assert api.merges() == []


def rerun_jobs(head, attempts):
    """One job record per (attempt, name); ids stay unique across attempts."""
    rows = []
    for attempt, names in enumerate(attempts, start=1):
        for name in names:
            rows.append({
                "id": 100 * attempt + len(rows), "name": name, "run_attempt": attempt,
                "run_id": 9, "head_sha": head, "status": "completed", "conclusion": "success",
            })
    return rows


def test_newest_attempt_of_a_job_decides(jobs, tmp_path):
    # Attempt 1 failed `unit`; attempt 2 passed it. Only the newest attempt decides.
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    api.run["run_attempt"] = 2
    rows = rerun_jobs(SHA, [
        ["contract", "unit", "regression", "e2e", "merge", *MATRIX],
        ["unit"],
    ])
    rows[1]["conclusion"] = "failure"
    api.jobs = rows
    assert resolve(module, api)["run_tests"] == "true"


def test_a_stale_green_attempt_cannot_outvote_a_newer_red_one(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    api.run["run_attempt"] = 2
    rows = rerun_jobs(SHA, [
        ["contract", "unit", "regression", "e2e", "merge", *MATRIX],
        ["unit"],
    ])
    rows[-1]["conclusion"] = "failure"
    api.jobs = rows
    with pytest.raises(module.PostMergeError, match="completed unit"):
        resolve(module, api)
    assert api.merges() == []


def test_duplicate_job_names_in_one_attempt_are_rejected(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    api.jobs = rerun_jobs(SHA, [["contract", "unit", "regression", "e2e", "merge", "merge", *MATRIX]])
    with pytest.raises(module.PostMergeError, match="duplicate job name in one attempt"):
        resolve(module, api)
    assert api.merges() == []


def test_the_native_review_job_posts_but_cannot_fail_the_pipeline(jobs):
    # A failed job fails the run and the caller only fires on a successful run.
    assert jobs["review"]["continue-on-error"] is True
    assert all("review" not in job.get("needs", []) for job in jobs.values())


def test_the_native_resolver_source_names_no_review_job(jobs, tmp_path):
    step = next(s for s in jobs["resolve"]["steps"] if s.get("name") == "Resolve protected merge")
    source = heredoc(step["run"], "python3")
    assert '"review"' not in source and "merge pending review" not in source
    assert "review_pending" not in source

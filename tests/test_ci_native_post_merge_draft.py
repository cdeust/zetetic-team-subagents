"""The native post-merge resolver declines a draft PR's green Pipeline.

Port of #226 (tools/ci_post_merge.py) to the inline resolver of
templates/ci/native/pipeline.yml. A draft's Pipeline succeeds with review and
merge skipped (`!github.event.pull_request.draft`); the resolver then failed
main with "source merge gate requires completed review" (zetetic #219, runs
40865808090 and 40875336583). In the native profile the skipped merge job keeps
its unevaluated display name: Cortex run 40832536658 lists it as
"needs.review.outputs.state == 'pending' && 'merge pending review' || 'merge'".
"""

import json
import re

import pytest

from test_ci_native_gate import MATRIX, SHA, FakeGitHub, jobs, resolve, resolver  # noqa: F401

UNEVALUATED_MERGE = "needs.review.outputs.state == 'pending' && 'merge pending review' || 'merge'"
TESTS = ["contract", "unit", "regression", "e2e", *MATRIX]
DECLINE = {
    "tested_sha": SHA,
    "run_tests": "false",
    "pr_number": "7",
    "reason": "Draft PR: its Pipeline skipped review and merge; nothing to merge",
}


def draft_run(merge_name=UNEVALUATED_MERGE, draft=True, skipped=("review", "merge")):
    api = FakeGitHub(SHA, SHA, "merge")
    api.pr["draft"] = draft
    for job in api.jobs:
        if job["name"] == "merge" and "merge" in skipped:
            job["name"] = merge_name
            job["conclusion"] = "skipped"
        elif job["name"] in skipped:
            job["conclusion"] = "skipped"
    return api


@pytest.mark.parametrize("merge_name", [UNEVALUATED_MERGE, "merge"])
def test_draft_pipeline_without_merge_request_declines_without_failing(jobs, tmp_path, merge_name):
    module = resolver(jobs, tmp_path)
    api = draft_run(merge_name)
    assert resolve(module, api) == DECLINE
    assert [call for call in api.calls if call[0] != "GET"] == []


def test_skipped_review_and_merge_on_a_ready_pr_still_fails(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = draft_run(draft=False)
    with pytest.raises(module.PostMergeError, match="not a draft"):
        resolve(module, api)
    assert api.merges() == []


@pytest.mark.parametrize("skipped", [("review",), ("merge",)])
def test_draft_with_only_one_gate_job_skipped_still_fails(jobs, tmp_path, skipped):
    module = resolver(jobs, tmp_path)
    api = draft_run(skipped=skipped)
    with pytest.raises(module.PostMergeError, match="merge"):
        resolve(module, api)
    assert api.merges() == []


@pytest.mark.parametrize("name", TESTS)
def test_draft_decline_still_requires_every_test_job(jobs, tmp_path, name):
    module = resolver(jobs, tmp_path)
    api = draft_run(skipped=("review", "merge", name))
    with pytest.raises(module.PostMergeError, match=re.escape(f"completed {name}")):
        resolve(module, api)
    assert api.merges() == []


def test_a_green_run_whose_pr_went_back_to_draft_still_fails(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = FakeGitHub(SHA, SHA, "merge")
    api.pr["draft"] = True
    module._proof.authorize_workflow = lambda *args: None  # Only the draft refusal is under test.
    with pytest.raises(module.PostMergeError, match="PR is closed or draft"):
        resolve(module, api)
    assert api.merges() == []


def test_unevaluated_merge_name_is_accepted_only_when_skipped(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = draft_run(skipped=("review", "merge"))
    for job in api.jobs:
        if job["name"] == UNEVALUATED_MERGE:
            job["conclusion"] = "success"
    with pytest.raises(module.PostMergeError, match="merge"):
        resolve(module, api)
    assert api.merges() == []


def test_cli_draft_decline_exits_zero_without_tests(jobs, tmp_path, monkeypatch):
    module = resolver(jobs, tmp_path)
    api = draft_run()
    module.GitHub = lambda token: api
    event_file = tmp_path / "event.json"
    output = tmp_path / "output"
    event_file.write_text(json.dumps({"repository": {"full_name": "o/r"}, "workflow_run": dict(api.run)}))
    for key, value in {
        "GITHUB_EVENT_NAME": "workflow_run",
        "GITHUB_EVENT_PATH": str(event_file),
        "GITHUB_REPOSITORY": "o/r",
        "GH_TOKEN": "fixture-token",
        "GITHUB_OUTPUT": str(output),
    }.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    assert "run_tests=false\n" in output.read_text()
    assert f"tested_sha={SHA}\n" in output.read_text()
    assert api.merges() == []

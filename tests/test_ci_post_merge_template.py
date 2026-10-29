"""Generated post-merge tests must use the resolver's exact protected merge SHA."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("unit", "regression", "e2e", "environment", "install")


def workflow():
    return yaml.safe_load((ROOT / "templates/ci/pipeline.yml").read_text())


def test_completion_trigger_ignores_main_and_cannot_recurse():
    on = workflow()[True]
    assert "workflow_call" not in on
    assert "workflow_run" not in on
    caller = yaml.safe_load(
        (ROOT / "templates/ci/pipeline-after-merge.yml").read_text()
    )
    assert caller[True]["workflow_run"] == {
        "workflows": ["Pipeline"],
        "types": ["completed"],
        "branches-ignore": ["main"],
    }
    resolve = workflow()["jobs"]["resolve"]
    for guard in (
        "github.event_name == 'workflow_run'",
        "github.event.workflow_run.event == 'pull_request'",
        "github.event.workflow_run.conclusion == 'success'",
    ):
        assert guard in resolve["if"]
    assert not any("uses" in step for step in resolve["steps"])


def test_only_resolver_and_existing_review_tag_jobs_can_write():
    jobs = workflow()["jobs"]
    assert jobs["resolve"]["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "read",
    }
    for name in ("contract", "merge", *CATEGORIES):
        assert "write" not in jobs[name].get("permissions", {}).values()


def test_contract_allows_normal_events_but_requires_successful_resolve_for_completion():
    contract = workflow()["jobs"]["contract"]
    assert contract["needs"] == "resolve"
    for guard in (
        "always()",
        "!cancelled()",
        "github.event_name != 'workflow_run'",
        "needs.resolve.result == 'success'",
        "needs.resolve.outputs.run_tests == 'true'",
    ):
        assert guard in contract["if"]
    assert contract["outputs"]["tested_sha"] == "${{ steps.source.outputs.tested_sha }}"
    checkout = next(step for step in contract["steps"] if "uses" in step)
    assert (
        checkout["with"]["ref"]
        == "${{ github.event_name == 'workflow_run' && needs.resolve.outputs.tested_sha || github.sha }}"
    )


def test_every_checkout_is_the_contract_sha_and_the_release_tags_that_commit():
    jobs = workflow()["jobs"]
    for name in CATEGORIES:
        checkout = next(
            step
            for step in jobs[name]["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == "${{ needs.contract.outputs.tested_sha }}"
    checkout = next(step for step in jobs["tag"]["steps"] if "uses" in step)
    assert checkout["with"]["ref"] == "${{ needs.contract.outputs.tested_sha }}"
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["ssh-key"] == "${{ secrets.RELEASE_TAG_SSH_KEY }}"
    publish = next(step for step in jobs["tag"]["steps"] if step.get("id") == "publish")
    assert publish["env"]["TESTED_SHA"] == "${{ needs.contract.outputs.tested_sha }}"
    assert "$GITHUB_SHA" not in publish["run"]


def test_review_checkout_explicitly_excludes_completion_events_and_forks():
    review = workflow()["jobs"]["review"]
    checkout = next(step for step in review["steps"] if "uses" in step)
    for guard in (
        "github.event_name == 'pull_request'",
        "github.event.pull_request.head.repo.full_name == github.repository",
    ):
        assert guard in review["if"]
        assert guard in checkout["if"]


def test_merge_gate_reads_nothing_but_the_test_jobs():
    job = workflow()["jobs"]["merge"]
    body = "\n".join(step.get("run", "") for step in job["steps"])
    assert "gh " not in body and "headRefOid" not in body
    assert "review" not in job["needs"]


def test_the_review_job_posts_but_cannot_fail_the_pipeline():
    # A failed job fails the run and the caller only fires on a successful run.
    jobs = workflow()["jobs"]
    assert jobs["review"]["continue-on-error"] is True
    assert all("review" not in job.get("needs", []) for job in jobs.values())


def test_completion_and_push_runs_cannot_replace_other_heads_pending_tests():
    group = workflow()["concurrency"]["group"]
    assert "github.event_name" in group
    assert "github.event.workflow_run.id" in group
    assert "github.run_id" in group
    assert (
        workflow()["concurrency"]["cancel-in-progress"]
        == "${{ github.event_name == 'pull_request' }}"
    )


def test_resolver_is_embedded_byte_for_byte_without_consumer_script_dependency():
    step = workflow()["jobs"]["resolve"]["steps"][0]
    lines = step["run"].splitlines(keepends=True)
    assert lines[0] == "python3 - <<'PY'\n"
    assert lines[-1] == "PY\n"
    assert "".join(lines[1:-1]) == (ROOT / "tools/ci_post_merge.py").read_text()


def test_release_failure_cannot_emit_the_old_always_success_summary():
    steps = workflow()["jobs"]["tag"]["steps"]
    failure = next(
        step for step in steps if step["name"] == "Report failed release publication"
    )
    assert failure["if"].startswith("failure()")
    assert "no publication success is claimed" in failure["run"]
    assert not any(step.get("if") == "always()" for step in steps)

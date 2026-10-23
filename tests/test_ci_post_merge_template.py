"""Generated post-merge tests must use the resolver's exact protected merge SHA."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("unit", "regression", "e2e", "environment", "install")


def workflow():
    return yaml.safe_load((ROOT / "templates/ci/pipeline.yml").read_text())


def test_completion_trigger_ignores_main_and_cannot_recurse():
    on = workflow()[True]
    assert on["workflow_run"] == {
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


def test_every_test_and_tag_checkout_uses_contract_sha():
    jobs = workflow()["jobs"]
    for name in (*CATEGORIES, "tag"):
        checkout = next(
            step
            for step in jobs[name]["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == "${{ needs.contract.outputs.tested_sha }}"
    publish = next(step for step in jobs["tag"]["steps"] if step.get("id") == "publish")
    assert publish["env"]["TESTED_SHA"] == "${{ needs.contract.outputs.tested_sha }}"
    assert "$GITHUB_SHA" not in publish["run"]


def test_merge_gate_does_not_arm_an_event_suppressing_async_merge():
    job = workflow()["jobs"]["merge"]
    body = "\n".join(step.get("run", "") for step in job["steps"])
    assert "gh pr merge" not in body
    assert "headRefOid" in body
    assert "hold" in body and "do-not-merge" in body


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

"""Execute generated CI guards against PR and job-state fixtures.

Sources: PR45's passing Claude 2.1.306 unit job; gh pr merge's documented
--match-head-commit; claude-code-action/action.yml allowed_bots input.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("unit", "regression", "e2e", "environment", "install")
HEAD = "a" * 40
GIT_STUB = r"""
git() {
  case "$1" in
    cat-file) return 0 ;;
    rev-parse) printf '%s\n' "${FIXTURE_CHECKOUT:-$HEAD_SHA}" ;;
    log) printf '%s\n' "${FIXTURE_AUTHOR:-person@example.invalid}" ;;
    diff) printf '%s\n' "${FIXTURE_CHANGED:-src/product.py}"; return "${FIXTURE_DIFF_RC:-0}" ;;
    *) return 91 ;;
  esac
}
"""
GH_STUB = r"""
gh() {
  case "$1 $2" in
    'pr view') printf '%s\n' "$FIXTURE_PR"; return "${FIXTURE_VIEW_RC:-0}" ;;
    'pr merge') printf '%s\n' "$@" > "$FIXTURE_MERGE"; return "${FIXTURE_MERGE_RC:-0}" ;;
    *) return 91 ;;
  esac
}
"""


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load((ROOT / "templates/ci/pipeline.yml").read_text())


def step(workflow, job, name):
    return next(s for s in workflow["jobs"][job]["steps"] if s.get("name") == name)


def execute(script, tmp_path, overrides=None, stub=""):
    env = dict(
        os.environ,
        GITHUB_OUTPUT=str(tmp_path / "output"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
        HEAD_SHA=HEAD,
        BASE_REF="main",
        PR="42",
        ACTOR="person",
    )
    env.update(overrides or {})
    return subprocess.run(
        ["bash", "-eo", "pipefail", "-c", stub + script],
        env=env,
        capture_output=True,
        text=True,
    )


def guard(
    workflow,
    tmp_path,
    author="person@example.invalid",
    changed="src/product.py",
    **extra,
):
    env = {
        "FIXTURE_AUTHOR": author,
        "FIXTURE_CHANGED": changed,
        "TEST_RESULTS": json.dumps(
            {name: {"result": "success"} for name in CATEGORIES}
        ),
    }
    env.update(extra)
    result = execute(
        step(workflow, "review", "Review guard")["run"], tmp_path, env, GIT_STUB
    )
    output = tmp_path / "output"
    values = (
        dict(line.split("=", 1) for line in output.read_text().splitlines())
        if output.exists()
        else {}
    )
    return result, values


def test_human_head_runs_native_review_and_fix(workflow, tmp_path):
    result, values = guard(workflow, tmp_path)
    assert result.returncode == 0, result.stderr
    assert values == {"review": "true", "fix": "true"}


def test_green_claude_head_does_not_repeat_review_or_fix(workflow, tmp_path):
    result, values = guard(
        workflow, tmp_path, "41898282+claude[bot]@users.noreply.github.com"
    )
    assert result.returncode == 0, result.stderr
    assert values == {"review": "false", "fix": "false"}


@pytest.mark.parametrize("failed", CATEGORIES)
def test_red_claude_head_still_runs_fix(workflow, tmp_path, failed):
    results = {
        name: {"result": "failure" if name == failed else "success"}
        for name in CATEGORIES
    }
    result, values = guard(
        workflow,
        tmp_path,
        "209825114+claude[bot]@users.noreply.github.com",
        TEST_RESULTS=json.dumps(results),
    )
    assert result.returncode == 0, result.stderr
    assert values == {"review": "false", "fix": "true"}


@pytest.mark.parametrize(
    "author",
    ["person@example.invalid", "41898282+claude[bot]@users.noreply.github.com"],
)
def test_workflow_bootstrap_skips_review_and_fix(workflow, tmp_path, author):
    result, values = guard(workflow, tmp_path, author, ".github/workflows/pipeline.yml")
    assert result.returncode == 0, result.stderr
    assert values == {"review": "false", "fix": "false"}


@pytest.mark.parametrize(
    "extra", [{"FIXTURE_CHECKOUT": "b" * 40}, {"FIXTURE_DIFF_RC": "128"}]
)
def test_guard_rejects_stale_checkout_or_unreadable_diff(workflow, tmp_path, extra):
    result, _ = guard(workflow, tmp_path, **extra)
    assert result.returncode != 0


def gate(workflow, tmp_path, **overrides):
    env = {name.upper(): "success" for name in (*CATEGORIES, "review", "contract")}
    env.update(overrides)
    return execute(workflow["jobs"]["merge"]["steps"][0]["run"], tmp_path, env)


@pytest.mark.parametrize("job", (*CATEGORIES, "review", "contract"))
@pytest.mark.parametrize("status", ["failure", "cancelled", "timed_out", "skipped", ""])
def test_merge_rejects_every_incomplete_required_job(workflow, tmp_path, job, status):
    assert gate(workflow, tmp_path, **{job.upper(): status}).returncode != 0


def test_merge_accepts_green_jobs_and_explicit_dependabot_review_skip(
    workflow, tmp_path
):
    assert gate(workflow, tmp_path).returncode == 0
    assert (
        gate(workflow, tmp_path, REVIEW="skipped", ACTOR="dependabot[bot]").returncode
        == 0
    )


def live_pr(**overrides):
    return {
        "state": "OPEN",
        "isDraft": False,
        "headRefOid": HEAD,
        "title": "Fix the product",
        "labels": [],
        **overrides,
    }


def arm(workflow, tmp_path, record, rc="0"):
    path = tmp_path / "merge-argv"
    result = execute(
        step(workflow, "merge", "Verify live PR eligibility")["run"],
        tmp_path,
        {
            "FIXTURE_PR": json.dumps(record),
            "FIXTURE_MERGE": str(path),
            "FIXTURE_VIEW_RC": rc,
        },
        GH_STUB,
    )
    return result, path


@pytest.mark.parametrize(
    "record",
    [
        live_pr(state="CLOSED"),
        live_pr(state="MERGED"),
        live_pr(isDraft=True),
        live_pr(headRefOid="b" * 40),
        live_pr(labels=[{"name": "hold"}]),
        live_pr(labels=[{"name": "DO-NOT-MERGE"}]),
        live_pr(title="DO NOT MERGE: investigation"),
        {},
    ],
)
def test_merge_refuses_ineligible_live_pr_before_mutation(workflow, tmp_path, record):
    result, path = arm(workflow, tmp_path, record)
    assert result.returncode != 0
    assert not path.exists()


def test_merge_gate_validates_head_without_mutation(workflow, tmp_path):
    result, path = arm(workflow, tmp_path, live_pr())
    assert result.returncode == 0, result.stderr
    assert not path.exists()



def test_failed_live_pr_read_is_not_reinterpreted_as_eligible(workflow, tmp_path):
    result, _ = arm(
        workflow, tmp_path, live_pr(autoMergeRequest={"enabledAt": "today"}), "1"
    )
    assert result.returncode != 0


def test_action_permissions_and_fix_condition_preserve_bot_repairs(workflow):
    review = workflow["jobs"]["review"]
    assert set(CATEGORIES) <= set(review["needs"])
    actions = [
        s for s in review["steps"] if s.get("uses", "").startswith("anthropics/")
    ]
    assert [s["if"] for s in actions] == [
        "steps.guard.outputs.review == 'true'",
        "steps.guard.outputs.fix == 'true'",
    ]
    for action in actions:
        assert (
            action["with"]["allowed_bots"] == "claude[bot],chatgpt-codex-connector[bot]"
        )
        assert '"Bash"' not in action["with"]["claude_args"]
    assert set(CATEGORIES) <= set(workflow["jobs"]["tag"]["needs"])


@pytest.mark.parametrize("job", ["review", "merge"])
def test_mutating_jobs_handle_failures_but_stop_on_workflow_cancellation(workflow, job):
    # GitHub re-evaluates job conditions on cancellation: always() alone
    # keeps the job alive. Keep failure handling, but veto cancellation.
    # Source: docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation
    condition = workflow["jobs"][job]["if"]
    assert condition.startswith("always() && !cancelled() && ")
    assert "needs." not in condition
    assert "success()" not in condition

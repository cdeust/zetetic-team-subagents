"""Execute generated CI guards against PR and job-state fixtures.

Source: Cortex ADR-1121, the resolver merges on the verdict of the reviewed head.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("unit", "regression", "e2e", "environment", "install")
HEAD = "a" * 40
# Shared with tests/test_ci_native_gate.py, whose native profile still calls gh.
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
        PR_AUTHOR="person",
        REPO_OWNER="owner",
        HEAD_REF="fix/product",
        DEFAULT_BRANCH="main",
    )
    env.update(overrides or {})
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", stub + script],
        env=env,
        capture_output=True,
        text=True,
    )


def gate(workflow, tmp_path, **overrides):
    env = {name.upper(): "success" for name in (*CATEGORIES, "contract")}
    env.update(overrides)
    return execute(workflow["jobs"]["merge"]["steps"][0]["run"], tmp_path, env)


@pytest.mark.parametrize("job", (*CATEGORIES, "contract"))
@pytest.mark.parametrize("status", ["failure", "cancelled", "timed_out", "skipped", ""])
def test_merge_rejects_every_incomplete_required_job(workflow, tmp_path, job, status):
    assert gate(workflow, tmp_path, **{job.upper(): status}).returncode != 0


def test_merge_accepts_green_test_jobs(workflow, tmp_path):
    assert gate(workflow, tmp_path).returncode == 0


def test_merge_is_the_aggregate_of_the_test_jobs_of_the_run(workflow):
    """Owner rule 2026-10-29: the aggregate reads the test jobs and nothing else."""
    merge = workflow["jobs"]["merge"]
    assert set(merge["needs"]) == {"contract", *CATEGORIES}
    # The job merges nothing: the resolver merges once the Claude verdict of this
    # head approves (Cortex ADR-1121), so it holds no write permission and never
    # arms GitHub auto-merge, which would merge on green tests without a verdict.
    assert [s.get("name") for s in merge["steps"]] == ["Require the test jobs of this run"]
    assert merge["permissions"] == {"contents": "read"}
    text = yaml.safe_dump(merge)
    for forbidden in ("review", "gh pr", "headRefOid", "origin/main", "refs/heads/main",
                      "git fetch", "git diff", "compare", "autopilot", '"hold"', "--auto"):
        assert forbidden not in text.replace("pull_request", ""), forbidden


def test_the_pipeline_carries_no_review_or_fix_job(workflow):
    """The review is claude-review.yml's; the Pipeline never holds the OAuth secret."""
    assert "review" not in workflow["jobs"]
    text = (ROOT / "templates/ci/pipeline.yml").read_text()
    assert "claude-code-action@" not in text
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in text
    assert set(CATEGORIES) <= set(workflow["jobs"]["tag"]["needs"])


def test_merge_handles_failures_but_stops_on_workflow_cancellation(workflow):
    # GitHub re-evaluates job conditions on cancellation: always() alone
    # keeps the job alive. Keep failure handling, but veto cancellation.
    # Source: docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation
    condition = workflow["jobs"]["merge"]["if"]
    assert condition.startswith("always() && !cancelled() && ")
    assert "needs." not in condition
    assert "success()" not in condition

"""Scheduled fallback is trusted, policy-bound and does not call a model."""

from pathlib import Path

import yaml

from scripts.lib import render_ci as renderer

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "templates/ci/native/assets/.github/workflows/Codex.yml"


def test_scheduled_reconciliation_uses_supported_default_branch_events():
    # source: GitHub Actions schedule docs specify the five-minute minimum.
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow[True]["schedule"] == [{"cron": "*/5 * * * *"}]
    assert "workflow_dispatch" in workflow[True]
    assert "pull_request_review_thread" not in workflow[True]
    assert set(workflow[True]) >= {"issue_comment", "workflow_run"}


def test_only_discovery_selects_matrix_and_all_helpers_come_from_main():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    discover = workflow["jobs"]["reconcile-identify"]
    worker = workflow["jobs"]["reconcile"]
    assert discover["permissions"]["actions"] == "read"
    assert discover["concurrency"] == {
        "group": "codex-review-discovery-${{ github.repository }}",
        "cancel-in-progress": False,
    }
    assert worker["permissions"]["actions"] == "write"
    assert (
        worker["strategy"]["matrix"]["include"]
        == "${{ fromJSON(needs.reconcile-identify.outputs.prs) }}"
    )
    assert "!= '[]'" in worker["if"]
    assert worker["concurrency"] == {
        "group": "codex-review-completion-${{ github.repository }}-${{ matrix.number }}",
        "cancel-in-progress": False,
    }
    for job in (discover, worker):
        checkout = job["steps"][0]
        assert checkout["with"]["ref"] == "main"
        assert checkout["with"]["persist-credentials"] is False
        assert "claude" not in str(job).lower()
        assert "secrets." not in str(job)
    assert "--list" in discover["steps"][-1]["run"]
    assert '--pr "$EXPECTED_PR" --sha "$HEAD_SHA"' in worker["steps"][-1]["run"]


def test_rendered_workflow_limits_checks_read_to_discovery(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    workflow = yaml.safe_load(files[tmp_path / ".github/workflows/Codex.yml"])
    base = {
        "contents": "read",
        "pull-requests": "read",
        "issues": "read",
        "actions": "read",
    }
    assert workflow["permissions"] == base
    assert workflow["jobs"]["reconcile-identify"]["permissions"] == {
        **base,
        "checks": "read",
    }
    assert {
        name
        for name, job in workflow["jobs"].items()
        if "checks" in job.get("permissions", {})
    } == {"reconcile-identify"}

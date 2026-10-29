"""Recovery contracts are delivered and executed by the native CI itself."""

import subprocess
import sys

import yaml

from scripts.lib import render_ci

STEP = "Test native review recovery and resumption"
COMMAND = "python3 -B -m unittest discover -s scripts/tests -p 'test_ci_codex_review_*.py' -v"


def test_native_contract_runs_the_shipped_recovery_modules(tmp_path):
    files = render_ci.prepare_files(tmp_path, native_review=True)
    for workflow in ("pipeline.yml", "pipeline-post-merge.yml"):
        document = yaml.safe_load(files[tmp_path / ".github/workflows" / workflow])
        steps = document["jobs"]["contract"]["steps"]
        matching = [step for step in steps if step.get("name") == STEP]
        assert matching == [dict(name=STEP, run=COMMAND)]
        assert steps.index(matching[0]) < next(i for i, step in enumerate(steps) if step.get("id") == "commands")
    render_ci.deliver(files)
    result = subprocess.run(
        [sys.executable, "-B", "-S", "-m", "unittest", "discover", "-s", "scripts/tests",
         "-p", "test_ci_codex_review_*.py", "-v"],
        cwd=tmp_path, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_completed_unknown_security_requests_review_instead_of_stalling" in result.stderr
    assert "test_positive_current_findings_request_native_fix" in result.stderr
    assert "test_failed_category_is_discovered_even_when_pending_merge_failed" in result.stderr
    assert "\nOK\n" in result.stderr


def test_native_request_workers_have_comment_write_and_shared_serialization(tmp_path):
    files = render_ci.prepare_files(tmp_path, native_review=True)
    document = yaml.safe_load(files[tmp_path / ".github/workflows/Codex.yml"])
    for name in ("resume", "reconcile"):
        worker = document["jobs"][name]
        assert worker["permissions"]["issues"] == "read"
        assert worker["permissions"]["pull-requests"] == "write"
        assert worker["permissions"]["actions"] == "write"
        assert worker["concurrency"]["group"].startswith("codex-review-completion-")
        assert worker["concurrency"]["cancel-in-progress"] is False
        assert worker["steps"][0]["with"]["ref"] == "main"
        assert worker["steps"][0]["with"]["persist-credentials"] is False
    assert document["jobs"]["reconcile-identify"]["permissions"]["issues"] == "read"

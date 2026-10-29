"""Native consumers receive and execute tests of their actual workflow controller."""
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts.lib import render_ci

ASSET = "scripts/tests/test_ci_workflow_authorization.py"
STEP = "Test embedded workflow authorization"
COMMAND = "python3 -m unittest discover -s scripts/tests -p test_ci_workflow_authorization.py -v"


@pytest.mark.parametrize("no_schedule", [False, True])
def test_native_export_executes_actual_workflow_contract(tmp_path, no_schedule):
    files = render_ci.prepare_files(tmp_path, native_review=True, no_schedule=no_schedule)
    assert tmp_path / ASSET in files
    for workflow in ("pipeline.yml", "pipeline-post-merge.yml"):
        document = yaml.safe_load(files[tmp_path / ".github/workflows" / workflow])
        steps = document["jobs"]["contract"]["steps"]
        matching = [step for step in steps if step.get("name") == STEP]
        assert matching == [{"name": STEP, "run": COMMAND}]
        assert steps.index(matching[0]) < next(i for i, step in enumerate(steps) if step.get("id") == "commands")
    render_ci.deliver(files)
    # -S proves the exported consumer tests use only the standard library.
    result = subprocess.run(
        [sys.executable, "-S", "-m", "unittest", "discover", "-s", "scripts/tests",
         "-p", "test_ci_workflow_authorization.py", "-v"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "\nOK\n" in result.stderr


def test_legacy_profile_does_not_require_native_authorization_tests(tmp_path):
    files = render_ci.prepare_files(tmp_path)
    assert tmp_path / ASSET not in files
    assert STEP not in files[tmp_path / ".github/workflows/pipeline.yml"].decode()


def test_exported_contract_catches_missing_authorization_in_actual_workflow(tmp_path: Path) -> None:
    render_ci.deliver(render_ci.prepare_files(tmp_path, native_review=True))
    workflow = tmp_path / ".github/workflows/pipeline-post-merge.yml"
    text = workflow.read_text()
    call = "_proof.authorize_workflow(run, repository, api, PostMergeError)"
    assert text.count(call) == 1
    workflow.write_text(text.replace(call, "pass  # fixture mutation removes authorization"))
    result = subprocess.run(
        [sys.executable, "-S", "-m", "unittest", "discover", "-s", "scripts/tests",
         "-p", "test_ci_workflow_authorization.py", "-v"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "FAIL: test_successful_fake_job_names_do_not_authorize_merge" in result.stderr
    assert "FAIL: test_rejected_proof_has_nonzero_cli_and_no_output" in result.stderr

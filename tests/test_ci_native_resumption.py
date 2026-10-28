"""Deliver and execute the native gate's observable decision contracts.

Source: Spec PR159 findings4395992283/4395992285 and Cortex f4831d15 tests.
"""

from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts.lib import render_ci as renderer

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "templates/ci/native/assets"
CONTRACTS = (
    "test_ci_codex_review_resume.py",
    "test_ci_codex_review_event.py",
    "test_ci_codex_review_event_attempts.py",
    "test_ci_codex_review_event_cli.py",
    "test_ci_codex_review_reconcile.py",
)


def test_native_profile_delivers_executable_resumption_contracts(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    for name in (
        *CONTRACTS,
        "codex_resume_fixtures.py",
        "test_ci_codex_review_event_fixtures.py",
    ):
        assert files[tmp_path / "scripts/tests" / name]


@pytest.mark.spawns
def test_native_decision_and_coordinator_contracts_pass():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(ASSETS / "scripts/tests"),
            "-p",
            "test_ci_codex_review_*.py",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ran " in result.stderr and "Ran 0 tests" not in result.stderr


def test_completion_does_not_register_a_webhook_only_actions_event():
    # source: GitHub's supported Actions events, unlike the separate webhook catalog.
    # https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
    workflow = yaml.safe_load((ASSETS / ".github/workflows/Codex.yml").read_text())
    assert "pull_request_review_thread" not in workflow[True]

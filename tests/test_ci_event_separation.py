"""The privileged completion event cannot reach PR review (Cortex CodeQL184)."""

import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("unit", "regression", "e2e", "environment", "install")
DIRECT = "pipeline.yml"
ENGINE = "pipeline-post-merge.yml"
CALLER = "pipeline-after-merge.yml"


@pytest.fixture
def generated(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    env["TMPDIR"] = str(tmp_path)
    subprocess.run(
        ["bash", str(ROOT / "scripts/setup.sh"), "render-ci", str(tmp_path)],
        check=True,
        env=env,
        capture_output=True,
    )
    return {
        path.name: yaml.safe_load(path.read_text())
        for path in (tmp_path / ".github/workflows").glob("*.yml")
    }


def test_direct_receipt_remains_pipeline_without_a_reusable_entry(generated):
    direct = generated[DIRECT]
    assert direct["name"] == "Pipeline"
    assert set(direct[True]) == {"push", "pull_request"}
    assert list(direct["jobs"]) == ["contract", *CATEGORIES, "review", "merge", "tag"]
    contract = direct["jobs"]["contract"]
    assert "needs" not in contract
    assert contract["if"] == "!cancelled()"
    assert contract["steps"][0]["with"]["ref"] == "${{ github.sha }}"


def test_completion_has_no_path_to_review_or_merge(generated):
    engine = generated[ENGINE]
    assert engine[True] == {
        "workflow_call": {"secrets": {"RELEASE_TAG_SSH_KEY": {"required": False}}}
    }
    assert list(engine["jobs"]) == ["resolve", "contract", *CATEGORIES, "tag"]
    for job in engine["jobs"].values():
        assert "uses" not in job
        assert not any(
            "claude-code-action" in step.get("uses", "") for step in job["steps"]
        )
    caller = generated[CALLER]["jobs"]["pipeline"]
    assert caller["uses"] == "./.github/workflows/" + ENGINE
    assert caller["secrets"] == {
        "RELEASE_TAG_SSH_KEY": "${{ secrets.RELEASE_TAG_SSH_KEY }}"
    }
    assert caller["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "read",
    }


def test_completion_contract_has_no_fallback_commit(generated):
    contract = generated[ENGINE]["jobs"]["contract"]
    assert contract["needs"] == "resolve"
    assert contract["if"] == (
        "!cancelled() && github.event_name == 'workflow_run' "
        "&& needs.resolve.result == 'success' && needs.resolve.outputs.run_tests == 'true'"
    )
    assert (
        contract["steps"][0]["with"]["ref"] == "${{ needs.resolve.outputs.tested_sha }}"
    )
    assert (
        contract["steps"][1]["env"]["EXPECTED_SHA"]
        == "${{ needs.resolve.outputs.tested_sha }}"
    )
    assert "github.sha" not in str(contract)


def test_five_category_jobs_are_identical_in_both_entry_paths(generated):
    canonical = yaml.safe_load((ROOT / "templates/ci/pipeline.yml").read_text())
    for name in CATEGORIES:
        assert generated[DIRECT]["jobs"][name] == canonical["jobs"][name]
        assert generated[ENGINE]["jobs"][name] == canonical["jobs"][name]
    direct_tag = generated[DIRECT]["jobs"]["tag"]
    post_tag = generated[ENGINE]["jobs"]["tag"]
    assert direct_tag["steps"] == post_tag["steps"] == canonical["jobs"]["tag"]["steps"]
    assert "github.event_name == 'workflow_run'" not in direct_tag["if"]
    assert (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
        in direct_tag["if"]
    )
    assert "github.event_name == 'workflow_run'" in post_tag["if"]
    assert "github.event_name == 'push'" not in post_tag["if"]

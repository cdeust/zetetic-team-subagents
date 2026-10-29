"""GitHub refuses self-listening workflows (source run40017492191)."""

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ("pipeline.yml", "pipeline-after-merge.yml", "pipeline-post-merge.yml")


def documents():
    return [
        yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
        for name in FILES
    ]


def test_completion_listener_has_a_distinct_name_and_no_self_listener():
    pipeline, caller, engine = documents()
    assert pipeline["name"] == "Pipeline"
    assert caller["name"] == "Pipeline after merge"
    assert "workflow_call" not in pipeline[True]
    assert "workflow_call" in engine[True]
    assert "workflow_run" not in pipeline[True]
    assert caller[True] == {
        "workflow_run": {
            "workflows": ["Pipeline"],
            "types": ["completed"],
            "branches-ignore": ["main"],
        }
    }
    for doc in (pipeline, caller):
        assert doc["name"] not in doc[True].get("workflow_run", {}).get("workflows", [])


def test_completion_caller_uses_same_commit_and_inherits_required_permissions():
    pipeline, caller, _engine = documents()
    assert set(caller["jobs"]) == {"pipeline"}
    job = caller["jobs"]["pipeline"]
    assert job["uses"] == "./.github/workflows/pipeline-post-merge.yml"
    assert job["secrets"] == {
        "RELEASE_TAG_SSH_KEY": "${{ secrets.RELEASE_TAG_SSH_KEY }}"
    }
    assert "concurrency" not in caller and "concurrency" not in job
    assert "concurrency" in pipeline
    assert job["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "read",
    }
    assert set(job) == {"if", "uses", "secrets", "permissions"}
    assert "github.event.workflow_run.event == 'pull_request'" in job["if"]
    assert "github.event.workflow_run.conclusion == 'success'" in job["if"]


def test_renderer_generates_three_files_in_empty_consumer_and_keeps_config(tmp_path):
    env = {
        key: value for key, value in os.environ.items() if key != "CLAUDE_PLUGIN_ROOT"
    }
    env["TMPDIR"] = str(tmp_path)
    command = ["bash", str(ROOT / "scripts/setup.sh"), "render-ci", str(tmp_path)]
    subprocess.run(command, check=True, env=env, capture_output=True)
    for name in FILES:
        rendered = (tmp_path / ".github/workflows" / name).read_bytes()
        assert rendered == (ROOT / ".github/workflows" / name).read_bytes()
    config = tmp_path / "ci.json"
    config.write_text('{"unit":"owned"}\n')
    before = {
        name: (tmp_path / ".github/workflows" / name).read_bytes() for name in FILES
    }
    subprocess.run(command, check=True, env=env, capture_output=True)
    assert config.read_text() == '{"unit":"owned"}\n'
    assert all(
        (tmp_path / ".github/workflows" / name).read_bytes() == body
        for name, body in before.items()
    )

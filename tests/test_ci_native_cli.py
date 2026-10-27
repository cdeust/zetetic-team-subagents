"""Native CI uses the frozen CLI project; legacy generation stays independent."""

import json

import pytest
import yaml

from scripts.lib import render_ci as renderer


def test_native_delivers_private_cli_project_with_integrity_lock(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    root = tmp_path / ".github/claude-cli"
    package = json.loads(files[root / "package.json"])
    lock = json.loads(files[root / "package-lock.json"])
    assert package["private"] is True
    assert package["dependencies"] == {"@anthropic-ai/claude-code": "2.1.306"}
    assert lock["packages"][""]["dependencies"] == package["dependencies"]
    for name, data in lock["packages"].items():
        if name:
            assert data["version"] == "2.1.306"
            assert data["integrity"].startswith("sha512-")
            assert data["resolved"].startswith("https://registry.npmjs.org/")


@pytest.mark.parametrize("workflow", ["pipeline.yml", "pipeline-post-merge.yml"])
def test_native_cli_installs_from_lock_and_exports_its_bin(tmp_path, workflow):
    files = renderer.prepare_files(tmp_path, native_review=True)
    document = yaml.safe_load(files[tmp_path / ".github/workflows" / workflow])
    for category in ("environment", "install"):
        steps = document["jobs"][category]["steps"]
        command = next(
            s["run"] for s in steps if s.get("name") == "Install the Claude Code CLI"
        )
        assert 'npm ci --prefix "$GITHUB_WORKSPACE/.github/claude-cli"' in command
        assert (
            'echo "$GITHUB_WORKSPACE/.github/claude-cli/node_modules/.bin" >> "$GITHUB_PATH"'
            in command
        )
        assert "npm install -g" not in command

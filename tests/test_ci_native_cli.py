"""Both pipeline profiles install the integrity-locked CLI project."""

import json
from pathlib import Path

import pytest
import yaml

from scripts.lib import render_ci as renderer


@pytest.mark.parametrize("native_review", [False, True])
def test_delivers_private_cli_project_with_integrity_lock(tmp_path, native_review):
    files = renderer.prepare_files(tmp_path, native_review=native_review)
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


@pytest.mark.parametrize("native_review", [False, True])
@pytest.mark.parametrize("workflow", ["pipeline.yml", "pipeline-post-merge.yml"])
def test_cli_installs_from_lock_and_exports_its_bin(tmp_path, workflow, native_review):
    files = renderer.prepare_files(tmp_path, native_review=native_review)
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


def test_repository_ships_the_same_cli_manifest_and_lock(tmp_path):
    root = Path(__file__).resolve().parents[1]
    files = renderer.prepare_files(tmp_path, native_review=True)
    for name in ("package.json", "package-lock.json"):
        path = Path(".github/claude-cli") / name
        assert (root / path).read_bytes() == files[tmp_path / path]

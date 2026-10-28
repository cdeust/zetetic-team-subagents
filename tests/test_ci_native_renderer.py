"""Opt-in delivery of the native review configuration proven in Cortex PR811."""

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts.lib import render_ci as renderer

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "templates/ci/native"


def native_common_jobs():
    # Source: Cortex8e7375bf/Spec616eb04 pin v7.1.0; npm ci docs define frozen installs.
    text = renderer.artifacts()["pipeline.yml"].replace(
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0",
        "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0",
    )
    text = text.replace(
        "        run: npm install -g @anthropic-ai/claude-code@2.1.306",
        "        run: |\n"
        '          npm ci --prefix "$GITHUB_WORKSPACE/.github/claude-cli"\n'
        '          echo "$GITHUB_WORKSPACE/.github/claude-cli/node_modules/.bin" >> "$GITHUB_PATH"',
    )
    return yaml.safe_load(text)


def test_native_keeps_common_jobs_and_separates_both_reviewers(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    direct = yaml.safe_load(files[tmp_path / ".github/workflows/pipeline.yml"])
    legacy = native_common_jobs()
    for name in ("contract", *renderer.CATEGORIES, "tag"):
        assert direct["jobs"][name] == legacy["jobs"][name]
    review = str(direct["jobs"]["review"])
    assert "claude-code-action" not in review
    assert "Require completed Codex reviews" in review
    assert "CODEX_COMPLETION_ONLY" in review
    claude = yaml.safe_load(files[tmp_path / ".github/workflows/claude-review.yml"])
    assert set(claude[True]) == {"pull_request"}
    assert claude["jobs"]["review"]["steps"][-1]["with"]["track_progress"] is True
    assert (
        "security-code-reviewer"
        in files[tmp_path / ".claude/commands/review-pr.md"].decode()
    )
    runtime = files[tmp_path / "scripts/ci_codex_review_runtime.py"].decode()
    assert "resolvedBy" in runtime
    assert "_trusted_resolver" in runtime
    reader = files[tmp_path / "scripts/ci_codex_reviews.py"].decode()
    assert 'KINDS = ("code_review", "security_review")' in reader


def test_native_cli_preserves_configuration_and_unrelated_files(tmp_path):
    settings = tmp_path / "ci.json"
    settings.write_bytes(b'{"unit":"owner command"}\n')
    unrelated = tmp_path / "owner.txt"
    unrelated.write_text("keep")
    env = {key: val for key, val in os.environ.items() if key != "CLAUDE_PLUGIN_ROOT"}
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/setup.sh"),
            "render-ci",
            str(tmp_path),
            "--native-review",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert settings.read_bytes() == b'{"unit":"owner command"}\n'
    assert unrelated.read_text() == "keep"
    assert (tmp_path / "scripts/ci_codex_reviews.py").is_file()
    assert (tmp_path / ".github/workflows/Codex.yml").is_file()


def original_security_runtime(delivered):
    original = delivered.replace(
        b"if not expected.issubset(states):", b"if states.keys() != expected:"
    ).replace(b'"finding_ids": sorted(expected),', b'"finding_ids": sorted(states),')
    return re.sub(
        rb'"state": \(\n *"success" if all\(states\[identity\] for identity in expected\) else "unresolved"\n *\),',
        b'"state": "success" if all(states.values()) else "unresolved",',
        original,
    )


def original_asset(delivered, relative):
    if relative == "scripts/ci_codex_review_runtime.py":
        return original_security_runtime(delivered)
    original = delivered.replace(b"            --strict-mcp-config\n", b"")
    original = original.replace(
        b'--model "claude-opus-5-5"', b'--model "claude-opus-4-7"'
    )
    if relative.endswith("/claude-review.yml"):
        original = original.replace(b"  pull_request:\n", b"  pull_request_target:\n")
        original = original.replace(b"      id-token: write\n", b"")
        original = original.replace(
            b"          claude_code_oauth_token:",
            b"          github_token: ${{ secrets.GITHUB_TOKEN }}\n          claude_code_oauth_token:",
        )
        original = original.replace(
            b"# Native App OIDC auth on same-repository PRs; main checkout retained.",
            b"# Trusted-base variant: upstream docs/security.md. Auth: upstream issue713.",
        )
    return original


def test_native_assets_match_the_pinned_source_receipt(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    receipt = json.loads((NATIVE / "source.json").read_text())
    assert receipt["commit"] == "8e7375bf2edfb33fb9c45809b9af6b428f0f4235"
    for relative, digest in receipt["assets"].items():
        assert hashlib.sha256(files[tmp_path / relative]).hexdigest() == digest
    assert len(receipt["assets"]) == 11
    for relative, source in receipt["adapted_assets"].items():
        delivered = files[tmp_path / relative]
        assert hashlib.sha256(delivered).hexdigest() == source["sha256"]
        original = original_asset(delivered, relative)
        assert hashlib.sha256(original).hexdigest() == source["source_sha256"]
    assert len(receipt["adapted_assets"]) == 3
    for relative, digest in receipt["authored_assets"].items():
        assert hashlib.sha256(files[tmp_path / relative]).hexdigest() == digest
    assert (
        set(receipt["assets"])
        | set(receipt["adapted_assets"])
        | set(receipt["authored_assets"])
    ) == set(renderer.NATIVE_ASSETS)
    jobs = renderer.split_jobs((NATIVE / "pipeline.yml").read_text())[1]
    for name, source in receipt["jobs"].items():
        assert hashlib.sha256(jobs[name].encode()).hexdigest() == source["sha256"]
    for name, source in receipt["adapted_jobs"].items():
        delivered = jobs[name].encode()
        assert hashlib.sha256(delivered).hexdigest() == source["sha256"]
        assert (
            hashlib.sha256(original_security_runtime(delivered)).hexdigest()
            == source["source_sha256"]
        )


def test_native_delivery_rolls_back_workflows_and_assets(tmp_path, monkeypatch):
    files = renderer.prepare_files(tmp_path, native_review=True)
    old = tmp_path / ".github/workflows/pipeline.yml"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"previous workflow")
    before = {path: path.read_bytes() if path.exists() else None for path in files}
    last = list(files)[-1]
    replace = renderer.os.replace

    def fail_last(temporary, destination):
        if destination == last:
            raise OSError("fixture native delivery failure")
        replace(temporary, destination)

    monkeypatch.setattr(renderer.os, "replace", fail_last)
    with pytest.raises(OSError, match="fixture native delivery failure"):
        renderer.deliver(files)
    assert {p: p.read_bytes() if p.exists() else None for p in files} == before
    assert not list(tmp_path.rglob(".render-ci-*"))


def test_native_invalid_asset_destination_preflights_the_entire_set(tmp_path):
    directory = tmp_path / ".claude/agents/security-code-reviewer.md"
    directory.mkdir(parents=True)
    with pytest.raises(ValueError, match="non-file"):
        renderer.prepare_files(tmp_path, native_review=True)
    assert not (tmp_path / ".github").exists()


def test_native_symlinked_parent_cannot_escape_the_destination(tmp_path):
    target = tmp_path / "consumer"
    outside = tmp_path / "outside"
    target.mkdir()
    outside.mkdir()
    (target / "scripts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        renderer.prepare_files(target, native_review=True)
    assert list(outside.iterdir()) == []
    assert not (target / ".github").exists()


def test_native_rendered_workflows_pass_actionlint(tmp_path):
    import shutil
    import sysconfig

    renderer.deliver(renderer.prepare_files(tmp_path, native_review=True))
    scripts = Path(sysconfig.get_path("scripts")) / "actionlint"
    linter = str(scripts) if scripts.is_file() else shutil.which("actionlint")
    assert linter, "actionlint missing: install requirements-dev.lock"
    workflows = sorted((tmp_path / ".github/workflows").glob("*.yml"))
    assert len(workflows) == 6
    result = subprocess.run(
        [linter, *map(str, workflows)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_inline_codex_readers_match_the_delivered_scripts(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    direct = yaml.safe_load(files[tmp_path / ".github/workflows/pipeline.yml"])
    command = direct["jobs"]["review"]["steps"][0]["run"]
    for variable, filename in (
        ("RUNTIME_SOURCE", "ci_codex_review_runtime.py"),
        ("READER_SOURCE", "ci_codex_reviews.py"),
    ):
        embedded = command.split(variable + " = r'''\n", 1)[1].split("\n'''", 1)[0]
        assert embedded == files[tmp_path / "scripts" / filename].decode().rstrip()


@pytest.mark.parametrize("workflow", ["claude-review.yml", "claude.yml"])
def test_native_claude_limits_mcp_to_the_actions_configuration(tmp_path, workflow):
    import shlex

    files = renderer.prepare_files(tmp_path, native_review=True)
    document = yaml.safe_load(files[tmp_path / ".github/workflows" / workflow])
    steps = next(iter(document["jobs"].values()))["steps"]
    action = next(
        step
        for step in steps
        if "anthropics/claude-code-action@" in step.get("uses", "")
    )
    arguments = shlex.split(action["with"]["claude_args"])
    assert arguments.count("--strict-mcp-config") == 1
    assert arguments[arguments.index("--model") + 1] == "claude-opus-5-5"
    assert "--mcp-config" not in arguments  # The pinned action supplies its own.
    assert files[tmp_path / ".claude/commands/review-pr.md"]
    reviewers = [
        name for name in renderer.NATIVE_ASSETS if name.startswith(".claude/agents/")
    ]
    assert len(reviewers) == 5
    assert all(files[tmp_path / name] for name in reviewers)


def test_native_claude_uses_app_oidc_and_a_main_checkout(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    document = yaml.safe_load(files[tmp_path / ".github/workflows/claude-review.yml"])
    job = document["jobs"]["review"]
    assert job["permissions"].get("id-token") == "write"
    assert "github_token" not in job["steps"][-1]["with"]
    assert job["steps"][0]["with"]["ref"] == "main"
    assert "head.repo.full_name == github.repository" in job["if"]
    assert "!github.event.pull_request.draft" in job["if"]

"""Strict source boundaries and complete-set delivery for generated workflows."""

from pathlib import Path
import shutil

import pytest
import yaml

from scripts.lib import render_ci as renderer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    shutil.copytree(ROOT / "templates/ci", root / "templates/ci")
    return root


@pytest.mark.parametrize(
    "before,after",
    [
        ("  unit:\n", "  unknown:\n"),
        ("  unit:\n", "  unit:\n  unit:\n"),
        ("    needs: resolve\n", "    needs: missing\n"),
        ("needs.resolve.outputs.tested_sha || github.sha", "github.sha"),
        ("on:\n", "on:\n  workflow_call:\n"),
        ("jobs:\n", "jobs:\njobs:\n"),
    ],
)
def test_source_drift_fails_before_any_destination_write(
    source, tmp_path, before, after
):
    template = source / "templates/ci/pipeline.yml"
    template.write_text(template.read_text().replace(before, after))
    target = tmp_path / "consumer"
    target.mkdir()
    existing = target / ".github/workflows/pipeline.yml"
    existing.parent.mkdir(parents=True)
    existing.write_text("old workflow\n")
    with pytest.raises(ValueError):
        renderer.deliver(renderer.prepare_files(target, source))
    assert existing.read_text() == "old workflow\n"
    assert sorted(
        p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()
    ) == [".github/workflows/pipeline.yml"]


@pytest.mark.parametrize("destination", ["pipeline.yml", "another.yml"])
def test_caller_cannot_reconnect_completion_to_review(source, destination):
    caller = source / "templates/ci/pipeline-after-merge.yml"
    caller.write_text(
        caller.read_text().replace("pipeline-post-merge.yml", destination)
    )
    with pytest.raises(ValueError, match="target only"):
        renderer.artifacts(source)


def test_injected_review_action_in_common_tests_cannot_enter_completion(source):
    template = source / "templates/ci/pipeline.yml"
    original = template.read_text()
    jobs = yaml.safe_load(original)["jobs"]
    # source: the pin of .github/workflows/claude-review.yml.
    action = "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb"
    unit = renderer.split_jobs(original)[1]["unit"]
    injected = unit.replace(jobs["unit"]["steps"][0]["uses"], action, 1)
    template.write_text(original.replace(unit, injected, 1))
    assert (
        yaml.safe_load(template.read_text())["jobs"]["unit"]["steps"][0]["uses"]
        == action
    )
    with pytest.raises(ValueError, match="PR review action"):
        renderer.artifacts(source)


@pytest.mark.parametrize("existing", [False, True])
def test_failed_delivery_restores_every_original_file(tmp_path, monkeypatch, existing):
    paths = [
        tmp_path / name
        for name in (
            "pipeline.yml",
            "pipeline-post-merge.yml",
            "pipeline-after-merge.yml",
        )
    ]
    if existing:
        for path in paths:
            path.write_bytes(b"previous " + path.name.encode())
    before = {path: path.read_bytes() if path.exists() else None for path in paths}
    replace = renderer.os.replace

    def fail_last_once(temporary, destination):
        if destination == paths[-1]:
            raise OSError("fixture disk failure")
        replace(temporary, destination)

    monkeypatch.setattr(renderer.os, "replace", fail_last_once)
    with pytest.raises(OSError, match="fixture disk failure"):
        renderer.deliver({path: b"new " + path.name.encode() for path in paths})
    assert {
        path: path.read_bytes() if path.exists() else None for path in paths
    } == before
    assert not list(tmp_path.glob(".render-ci-*"))


def test_invalid_last_destination_preserves_the_other_workflows(source, tmp_path):
    target = tmp_path / "consumer"
    target.mkdir()
    files = target / ".github/workflows"
    files.mkdir(parents=True)
    (files / "pipeline.yml").write_text("old workflow")
    (files / "pipeline-after-merge.yml").mkdir()
    with pytest.raises(ValueError, match="non-file"):
        renderer.prepare_files(target, source)
    assert (files / "pipeline.yml").read_text() == "old workflow"
    assert not (files / "pipeline-post-merge.yml").exists()


def test_dry_run_creates_no_destination_files(source, tmp_path):
    target = tmp_path / "consumer"
    target.mkdir()
    renderer.deliver(renderer.prepare_files(target, source), dry_run=True)
    assert list(target.iterdir()) == []


def test_default_profile_delivers_the_review_its_resolver_waits_for(tmp_path):
    # The default resolver holds every merge without an approving verdict of
    # claude-review.yml: a consumer rendered without that workflow, its budget
    # script and its reviewers could never merge (Codex P1 on #244).
    files = renderer.prepare_files(tmp_path)
    for name in renderer.REVIEW_ASSETS:
        # One source: what a consumer receives is what this repository runs.
        assert files[tmp_path / name] == (ROOT / name).read_bytes(), name
    workflow = yaml.safe_load(files[tmp_path / ".github/workflows/claude-review.yml"])
    assert workflow["name"] == "PR Review"
    caller = yaml.safe_load(files[tmp_path / ".github/workflows/pipeline-after-merge.yml"])
    assert workflow["name"] in caller[True]["workflow_run"]["workflows"]
    review = workflow["jobs"]["review"]["steps"][-1]["with"]["prompt"]
    assert review.startswith("/review-pr ") and "Verdict: approve" in review
    budget = workflow["jobs"]["budget"]["steps"][-1]["run"]
    assert "scripts/ci_review_budget.py" in budget


def test_native_profile_keeps_its_own_review_assets(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    assert tmp_path / "scripts/ci_review_budget.py" not in files


def test_native_caller_wakes_on_the_pipeline_only(tmp_path):
    # The native resolver refuses any source but the Pipeline ("source workflow
    # differs"), so a review completion there would only start a failing run
    # (Codex P2 on #244). The default resolver handles both completions.
    name = tmp_path / ".github/workflows/pipeline-after-merge.yml"
    native = yaml.safe_load(renderer.prepare_files(tmp_path, native_review=True)[name])
    default = yaml.safe_load(renderer.prepare_files(tmp_path)[name])
    assert native[True]["workflow_run"]["workflows"] == ["Pipeline"]
    assert default[True]["workflow_run"]["workflows"] == ["Pipeline", "PR Review"]

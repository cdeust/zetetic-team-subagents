"""The tag job never checks out the tested commit (CodeQL actions/untrusted-checkout).

Source: CodeQL alerts on Cortex PR839 (pipeline-post-merge.yml:971, high) and
ai-architect-mcp-codebase PR471 (pipeline-post-merge.yml:972 high, pipeline.yml:1822
medium): "Checkout of untrusted code in a privileged workflow with later potential
execution (event trigger: workflow_run)". The job holds RELEASE_TAG_SSH_KEY, a
write-enabled deploy key, so the tested commit is fetched into a bare repository
and nothing from it is executed.
"""

from pathlib import Path

import yaml

from scripts.lib import render_ci as renderer

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = (
    ROOT / "templates/ci/pipeline.yml",
    ROOT / "templates/ci/native/pipeline.yml",
    ROOT / "templates/ci/native/generated/pipeline.yml",
)


def tag_job(text):
    return yaml.safe_load(text)["jobs"]["tag"]


def rendered_workflows(tmp_path, native):
    files = renderer.prepare_files(tmp_path, native_review=native)
    return {
        name: files[tmp_path / f".github/workflows/{name}"].decode()
        for name in ("pipeline.yml", "pipeline-post-merge.yml")
    }


def assert_no_checkout_in_tag(job):
    uses = [step.get("uses", "") for step in job["steps"]]
    assert not any(u.startswith("actions/checkout") for u in uses), uses
    assert "ssh-key" not in str(job)
    fetch = next(s for s in job["steps"] if s["name"] == "Fetch the tested commit into a bare repository")
    assert "git init --quiet --bare" in fetch["run"]
    assert 'fetch --quiet --depth=1 origin "$TESTED_SHA"' in fetch["run"]
    assert "StrictHostKeyChecking=yes" in fetch["run"]
    assert "gh api meta" in fetch["run"]
    publish = next(s for s in job["steps"] if s.get("id") == "publish")
    assert publish["working-directory"] == "${{ runner.temp }}/release-repo"


def test_template_tag_jobs_fetch_without_a_checkout():
    for template in TEMPLATES:
        assert_no_checkout_in_tag(tag_job(template.read_text()))


def test_rendered_tag_jobs_fetch_without_a_checkout(tmp_path):
    for native in (False, True):
        for name, text in rendered_workflows(tmp_path / str(native), native).items():
            assert_no_checkout_in_tag(tag_job(text)), name


def test_fetch_step_rejects_a_tampered_sha():
    """The SHA guard runs before any key material is written."""
    import subprocess

    job = tag_job(TEMPLATES[1].read_text())
    run = next(s["run"] for s in job["steps"] if s["name"] == "Fetch the tested commit into a bare repository")
    for sha in ("HEAD", "main; rm -rf /", "a" * 39, "A" * 40):
        result = subprocess.run(
            ["bash", "-c", run],
            env={"PATH": "/usr/bin:/bin", "TESTED_SHA": sha, "SSH_KEY": "k", "RUNNER_TEMP": "/nonexistent", "GITHUB_ENV": "/dev/null", "GITHUB_REPOSITORY": "o/r"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, sha
        assert "tested_sha is not" in result.stdout, result.stdout

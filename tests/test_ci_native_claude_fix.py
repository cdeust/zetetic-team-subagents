"""Owner fix permissions and SSH transport from the canonical native export."""
import os
import json
import shlex
import subprocess

import yaml
import pytest

from scripts.lib import render_ci as renderer


def owner_workflow(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    return yaml.safe_load(files[tmp_path / ".github/workflows/claude.yml"])


def test_owner_fix_inherits_workspace_edits_and_allows_validation(tmp_path):
    workflow = owner_workflow(tmp_path)
    job = workflow["jobs"]["claude"]
    assert set(workflow[True]) == {"issue_comment", "issues"}
    assert "github.event.sender.login == github.repository_owner" in job["if"]
    assert "github.event.issue.user.login == github.repository_owner" in job["if"]
    action = next(s for s in job["steps"] if "claude-code-action@" in s.get("uses", ""))
    args = shlex.split(action["with"]["claude_args"])
    # Native Claude auto mode classifies shell commands; do not bypass it with
    # interpreter or unrestricted git/gh allowances (Claude PR8 review6494974069).
    assert args[args.index("--permission-mode") + 1] == "auto"
    assert "--dangerously-skip-permissions" not in args
    tools = set(args[args.index("--allowedTools") + 1].split(","))
    assert tools == {"Task"}
    assert action["with"]["include_comments_by_actor"] == "${{ github.repository_owner }}"
    assert "github_token" not in action["with"]
    prompt = args[args.index("--append-system-prompt") + 1]
    assert "canonical source and run render-ci" in prompt
    assert "never push main" in prompt


def test_owner_fix_keeps_action_app_token_for_automatic_ci(tmp_path):
    steps = owner_workflow(tmp_path)["jobs"]["claude"]["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    action = next(s for s in steps if "claude-code-action@" in s.get("uses", ""))
    assert "github_token" not in action["with"]


@pytest.mark.parametrize("case", [
    ("owner/repo", "fix/feature", True, True),
    ("untrusted/fork", "fix/feature", True, False),
    ("owner/repo", "main", True, False),
    (None, "fix/feature", True, False),
    ("owner/repo", "fix/feature", False, False),
])
def test_owner_pr_target_is_authorized_before_checkout(tmp_path, case):
    repo, branch, api_ok, allowed = case
    steps = owner_workflow(tmp_path)["jobs"]["claude"]["steps"]
    guard = steps[0]
    assert guard["name"] == "Authorize owner fix target"
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"issue": {"pull_request": {"url": "pr"}}}))
    metadata = tmp_path / "pr.json"
    metadata.write_text(json.dumps({"head": {"repo": {"full_name": repo}, "ref": branch}, "base": {"repo": {"default_branch": "main"}}}))
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/sh\ncat "$PR_METADATA"\nexit "$API_EXIT"\n')
    gh.chmod(0o755)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
           "GITHUB_EVENT_PATH": str(event), "PR_METADATA": str(metadata),
           "API_EXIT": "0" if api_ok else "1", "GH_REPO": "owner/repo", "ISSUE_NUMBER": "1"}
    result = subprocess.run(["bash", "-e", "-c", guard["run"]], cwd=tmp_path, env=env, capture_output=True)
    assert (result.returncode == 0) is allowed


def test_untrusted_review_gets_no_ssh_or_write_tools(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    workflow = yaml.safe_load(files[tmp_path / ".github/workflows/claude-review.yml"])
    job = workflow["jobs"]["review"]
    assert job["permissions"]["contents"] == "read"
    assert "head.repo.full_name == github.repository" in job["if"]
    assert "CI_AGENT_SSH_KEY" not in str(workflow)
    action = job["steps"][-1]
    args = shlex.split(action["with"]["claude_args"])
    tools = set(args[args.index("--allowedTools") + 1].split(","))
    assert not tools & {"Edit", "Write", "MultiEdit", "Bash", "Bash(git:*)"}


def test_automatic_fix_has_workspace_permission_and_can_render_workflows():
    workflow = yaml.safe_load((renderer.ROOT / "templates/ci/pipeline.yml").read_text())
    step = next(s for s in workflow["jobs"]["review"]["steps"] if s.get("name") == "Fix")
    args = shlex.split(step["with"]["claude_args"])
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    prompt = step["with"]["prompt"]
    assert "Never edit .github/workflows/pipeline.yml" not in prompt
    assert "correct the product, not the pipeline" not in prompt
    assert "preserve every required check" in prompt
    assert "render-ci" in prompt
    assert "canonical" in prompt
    assert "never push main" in prompt


def test_native_skill_default_head_exists_before_model(tmp_path):
    files = renderer.prepare_files(tmp_path, native_review=True)
    for name in ("claude.yml", "claude-review.yml"):
        workflow = yaml.safe_load(files[tmp_path / ".github/workflows" / name])
        job = next(iter(workflow["jobs"].values()))
        steps = job["steps"]
        step_name = "Establish default branch reference"
        reference = next(step for step in steps if step.get("name") == step_name)
        action = next(step for step in steps if "claude-code-action@" in step.get("uses", ""))
        assert steps.index(reference) < steps.index(action)
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "--allow-empty", "-qm", "fixture"], cwd=repo, check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo, check=True)
        env = {**os.environ, "DEFAULT_BRANCH": "main"}
        subprocess.run(["bash", "-e", "-c", reference["run"]], cwd=repo, env=env, check=True)
        target = subprocess.check_output(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo, text=True)
        assert target.strip() == "refs/remotes/origin/main"
        env["DEFAULT_BRANCH"] = "missing"
        assert subprocess.run(["bash", "-e", "-c", reference["run"]], cwd=repo, env=env).returncode != 0

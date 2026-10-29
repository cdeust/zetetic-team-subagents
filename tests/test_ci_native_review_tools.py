"""The native Claude review gets the tools of its procedure, as #211 did for legacy.

Evidence (docs/verification/native-review-tools-fix-guard-20261029.md): the
native review launched its five reviewer agents, but 24 of the 25 measured runs
had 1 to 10 permission denials, Cortex PR834 wrote "I read the code but did not run
the tests: the sandbox does not allow pytest", and the three ci-autonome runs
logged "The github_ci MCP server requires 'actions: read' permission", so the
reviewer could not read the Pipeline test logs of a private repository.
"""

import json
import os
import re
import shlex
import subprocess

import pytest
import yaml

from scripts.lib import render_ci as renderer


@pytest.fixture(scope="module")
def review(tmp_path_factory):
    target = tmp_path_factory.mktemp("native")
    files = renderer.prepare_files(target, native_review=True)
    return yaml.safe_load(files[target / ".github/workflows/claude-review.yml"])["jobs"]["review"]


def step(job, name):
    return next(s for s in job["steps"] if s.get("name") == name)


def allowed_tools(action) -> list[str]:
    arguments = shlex.split(action["with"]["claude_args"])
    return arguments[arguments.index("--allowedTools") + 1].split(",")


def test_the_reviewer_can_read_the_pipeline_logs_of_a_private_repository(review):
    # The pinned action installs its github_ci tools only when the workflow
    # token has actions: read (src/mcp/install-mcp-server.ts, 8041f1d).
    assert review["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "id-token": "write",
        "actions": "read",
    }


def test_the_review_has_the_tools_of_its_procedure_and_none_that_edit(review):
    tools = allowed_tools(step(review, "PR Review"))
    # .claude/commands/review-pr.md: its allowed-tools and its five subagents.
    procedure = {
        "mcp__github_inline_comment__create_inline_comment", "Agent",
        "Bash(gh pr comment:*)", "Bash(gh pr diff:*)", "Bash(gh pr view:*)",
    }
    reading = {"Read", "Glob", "Grep", "LS", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)"}
    pipeline_logs = {
        "mcp__github_ci__get_ci_status",
        "mcp__github_ci__get_workflow_run_details",
        "mcp__github_ci__download_job_log",
    }
    testing = {"Bash(python3 -m pytest:*)", "Bash(python -m pytest:*)", "Bash(pytest:*)", "Bash(cargo test:*)", "Bash(npm test:*)"}
    assert set(tools) == procedure | reading | pipeline_logs | testing
    assert len(tools) == len(set(tools))
    for tool in tools:
        assert tool not in {"Edit", "MultiEdit", "Write", "NotebookEdit", "Bash"}, tool
        if tool.startswith("Bash(") and tool != "Bash(pytest:*)":
            # A Bash rule names a command and its subcommand: no bare git, gh or bash.
            assert len(tool[len("Bash("):-len(":*)")].split()) >= 2, tool


def test_the_review_keeps_its_mode_model_and_mcp_isolation(review):
    arguments = shlex.split(step(review, "PR Review")["with"]["claude_args"])
    assert arguments[:3] == ["--strict-mcp-config", "--permission-mode", "auto"]
    assert arguments[-2:] == ["--model", "claude-opus-5-5"]


def test_the_review_prompt_requires_the_whole_diff_the_tests_and_the_head(review):
    prompt = step(review, "PR Review")["with"]["prompt"]
    first, rest = prompt.split("\n", 1)
    assert first == (
        "/review-pr REPO: ${{ github.repository }} "
        "PR_NUMBER: ${{ github.event.pull_request.number }}"
    )
    for required in (
        "${{ github.event.pull_request.head.sha }}",
        "no reason to stop",
        "read the whole diff (gh pr diff)",
        "read every changed file in full and the tests that cover it",
        "the Pipeline run of this head",
        "mcp__github_ci__get_ci_status",
        "download_job_log",
        "if that run has not finished, say so",
        "run the tests that cover the changed code",
        "only when every step ran",
        "names that step and why",
        "Complete all five reviews using foreground agents",
    ):
        assert required in rest, required


def test_the_reviewer_gets_the_hashed_dev_dependencies_when_the_repository_declares_them(review):
    names = [s.get("name") for s in review["steps"]]
    install = step(review, "Install the test dependencies for the review")
    assert names.index("Install subprocess isolation") < names.index(install["name"])
    assert names.index(install["name"]) < names.index("PR Review")
    assert install["if"] == "hashFiles('requirements-dev.lock') != ''"
    assert "--require-hashes -r requirements-dev.lock" in install["run"]
    assert '>> "$GITHUB_PATH"' in install["run"]


def run_failure_namer(review, tmp_path, execution_file: str):
    namer = step(review, "Name the review failure")
    assert namer["if"] == "failure() && steps.claude_review.outcome == 'failure'"
    assert namer["env"]["EXECUTION_FILE"] == "${{ steps.claude_review.outputs.execution_file }}"
    script = tmp_path / "namer.sh"
    script.write_text(namer["run"])
    env = {"PATH": os.environ["PATH"], "EXECUTION_FILE": execution_file}
    return subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, text=True)


def test_a_failed_review_names_its_error_class_and_not_its_text(review, tmp_path):
    action = step(review, "PR Review")
    assert action["id"] == "claude_review"
    assert action["with"]["show_full_output"] is False
    assert [s.get("name") for s in review["steps"]][-1] == "Name the review failure"
    execution = tmp_path / "claude-execution-output.json"
    execution.write_text(json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 401,
         "terminal_reason": "api_error", "stop_reason": None, "num_turns": 1,
         "result": "quoted code under review"},
    ]))
    done = run_failure_namer(review, tmp_path, str(execution))
    assert done.returncode == 1
    assert done.stdout.strip() == (
        "::error::Review result: subtype=success is_error=true api_error_status=401 "
        "terminal_reason=api_error stop_reason=null num_turns=1"
    )
    assert "quoted code" not in done.stdout + done.stderr


def test_a_review_that_failed_before_any_result_says_so(review, tmp_path):
    for missing in ("", str(tmp_path / "absent.json")):
        done = run_failure_namer(review, tmp_path, missing)
        assert done.returncode == 1
        assert "no execution file" in done.stdout


def test_the_failure_namer_matches_the_legacy_one(review):
    legacy = yaml.safe_load(renderer.artifacts()["pipeline.yml"])
    original = step(legacy["jobs"]["review"], "Name the review failure")
    assert re.sub(r"\s+", " ", step(review, "Name the review failure")["run"]) == re.sub(
        r"\s+", " ", original["run"]
    )

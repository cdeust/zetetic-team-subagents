"""The single CI template (templates/ci/pipeline.yml): the shape the design
fixes and the invariants a hand edit would break silently. Design:
docs/superpowers/specs/2026-10-22-single-ci-design.md, "ci.yml, generated from
one template" and decisions 1 to 9."""
from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

from scripts.lib.render_ci import workflow as render_workflow

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "templates" / "ci" / "pipeline.yml"
DESIGN = "docs/superpowers/specs/2026-10-22-single-ci-design.md"
JOBS = ["resolve", "contract", "unit", "regression", "e2e", "environment", "install", "review", "merge", "tag"]
PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "6d4fd22b20465ccc0f7354476588e8df7c9ca0e0",
    "anthropics/claude-code-action": "8041f1d17e0e7d2f2cfe35002962e9f26237c0bb",
}
# source: claude-mods PR45, unit job119805310369 passed with Claude 2.1.306.
CLI_PIN = "npm install -g @anthropic-ai/claude-code@2.1.306"


@pytest.fixture(scope="module")
def text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(text):
    return yaml.safe_load(text)


def heredoc(text: str, opener: str) -> str:
    """The body of the ``<<'PY'`` heredoc whose opening line contains
    ``opener``, dedented: what ``python3 -`` executes."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if opener in line and line.rstrip().endswith("<<'PY'"))
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start + 1:]:
        if line.strip() == "PY" and len(line) - len(line.lstrip()) == indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


def test_the_workflow_is_named_pipeline_and_runs_on_pull_requests_and_main(workflow):
    assert workflow["name"] == "Pipeline"
    on = workflow[True] if True in workflow else workflow["on"]
    assert on["pull_request"]["types"] == ["opened", "synchronize", "reopened", "ready_for_review"]
    assert on["push"]["branches"] == ["main"]


def test_the_jobs_include_protected_resolution_before_the_test_categories(workflow):
    assert list(workflow["jobs"]) == JOBS


def test_the_jobs_chain_in_dependency_order(workflow):
    jobs = workflow["jobs"]
    assert jobs["unit"]["needs"] == "contract"
    chain = ["unit", "regression", "e2e", "environment", "install"]
    for previous, job in zip(chain, chain[1:]):
        assert jobs[job]["needs"] == ["contract", previous], job
    assert jobs["review"]["needs"] == chain
    assert sorted(jobs["merge"]["needs"]) == sorted(["contract", "unit", "regression", "e2e", "environment", "install"])
    assert jobs["tag"]["needs"] == ["contract", *chain]


def test_the_contract_step_is_the_validator_byte_for_byte(text):
    assert heredoc(text, "python3 - \"$GITHUB_WORKSPACE\"") == (REPO / "tools" / "ci_contract.py").read_text(encoding="utf-8")


def test_the_coverage_step_is_the_reader_byte_for_byte(text):
    assert heredoc(text, "python3 - coverage.xml --min 90") == (REPO / "tools" / "ci_coverage.py").read_text(encoding="utf-8")


def test_every_action_is_pinned_by_commit_sha(text):
    uses = re.findall(r"^\s*(?:- )?uses:\s*(\S+)", text, re.M)
    assert uses, "no uses: lines"
    for ref in uses:
        action, _, sha = ref.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", sha), ref
        assert PINS.get(action, sha) == sha, ref
    assert uses.count(f"anthropics/claude-code-action@{PINS['anthropics/claude-code-action']}") == 2


def test_the_cli_is_installed_at_the_pinned_version_on_both_matrices(workflow, text):
    assert text.count(CLI_PIN) == 2
    for job in ("environment", "install"):
        assert workflow["jobs"][job]["strategy"]["matrix"]["os"] == ["ubuntu-latest", "macos-latest", "windows-latest"]
        assert workflow["jobs"][job]["runs-on"] == "${{ matrix.os }}"


def test_the_review_is_the_documented_code_review_invocation(workflow):
    steps = workflow["jobs"]["review"]["steps"]
    review = next(s for s in steps if s.get("with", {}).get("plugins") == "code-review@claude-code-plugins")
    assert review["with"]["plugin_marketplaces"] == "https://github.com/anthropics/claude-code.git"
    assert review["with"]["prompt"].startswith("/code-review:code-review --comment ")
    assert review["with"]["allowed_bots"] == "claude[bot],chatgpt-codex-connector[bot]"


def review_step(workflow, name):
    return next(s for s in workflow["jobs"]["review"]["steps"] if s.get("name") == name)


def allowed_tools(step) -> list[str]:
    match = re.fullmatch(r'--allowedTools "([^"]+)"', step["with"]["claude_args"].strip())
    assert match, step["with"]["claude_args"]
    return match.group(1).split(",")


def test_the_review_has_the_tools_its_procedure_uses_and_none_that_edit(workflow):
    # PR #207: with the inline-comment tool alone the review ran 3 turns in 9 s,
    # launched none of the skill's subagents, read no CLAUDE.md and still posted
    # "No issues found" (reproduced: docs/verification/review-bot-tools-20261029.md).
    tools = allowed_tools(review_step(workflow, "Review"))
    # The plugin's commands/code-review.md: its allowed-tools, its subagents (Task).
    procedure = {
        "mcp__github_inline_comment__create_inline_comment", "Task",
        "Bash(gh pr diff:*)", "Bash(gh pr view:*)", "Bash(gh pr comment:*)", "Bash(gh pr list:*)",
        "Bash(gh issue view:*)", "Bash(gh issue list:*)", "Bash(gh search:*)",
    }
    reading = {"Read", "Glob", "Grep", "LS", "Bash(gh run view:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)"}
    testing = {"Bash(python3 -m pytest:*)", "Bash(python -m pytest:*)", "Bash(pytest:*)", "Bash(cargo test:*)", "Bash(npm test:*)"}
    assert set(tools) == procedure | reading | testing
    assert len(tools) == len(set(tools))
    for tool in tools:
        assert tool not in {"Edit", "MultiEdit", "Write", "NotebookEdit", "Bash"}, tool
        if tool.startswith("Bash(") and tool != "Bash(pytest:*)":
            # A Bash rule names a command and its subcommand: no bare git, gh or bash.
            assert len(tool[len("Bash("):-len(":*)")].split()) >= 2, tool


def test_the_review_prompt_requires_the_whole_diff_the_tests_and_the_head(workflow):
    prompt = review_step(workflow, "Review")["with"]["prompt"]
    first, rest = prompt.split("\n", 1)
    assert first == (
        "/code-review:code-review --comment "
        "${{ github.repository }}/pull/${{ github.event.pull_request.number }}"
    )
    for required in (
        "${{ github.event.pull_request.head.sha }}",
        "no reason to stop",
        "read the whole diff (gh pr diff)",
        "read every changed file in full and the tests that cover it",
        "gh run view ${{ github.run_id }} --log",
        "run the tests that cover the changed code",
        "Launch the subagents the procedure names",
        "only when every step ran",
        "names that step and why",
    ):
        assert required in rest, required


def test_the_reviewer_gets_the_hashed_dev_dependencies_when_the_repository_declares_them(workflow):
    names = [s.get("name") for s in workflow["jobs"]["review"]["steps"]]
    install = review_step(workflow, "Install the test dependencies for the review")
    assert names.index(install["name"]) < names.index("Review")
    assert install["if"] == "steps.guard.outputs.review == 'true' && hashFiles('requirements-dev.lock') != ''"
    assert "--require-hashes -r requirements-dev.lock" in install["run"]
    assert '>> "$GITHUB_PATH"' in install["run"]


def run_failure_namer(workflow, tmp_path, execution_file: str):
    step = review_step(workflow, "Name the review failure")
    assert step["if"] == "failure() && steps.claude_review.outcome == 'failure'"
    assert step["env"]["EXECUTION_FILE"] == "${{ steps.claude_review.outputs.execution_file }}"
    script = tmp_path / "namer.sh"
    script.write_text(step["run"])
    env = {"PATH": os.environ["PATH"], "EXECUTION_FILE": execution_file}
    return subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, text=True)


def test_a_failed_review_names_its_error_class_and_not_its_text(workflow, tmp_path):
    # Runs 40186210241 (#191) and 40201492297 (#192): is_error:true in 434 ms,
    # cost 0, and no error class anywhere in the log (show_full_output: false).
    review = review_step(workflow, "Review")
    assert review["id"] == "claude_review"
    assert review["with"]["show_full_output"] is False
    execution = tmp_path / "claude-execution-output.json"
    execution.write_text(json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 401,
         "terminal_reason": "api_error", "stop_reason": None, "num_turns": 1,
         "result": "quoted code under review"},
    ]))
    done = run_failure_namer(workflow, tmp_path, str(execution))
    assert done.returncode == 1
    assert done.stdout.strip() == (
        "::error::Review result: subtype=success is_error=true api_error_status=401 "
        "terminal_reason=api_error stop_reason=null num_turns=1"
    )
    assert "quoted code" not in done.stdout + done.stderr


def test_a_review_that_failed_before_any_result_says_so(workflow, tmp_path):
    for missing in ("", str(tmp_path / "absent.json")):
        done = run_failure_namer(workflow, tmp_path, missing)
        assert done.returncode == 1
        assert "no execution file" in done.stdout


def test_the_review_skips_drafts_forks_dependabot_and_duplicate_bot_review(workflow, text):
    cond = workflow["jobs"]["review"]["if"]
    for clause in ("github.event_name == 'pull_request'", "!github.event.pull_request.draft",
                   "github.event.pull_request.head.repo.full_name == github.repository",
                   "github.actor != 'dependabot[bot]'"):
        assert clause in cond, clause
    assert "+claude[bot]@users.noreply.github.com" in text
    assert ".github/workflows/pipeline.yml" in text


def test_the_fix_pushes_with_the_claude_app_token_so_the_pipeline_runs_on_it(workflow, text):
    # PR #171, commit ae628d6 (2026-10-29): the Fix push went out as
    # github-actions[bot] and its pull_request runs stayed action_required.
    # A GITHUB_TOKEN push creates runs that wait for approval; an App token
    # push runs them (docs.github.com, "Triggering a workflow from a workflow").
    # checkout v7 keeps GITHUB_TOKEN in an includeIf file that the action does
    # not clear (run 40820034691: "No existing authentication headers to
    # remove"), so the checkout must not persist it.
    rendered = yaml.safe_load((REPO / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8"))
    for source in (workflow, rendered):
        steps = source["jobs"]["review"]["steps"]
        checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
        assert checkout["with"].get("persist-credentials") is False
        fix = next(s for s in steps if s.get("name") == "Fix")
        assert "github_token" not in fix["with"], "the Fix push keeps the action's App token"
    assert "Its push is a synchronize event; the five tests run again on it." not in text


def test_the_merge_checks_failed_jobs_unless_the_run_is_cancelled(workflow):
    # claude-mods #38 and session-optimizer #73 (2026-10-22) auto-merged on a
    # red pipeline: a skipped required check is satisfied, so the job's if:
    # carries no needs.* result and the first step fails explicitly.
    job = workflow["jobs"]["merge"]
    cond = job["if"]
    assert cond.startswith("always() && !cancelled() && ")
    assert "needs." not in cond
    for clause in ("github.event_name == 'pull_request'", "!github.event.pull_request.draft",
                   "github.event.pull_request.head.repo.full_name == github.repository"):
        assert clause in cond, clause
    steps = job["steps"]
    assert not any(s.get("uses", "").startswith("actions/checkout") for s in steps), "merge checks out nothing"
    gate = steps[0]
    for name in ("unit", "regression", "e2e", "environment", "install"):
        assert f"${{{{ needs.{name}.result }}}}" in gate["env"].values(), name
    assert "exit 1" in gate["run"]
    assert len(steps) == 1 and "gh " not in gate["run"] and "headRefOid" not in gate["run"]


def test_the_tag_runs_on_push_or_resolved_merge_over_the_deploy_key(workflow):
    job = workflow["jobs"]["tag"]
    assert "((github.event_name == 'push' && github.ref == 'refs/heads/main') || github.event_name == 'workflow_run')" in job["if"]
    assert "!cancelled()" in job["if"]
    assert job["concurrency"] == {"group": "release-tag-${{ needs.contract.outputs.release_group }}", "cancel-in-progress": False}
    checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["ssh-key"] == "${{ secrets.RELEASE_TAG_SSH_KEY }}"
    publish = next(s for s in job["steps"] if s.get("name") == "Publish declared package tags")
    assert publish["env"]["RELEASE_TAGS"] == "${{ needs.contract.outputs.release_tags }}"
    assert heredoc(publish["run"], "python3 -") == (REPO / "tools/ci_tag.py").read_text()


def test_comment_blocks_are_short_and_cite_the_design(text):
    blocks, current = [], []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    long = [b[0] for b in blocks if len(b) >= 10]
    assert not long, f"comment blocks of 10 lines or more: {long}"
    assert any(DESIGN in line for b in blocks for line in b)


def test_this_repository_runs_the_rendered_template(text):
    # What `scripts/setup.sh render-ci .` writes: the fixed header line (no hash,
    # owner rule 2026-10-29), then the template byte for byte (plan task 1.5).
    rendered = (REPO / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    header, _, body = rendered.partition("\n")
    assert header == "# generated by zetetic-team-subagents render-ci"
    assert body == render_workflow(text, False)

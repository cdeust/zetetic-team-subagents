"""The single CI template (templates/ci/pipeline.yml): the shape the design
fixes and the invariants a hand edit would break silently. Design:
docs/superpowers/specs/2026-10-22-single-ci-design.md, "ci.yml, generated from
one template" and decisions 1 to 9."""
from __future__ import annotations

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
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "anthropics/claude-code-action": "a5a423f75c251dcbff8a74e99f83b2cb03c72bfa",
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
    assert sorted(jobs["merge"]["needs"]) == sorted(["contract", "unit", "regression", "e2e", "environment", "install", "review"])
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
    assert review["with"]["claude_args"] == '--allowedTools "mcp__github_inline_comment__create_inline_comment"'
    assert review["with"]["allowed_bots"] == "claude[bot],chatgpt-codex-connector[bot]"


def test_the_review_skips_drafts_forks_dependabot_and_duplicate_bot_review(workflow, text):
    cond = workflow["jobs"]["review"]["if"]
    for clause in ("github.event_name == 'pull_request'", "!github.event.pull_request.draft",
                   "github.event.pull_request.head.repo.full_name == github.repository",
                   "github.actor != 'dependabot[bot]'"):
        assert clause in cond, clause
    assert "+claude[bot]@users.noreply.github.com" in text
    assert ".github/workflows/pipeline.yml" in text


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
    for name in ("unit", "regression", "e2e", "environment", "install", "review"):
        assert f"${{{{ needs.{name}.result }}}}" in gate["env"].values(), name
    assert "exit 1" in gate["run"]
    assert "gh pr merge" not in steps[-1]["run"]
    assert "headRefOid" in steps[-1]["run"]


def test_the_merge_names_the_repository_for_gh_without_a_checkout(workflow):
    # session-optimizer #65, run 39756969927 (2026-10-22): every stage green,
    # merge failed with "fatal: not a git repository" because gh pr merge
    # inferred the repository from a checkout the job does not have.
    steps = workflow["jobs"]["merge"]["steps"]
    arm = next(s for s in steps if s.get("name") == "Verify live PR eligibility")
    assert arm["env"].get("GH_REPO") == "${{ github.repository }}"
    assert arm["env"]["GH_TOKEN"] == "${{ github.token }}"


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
    # What `scripts/setup.sh render-ci .` writes: the header line with the
    # template's blob id, then the template byte for byte (plan task 1.5).
    rendered = (REPO / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    header, _, body = rendered.partition("\n")
    blob = subprocess.check_output(["git", "hash-object", str(TEMPLATE)], cwd=REPO, text=True).strip()
    assert header == f"# generated by zetetic-team-subagents render-ci {blob}"
    assert body == render_workflow(text, False)

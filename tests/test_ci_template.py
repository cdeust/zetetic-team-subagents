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
JOBS = ["resolve", "close-issues", "contract", "unit", "regression", "e2e", "environment", "install", "merge", "tag"]
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
    # The review is claude-review.yml's: the Pipeline never runs the Claude action.
    assert not any(ref.startswith("anthropics/claude-code-action@") for ref in uses)


def test_the_cli_is_installed_at_the_pinned_version_on_both_matrices(workflow, text):
    assert text.count(CLI_PIN) == 2
    for job in ("environment", "install"):
        assert workflow["jobs"][job]["strategy"]["matrix"]["os"] == ["ubuntu-latest", "macos-latest", "windows-latest"]
        assert workflow["jobs"][job]["runs-on"] == "${{ matrix.os }}"


def test_the_pipeline_holds_no_review_and_no_fix(workflow, text):
    # Cortex ADR-1121: the review is the PR Review workflow (claude-review.yml) and
    # the resolver merges on its verdict, so no job here reviews, fixes or pushes.
    assert "review" not in workflow["jobs"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in text
    assert "id-token: write" not in text


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
    assert "gh " not in gate["run"] and "headRefOid" not in gate["run"]
    # The aggregate merges nothing and arms nothing: GitHub auto-merge would merge
    # on green tests alone, before the Claude verdict the resolver waits for.
    assert len(steps) == 1 and job["permissions"] == {"contents": "read"}


def test_the_tag_runs_on_push_or_resolved_merge_over_the_deploy_key(workflow):
    job = workflow["jobs"]["tag"]
    assert "((github.event_name == 'push' && github.ref == 'refs/heads/main') || github.event_name == 'workflow_run')" in job["if"]
    assert "!cancelled()" in job["if"]
    assert job["concurrency"] == {"group": "release-tag-${{ needs.contract.outputs.release_group }}", "cancel-in-progress": False}
    # CodeQL actions/untrusted-checkout: the job holds the deploy key, so it
    # checks nothing out; the tested commit is fetched by SHA into a bare repo.
    assert not any(s.get("uses", "").startswith("actions/checkout") for s in job["steps"])
    fetch = next(s for s in job["steps"] if s.get("name") == "Fetch the tested commit into a bare repository")
    assert fetch["env"]["SSH_KEY"] == "${{ secrets.RELEASE_TAG_SSH_KEY }}"
    assert "git init --quiet --bare" in fetch["run"]
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

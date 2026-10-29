"""The legacy Fix step runs only for a named cause, never on a green run without one.

Owner rule (2026-10-29): the Claude and Codex reviews must lead to changes, so
Fix applies review findings as well as test failures. Run 40862677865 had every
test green and pushed e1dcc25 for an open Codex P2 on PR #223, with no cause
named anywhere. Causes: test_failure (a test job of this run failed) and
review_findings (the Codex summary reports unresolved findings for this head,
the Claude verdict marker of #221 says merge:false for this head, or a review
thread opened by Claude or Codex is unresolved and not outdated).
"""

import json
import re

import pytest

from test_ci_pr_safety import TESTS, execute, guard, results, step, workflow  # noqa: F401

HEAD = "a" * 40
OTHER = "b" * 40
CAUSE_STEP = "Name the causes for Fix"
FIX_CONDITION = "success() && !cancelled() && steps.cause.outputs.cause != ''"
GH_FIXTURE = r"""
gh() {
  case "$1 $2" in
    'api graphql') cat "$FIXTURE_THREADS"; return "${FIXTURE_GH_RC:-0}" ;;
    'api repos/'*) cat "$FIXTURE_COMMENTS"; return "${FIXTURE_GH_RC:-0}" ;;
    *) return 91 ;;
  esac
}
"""


def codex_summary(sha=HEAD, unresolved=True):
    # Shape of PR #223 comment 6494587147 (chatgpt-codex-connector[bot]).
    state = {
        "code_review": {"commit_sha": sha, "has_any_findings": unresolved,
                        "has_unresolved_findings": unresolved, "status": "completed"},
        "security_review": {"commit_sha": sha, "has_any_findings": None,
                            "has_unresolved_findings": None, "status": "completed"},
    }
    body = ("<!-- codex-pull-request-review-summary -->\n"
            f"<!-- codex-review-state:v1 {json.dumps(state, separators=(',', ':'))} -->\n")
    return {"user": {"login": "chatgpt-codex-connector[bot]", "type": "Bot"}, "body": body}


def claude_verdict(sha=HEAD, merge=False):
    marker = json.dumps({"head": sha, "merge": merge}, separators=(",", ":"))
    body = f"Review of the head.\n<!-- claude-review-verdict:v1 {marker} -->"
    return {"user": {"login": "claude[bot]", "type": "Bot"}, "body": body}


def thread(login="chatgpt-codex-connector", kind="Bot", resolved=False, outdated=False):
    author = {"__typename": kind, "login": login}
    return {"isResolved": resolved, "isOutdated": outdated,
            "comments": {"nodes": [{"author": author}]}}


def name_causes(workflow, tmp_path, comments=(), threads=(), **env):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "comments.json").write_text(json.dumps([list(comments)]))
    graph = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": list(threads)}}}}}
    (tmp_path / "threads.json").write_text(json.dumps(graph))
    values = {"FIXTURE_COMMENTS": str(tmp_path / "comments.json"),
              "FIXTURE_THREADS": str(tmp_path / "threads.json"),
              "GITHUB_REPOSITORY": "o/r", "PR": "42", "HEAD_SHA": HEAD,
              "TEST_FAILURE": "false", "CLAUDE_HEAD": "false", **env}
    script = step(workflow, "review", CAUSE_STEP)["run"]
    result = execute(script, tmp_path, values, GH_FIXTURE)
    output = tmp_path / "output"
    text = output.read_text() if output.exists() else ""
    return result, dict(line.split("=", 1) for line in text.splitlines())


def fix_runs(workflow, cause, *, cancelled=False, earlier_step_failed=False):
    """Evaluate the Fix step's conjunction; hosted execution remains required.

    success() is false once the run is cancelled or an earlier step failed
    (docs.github.com, "Expressions", status check functions)."""
    expression = step(workflow, "review", "Fix")["if"]
    assert expression == FIX_CONDITION
    expression = expression.replace(
        "success()", repr(not cancelled and not earlier_step_failed)
    ).replace("!cancelled()", repr(not cancelled))
    expression = expression.replace("steps.cause.outputs.cause", repr(cause))
    expression = expression.replace("&&", " and ")
    assert re.fullmatch(r"[\s()'a-zA-Z_=!,]+", expression)
    return eval(expression, {"__builtins__": {}}, {})


def test_the_cause_step_runs_after_review_for_every_repairable_head(workflow):
    names = [s.get("name") for s in workflow["jobs"]["review"]["steps"]]
    assert names.index("Review") < names.index(CAUSE_STEP) < names.index("Fix")
    assert step(workflow, "review", CAUSE_STEP)["if"] == "steps.guard.outputs.repair == 'true'"


def test_green_run_with_an_open_codex_finding_runs_fix(workflow, tmp_path):
    # The e1dcc25 case: every test green, an unresolved Codex finding on the head.
    result, values = name_causes(workflow, tmp_path, [codex_summary()])
    assert result.returncode == 0, result.stderr
    assert values == {"cause": "review_findings"}
    assert fix_runs(workflow, values["cause"])
    assert "Fix cause: review_findings" in (tmp_path / "summary").read_text()


def test_green_run_without_a_finding_skips_fix(workflow, tmp_path):
    result, values = name_causes(
        workflow, tmp_path, [codex_summary(unresolved=False), claude_verdict(merge=True)],
        [thread(resolved=True), thread(outdated=True), thread("person", "User")],
    )
    assert result.returncode == 0, result.stderr
    assert values == {"cause": ""}
    assert not fix_runs(workflow, values["cause"])
    assert "Fix cause: none" in (tmp_path / "summary").read_text()


def test_cancelled_run_with_a_finding_skips_fix(workflow, tmp_path):
    _, values = name_causes(workflow, tmp_path, [codex_summary()], TEST_FAILURE="true")
    assert values == {"cause": "test_failure,review_findings"}
    assert not fix_runs(workflow, values["cause"], cancelled=True)


def test_a_failed_earlier_step_skips_fix(workflow, tmp_path):
    _, values = name_causes(workflow, tmp_path, TEST_FAILURE="true")
    assert not fix_runs(workflow, values["cause"], earlier_step_failed=True)


@pytest.mark.parametrize("failed", TESTS)
def test_a_failed_test_job_is_named_and_runs_fix(workflow, tmp_path, failed):
    result, guarded = guard(workflow, tmp_path, TEST_RESULTS=results(**{failed: "failure"}))
    assert result.returncode == 0, result.stderr
    _, values = name_causes(workflow, tmp_path / "cause", TEST_FAILURE=guarded["test_failure"])
    assert values == {"cause": "test_failure"}
    assert fix_runs(workflow, values["cause"])


@pytest.mark.parametrize(
    "comment",
    [codex_summary(sha=OTHER), claude_verdict(sha=OTHER), claude_verdict(merge=True),
     {**codex_summary(), "user": {"login": "someone", "type": "User"}},
     {**claude_verdict(), "user": {"login": "someone", "type": "User"}}],
    ids=["codex-other-head", "claude-other-head", "claude-merge-true",
         "codex-shape-from-a-user", "claude-shape-from-a-user"],
)
def test_a_verdict_counts_only_from_its_bot_for_this_head(workflow, tmp_path, comment):
    _, values = name_causes(workflow, tmp_path, [comment])
    assert values == {"cause": ""}


def test_a_claude_merge_false_verdict_for_the_head_runs_fix(workflow, tmp_path):
    _, values = name_causes(workflow, tmp_path, [claude_verdict()])
    assert values == {"cause": "review_findings"}


@pytest.mark.parametrize("login", ["claude", "chatgpt-codex-connector"])
def test_an_open_bot_thread_runs_fix_on_a_human_head(workflow, tmp_path, login):
    _, values = name_causes(workflow, tmp_path, threads=[thread(login)])
    assert values == {"cause": "review_findings"}


def test_an_open_thread_alone_cannot_rerun_fix_on_its_own_push(workflow, tmp_path):
    # A Fix push is a Claude head; threads are not tied to a head (loop guard).
    _, values = name_causes(workflow, tmp_path, threads=[thread()], CLAUDE_HEAD="true")
    assert values == {"cause": ""}
    _, values = name_causes(workflow, tmp_path / "h", [codex_summary()], CLAUDE_HEAD="true")
    assert values == {"cause": "review_findings"}


def test_an_unreadable_review_state_fails_closed(workflow, tmp_path):
    result, values = name_causes(workflow, tmp_path, [codex_summary()], FIXTURE_GH_RC="1")
    assert result.returncode != 0
    assert values == {}


def test_fix_skips_a_non_owner_workflow_change(workflow, tmp_path):
    result, values = guard(workflow, tmp_path, changed=".github/workflows/pipeline.yml",
                           TEST_RESULTS=results(unit="failure"))
    assert result.returncode == 0, result.stderr
    # repair=false skips the cause step, so its output stays empty.
    assert values["repair"] == "false"
    assert not fix_runs(workflow, "")


def test_the_fix_prompt_names_its_causes(workflow):
    prompt = step(workflow, "review", "Fix")["with"]["prompt"]
    assert "Causes: ${{ steps.cause.outputs.cause }}." in prompt
    collect = step(workflow, "review", "Collect the failed jobs of this run")
    assert collect["if"] == (
        "steps.guard.outputs.test_failure == 'true' && steps.guard.outputs.repair == 'true'"
    )

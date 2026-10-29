"""A review hold is lifted only when Codex and Claude both conclude to merge.

Owner rule, 2026-10-29 (verbatim): "until the review of codex and claude (done
autonomously) are there, it cannot merge, the hold should be removed after
reviewers agree on merging". `hold` and `autopilot:hold` mean "reviews
incomplete"; `do-not-merge` and a "do not merge" title stay the owner's holds.
These are the rules of the Cortex convergence planner (cdeust/Cortex PR834,
scripts/ci_autopilot_converge_plan.py REVIEW_HOLDS, OWNER_HOLDS, _claude),
carried into the native template.

State table: one row per test below. Codex code, Codex security (flags or a
native receipt), the Claude marker for the head, then labels and title.

| Codex code | Codex security       | Claude          | reader (state, reason)                    |
|------------|----------------------|-----------------|-------------------------------------------|
| clean      | clean                | merge           | success, reviews_complete                 |
| clean      | null + receipt       | merge           | success, reviews_complete                 |
| clean      | clean                | merge, self-edit| success, reviews_complete                 |
| clean      | clean                | none            | pending, claude_verdict_missing           |
| clean      | clean                | other head      | pending, claude_verdict_missing           |
| clean      | clean                | two markers     | pending, claude_verdict_missing           |
| clean      | clean                | posted by human | pending, claude_verdict_missing           |
| clean      | clean                | human-edited    | blocked, claude_verdict_unreadable        |
| clean      | clean                | merge:false     | blocked, claude_refused                   |
| clean      | null, no receipt     | merge           | blocked, codex_security_verdict_missing   |
| clean      | running              | merge           | pending, review_pending                   |
| clean      | running              | none            | pending, review_pending (both named)      |
| no summary | no summary           | merge           | pending, review_missing                   |
| findings   | clean                | merge           | blocked, review_unresolved                |
| clean      | clean                | Dependabot PR   | success, reviews_complete (D5)            |
| findings   | clean                | Dependabot PR   | blocked, review_unresolved (D5)           |
| clean      | clean                | Dependabot, false | blocked, claude_refused (D5)            |

| failed + usage-limit notice last | any | merge | pending, codex_quota_exhausted (D6) |
| failed, notice older than summary | any  | merge | blocked, review_failed (D6)         |

D6 (coordinator, 2026-10-29): a failed Codex kind whose latest Codex Bot comment
is a usage-limit notice waits for quota (pending, `codex_quota_exhausted`), never
`review_failed`. Real notices: tests/fixtures/codex_quota/comments-20261029.json.

D5 (coordinator, 2026-10-29): the Claude review skips Dependabot PRs by design
(PR #224, no Actions secrets). On a PR whose GraphQL author is dependabot/Bot and
whose branch is dependabot/*, an absent marker reads `not_applicable_dependabot`
and counts as agreement; Codex and the tests decide. Any other PR needs the marker.

| reader state | labels / title              | merge job              | resolve                         |
|--------------|-----------------------------|------------------------|---------------------------------|
| success      | hold, autopilot:hold        | merge, green           | DELETE both, GET, PUT (merged)  |
| pending      | hold                        | merge pending review   | nothing: hold kept, cause named |
| success      | do-not-merge (+ hold)       | red, held by label     | refused before any DELETE       |
| success      | "do not merge" title + hold | red, held by title     | refused before any DELETE       |
| success      | hold re-added after DELETE  | merge, green           | refused before PUT              |

Claude identity: GraphQL author `claude`/Bot, id BOT_kgDODIGtWg, of
cdeust/claude-mods PR51 comment 6494419619 (REST user claude[bot], comment
6491944909), read on 2026-10-29.
"""

import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import unquote

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "templates/ci/native"
SCRIPTS = NATIVE / "assets/scripts"
SHA = "a" * 40
OLD = "b" * 40
REPO, PR = "owner/project", 464  # source: fixture identity of test_ci_native_editor.py.
CODEX_ID = "BOT_kgDOC98s_g"
CLAUDE_ID = "BOT_kgDODIGtWg"
CLEAN = dict(has_any_findings=False, has_unresolved_findings=False)


def claude_row(sha, merge=True, **fields):
    """The native Claude review's final comment, ending with its verdict marker.

    fields: identity, stamp, body, editor, edited, login, kind.
    """
    marker = json.dumps({"head": sha, "merge": merge}, separators=(",", ":"))
    body = "I found no correctness or security problems.\n\n"
    body += "<!-- claude-review-verdict:v1 " + marker + " -->\n"
    return dict(
        id=fields.get("identity", 900001),
        updated_at=fields.get("stamp", "2026-10-29T08:10:00Z"),
        body=fields.get("body", body),
        editor=fields.get("editor"),
        lastEditedAt=fields.get("edited"),
        user=dict(
            login=fields.get("login", "claude[bot]"),
            type=fields.get("kind", "Bot"),
            node_id=CLAUDE_ID,
        ),
    )


def codex_row(code=None, security=None, identity=1, body_suffix=""):
    review = dict(commit_sha=SHA, status="completed", **CLEAN)
    state = dict(code_review=code or review, security_review=security or review)
    body = "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "
    body += json.dumps(state) + " -->" + body_suffix
    user = dict(login="chatgpt-codex-connector[bot]", type="Bot", node_id=CODEX_ID)
    return dict(id=identity, updated_at="2026-10-29T08:05:22Z", body=body,
                editor=None, lastEditedAt=None, user=user)


def reader():
    for name in ("ci_codex_review_comments", "ci_codex_review_runtime", "ci_codex_review_agreement"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("hold_lift_reader", SCRIPTS / "ci_codex_reviews.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(rows, dependabot=False):
    module = reader()
    rows = sys.modules["ci_codex_review_comments"].Comments(rows)
    rows.dependabot = dependabot
    # The repository's commits API resolves a receipt's prefix to the head (#227).
    commits = {f"repos/{REPO}/commits/{SHA[:10]}": {"sha": SHA}}
    with patch.object(sys.modules["ci_codex_review_runtime"], "_api", side_effect=commits.__getitem__):
        return module.review_evidence(rows, SHA, REPO, PR)


def null_security():
    return dict(commit_sha=SHA, status="completed", has_any_findings=None,
                has_unresolved_findings=None)


def receipt_rows():
    metadata = dict(headSha=SHA, pullRequestNumber=PR, repository=REPO, status="completed")
    suffix = "\n<!-- codex-security-review:v1 " + json.dumps(metadata) + " -->"
    receipt = codex_row(identity=9)
    # The exact native receipt form (#225, cortex-viz PR213 receipt6491350304).
    receipt["body"] = (
        "<!-- codex-review-receipt:v1 -->\n\n### \U0001f6e1\ufe0f Codex Security Review\n\n"
        "Security review completed. No security issues were found in this pull request.\n\n"
        "**Reviewed commit:** `" + SHA[:10] + "`\n\n"
        "[View security finding report](https://chatgpt.com/codex/cloud/tasks/task_e_0a1b)\n\n"
        "_Only the user who started this review can view the report in Codex._\n\n"
        "<details> <summary>\u2139\ufe0f About Codex security reviews in GitHub</summary>\n<br/>\n\n"
        "This is an experimental Codex feature. Security reviews are triggered when:\n"
        '- You comment "@codex security review"\n'
        '- A regular code review gets triggered (for example, "@codex review" or when a'
        " PR is opened), and you\u2019re opted in so security review runs alongside code review\n\n"
        "Once complete, Codex will leave suggestions, or a comment if no findings are found.\n\n\n"
        "</details>"
    )
    return [codex_row(security=null_security(), body_suffix=suffix), receipt]


HUMAN = dict(login="writer", __typename="User", id="U_writer")
SELF = dict(login="claude", __typename="Bot", id=CLAUDE_ID)
RUNNING = dict(commit_sha=SHA, status="running", has_any_findings=None,
               has_unresolved_findings=None)
FINDINGS = dict(commit_sha=SHA, status="completed", has_any_findings=True,
                has_unresolved_findings=True)
TWO = claude_row(SHA)["body"] * 2
TABLE = {
    "both_agree": ([codex_row(), claude_row(SHA)], "success", "reviews_complete", True, []),
    "receipt_and_claude": (
        [*receipt_rows(), claude_row(SHA)], "success", "reviews_complete", True, []),
    # The production path: comment6494419619 was last edited by claude/Bot itself.
    "claude_self_edited": (
        [codex_row(), claude_row(SHA, editor=SELF, edited="2026-10-29T08:11:00Z")],
        "success", "reviews_complete", True, []),
    "claude_missing": ([codex_row()], "pending", "claude_verdict_missing", False,
                       ["claude_verdict_missing"]),
    "claude_other_head": ([codex_row(), claude_row(OLD)], "pending",
                          "claude_verdict_missing", False, ["claude_verdict_missing"]),
    "claude_two_markers": ([codex_row(), claude_row(SHA, body=TWO)], "pending",
                           "claude_verdict_missing", False, ["claude_verdict_missing"]),
    "claude_marker_by_human": (
        [codex_row(), claude_row(SHA, login="writer", kind="User")], "pending",
        "claude_verdict_missing", False, ["claude_verdict_missing"]),
    "claude_edited_by_human": (
        [codex_row(), claude_row(SHA, editor=HUMAN, edited="2026-10-29T08:11:00Z")],
        "blocked", "claude_verdict_unreadable", False, ["claude_verdict_unreadable"]),
    "claude_refuses": ([codex_row(), claude_row(SHA, merge=False)], "blocked",
                       "claude_refused", True, ["claude_refused"]),
    "codex_security_null_no_receipt": (
        [receipt_rows()[0], claude_row(SHA)], "blocked",
        "codex_security_verdict_missing", False, ["codex_security_verdict_missing"]),
    "codex_security_running": (
        [codex_row(security=RUNNING), claude_row(SHA)], "pending", "review_pending",
        False, ["codex_security_verdict_missing"]),
    "codex_running_and_claude_missing": (
        [codex_row(security=RUNNING)], "pending", "review_pending", False,
        ["codex_security_verdict_missing", "claude_verdict_missing"]),
    "codex_summary_missing": ([claude_row(SHA)], "pending", "review_missing", False,
                              ["codex_code_verdict_missing", "codex_security_verdict_missing"]),
    "codex_findings": ([codex_row(code=FINDINGS), claude_row(SHA)], "blocked",
                       "review_unresolved", True, ["codex_code_findings_unresolved"]),
}


TABLE.update({
    "dependabot_codex_clean": ([codex_row()], "success", "reviews_complete", True, []),
    "dependabot_codex_findings": ([codex_row(code=FINDINGS)], "blocked", "review_unresolved",
                                  True, ["codex_code_findings_unresolved"]),
    "dependabot_claude_refuses": ([codex_row(), claude_row(SHA, merge=False)], "blocked",
                                  "claude_refused", True, ["claude_refused"]),
})


@pytest.mark.parametrize("row", list(TABLE))
def test_state_table_row(row):
    rows, state, reason, complete, causes = TABLE[row]
    result = evidence(rows, dependabot=row.startswith("dependabot_"))
    assert (result["state"], result["reason"], result["reviews_complete"]) == (
        state, reason, complete)
    assert result["causes"] == causes


QUOTA = json.loads((ROOT / "tests/fixtures/codex_quota/comments-20261029.json").read_text())
FAILED_CODE = dict(commit_sha=SHA, status="failed", has_any_findings=True,
                   has_unresolved_findings=True)
NO_SECURITY = dict(commit_sha=None, status=None, has_any_findings=None,
                   has_unresolved_findings=None)


def notice(name, stamp=None):
    """A real Codex usage-limit notice, as a normalized GraphQL comment row."""
    real = QUOTA[name]
    row = codex_row(identity=real["id"])
    row.update(body=real["body"], updated_at=stamp or "2026-10-29T08:06:00Z")
    return row


@pytest.mark.parametrize("name", ["ai-architect-mcp-spec-164-6497379059",
                                  "ai-architect-mcp-codebase-469-6497357065"])
def test_code_review_quota_notice_waits_by_name(name):
    rows = [codex_row(code=FAILED_CODE, security=NO_SECURITY), notice(name), claude_row(SHA)]
    result = evidence(rows)
    assert (result["state"], result["reason"]) == ("pending", "codex_quota_exhausted")
    assert result["causes"] == ["codex_quota_exhausted", "codex_security_verdict_missing"]


def test_security_review_quota_notice_on_the_real_summary_waits_by_name():
    # cdeust/ci-autonome PR9: summary6496243120 (code running, security failed),
    # then notice6497426761 two seconds later.
    summary, real = QUOTA["ci-autonome-9-6496243120"], QUOTA["ci-autonome-9-6497426761"]
    head = "6c765807c0b93cf168ebe3b5d1eba708b843cbe6"
    rows = [codex_row(identity=summary["id"]), codex_row(identity=real["id"])]
    rows[0].update(body=summary["body"], updated_at=summary["updated_at"])
    rows[1].update(body=real["body"], updated_at=real["updated_at"])
    result = reader().review_evidence(rows, head, "cdeust/ci-autonome", 9)
    assert (result["state"], result["reason"]) == ("pending", "codex_quota_exhausted")
    assert result["causes"] == ["codex_code_verdict_missing", "codex_quota_exhausted",
                                "claude_verdict_missing"]
    rows[1]["updated_at"] = "2026-10-29T13:03:14Z"  # the summary moved on after it
    assert evidence_for(rows, head)["reason"] == "review_failed"


def evidence_for(rows, head):
    return reader().review_evidence(rows, head, "cdeust/ci-autonome", 9)


def test_failed_review_without_notice_still_blocks():
    result = evidence([codex_row(code=FAILED_CODE, security=NO_SECURITY), claude_row(SHA)])
    assert (result["state"], result["reason"]) == ("blocked", "review_failed")


def test_dependabot_agreement_is_named():
    result = evidence([codex_row()], dependabot=True)
    assert result["claude"] == {"verdict": "not_applicable_dependabot", "comment_id": 0}


def graph_page(rows, author, ref):
    """One GraphQL comments page of the PR, with the PR author and branch."""
    nodes = [dict(databaseId=r["id"], body=r["body"], updatedAt=r["updated_at"],
                  author=dict(login=r["user"]["login"].removesuffix("[bot]"),
                              __typename=r["user"]["type"], id=r["user"]["node_id"]),
                  editor=r["editor"], lastEditedAt=r["lastEditedAt"]) for r in rows]
    pull = dict(number=PR, headRefOid=SHA, author=author, headRefName=ref,
                comments=dict(nodes=nodes, pageInfo=dict(hasNextPage=False, endCursor=None)))
    return dict(data=dict(repository=dict(pullRequest=pull)))


BOT_DEPENDABOT = dict(login="dependabot", __typename="Bot")


@pytest.mark.parametrize(
    "author, ref, expected",
    [
        (BOT_DEPENDABOT, "dependabot/github_actions/x", ("success", True)),
        (dict(login="dependabot", __typename="User"), "dependabot/x", ("pending", False)),
        (BOT_DEPENDABOT, "fix/x", ("pending", False)),
        (dict(login="writer", __typename="User"), "dependabot/x", ("pending", False)),
        (None, None, ("pending", False)),
    ],
    ids=["dependabot", "user-named-dependabot", "other-branch", "human", "fields-absent"],
)
def test_dependabot_is_read_from_the_comments_node(author, ref, expected):
    module = reader()
    comments = sys.modules["ci_codex_review_comments"]
    assert "headRefName author { login __typename }" in comments.COMMENTS_QUERY
    rows = comments._comment_pages([graph_page([codex_row()], author, ref)], SHA, PR)
    result = module.review_evidence(rows, SHA, REPO, PR)
    assert (result["state"], rows.dependabot) == expected


def test_latest_claude_verdict_for_the_head_decides():
    refused = claude_row(SHA, merge=False, identity=900001, stamp="2026-10-29T08:10:00Z")
    agreed = claude_row(SHA, merge=True, identity=900002, stamp="2026-10-29T08:20:00Z")
    stale = claude_row(OLD, merge=False, identity=900003, stamp="2026-10-29T08:30:00Z")
    result = evidence([codex_row(), refused, agreed, stale])
    assert (result["state"], result["claude"]) == (
        "success", {"verdict": "merge", "comment_id": 900002})


def test_gate_outputs_name_the_causes(tmp_path, monkeypatch):
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    module = reader()
    module._outputs(evidence([codex_row(security=RUNNING)]))
    lines = output.read_text().splitlines()
    assert "state=pending" in lines and "reason=review_pending" in lines
    assert "causes=codex_security_verdict_missing,claude_verdict_missing" in lines


@pytest.fixture(scope="module")
def jobs():
    return yaml.safe_load((NATIVE / "pipeline.yml").read_text())["jobs"]


def test_the_merge_job_waits_for_no_review_and_reads_no_pull_request(jobs):
    """Owner rule 2026-10-29: merge is the aggregate of the test jobs; review states stay with the review job."""
    assert "review" not in jobs["merge"]["needs"]
    assert jobs["review"]["outputs"]["causes"] == "${{ steps.evidence.outputs.causes }}"
    assert jobs["merge"]["permissions"] == {"contents": "read"}


# The resolve job (workflow_run, main's definition, pull-requests: write).
class LabelAPI:
    """REST double: labels removed by DELETE, then the PR re-read and merged."""

    def __init__(self, pr, after_get=None):
        self.pr, self.after_get, self.calls = pr, after_get, []

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        if method == "DELETE":
            name = unquote(path.rsplit("/", 1)[1])
            self.pr["labels"] = [x for x in self.pr["labels"] if x["name"] != name]
            return self.pr["labels"]
        if method == "GET":
            if self.after_get:
                self.after_get(self.pr)
            return self.pr
        if method == "PUT":
            return {"merged": True, "sha": "c" * 40}
        raise AssertionError(f"unexpected request {method} {path}")


def resolver(jobs, tmp_path):
    from test_ci_native_gate import resolver as load

    return load(jobs, tmp_path)


def held_pr(labels, title="fix"):
    repo = dict(full_name="o/r")
    return dict(number=7, state="open", draft=False, title=title,
                labels=[dict(name=name) for name in labels],
                head=dict(sha=SHA, repo=repo), base=dict(ref="main", repo=repo))


MERGE_PATH = "/repos/o/r/pulls/7/merge"  # source: resolve() passes pr_path + "/merge".


def test_agreement_lifts_review_holds_then_merges(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = LabelAPI(held_pr(["hold", "bug", "Autopilot:Hold"]))
    assert module._merge_open_pr(api.pr, MERGE_PATH, SHA, api) == "c" * 40
    assert api.calls == [
        ("DELETE", "/repos/o/r/issues/7/labels/hold"),
        ("DELETE", "/repos/o/r/issues/7/labels/Autopilot%3AHold"),
        ("GET", "/repos/o/r/pulls/7"),
        ("PUT", MERGE_PATH),
    ]
    assert [x["name"] for x in api.pr["labels"]] == ["bug"]


def test_unheld_pr_merges_without_label_calls(jobs, tmp_path):
    module = resolver(jobs, tmp_path)
    api = LabelAPI(held_pr(["bug"]))
    module._merge_open_pr(api.pr, MERGE_PATH, SHA, api)
    assert api.calls == [("PUT", MERGE_PATH)]


@pytest.mark.parametrize(
    "pr, message",
    [
        (held_pr(["hold", "do-not-merge"]), "PR label holds merge"),
        (held_pr(["DO-NOT-MERGE"]), "PR label holds merge"),
        (held_pr(["hold"], "fix: do not merge"), "PR title holds merge"),
    ],
)
def test_owner_holds_are_never_touched(jobs, tmp_path, pr, message):
    module = resolver(jobs, tmp_path)
    api = LabelAPI(pr)
    with pytest.raises(module.PostMergeError, match=message):
        module._merge_open_pr(api.pr, MERGE_PATH, SHA, api)
    assert api.calls == []


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda pr: pr["labels"].append(dict(name="hold")), "PR label holds merge"),
        (lambda pr: pr["labels"].append(dict(name="do-not-merge")), "PR label holds merge"),
        (lambda pr: pr["head"].update(sha=OLD), "PR head advanced after testing"),
    ],
    ids=["hold-readded", "owner-hold-added", "head-moved"],
)
def test_change_during_the_lift_refuses_the_merge(jobs, tmp_path, change, message):
    module = resolver(jobs, tmp_path)
    api = LabelAPI(held_pr(["hold"]), after_get=change)
    with pytest.raises(module.PostMergeError, match=message):
        module._merge_open_pr(api.pr, MERGE_PATH, SHA, api)
    assert ("PUT", MERGE_PATH) not in api.calls

"""Exercise the code that the opt-in renderer puts in the trusted merge job."""

import json
import textwrap

import pytest

from scripts.lib import render_ci as renderer

HEAD = "c" * 40
STALE = "d" * 40
MERGED = "e" * 40
REPO = "o/r"
PR = 7


@pytest.fixture
def target(tmp_path):
    for name, data in renderer.prepare_files(tmp_path).items():
        name.parent.mkdir(parents=True, exist_ok=True)
        name.write_bytes(data)
    return tmp_path


@pytest.fixture
def resolver(target):
    files = renderer.prepare_files(target, native_verdict=True)
    workflow = files[target / renderer.POST_MERGE].decode()
    script = workflow.split("          python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    namespace = {"__name__": "resolver_test"}
    exec(compile(textwrap.dedent(script), "trusted_resolver", "exec"), namespace)
    return namespace


def test_overlay_preserves_consumer_workflows_and_budget(target):
    post_merge = target / renderer.POST_MERGE
    custom = post_merge.read_bytes().replace(b'CLAUDE_CODE_VERSION: "2.1.306"', b'CLAUDE_CODE_VERSION: "custom"')
    post_merge.write_bytes(custom)
    review = target / ".github/workflows/claude-review.yml"
    review.write_bytes(b"consumer review workflow\n")
    budget = target / "scripts/ci_review_budget.py"
    budget.write_bytes(b"consumer budget\n")
    files = renderer.prepare_files(target, native_verdict=True)
    assert set(files) == {post_merge, target / renderer.NATIVE_PARSER}
    assert b'CLAUDE_CODE_VERSION: "custom"' in files[post_merge]
    assert b"def _selected_review_approves(" in files[post_merge]
    source = files[target / renderer.NATIVE_PARSER].decode()
    assert textwrap.indent(source, " " * 10) in files[post_merge].decode()
    renderer.deliver(files)
    assert review.read_bytes() == b"consumer review workflow\n"
    assert budget.read_bytes() == b"consumer budget\n"
    assert renderer.prepare_files(target) == files
    assert renderer.prepare_files(target, native_verdict=True) == files
    with pytest.raises(ValueError, match="conflicts"):
        renderer.prepare_files(target, native_review=True)


def test_overlay_refuses_incompatible_resolver_without_writing(target):
    post_merge = target / renderer.POST_MERGE
    post_merge.write_text("custom engine without legacy gate\n")
    with pytest.raises(ValueError, match="Canonical template changed"):
        renderer.prepare_files(target, native_verdict=True)
    assert post_merge.read_text() == "custom engine without legacy gate\n"
    assert not (target / renderer.NATIVE_PARSER).exists()


def review_run(attempt=1, head=HEAD, conclusion="success"):
    return {
        "id": 42, "head_sha": head, "run_attempt": attempt, "event": "pull_request",
        "head_repository": {"full_name": REPO}, "path": ".github/workflows/claude-review.yml",
        "repository": {"full_name": REPO}, "pull_requests": [{"number": PR}],
        "created_at": "2026-11-22T10:00:00Z", "status": "completed", "conclusion": conclusion,
    }


def review_job(name, *, attempt=1, conclusion="success"):
    return {
        "name": name, "id": attempt if name.startswith("Codex") else 3,
        "run_attempt": attempt, "head_sha": HEAD, "run_id": 42,
        "status": "completed", "conclusion": conclusion,
        "steps": [{"name": "PR Review", "status": "completed", "conclusion": conclusion}],
    }


def summary(namespace, *, head=HEAD, unresolved=False, author=None, editor=None, status="completed"):
    data = {"code_review": {
        "commit_sha": head, "status": status, "has_any_findings": unresolved,
        "has_unresolved_findings": unresolved,
    }}
    return {
        "author": namespace["BOT"] if author is None else author,
        "lastEditedAt": None if editor is None else "2026-11-22",
        "editor": editor,
        "body": namespace["SUMMARY"] + "\n" + namespace["PREFIX"] + json.dumps(data) + " -->",
    }


def page(*nodes, head=HEAD, has_next=False):
    return {"data": {"repository": {"pullRequest": {
        "headRefOid": head, "state": "OPEN", "isDraft": False,
        "comments": {
            "nodes": nodes,
            "pageInfo": {"hasNextPage": has_next, "endCursor": "next" if has_next else None},
        },
    }}}}


def route(*, source_attempt=1, **overrides):
    return {
        "id": 43, "head_sha": STALE, "run_attempt": 1, "event": "workflow_run",
        "head_repository": {"full_name": REPO}, "repository": {"full_name": REPO},
        "head_branch": "main", "status": "completed", "conclusion": "success",
        "display_title": f"Route PR Review 42 attempt {source_attempt}",
        "path": ".github/workflows/review-subscription.yml", **overrides,
    }


def route_job(choice="Request Codex", *, attempt=1, **overrides):
    return {
        "name": "select", "id": 4, "run_attempt": attempt, "head_sha": STALE,
        "run_id": 43, "status": "completed", "conclusion": "success",
        "steps": [{"name": choice, "status": "completed", "conclusion": "success"}],
        **overrides,
    }


class GitHubFixture:
    def __init__(self, *, jobs, pages, run=None, routes=None, route_jobs=None, comments=()):
        self.run = run or review_run()
        self.jobs = jobs
        self.pages = pages
        self.routes = [route()] if routes is None else routes
        self.route_jobs = {43: [route_job()]} if route_jobs is None else route_jobs
        self.comments = comments
        self.graphql = []
        self.merges = []

    def records(self, path, key=None):
        if path == f"/repos/{REPO}/issues/{PR}/comments":
            return iter(self.comments)
        if path == f"/repos/{REPO}/actions/workflows/claude-review.yml/runs?head_sha={HEAD}&event=pull_request":
            assert key == "workflow_runs"
            return iter([self.run])
        if path.startswith(f"/repos/{REPO}/actions/workflows/review-subscription.yml/runs?"):
            assert "event=workflow_run&branch=main&created=" in path
            assert key == "workflow_runs"
            return iter(self.routes)
        prefix = f"/repos/{REPO}/actions/runs/"
        run_id, endpoint, attempt, resource = path.removeprefix(prefix).split("/")
        assert key == "jobs" and endpoint == "attempts" and resource == "jobs"
        if int(run_id) == 42:
            return iter(job for job in self.jobs if job["run_attempt"] == int(attempt))
        return iter(self.route_jobs[int(run_id)])

    def request(self, method, path, body):
        if path == "/graphql":
            assert method == "POST"
            self.graphql.append(body["variables"])
            return next(self.pages)
        assert method == "PUT" and path == f"/repos/{REPO}/pulls/{PR}/merge"
        self.merges.append(body)
        return {"merged": True, "sha": MERGED}


def merge(namespace, api):
    namespace["_is_low_risk"] = lambda *_: False
    return namespace["_merge_open_pr"](
        {"number": PR, "state": "open", "draft": False}, f"/repos/{REPO}/pulls/{PR}/merge",
        HEAD, api, REPO,
    )


def test_authentic_native_approval_after_pagination_merges_exact_head(resolver):
    api = GitHubFixture(
        jobs=[review_job("Codex GitHub review")],
        pages=iter([page(has_next=True), page(summary(resolver, editor=resolver["BOT"]))]),
    )
    assert merge(resolver, api) == MERGED
    assert api.graphql == [{"owner": "o", "repo": "r", "pr": PR},
                           {"owner": "o", "repo": "r", "pr": PR, "endCursor": "next"}]
    assert api.merges == [{"sha": HEAD, "merge_method": "squash"}]


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        ("block", "review verdict is block"),
        ("forgery", "verdict is pending"),
        ("editor", "Unverified editor"),
        ("old_summary", "verdict is pending"),
        ("stale_pr", "PR closed or head changed"),
        ("duplicate", "Ambiguous Codex"),
        ("in_progress", "verdict is pending"),
    ],
)
def test_failed_native_run_never_falls_back_to_claude(resolver, evidence, reason):
    approved = summary(resolver)
    pages = {
        "block": page(summary(resolver, unresolved=True)),
        "forgery": page(summary(resolver, author={**resolver["BOT"], "id": "wrong"})),
        "editor": page(summary(resolver, editor={**resolver["BOT"], "id": "wrong"})),
        "old_summary": page(summary(resolver, head=STALE)),
        "stale_pr": page(approved, head=STALE),
        "duplicate": page(approved, approved),
        "in_progress": page(summary(resolver, status="running")),
    }
    api = GitHubFixture(
        run=review_run(conclusion="failure"),
        jobs=[review_job("Codex GitHub review", conclusion="failure"), review_job("Claude review")],
        pages=iter([pages[evidence]]),
    )
    with pytest.raises((resolver["PostMergeError"], ValueError), match=reason):
        merge(resolver, api)
    assert api.merges == []


def claude_comment(verdict, *, attempt=1, repo=REPO, author="claude[bot]"):
    return {
        "user": {"login": author, "type": "Bot"},
        "updated_at": "2026-11-22T10:30:00Z",
        "body": f"[View job run](https://github.com/{repo}/actions/runs/42/attempts/{attempt})\n"
                f"Verdict: {verdict}",
    }


def test_both_admitted_reviewers_remain_required_after_partial_rerun(resolver):
    api = GitHubFixture(
        run=review_run(attempt=2),
        jobs=[review_job("Codex GitHub review"), review_job("Codex GitHub review", attempt=2, conclusion="skipped"),
              review_job("Claude review", attempt=2)],
        routes=[route(), route(source_attempt=2, id=44)],
        route_jobs={43: [route_job()], 44: [route_job("Select Claude", run_id=44)]},
        comments=[claude_comment("approve", attempt=2)],
        pages=iter([page(summary(resolver))]),
    )
    with pytest.raises(resolver["PostMergeError"], match="no admitted native Codex review"):
        merge(resolver, api)
    assert not api.merges


def test_latest_admitted_claude_attempt_requires_its_own_verdict(resolver):
    api = GitHubFixture(
        run=review_run(attempt=2),
        jobs=[review_job("Claude review", attempt=2)],
        routes=[route(source_attempt=2)],
        route_jobs={43: [route_job("Select Claude")]},
        pages=iter([]),
        comments=[claude_comment("approve"), claude_comment("approve", attempt=2, repo="wrong/repo")],
    )
    with pytest.raises(resolver["PostMergeError"], match="no verdict from an admitted Claude attempt"):
        merge(resolver, api)
    assert not api.merges

    api.comments.append(claude_comment("block", attempt=2))
    with pytest.raises(resolver["PostMergeError"], match="Claude review verdict is block"):
        merge(resolver, api)
    assert not api.merges

    api.comments[-1] = claude_comment("approve", attempt=2)
    assert merge(resolver, api) == MERGED
    assert api.graphql == []


def test_omitted_native_job_cannot_fall_back_to_claude(resolver):
    api = GitHubFixture(
        jobs=[review_job("Claude review")], pages=iter([page(summary(resolver))]),
        comments=[claude_comment("approve")],
    )
    with pytest.raises(resolver["PostMergeError"], match="no admitted native Codex review"):
        merge(resolver, api)
    assert not api.merges


@pytest.mark.parametrize(
    ("route_rows", "jobs"),
    [
        ([], [route_job()]),
        ([route(event="pull_request")], [route_job()]),
        ([route(head_branch="feature")], [route_job()]),
        ([route(repository={"full_name": "other/repo"})], [route_job()]),
        ([route(source_attempt=2)], [route_job()]),
        ([route(display_title="Route PR Review 143 attempt 1")], [route_job()]),
        ([route(), route(id=44, status="in_progress")], [route_job()]),
        ([route()], [route_job(name="attacker")]),
        ([route()], [route_job(status="in_progress")]),
    ],
)
def test_native_approval_requires_default_branch_admission(resolver, route_rows, jobs):
    api = GitHubFixture(
        jobs=[review_job("Codex GitHub review")], pages=iter([page(summary(resolver))]),
        routes=route_rows, route_jobs={43: jobs},
    )
    with pytest.raises(resolver["PostMergeError"], match="latest review admission is unverified"):
        merge(resolver, api)
    assert not api.merges


def test_approval_requires_review_job_to_succeed(resolver):
    api = GitHubFixture(
        jobs=[review_job("Codex GitHub review", conclusion="failure")],
        pages=iter([page(summary(resolver))]),
    )
    with pytest.raises(resolver["PostMergeError"], match="no admitted native Codex review"):
        merge(resolver, api)
    assert not api.merges


def test_other_pr_with_same_head_cannot_supply_native_route(resolver):
    run = {**review_run(), "pull_requests": [{"number": PR + 1}]}
    api = GitHubFixture(run=run, jobs=[review_job("Codex GitHub review")], pages=iter([]))

    with pytest.raises(resolver["PostMergeError"], match="no candidate review run"):
        merge(resolver, api)
    assert not api.merges
    assert api.graphql == []


@pytest.mark.parametrize(
    ("provider", "choice", "job", "rejection"),
    [
        ("claude", "Select Claude", "Claude review", "no admitted Claude review"),
        ("codex", "Request Codex", "Codex GitHub review", "no admitted native Codex review"),
    ],
)
def test_successful_review_job_cannot_approve_a_failed_run(resolver, provider, choice, job, rejection):
    api = GitHubFixture(
        run=review_run(conclusion="failure"),
        jobs=[review_job(job)],
        route_jobs={43: [route_job(choice)]},
        comments=[claude_comment("approve")],
        pages=iter([page(summary(resolver))] if provider == "codex" else []),
    )
    with pytest.raises(resolver["PostMergeError"], match=rejection):
        merge(resolver, api)
    assert not api.merges

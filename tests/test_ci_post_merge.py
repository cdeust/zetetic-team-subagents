"""Exercise the protected resolver through actual urllib Request/JSON boundaries."""

import json
from copy import deepcopy
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest

from tools import ci_post_merge as resolver

REPO = "cdeust/example"
HEAD = "a" * 40
MERGED = "b" * 40
# Owner rule 2026-10-29: the required jobs are the tests and their aggregate.
JOB_NAMES = ["contract", "unit", "regression", "e2e", "merge"] + [
    f"{category} ({runner})"
    for category in ("environment", "install")
    for runner in ("ubuntu-latest", "macos-latest", "windows-latest")
]
PREFIX = f"/repos/{REPO}"
RUN_PATH = f"{PREFIX}/actions/runs/71"
JOBS_PATH = RUN_PATH + "/jobs?filter=all&per_page=100&page=1"
# The Claude review of this head (claude-review.yml) and its verdict comment: the
# resolver merges only on an approving verdict bound to that run (Cortex ADR-1121).
REVIEW_RUN = 90
REVIEW_RUNS_PATH = (
    PREFIX + f"/actions/workflows/claude-review.yml/runs?head_sha={HEAD}&per_page=100&page=1"
)
REVIEW_JOBS_PATH = PREFIX + f"/actions/runs/{REVIEW_RUN}/jobs?per_page=100&page=1"
COMMENTS_PATH = PREFIX + "/issues/42/comments?per_page=100&page=1"


def job_row(name, identity, conclusion="success"):
    return {
        "id": identity,
        "run_id": 71,
        "run_attempt": 1,
        "head_sha": HEAD,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
    }


def verdict(word, run=REVIEW_RUN, updated="2026-11-10T00:00:00Z"):
    return {
        "user": {"login": "claude[bot]", "type": "Bot"},
        "updated_at": updated,
        "body": f"Review of https://github.com/{REPO}/actions/runs/{run}\n\nVerdict: {word}\n",
    }
PR_PATH = PREFIX + "/pulls/42"
COMPARE_PATH = PREFIX + f"/compare/main...{MERGED}"
PUSH_PATH = (
    PREFIX
    + f"/actions/workflows/pipeline.yml/runs?event=push&head_sha={MERGED}&per_page=100&page=1"
)


@pytest.fixture
def scenario(monkeypatch):
    run = {
        "id": 71,
        "run_attempt": 1,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_repository": {"full_name": REPO},
        "head_branch": "fix/feature",
        "head_sha": HEAD,
        "name": "Pipeline",
        "path": ".github/workflows/pipeline.yml",
        "pull_requests": [{"number": 42}],
        "actor": {"login": "owner"},
    }
    pr = {
        "number": 42,
        "state": "open",
        "draft": False,
        "merged": False,
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
        "base": {"ref": "main", "repo": {"full_name": REPO}},
        "user": {"login": "owner", "type": "User"},
        "title": "Fix feature",
        "labels": [],
    }
    event = {"repository": {"full_name": REPO}, "workflow_run": deepcopy(run)}
    jobs = [job_row(name, 500 + index) for index, name in enumerate(JOB_NAMES)]
    review_jobs = [
        {"name": "Claude review", "steps": [{"name": "PR Review", "conclusion": "success"}]}
    ]
    responses = {
        ("GET", RUN_PATH): run,
        ("GET", JOBS_PATH): {"jobs": jobs},
        ("GET", PR_PATH): pr,
        ("GET", REVIEW_RUNS_PATH): {
            "workflow_runs": [{"id": REVIEW_RUN, "head_sha": HEAD, "conclusion": "success"}]
        },
        ("GET", REVIEW_JOBS_PATH): {"jobs": review_jobs},
        ("GET", COMMENTS_PATH): [verdict("approve")],
        ("PUT", PR_PATH + "/merge"): {"merged": True, "sha": MERGED},
        ("GET", PUSH_PATH): {"workflow_runs": []},
    }
    requests = []

    def open_request(request):
        assert request.full_url.startswith(
            "https://api.github.com/repos/cdeust/example/"
        )
        assert request.get_header("Authorization") == "Bearer fixture-token"
        url = urlsplit(request.full_url)
        path = url.path + ("?" + url.query if url.query else "")
        requests.append(
            (request.method, path, json.loads(request.data) if request.data else None)
        )
        response = responses[(request.method, path)]
        if callable(response):
            response = response()
        if isinstance(response, Exception):
            raise response
        if request.method == "PUT" and response.get("merged") is True:
            pr.update(merged=True, state="closed", merge_commit_sha=response.get("sha"))
        return BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(resolver, "urlopen", open_request)
    return event, run, pr, responses, requests


def execute(scenario):
    return resolver.resolve(scenario[0], REPO, resolver.GitHub("fixture-token"))


def assert_no_merge(scenario):
    assert all(method != "PUT" for method, _, _ in scenario[-1])


def test_success_uses_tested_head_precondition_and_returns_merge_sha(scenario):
    result = execute(scenario)
    assert result["tested_sha"] == MERGED
    assert result["tested_sha"] != HEAD
    assert result["run_tests"] == "true"
    assert result["pr_number"] == "42"
    assert (
        "PUT",
        PR_PATH + "/merge",
        {"sha": HEAD, "merge_method": "squash"},
    ) in scenario[-1]
    assert sum(method == "PUT" for method, _, _ in scenario[-1]) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"event": "push"},
        {"conclusion": "failure"},
        {"status": "in_progress"},
        {"head_repository": {"full_name": "outsider/example"}},
        {"head_branch": "main"},
        {"path": ".github/workflows/fake.yml"},
        {"name": "Fake"},
        {"id": "71"},
        {"head_sha": "short"},
    ],
)
def test_untrusted_event_never_contacts_github(scenario, changes):
    scenario[0]["workflow_run"].update(changes)
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)
    assert scenario[-1] == []


def test_event_repository_must_match_runner_repository(scenario):
    scenario[0]["repository"]["full_name"] = "outsider/example"
    with pytest.raises(resolver.PostMergeError, match="event repository"):
        execute(scenario)
    assert scenario[-1] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"run_attempt": 2},
        {"head_sha": "c" * 40},
        {"conclusion": "cancelled"},
    ],
)
def test_live_source_run_must_still_be_the_successful_attempt(scenario, changes):
    scenario[1].update(changes)
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)
    assert_no_merge(scenario)


@pytest.mark.parametrize(
    "jobs",
    [
        [],
        [job_row("merge", 1, "skipped")],
        [job_row("merge", 1, "failure")],
        [job_row("merge", 1), job_row("merge", 2)],
    ],
)
def test_missing_or_incomplete_merge_gate_fails(scenario, jobs):
    scenario[3][("GET", JOBS_PATH)] = {"jobs": jobs}
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)
    assert_no_merge(scenario)


@pytest.mark.parametrize(
    "changes",
    [
        {"draft": True},
        {"state": "closed"},
        {"title": "Please DO NOT MERGE this"},
        {"labels": [{"name": "HoLd"}]},
        {"labels": [{"name": "do-not-merge"}]},
        {"head": {"sha": "c" * 40, "repo": {"full_name": REPO}}},
        {"head": {"sha": HEAD, "repo": {"full_name": "outsider/example"}}},
        {"base": {"ref": "release", "repo": {"full_name": REPO}}},
    ],
)
def test_live_pr_guards_prevent_merge(scenario, changes):
    scenario[2].update(changes)
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)
    assert_no_merge(scenario)


@pytest.mark.parametrize("status", [403, 405, 409, 422])
def test_github_refusal_is_visible_without_retry_or_bypass(scenario, status):
    scenario[3][("PUT", PR_PATH + "/merge")] = HTTPError(
        "https://api.github.com", status, "denied fixture-token", {}, None
    )
    with pytest.raises(resolver.PostMergeError, match=f"HTTP {status}") as error:
        execute(scenario)
    assert "fixture-token" not in str(error.value)
    assert sum(method == "PUT" for method, _, _ in scenario[-1]) == 1


@pytest.mark.parametrize(
    "reply",
    [
        {"merged": False, "sha": MERGED},
        {"merged": True, "sha": "main"},
        {"merged": True},
    ],
)
def test_unconfirmed_merge_never_produces_test_target(scenario, reply):
    scenario[3][("PUT", PR_PATH + "/merge")] = reply
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)


def test_already_merged_uses_confirmed_sha_without_new_merge(scenario):
    scenario[2].update(merged=True, state="closed", merge_commit_sha=MERGED)
    result = execute(scenario)
    assert result["tested_sha"] == MERGED
    assert result["run_tests"] == "true"
    assert_no_merge(scenario)


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [
        ("in_progress", None),
        ("queued", None),
        ("completed", "success"),
        ("completed", "failure"),
    ],
)
def test_human_push_of_exact_merge_commit_avoids_duplicate_suite(
    scenario, status, conclusion
):
    scenario[2].update(merged=True, state="closed", merge_commit_sha=MERGED)
    scenario[3][("GET", PUSH_PATH)] = {
        "workflow_runs": [
            {
                "event": "push",
                "status": status,
                "conclusion": conclusion,
                "head_sha": MERGED,
                "head_branch": "main",
                "path": ".github/workflows/pipeline.yml",
            }
        ]
    }
    assert execute(scenario)["run_tests"] == "false"
    assert_no_merge(scenario)


def test_unrelated_push_does_not_substitute_current_main_for_merge_commit(scenario):
    scenario[2].update(merged=True, state="closed", merge_commit_sha=MERGED)
    scenario[3][("GET", PUSH_PATH)] = {
        "workflow_runs": [
            {
                "event": "push",
                "head_sha": "c" * 40,
                "head_branch": "main",
                "path": ".github/workflows/pipeline.yml",
            }
        ]
    }
    result = execute(scenario)
    assert result["run_tests"] == "true"
    assert result["tested_sha"] == MERGED


def test_empty_run_pr_association_resolves_exact_commit_pr(scenario):
    scenario[1]["pull_requests"] = []
    scenario[3][("GET", f"{PREFIX}/commits/{HEAD}/pulls?per_page=100&page=1")] = [
        {
            **deepcopy(scenario[2]),
            "base": {"ref": "other", "repo": {"full_name": REPO}},
        },
        scenario[2],
    ]
    assert execute(scenario)["pr_number"] == "42"


def test_ambiguous_pr_association_fails(scenario):
    scenario[1]["pull_requests"] = [{"number": 42}, {"number": 43}]
    with pytest.raises(resolver.PostMergeError, match="exactly one"):
        execute(scenario)
    assert_no_merge(scenario)


def test_merge_gate_on_second_jobs_page_is_checked(scenario):
    complete_jobs = scenario[3][("GET", JOBS_PATH)]
    scenario[3][("GET", JOBS_PATH)] = {
        "jobs": [
            job_row(f"unrelated {index}", 1000 + index)
            for index in range(100)
        ]
    }
    scenario[3][("GET", JOBS_PATH.replace("&page=1", "&page=2"))] = complete_jobs
    assert execute(scenario)["tested_sha"] == MERGED


def test_network_failure_does_not_retry_or_reveal_token(scenario):
    scenario[3][("GET", RUN_PATH)] = URLError("fixture-token")
    with pytest.raises(resolver.PostMergeError, match="unreadable response") as error:
        execute(scenario)
    assert "fixture-token" not in str(error.value)
    assert len(scenario[-1]) == 1


def test_cli_writes_outputs_only_after_confirmed_merge(scenario, tmp_path, monkeypatch):
    event_file = tmp_path / "event.json"
    output = tmp_path / "output"
    event_file.write_text(json.dumps(scenario[0]))
    for key, value in {
        "GITHUB_EVENT_NAME": "workflow_run",
        "GITHUB_EVENT_PATH": str(event_file),
        "GITHUB_REPOSITORY": REPO,
        "GH_TOKEN": "fixture-token",
        "GITHUB_OUTPUT": str(output),
    }.items():
        monkeypatch.setenv(key, value)
    assert resolver.main() == 0
    assert f"tested_sha={MERGED}\n" in output.read_text()
    assert "run_tests=true\n" in output.read_text()
    output.unlink()
    scenario[2].update(merged=False, state="open")
    scenario[2]["draft"] = True
    assert resolver.main() == 1
    assert not output.exists()


def test_cli_rejects_other_event_before_api(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert resolver.main() == 1
    assert "resolver requires workflow_run" in capsys.readouterr().err


def test_empty_token_is_rejected():
    with pytest.raises(resolver.PostMergeError, match="GH_TOKEN"):
        resolver.GitHub("")


@pytest.mark.parametrize(
    "conclusion", ["cancelled", "skipped", "timed_out", "action_required"]
)
def test_unfinished_push_does_not_suppress_post_merge_tests(scenario, conclusion):
    scenario[2].update(merged=True, state="closed", merge_commit_sha=MERGED)
    scenario[3][("GET", PUSH_PATH)] = {
        "workflow_runs": [
            {
                "event": "push",
                "head_sha": MERGED,
                "head_branch": "main",
                "path": ".github/workflows/pipeline.yml",
                "status": "completed",
                "conclusion": conclusion,
            }
        ]
    }
    assert execute(scenario)["run_tests"] == "true"
    assert_no_merge(scenario)


def test_malformed_jobs_reply_is_not_treated_as_completed_gate(scenario):
    scenario[3][("GET", JOBS_PATH)] = {"jobs": None}
    with pytest.raises(resolver.PostMergeError, match="invalid record list"):
        execute(scenario)
    assert_no_merge(scenario)


@pytest.mark.parametrize("name", [name for name in JOB_NAMES if name != "merge"])
@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "skipped", "failure", "in_progress"]
)
def test_every_required_job_must_complete_once(scenario, name, fault):
    jobs = scenario[3][("GET", JOBS_PATH)]["jobs"]
    job = next(job for job in jobs if job["name"] == name)
    if fault == "missing":
        jobs.remove(job)
    elif fault == "duplicate":
        jobs.append(deepcopy(job))
    elif fault == "in_progress":
        job["status"] = "in_progress"
    else:
        job["conclusion"] = fault
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)
    assert_no_merge(scenario)


@pytest.mark.parametrize("attempt", [None, 0, -1, "1", True])
def test_run_attempt_requires_a_positive_integer(scenario, attempt):
    scenario[0]["workflow_run"]["run_attempt"] = attempt
    scenario[1]["run_attempt"] = attempt
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)
    assert_no_merge(scenario)


# The review is claude-review.yml's own run, never a job of the Pipeline: the
# resolver reads its verdict comment, bound to the run that reviewed this head.
def test_an_approving_verdict_of_this_head_merges(scenario):
    assert execute(scenario)["tested_sha"] == MERGED
    assert [m for m, _, _ in scenario[-1] if m == "PUT"] == ["PUT"]


@pytest.mark.parametrize(
    "comments, reason",
    [
        ([], "has not posted a verdict"),
        ([verdict("block")], "verdict is block"),
        ([verdict("approve", run=89)], "has not posted a verdict"),
        (
            [verdict("approve"), verdict("block", updated="2026-11-10T00:05:00Z")],
            "verdict is block",
        ),
        (
            [dict(verdict("approve"), user={"login": "owner", "type": "User"})],
            "has not posted a verdict",
        ),
    ],
)
def test_anything_but_an_approving_verdict_of_this_head_holds_the_merge(
    scenario, comments, reason
):
    scenario[3][("GET", COMMENTS_PATH)] = comments
    with pytest.raises(resolver.PostMergeError, match="merge held: .*" + reason):
        execute(scenario)
    assert_no_merge(scenario)


def test_a_head_no_review_ran_on_is_held(scenario):
    scenario[3][("GET", REVIEW_RUNS_PATH)] = {"workflow_runs": []}
    with pytest.raises(resolver.PostMergeError, match="no Claude review ran on this head"):
        execute(scenario)
    assert_no_merge(scenario)


def test_a_test_job_still_blocks_when_the_verdict_approves(scenario):
    next(
        job for job in scenario[3][("GET", JOBS_PATH)]["jobs"] if job["name"] == "unit"
    )["conclusion"] = "failure"
    with pytest.raises(resolver.PostMergeError, match="completed unit"):
        execute(scenario)
    assert_no_merge(scenario)


def test_extra_environment_variant_is_rejected(scenario):
    scenario[3][("GET", JOBS_PATH)]["jobs"].append(
        job_row("environment (other)", 900)
    )
    with pytest.raises(resolver.PostMergeError):
        execute(scenario)
    assert_no_merge(scenario)


def test_a_draft_is_never_merged(scenario):
    scenario[2]["draft"] = True
    with pytest.raises(resolver.PostMergeError, match="closed or draft"):
        execute(scenario)
    assert_no_merge(scenario)

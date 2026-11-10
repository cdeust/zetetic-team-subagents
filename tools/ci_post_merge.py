#!/usr/bin/env python3
"""Resolve a completed PR Pipeline to its protected merge commit.

The PR's required merge job validates eligibility. This workflow_run merges
synchronously after that check completes, without polling or rule bypass.
Sources:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run
https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PostMergeError(Exception):
    """The event cannot authorize a protected merge or a tested commit."""


class GitHub:
    def __init__(self, token: str):
        if not token:
            raise PostMergeError("GH_TOKEN is required")
        self.token = token

    def request(self, method: str, path: str, body=None):
        request = Request(
            "https://api.github.com" + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request) as response:
                return json.load(response)
        except HTTPError as exc:
            # Never print headers or the untrusted response body.
            raise PostMergeError(f"GitHub {method} {path}: HTTP {exc.code}") from exc
        except (URLError, ValueError) as exc:
            raise PostMergeError(
                f"GitHub {method} {path}: unreadable response"
            ) from exc

    def records(self, path: str, key: str | None = None):
        # Pagination only, not retries or polling. REST per_page maximum is 100.
        # https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            data = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            rows = data.get(key) if key and isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise PostMergeError("GitHub returned an invalid record list")
            yield from rows
            if len(rows) < 100:
                return
            page += 1


def require(condition, message):
    if not condition:
        raise PostMergeError(message)


def full_sha(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value),
        "GitHub did not return a full commit SHA",
    )
    return value


def _validate_run(run, repository):
    require(isinstance(run, dict), "missing workflow_run")
    require(run.get("event") == "pull_request", "source event is not pull_request")
    require(
        run.get("status") == "completed" and run.get("conclusion") == "success",
        "source Pipeline did not complete successfully",
    )
    require(
        run.get("head_repository", {}).get("full_name") == repository,
        "source head repository differs",
    )
    require(
        run.get("path") == ".github/workflows/pipeline.yml"
        and run.get("name") == "Pipeline",
        "source workflow differs",
    )
    require(
        run.get("head_branch") not in (None, "", "main"),
        "source must be a PR branch outside main",
    )
    require(type(run.get("id")) is int and run["id"] > 0, "invalid source run ID")
    require(
        type(run.get("run_attempt")) is int and run["run_attempt"] > 0,
        "invalid source run attempt",
    )
    full_sha(run.get("head_sha"))


def _validate_jobs(jobs):
    # Owner rule 2026-10-29: the required jobs are the tests and their
    # aggregate `merge`; the Claude verdict is read by
    # _review_approves. Overall success alone accepts skipped jobs.
    required = ["contract", "unit", "regression", "e2e", "merge"]
    for category in ("environment", "install"):
        expected = {
            f"{category} ({runner})"
            for runner in ("ubuntu-latest", "macos-latest", "windows-latest")
        }
        actual = [
            job.get("name", "")
            for job in jobs
            if job.get("name", "").startswith(category + " (")
        ]
        require(
            len(actual) == len(expected) and set(actual) == expected,
            f"source merge gate requires the exact {category} matrix",
        )
        required.extend(sorted(expected))
    for name in required:
        matching = [job for job in jobs if job.get("name") == name]
        require(
            len(matching) == 1, f"source merge gate requires exactly one {name} job"
        )
        job = matching[0]
        allowed = job.get("conclusion") == "success"
        require(
            job.get("status") == "completed" and allowed,
            f"source merge gate requires completed {name}",
        )


def _pr_identity(pr, repository, head):
    require(
        pr.get("head", {}).get("repo", {}).get("full_name") == repository,
        "PR head repository differs",
    )
    require(
        pr.get("base", {}).get("repo", {}).get("full_name") == repository
        and pr.get("base", {}).get("ref") == "main",
        "PR base is not this main",
    )
    require(pr.get("head", {}).get("sha") == head, "PR head advanced after testing")


def _effective_jobs(rows, run):
    # GitHub list-jobs filter=all includes jobs retained from earlier attempts.
    # source: https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run
    indexed, identities = {}, set()
    for job in rows:
        attempt, identity, name = job.get("run_attempt"), job.get("id"), job.get("name")
        require(type(attempt) is int and 0 < attempt <= run["run_attempt"],
                "invalid job attempt")
        require(type(identity) is int and identity > 0 and identity not in identities,
                "invalid or duplicate job identity")
        require(job.get("run_id") == run["id"] and job.get("head_sha") == run["head_sha"],
                "job source identity differs")
        require(isinstance(name, str), "invalid job name")
        identities.add(identity)
        previous = indexed.get(name)
        require(previous is None or previous["run_attempt"] != attempt,
                "duplicate job name in one attempt")
        if previous is None or attempt > previous["run_attempt"]:
            indexed[name] = job
    return list(indexed.values())


# source: .github/workflows/claude-review.yml, `name: PR Review`.
REVIEW_WORKFLOW_NAME = "PR Review"


def _pipeline_of_review(review, repository, api):
    """The successful Pipeline run of the head a completed review ran on.

    The review and the Pipeline finish in either order (ADR-1127). When the
    review ends last, its completion wakes the resolver, which then needs the
    Pipeline run of the same head: the newest one that succeeded. Without one
    the merge is held, and the Pipeline's own completion will wake the resolver.
    """
    require(
        review.get("path") == ".github/workflows/claude-review.yml"
        and review.get("event") == "pull_request"
        and review.get("status") == "completed"
        and review.get("conclusion") == "success",
        "source review did not complete successfully",
    )
    require(
        review.get("head_repository", {}).get("full_name") == repository,
        "source head repository differs",
    )
    head = full_sha(review.get("head_sha"))
    path = f"/repos/{repository}/actions/workflows/pipeline.yml/runs"
    runs = [
        run
        for run in api.records(
            f"{path}?head_sha={head}&event=pull_request&status=success",
            "workflow_runs",
        )
        if run.get("head_sha") == head and type(run.get("id")) is int
    ]
    require(runs, "merge held: Pipeline has not succeeded on this head")
    return max(runs, key=lambda run: run["id"])


def _source_run(event, repository, api):
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository),
        "invalid repository",
    )
    require(
        event.get("repository", {}).get("full_name") == repository,
        "event repository differs",
    )
    source = event.get("workflow_run")
    require(isinstance(source, dict), "missing workflow_run")
    prefix = f"/repos/{repository}"
    woken_by_review = source.get("name") == REVIEW_WORKFLOW_NAME
    if woken_by_review:
        source = _pipeline_of_review(source, repository, api)
    _validate_run(source, repository)
    run = api.request("GET", f"{prefix}/actions/runs/{source['id']}")
    _validate_run(run, repository)
    require(
        run["id"] == source["id"] and run["head_sha"] == source["head_sha"],
        "source run identity changed",
    )
    require(
        run.get("run_attempt") == source.get("run_attempt"),
        "source run has a newer attempt",
    )
    run["woken_by_review"] = woken_by_review
    jobs = _effective_jobs(
        api.records(f"{prefix}/actions/runs/{run['id']}/jobs?filter=all", "jobs"), run
    )
    _validate_jobs(jobs)
    return run


def _pull_request(run, repository, api):
    prefix = f"/repos/{repository}"
    # PR association can be empty; accept only one exact same-repository head.
    associations = run.get("pull_requests") or []
    if not associations:
        associations = [
            pr
            for pr in api.records(f"{prefix}/commits/{run['head_sha']}/pulls")
            if pr.get("head", {}).get("sha") == run["head_sha"]
            and pr.get("head", {}).get("repo", {}).get("full_name") == repository
            and pr.get("base", {}).get("ref") == "main"
            and pr.get("base", {}).get("repo", {}).get("full_name") == repository
        ]
    require(len(associations) == 1, "source run must identify exactly one PR")
    number = associations[0].get("number")
    require(type(number) is int and number > 0, "invalid PR number")
    pr = api.request("GET", f"{prefix}/pulls/{number}")
    _pr_identity(pr, repository, run["head_sha"])
    return number, pr


def _push_covers_commit(push, sha):
    if not (
        push.get("event") == "push"
        and push.get("head_sha") == sha
        and push.get("path") == ".github/workflows/pipeline.yml"
        and push.get("head_branch") == "main"
    ):
        return False
    return push.get("status") in (
        "queued",
        "in_progress",
        "waiting",
        "pending",
        "requested",
    ) or (
        push.get("status") == "completed"
        and push.get("conclusion") in ("success", "failure")
    )


def _has_push_pipeline(repository, sha, api):
    # Human merges normally have a push run already. Observe once; a
    # not-yet-visible push can cause duplicate tests, never skipped tests.
    pushes = api.records(
        f"/repos/{repository}/actions/workflows/pipeline.yml/runs?event=push&head_sha={sha}",
        "workflow_runs",
    )
    return any(_push_covers_commit(push, sha) for push in pushes)


def _ran_the_review(run, prefix, api):
    """True when this run's `Claude review` job executed the `PR Review` step."""
    jobs = api.records(f"{prefix}/actions/runs/{run['id']}/jobs", "jobs")
    return any(
        job.get("name") == "Claude review"
        and any(
            step.get("name") == "PR Review" and step.get("conclusion") == "success"
            for step in job.get("steps") or []
        )
        for job in jobs
    )


def _review_approves(number, head, repository, api):
    """The Claude review of this exact head decides the merge (ADR-1121).

    A verdict counts only when its comment links the run id of a claude-review.yml
    run of this head whose `PR Review` step succeeded. A review of an older head
    links another run, and a run that skipped the review (past the cap) has no
    such step, so neither can approve a newer head. The latest verdict wins.
    """
    prefix = f"/repos/{repository}"
    runs = [
        run
        for run in api.records(
            f"{prefix}/actions/workflows/claude-review.yml/runs?head_sha={head}",
            "workflow_runs",
        )
        if run.get("head_sha") == head and run.get("conclusion") == "success"
    ]
    reviewed = [run for run in runs if _ran_the_review(run, prefix, api)]
    require(reviewed, "merge held: no Claude review ran on this head")
    links = [f"/actions/runs/{run['id']}" for run in reviewed]
    verdicts = []
    for comment in api.records(f"{prefix}/issues/{number}/comments"):
        user = comment.get("user") or {}
        body = comment.get("body") or ""
        if user.get("login") != "claude[bot]" or user.get("type") != "Bot":
            continue
        if not any(re.search(re.escape(link) + r"(?!\d)", body) for link in links):
            continue
        found = re.findall(r"^Verdict: (approve|block)\s*$", body, re.M)
        if found:
            verdicts.append((comment["updated_at"], found[-1]))
    require(verdicts, "merge held: Claude has not posted a verdict on this head")
    require(max(verdicts)[1] == "approve", "merge held: Claude review verdict is block")


# Files a low-risk dependency update may touch (ADR-1126). Anything else, a
# workflow file first of all, keeps the PR on the reviewed path.
# source: the dependency manifests and locks of the ecosystems the consumers
# declare in .github/dependabot.yml (uv, npm, pnpm, cargo), matched by file
# name because each package carries its own manifest. requirements-dev.in/.txt
# is session-optimizer's uv-compiled pair (its dependabot.yml, uv ecosystem).
LOW_RISK_FILES = frozenset({
    "uv.lock", "pyproject.toml", "package-lock.json", "pnpm-lock.yaml",
    "package.json", "Cargo.lock", "Cargo.toml",
    "requirements-dev.in", "requirements-dev.txt",
})
# source: the `update-type` values Dependabot writes in its commit message,
# https://github.com/dependabot/fetch-metadata#outputs
LOW_RISK_UPDATES = frozenset(
    {"version-update:semver-minor", "version-update:semver-patch"}
)


def _declared_updates(commit):
    """Update types of one Dependabot commit, or None when it is not one.

    A git author is only a declared e-mail, and `verified` vouches for the
    committer's key. Dependabot's commits are committed and signed by GitHub
    itself (`web-flow`), where the author is the acting account and cannot be
    chosen. Every dependency the commit names must declare its update type.
    source: https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification
    """
    detail = commit.get("commit") or {}
    signed = (detail.get("verification") or {}).get("verified") is True
    author = (commit.get("author") or {}).get("login")
    committer = (commit.get("committer") or {}).get("login")
    if author != "dependabot[bot]" or committer != "web-flow" or not signed:
        return None
    message = detail.get("message") or ""
    updates = re.findall(r"^\s*update-type: (\S+)\s*$", message, re.M)
    names = re.findall(r"^\s*- dependency-name: ", message, re.M)
    return updates if updates and len(updates) == len(names) else None


def _is_low_risk(pr, repository, api):
    """True for a Dependabot minor or patch update of the dependency files.

    The tier comes from the change, not from a label or a title (ADR-1126): the
    PR is Dependabot's single commit (committed and signed by GitHub), every
    update it declares is minor or patch, and it touches nothing outside
    LOW_RISK_FILES. Such a PR merges on green required checks without a review.
    """
    user = pr.get("user") or {}
    if user.get("login") != "dependabot[bot]" or user.get("type") != "Bot":
        return False
    path = f"/repos/{repository}/pulls/{pr['number']}"
    commits = list(api.records(path + "/commits"))
    # Dependabot opens and rebases a PR as one commit; a second one is
    # someone else's work on its branch.
    if len(commits) != 1:
        return False
    updates = _declared_updates(commits[0])
    if updates is None or not set(updates) <= LOW_RISK_UPDATES:
        return False
    files = set()
    for row in api.records(path + "/files"):
        # A rename counts under both of its names.
        files |= {row.get("filename"), row.get("previous_filename")} - {None}
    names = {name.rsplit("/", 1)[-1] for name in files}
    # A workflow or action directory never holds a dependency manifest.
    if any(name.startswith(".github/") for name in files):
        return False
    return bool(files) and names <= LOW_RISK_FILES


def _merge_open_pr(pr, merge_path, head, api, repository):
    require(
        pr.get("state") == "open" and pr.get("draft") is False,
        "PR is closed or draft",
    )
    require("do not merge" not in pr.get("title", "").lower(), "PR title holds merge")
    require(
        not any(
            label.get("name", "").lower() in ("hold", "do-not-merge")
            for label in pr.get("labels", [])
        ),
        "PR label holds merge",
    )
    if _is_low_risk(pr, repository, api):
        print("post-merge: low-risk dependency update, no review required")
    else:
        _review_approves(pr["number"], head, repository, api)
    result = api.request(
        "PUT",
        merge_path,
        {"sha": head, "merge_method": "squash"},
    )
    require(result.get("merged") is True, "GitHub did not confirm a completed merge")
    return full_sha(result.get("sha"))


def _confirm_pr_merge(pr_path, original_pr, sha, api):
    # REST merge constrains only head SHA, not base ref. Re-read after PUT:
    # the PR must report this exact merge commit and the head that was tested.
    # https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request
    repository = original_pr["base"]["repo"]["full_name"]
    pr = api.request("GET", pr_path)
    _pr_identity(pr, repository, original_pr["head"]["sha"])
    require(
        pr.get("merged") is True and pr.get("merge_commit_sha") == sha,
        "PR does not confirm the returned merge commit",
    )


def resolve(event, repository: str, api: GitHub):
    run = _source_run(event, repository, api)
    number, pr = _pull_request(run, repository, api)
    pr_path = f"/repos/{repository}/pulls/{number}"
    already_merged = pr.get("merged") is True
    if already_merged:
        sha = full_sha(pr.get("merge_commit_sha"))
    else:
        sha = _merge_open_pr(pr, pr_path + "/merge", run["head_sha"], api, repository)
    _confirm_pr_merge(pr_path, pr, sha, api)
    if already_merged and _has_push_pipeline(repository, sha, api):
        return {
            "tested_sha": sha,
            "run_tests": "false",
            "pr_number": str(number),
            "reason": "An exact-SHA main push Pipeline already exists",
        }
    if already_merged and run.get("woken_by_review"):
        # The Pipeline's completion merged this PR and tests the merge commit.
        return {
            "tested_sha": sha,
            "run_tests": "false",
            "pr_number": str(number),
            "reason": "Already merged when the review completed",
        }
    return {
        "tested_sha": sha,
        "run_tests": "true",
        "pr_number": str(number),
        "reason": "Test the confirmed protected merge commit",
    }


# A merge that waits is not a failure of main: the review or the Pipeline of
# this head is not there yet, or a newer head has its own run. The run that
# brings the missing part wakes the resolver again (ADR-1127), so these end
# green with a notice instead of a red run on the default branch (ADR-1128).
WAITING = ("merge held:", "PR head advanced after testing")



def main():
    try:
        require(
            os.environ.get("GITHUB_EVENT_NAME") == "workflow_run",
            "resolver requires workflow_run",
        )
        event = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        result = resolve(
            event,
            os.environ["GITHUB_REPOSITORY"],
            GitHub(os.environ.get("GH_TOKEN", "")),
        )
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            for key, value in result.items():
                output.write(f"{key}={value}\n")
        print(
            f"PR #{result['pr_number']}: {result['reason']}; SHA {result['tested_sha']}"
        )
        return 0
    except PostMergeError as exc:
        if str(exc).startswith(WAITING):
            # No output is written: no downstream job runs, the run is green.
            print(f"::notice title=Merge not made::{exc}")
            return 0
        print(f"post-merge: {exc}", file=sys.stderr)
        return 1
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    ) as exc:
        print(f"post-merge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

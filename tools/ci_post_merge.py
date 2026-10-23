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


def _validate_jobs(jobs, actor):
    # Source: templates/ci/pipeline.yml, five categories and the existing
    # Dependabot review exception. Overall success alone accepts skipped jobs.
    required = ["contract", "unit", "regression", "e2e", "review", "merge"]
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
        allowed = job.get("conclusion") == "success" or (
            name == "review"
            and actor == "dependabot[bot]"
            and job.get("conclusion") == "skipped"
        )
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
    _validate_run(source, repository)
    prefix = f"/repos/{repository}"
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
    jobs = list(api.records(f"{prefix}/actions/runs/{run['id']}/jobs", "jobs"))
    _validate_jobs(jobs, run.get("actor", {}).get("login"))

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


def _merge_open_pr(pr, merge_path, head, api):
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
    result = api.request(
        "PUT",
        merge_path,
        {"sha": head, "merge_method": "squash"},
    )
    require(result.get("merged") is True, "GitHub did not confirm a completed merge")
    return full_sha(result.get("sha"))


def _confirm_main_merge(pr_path, original_pr, sha, api):
    # REST merge constrains only head SHA, not base ref. Re-read after PUT;
    # a retarget race must not authorize tests or release of a foreign merge.
    # https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request
    repository = original_pr["base"]["repo"]["full_name"]
    pr = api.request("GET", pr_path)
    _pr_identity(pr, repository, original_pr["head"]["sha"])
    require(
        pr.get("merged") is True and pr.get("merge_commit_sha") == sha,
        "PR does not confirm the returned merge commit",
    )
    # BASE...HEAD reports behind/identical only when HEAD is in BASE history.
    # https://docs.github.com/en/rest/commits/commits#compare-two-commits
    comparison = api.request(
        "GET", f"/repos/{repository}/compare/main...{full_sha(sha)}"
    )
    require(
        comparison.get("status") in ("behind", "identical")
        and comparison.get("merge_base_commit", {}).get("sha") == sha,
        "Merged commit is not confirmed in main history",
    )


def resolve(event, repository: str, api: GitHub):
    run = _source_run(event, repository, api)
    number, pr = _pull_request(run, repository, api)
    pr_path = f"/repos/{repository}/pulls/{number}"
    already_merged = pr.get("merged") is True
    if already_merged:
        sha = full_sha(pr.get("merge_commit_sha"))
    else:
        sha = _merge_open_pr(pr, pr_path + "/merge", run["head_sha"], api)
    _confirm_main_merge(pr_path, pr, sha, api)
    if already_merged and _has_push_pipeline(repository, sha, api):
        return {
            "tested_sha": sha,
            "run_tests": "false",
            "pr_number": str(number),
            "reason": "An exact-SHA main push Pipeline already exists",
        }
    return {
        "tested_sha": sha,
        "run_tests": "true",
        "pr_number": str(number),
        "reason": "Test the confirmed protected merge commit",
    }


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
    except (
        PostMergeError,
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

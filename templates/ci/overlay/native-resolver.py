def _native_pages(number, head, repository, api):
    owner, name = repository.split("/")
    variables = {"owner": owner, "repo": name, "pr": number}
    seen = set()
    while True:
        page = api.request("POST", "/graphql", {"query": QUERY, "variables": variables})
        yield page
        info = native_comments(page, head)["pageInfo"]
        if info["hasNextPage"] is False:
            return
        cursor = info["endCursor"]
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError("Invalid native review cursor")
        seen.add(cursor)
        variables = {**variables, "endCursor": cursor}


from urllib.parse import urlencode


def _trusted_routes(repository, api, created_at):
    # Only a default-branch workflow_run can attest the provider selected for
    # a PR workflow run and attempt. PR job names are controlled by the PR.
    prefix = f"/repos/{repository}/actions"
    route_path = ".github/workflows/review-subscription.yml"
    query = urlencode({"event": "workflow_run", "branch": "main", "created": ">=" + created_at})
    routes = {}
    for route in api.records(f"{prefix}/workflows/review-subscription.yml/runs?{query}", "workflow_runs"):
        if not (
            route.get("path") == route_path and route.get("event") == "workflow_run"
            and route.get("head_branch") == "main"
            and (route.get("head_repository") or {}).get("full_name") == repository
            and (route.get("repository") or {}).get("full_name") == repository
            and type(route.get("id")) is int and route["id"] > 0
        ):
            continue
        title = route["display_title"]
        if title not in routes or route["id"] > routes[title]["id"]:
            routes[title] = route
    return routes


def _route_provider(repository, api, route):
    if not route or route.get("status") != "completed" or route.get("conclusion") != "success":
        return None
    route_attempt = route.get("run_attempt")
    if type(route_attempt) is not int or route_attempt < 1:
        return None
    full_sha(route.get("head_sha"))
    prefix = f"/repos/{repository}/actions"
    jobs = api.records(f"{prefix}/runs/{route['id']}/attempts/{route_attempt}/jobs", "jobs")
    providers = {"Select Claude": "claude", "Request Codex": "codex", "Reuse Codex": "codex"}
    selected = [
        providers[step["name"]] for job in _effective_jobs(jobs, route)
        if job["name"] == "select" and job["run_attempt"] == route_attempt and _succeeded(job)
        for step in job.get("steps") or [] if step.get("name") in providers and _succeeded(step)
    ]
    return selected[0] if len(selected) == 1 else None


def _succeeded(record):
    return record.get("status") == "completed" and record.get("conclusion") == "success"


def _review_runs(number, head, repository, api):
    prefix = f"/repos/{repository}/actions"
    review_path = ".github/workflows/claude-review.yml"
    runs = [
        run for run in api.records(
            f"{prefix}/workflows/claude-review.yml/runs?head_sha={head}&event=pull_request",
            "workflow_runs",
        )
        if run.get("path") == review_path and run.get("event") == "pull_request"
        and run.get("head_sha") == head
        and (run.get("head_repository") or {}).get("full_name") == repository
        and (run.get("repository") or {}).get("full_name") == repository
        and [pr.get("number") for pr in run.get("pull_requests") or []] == [number]
        and type(run.get("id")) is int and run["id"] > 0
    ]
    return sorted(runs, key=lambda run: run["id"])


def _provider_admissions(runs, repository, api):
    routes = _trusted_routes(repository, api, min(run["created_at"] for run in runs))
    required, current = set(), {}
    for run in runs:
        attempt = run.get("run_attempt")
        require(type(attempt) is int and attempt > 0, "invalid review run attempt")
        for candidate in range(1, attempt + 1):
            title = f"Route PR Review {run['id']} attempt {candidate}"
            provider = _route_provider(repository, api, routes.get(title))
            if provider:
                required.add(provider)
                if candidate == attempt:
                    current[provider] = run
        if run is runs[-1]:
            require(run in current.values(), "merge held: latest review admission is unverified")
    return required, current


def _successful_review_job(provider, run, repository, api):
    if not _succeeded(run):
        return False
    job_name = {"claude": "Claude review", "codex": "Codex GitHub review"}[provider]
    attempt = run["run_attempt"]
    path = f"/repos/{repository}/actions/runs/{run['id']}/attempts/{attempt}/jobs"
    jobs = _effective_jobs(api.records(path, "jobs"), run)
    return any(
        job["name"] == job_name and job["run_attempt"] == attempt and _succeeded(job)
        and sum(step.get("name") == "PR Review" and _succeeded(step) for step in job.get("steps") or []) == 1
        for job in jobs
    )


def _admitted_claude_approves(number, run, repository, api):
    require(
        run and _successful_review_job("claude", run, repository, api),
        "merge held: no admitted Claude review ran on this head",
    )
    origin = f"https://github.com/{repository}/actions/runs/"
    link = f"]({origin}{run['id']}/attempts/{run['run_attempt']})"
    verdicts = []
    for comment in api.records(f"/repos/{repository}/issues/{number}/comments"):
        user, body = comment.get("user") or {}, comment.get("body") or ""
        if user.get("login") != "claude[bot]" or user.get("type") != "Bot" or link not in body:
            continue
        found = re.findall(r"^Verdict: (approve|block)\s*$", body, re.M)
        if found:
            verdicts.append((comment["updated_at"], found[-1]))
    require(verdicts, "merge held: no verdict from an admitted Claude attempt")
    require(max(verdicts)[1] == "approve", "merge held: Claude review verdict is block")


def _selected_review_approves(number, head, repository, api):
    runs = _review_runs(number, head, repository, api)
    require(runs, "merge held: no candidate review run on this PR head")
    required, admissions = _provider_admissions(runs, repository, api)
    if "codex" in required:
        verdict, _ = state(_native_pages(number, head, repository, api), head)
        require(verdict != "block", "merge held: native Codex review verdict is block")
        require(verdict == "approve", "merge held: native Codex verdict is pending")
        run = admissions.get("codex")
        require(
            run and _successful_review_job("codex", run, repository, api),
            "merge held: no admitted native Codex review ran on this head",
        )
    if "claude" in required:
        _admitted_claude_approves(number, admissions.get("claude"), repository, api)

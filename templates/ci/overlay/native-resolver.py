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


def _attempt_jobs(run, attempt, repository, api):
    path = f"/repos/{repository}/actions/runs/{run['id']}/attempts/{attempt}/jobs"
    jobs = list(api.records(path, "jobs"))
    require(all(job.get("run_attempt") == attempt for job in jobs), "job attempt differs")
    return _effective_jobs(jobs, run)


def _route_provider(repository, api, run, attempt, jobs):
    markers = [
        (step, re.fullmatch(r"Subscription decision run ([1-9][0-9]*)", step.get("name") or ""))
        for job in jobs if job["name"] == "Claude review budget" and _succeeded(job)
        for step in job.get("steps") or []
        if (step.get("name") or "").startswith("Subscription decision run ")
    ]
    if len(markers) != 1:
        return None
    step, match = markers[0]
    if not match or not _succeeded(step):
        return None
    route_id = int(match[1])
    prefix = f"/repos/{repository}/actions"
    route = api.request("GET", f"{prefix}/runs/{route_id}")
    if not (
        type(route.get("id")) is int and route["id"] == route_id
        and route.get("path") == ".github/workflows/review-subscription.yml"
        and route.get("event") == "workflow_run" and route.get("head_branch") == "main"
        and (route.get("head_repository") or {}).get("full_name") == repository
        and (route.get("repository") or {}).get("full_name") == repository
        and route.get("display_title") == f"Route PR Review {run['id']} attempt {attempt}"
        and type(route.get("run_attempt")) is int and route["run_attempt"] == 1
        and _succeeded(route)
    ):
        return None
    full_sha(route.get("head_sha"))
    providers = {"Select Claude": "claude", "Request Codex": "codex", "Reuse Codex": "codex"}
    selected = [
        providers[step["name"]] for job in _attempt_jobs(route, route["run_attempt"], repository, api)
        if job["name"] == "select" and _succeeded(job)
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
    admissions = []
    for run in runs:
        attempt = run.get("run_attempt")
        require(type(attempt) is int and attempt > 0, "invalid review run attempt")
        for candidate in range(1, attempt + 1):
            jobs = _attempt_jobs(run, candidate, repository, api)
            provider = _route_provider(repository, api, run, candidate, jobs)
            if provider:
                admissions.append((provider, run, candidate, {job["name"]: job for job in jobs}))
    latest = runs[-1]
    require(
        admissions and admissions[-1][1:3] == (latest, latest["run_attempt"]),
        "merge held: latest review admission is unverified",
    )
    return admissions


REVIEW_JOBS = {
    "claude": {
        "Claude review": ("PR Review",),
        "Verify Claude review verdict": ("Verify the verdict for this run",),
    },
    "codex": {
        "Codex GitHub review": ("PR Review",),
        "Verify native Codex review verdict": (
            "Read the OpenAI verdict from GitHub again", "Enforce the code review",
        ),
    },
}


def _verified_steps(job, expected_steps):
    steps = job.get("steps") or []
    for name in expected_steps:
        matches = [step for step in steps if step.get("name") == name]
        if len(matches) != 1 or not _succeeded(matches[0]):
            return False
    return True


def _verified_job(job, expected_steps):
    return _succeeded(job) and _verified_steps(job, expected_steps)


def _successful_review_job(provider, run, jobs):
    return _succeeded(run) and all(
        _verified_job(jobs.get(name, {}), steps) for name, steps in REVIEW_JOBS[provider].items()
    )


def _claude_verdicts(number, admissions, repository, api):
    origin = f"https://github.com/{repository}/actions/runs/"
    links = {
        f"]({origin}{run['id']}/attempts/{attempt})": (run["id"], attempt)
        for provider, run, attempt, _ in admissions if provider == "claude"
    }
    if not links:
        return {}
    verdicts = {}
    for comment in api.records(f"/repos/{repository}/issues/{number}/comments"):
        user, body = comment.get("user") or {}, comment.get("body") or ""
        if user.get("login") != "claude[bot]" or user.get("type") != "Bot":
            continue
        matched = [identity for link, identity in links.items() if link in body]
        found = re.findall(r"^Verdict: (approve|block)\s*$", body, re.M)
        if matched and found:
            require(len(matched) == 1 and len(found) == 1, "ambiguous Claude verdict evidence")
            verdicts.setdefault(matched[0], set()).add(found[0])
    return verdicts


def _selected_review_approves(number, head, repository, api):
    runs = _review_runs(number, head, repository, api)
    require(runs, "merge held: no candidate review run on this PR head")
    admissions = _provider_admissions(runs, repository, api)
    provider, run, attempt, jobs = admissions[-1]

    native = None
    if any(selected == "codex" for selected, _, _, _ in admissions):
        native, _ = state(_native_pages(number, head, repository, api), head)
        require(native != "block", "merge held: native Codex review verdict is block")
        require(native not in ("running", "queued"), "merge held: native Codex verdict is pending")
    claude = _claude_verdicts(number, admissions, repository, api)
    require(
        not any("block" in verdicts for verdicts in claude.values()),
        "merge held: Claude review verdict is block",
    )

    for previous_provider, previous_run, previous_attempt, previous_jobs in admissions[:-1]:
        if previous_provider == "codex" and native is None:
            require(
                not _verified_steps(
                    previous_jobs.get("Verify native Codex review verdict", {}),
                    ("Read the OpenAI verdict from GitHub again",),
                ),
                "merge held: historical native Codex verdict evidence is missing",
            )
        if previous_provider == "claude" and (previous_run["id"], previous_attempt) not in claude:
            require(
                not _verified_steps(
                    previous_jobs.get("Verify Claude review verdict", {}),
                    ("Verify the verdict for this run",),
                ),
                "merge held: historical Claude verdict evidence is missing",
            )

    if provider == "codex":
        require(native == "approve", "merge held: native Codex verdict is pending")
        require(
            _successful_review_job(provider, run, jobs),
            "merge held: no admitted native Codex review ran on this head",
        )
    else:
        require(
            _successful_review_job(provider, run, jobs),
            "merge held: no admitted Claude review ran on this head",
        )
        require(
            "approve" in claude.get((run["id"], attempt), ()),
            "merge held: no verdict from an admitted Claude attempt",
        )

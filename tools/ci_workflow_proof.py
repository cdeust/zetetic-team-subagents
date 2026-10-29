"""Authenticate the executed check definition through GitHub's run-file API.

Primary contract: https://docs.github.com/en/graphql/reference/actions#workflowrunfile
Candidate workflow contents are data only; no candidate program is executed.
"""
import base64
from collections.abc import Mapping
import re
from typing import Protocol, cast
from urllib.parse import quote

WORKFLOW = ".github/workflows/pipeline.yml"
SOURCE = "cdeust/zetetic-team-subagents"
PUBLISHED = "templates/ci/native/generated/pipeline.yml"
RUN_FILE_QUERY = """query($id: ID!) {
  node(id: $id) { ... on WorkflowRun {
    databaseId runAttempt
    file { path repositoryName repositoryFileUrl }
  } }
}"""


class GitHubAPI(Protocol):
    def request(
        self, method: str, path: str, body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]: ...


def _record(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError("invalid API object")
    return cast(Mapping[str, object], value)


def _contents(api: GitHubAPI, repository: str, path: str, ref: str) -> bytes:
    entry = api.request("GET", f"/repos/{repository}/contents/{path}?ref={quote(ref, safe='')}")
    content = entry.get("content")
    if (entry.get("type") != "file" or entry.get("encoding") != "base64"
            or not isinstance(content, str)):
        raise ValueError("definition unavailable")
    return base64.b64decode("".join(content.split()), validate=True)


def _executed_sha(run: Mapping[str, object], repository: str, api: GitHubAPI) -> str:
    node_id = run.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("run node missing")
    response = api.request("POST", "/graphql", {
        "query": RUN_FILE_QUERY, "variables": {"id": node_id},
    })
    if response.get("errors"):
        raise ValueError("GraphQL failed")
    node = _record(_record(response.get("data")).get("node"))
    if (type(node.get("databaseId")) is not int or type(node.get("runAttempt")) is not int
            or node["databaseId"] != run["id"] or node["runAttempt"] != run["run_attempt"]):
        raise ValueError("run identity differs")
    file = _record(node.get("file"))
    if file.get("repositoryName") != repository or file.get("path") != WORKFLOW:
        raise ValueError("source differs")
    url = file.get("repositoryFileUrl")
    if not isinstance(url, str):
        raise ValueError("file URL missing")
    match = re.fullmatch(
        r"https://github\.com/" + re.escape(repository) + r"/blob/([0-9a-f]{40})/"
        + re.escape(WORKFLOW), url,
    )
    if match is None:
        raise ValueError("immutable file identity missing")
    return match[1]


def authorize_workflow(
    run: Mapping[str, object], repository: str, api: GitHubAPI, error_type: type[Exception],
) -> None:
    """Authorize the exact executed definition or raise the resolver's error type."""
    try:
        sha = _executed_sha(run, repository, api)
        actual = _contents(api, repository, WORKFLOW, sha)
        installed = _contents(api, repository, WORKFLOW, "refs/heads/main")
        if actual != installed:
            published = _contents(api, SOURCE, PUBLISHED, "refs/heads/main")
            if actual != published:
                raise error_type("workflow proof definition is not trusted")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise error_type("workflow proof is unreadable or invalid") from exc

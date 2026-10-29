"""Authenticate the feedback passed to the automatic Claude Fix agent.

Sources: https://docs.github.com/en/graphql/reference/interfaces#comment
https://cli.github.com/manual/gh_api (paginated REST IDs, atomic GraphQL bodies).
"""

import json
import os
from pathlib import Path
import subprocess

# Source: GET /users/claude[bot] and /users/chatgpt-codex-connector[bot], 2026-10-29.
BOTS = {"BOT_kgDODIGtWg": "claude", "BOT_kgDOC98s_g": "chatgpt-codex-connector"}
ACTOR = "{ login __typename ... on User { id } ... on Bot { id } }"
FIELDS = f"id body lastEditedAt author {ACTOR} editor {ACTOR}"
NODES = "query($ids:[ID!]!) { nodes(ids:$ids) { " + " ".join(
    f"... on {kind} {{ {FIELDS} }}"
    for kind in ("IssueComment", "PullRequestReview", "PullRequestReviewComment")
) + " } }"
HEAD = """query($owner:String!,$name:String!,$number:Int!) {
  repository(owner:$owner,name:$name) {
    owner { id login __typename }
    pullRequest(number:$number) { headRefOid }
  }
}"""


def api(endpoint, fields=None, paginate=False):
    command = ["gh", "api", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    if fields is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(fields) if fields else None,
                            text=True, capture_output=True, check=True)
    value = json.loads(result.stdout)
    if isinstance(value, dict) and value.get("errors"):
        raise ValueError("graphql")
    return value


def trusted(actor, owner):
    if not isinstance(actor, dict):
        return False
    if actor == owner and actor.get("__typename") == "User":
        return True
    return (actor.get("__typename") == "Bot"
            and actor.get("id") in BOTS
            and BOTS.get(actor.get("id")) == actor.get("login"))


def authenticated(node, owner):
    if not isinstance(node, dict) or not trusted(node.get("author"), owner):
        return False
    if "editor" not in node or "lastEditedAt" not in node:
        raise ValueError("editor")
    if node["lastEditedAt"] is None:
        return node["editor"] is None
    # Even a trusted author cannot authenticate a body rewritten by another actor.
    return (isinstance(node["lastEditedAt"], str) and bool(node["lastEditedAt"])
            and node["editor"] == node["author"])


def head(repo, number, sha):
    owner, name = repo.split("/")
    result = api("graphql", {"query": HEAD, "variables": {
        "owner": owner, "name": name, "number": number,
    }})["data"]["repository"]
    if result["pullRequest"]["headRefOid"] != sha:
        raise ValueError("head_moved")
    identity = result["owner"]
    if identity.get("login") != owner or not identity.get("id"):
        raise ValueError("owner")
    return identity


def comment_nodes(repo, number):
    # REST per_page=100 is GitHub's documented maximum, not a heuristic limit.
    for resource in (f"issues/{number}/comments", f"pulls/{number}/comments",
                     f"pulls/{number}/reviews"):
        pages = api(f"repos/{repo}/{resource}?per_page=100", paginate=True)
        if not isinstance(pages, list):
            raise ValueError("pages")
        for page in pages:
            if not isinstance(page, list):
                raise ValueError("page")
            ids = [row["node_id"] for row in page]
            if not ids:
                continue
            nodes = api("graphql", {"query": NODES, "variables": {"ids": ids}})["data"]["nodes"]
            if len(nodes) != len(ids) or any(not isinstance(n, dict) for n in nodes):
                raise ValueError("nodes")
            if [n.get("id") for n in nodes] != ids:
                raise ValueError("identity")
            yield from nodes


def snapshot(repo, number, sha):
    owner = head(repo, number, sha)
    comments = []
    for node in comment_nodes(repo, number):
        if authenticated(node, owner):
            if not isinstance(node.get("body"), str):
                raise ValueError("body")
            comments.append({"id": node["id"], "author": node["author"]["login"],
                             "body": node["body"]})
    if head(repo, number, sha) != owner:
        raise ValueError("owner_changed")
    return {"head": sha, "comments": comments}


def main():
    try:
        result = snapshot(os.environ["GH_REPO"], int(os.environ["PR_NUMBER"]),
                          os.environ["HEAD_SHA"])
        Path(os.environ["FIX_CONTEXT"]).write_text(json.dumps(result), encoding="utf-8")
    except (KeyError, ValueError, TypeError, OSError, subprocess.SubprocessError):
        # Neither API payloads nor comment text belong in public error logs.
        raise SystemExit("Trusted fix context could not be authenticated") from None


if __name__ == "__main__":
    main()

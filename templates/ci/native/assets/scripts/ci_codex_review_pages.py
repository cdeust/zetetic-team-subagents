"""Normalize authenticated GraphQL comment pages and define their shared error."""

from __future__ import annotations

from typing import Any

Record = dict[str, Any]


class EvidenceError(ValueError):
    """Only fixed diagnostic categories may cross the CLI boundary."""


# Rule D5, 2026-10-29: Claude skips Dependabot (no Actions secrets, PR #224), so an absent
# marker agrees on a PR by GraphQL author dependabot/Bot on dependabot/* (prD evidence, PR212).
DEPENDABOT = {"login": "dependabot", "__typename": "Bot"}


class Comments(list):
    """Comment rows of one PR, read with its author from the same GraphQL node."""
    dependabot = False


# Body and edit attribution must come from the same authenticated API node.
# https://docs.github.com/en/graphql/reference/issues#issuecomment
COMMENTS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number headRefOid headRefName author { login __typename }
      comments(first:100, after:$endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          databaseId body updatedAt lastEditedAt
          author { login __typename ... on Bot { id } ... on User { id } }
          editor { login __typename ... on Bot { id } ... on User { id } }
        }
      }
    }
  }
}
"""


def _comment_row(node: Any) -> Record:
    keys = ("databaseId", "body", "updatedAt", "author", "editor", "lastEditedAt")
    if not isinstance(node, dict) or any(key not in node for key in keys):
        raise EvidenceError("protocol")
    identity = node["databaseId"]
    if type(identity) is not int or identity <= 0 or not isinstance(node["body"], str):
        raise EvidenceError("protocol")
    author = node["author"] or {}
    if not isinstance(author, dict):
        raise EvidenceError("protocol")
    login, kind = author.get("login"), author.get("__typename")
    if login in ("chatgpt-codex-connector", "claude") and kind == "Bot":
        login += "[bot]"  # REST form; GraphQL Bot logins omit it (prD evidence).
    return {
        "id": identity,
        "body": node["body"],
        "updated_at": node["updatedAt"],
        "user": {"login": login, "type": kind, "node_id": author.get("id")},
        "editor": node["editor"],
        "lastEditedAt": node["lastEditedAt"],
    }


def _comment_pages(pages: Any, sha: str, pr: int) -> list[Record]:
    if not isinstance(pages, list) or not pages:
        raise EvidenceError("protocol")
    rows, identities, cursors = Comments(), set(), set()
    try:
        for index, page in enumerate(pages):
            if page.get("errors"):
                raise EvidenceError("protocol")
            pull = page["data"]["repository"]["pullRequest"]
            if index == 0:  # Same node as the comments; absent fields mean not Dependabot.
                who, ref = pull.get("author"), str(pull.get("headRefName"))
                rows.dependabot = who == DEPENDABOT and ref.startswith("dependabot/")
            if pull["headRefOid"] != sha:
                raise EvidenceError("head_moved")
            if type(pull["number"]) is not int or pull["number"] != pr:
                raise EvidenceError("protocol")
            connection = pull["comments"]
            more, cursor = (
                connection["pageInfo"][key] for key in ("hasNextPage", "endCursor")
            )
            if type(more) is not bool or more != (index < len(pages) - 1):
                raise EvidenceError("protocol")
            if cursor is not None and (not isinstance(cursor, str) or not cursor):
                raise EvidenceError("protocol")
            if more and (cursor is None or cursor in cursors):
                raise EvidenceError("protocol")
            cursors.add(cursor)
            if not isinstance(connection["nodes"], list):
                raise EvidenceError("protocol")
            current = [_comment_row(node) for node in connection["nodes"]]
            current_ids = [row["id"] for row in current]
            if len(set(current_ids)) != len(current_ids) or identities.intersection(
                current_ids
            ):
                raise EvidenceError("protocol")
            identities.update(current_ids)
            rows.extend(current)
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceError("protocol") from exc
    return rows


def summary_comments(repo: str, pr: int, sha: str, request) -> list[Record]:
    owner, name = repo.split("/")
    fields = dict(query=COMMENTS_QUERY, owner=owner, name=name, number=pr)
    return _comment_pages(request("graphql", paginate=True, fields=fields), sha, pr)

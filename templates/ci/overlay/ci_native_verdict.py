"""Read native Codex code review state from complete GitHub GraphQL pages.

Connector identity and summary schema:
https://github.com/cdeust/ai-architect-mcp-spec/pull/391#issuecomment-7078116054
"""

import json

BOT = {"login": "chatgpt-codex-connector", "__typename": "Bot", "id": "BOT_kgDOC98s_g"}
SUMMARY = "<!-- codex-pull-request-review-summary -->"
PREFIX = "<!-- codex-review-state:v1 "
QUERY = """query($owner:String!, $repo:String!, $pr:Int!, $endCursor:String) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$pr) {
      headRefOid state isDraft
      comments(first:100, after:$endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes { body lastEditedAt author { __typename login ... on Bot { id } }
                editor { __typename login ... on Bot { id } } }
      }
    }
  }
}"""


def native_comments(page, sha, *, allow_draft_read=False):
    if page.get("errors"):
        raise ValueError("Unable to authenticate GitHub review")
    pull = page["data"]["repository"]["pullRequest"]
    if pull["headRefOid"] != sha or pull["state"] != "OPEN":
        raise ValueError("PR closed or head changed")
    if type(pull["isDraft"]) is not bool or (pull["isDraft"] and not allow_draft_read):
        raise ValueError("PR is a draft or draft state is unverified")
    return pull["comments"]


def state(pages, sha, *, allow_draft_read=False):
    """Return the authenticated exact-head verdict and whether CI requested it."""
    states = []
    requested = False
    more = True
    marker = f"@codex review\n\n<!-- ci-codex-review {sha} -->"
    for page in pages:
        if not more:
            raise ValueError("Unexpected native review page")
        comments = native_comments(page, sha, allow_draft_read=allow_draft_read)
        more = comments["pageInfo"]["hasNextPage"]
        if type(more) is not bool:
            raise ValueError("Invalid native review pagination")
        for row in comments["nodes"]:
            author, body = row["author"], row["body"]
            if author and author["__typename"] == "Bot" and author["login"] == "github-actions" and body == marker:
                requested = True
            if author != BOT or not body.startswith(SUMMARY + "\n"):
                continue
            expected_editor = None if row["lastEditedAt"] is None else BOT
            if row["editor"] != expected_editor:
                raise ValueError("Unverified editor of native Codex summary")
            line = body.split("\n", 2)[1]
            if not line.startswith(PREFIX) or not line.endswith(" -->"):
                raise ValueError("Native Codex review schema changed")
            review = json.loads(line[len(PREFIX):-4])["code_review"]
            if review is None or review["commit_sha"] != sha:
                continue
            status = review["status"]
            if status == "completed":
                flags = review.get("has_any_findings"), review.get("has_unresolved_findings")
                if any(type(flag) is not bool for flag in flags) or flags == (False, True):
                    raise ValueError("Invalid Codex findings")
                status = "block" if flags[1] else "approve"
            elif status not in {"running", "queued"}:
                raise ValueError("Codex did not complete a code review")
            states.append(status)
    if more:
        raise ValueError("Incomplete native review pagination")
    if len(states) > 1:
        raise ValueError("Ambiguous Codex review summaries")
    return (states[0] if states else None), requested

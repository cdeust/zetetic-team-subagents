"""Positive native clean-security receipts; unknown flags remain unchanged.

Source: https://github.com/cdeust/zetetic-team-subagents/pull/219#issuecomment-6491639753
The observed versioned format uses a ten-hex commit abbreviation and a 32-hex
opaque task suffix. A full SHA is also an exact binding. Abbreviations require
GitHub's unique commit resolution, never a prefix-only verdict.
"""

from datetime import datetime
import re

from ci_codex_review_comments import STAMP_PATTERN, _authenticate_editor, _bot_author
from ci_codex_review_runtime import EvidenceError

# source: native GraphQL actor on receipt6491639753 and summary6491366848.
BOT_NODE_ID = "BOT_kgDOC98s_g"
MARKER = "<!-- codex-review-receipt:v1 -->"
HEADING = "### 🛡️ Codex Security Review"
CLAIM = "Security review completed. No security issues were found in this pull request."
PREFIX = MARKER + "\n\n" + HEADING + "\n\n" + CLAIM + "\n\n"
NOTICE = "_Only the user who started this review can view the report in Codex._"


def _order(row):
    stamp, identity = row.get("updated_at"), row.get("id")
    if (not isinstance(stamp, str) or STAMP_PATTERN.fullmatch(stamp) is None
            or type(identity) is not int or identity <= 0):
        raise EvidenceError("protocol")
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")), identity
    except ValueError as exc:
        raise EvidenceError("protocol") from exc


def _authenticate(row):
    if not _bot_author(row) or row["user"].get("node_id") != BOT_NODE_ID:
        raise EvidenceError("protocol")
    _authenticate_editor(row)


def _eligible(target, current):
    repo, number, sha = target
    latest, review, metadata = current
    flags = (review.get("has_any_findings"), review.get("has_unresolved_findings"))
    body = latest["body"]
    if (re.search(r"(?im)^\s*#+\s*(?:Security\b|(?:Blocking|Advisory)\s+findings\b)", body)
            or "codex-security-review-finding:" in body):
        return False
    if (review.get("status") != "completed" or review.get("commit_sha") != sha
            or any(flag is True for flag in flags) or None not in flags
            or not isinstance(metadata, dict)
            or metadata.get("repository") != repo or type(metadata.get("pullRequestNumber")) is not int
            or metadata.get("pullRequestNumber") != number
            or metadata.get("headSha") != sha or metadata.get("status") != "completed"):
        return False
    return True


def _fields(body):
    required = (MARKER, CLAIM, "**Reviewed commit:**", "[View security finding report](",
                "https://chatgpt.com/codex/cloud/tasks/")
    if any(body.count(part) != 1 for part in required) or not body.rstrip().endswith("</details>"):
        raise EvidenceError("protocol")
    pattern = (re.escape(PREFIX)
               + r"\*\*Reviewed commit:\*\* `([0-9a-f]{10}|[0-9a-f]{40})`\n\n"
               + r"\[View security finding report\]\((https://chatgpt\.com/codex/cloud/tasks/task_e_[0-9a-f]{32})\)\n\n"
               + re.escape(NOTICE) + r"\n\n<details>")
    match = re.match(pattern, body)
    if match is None:
        raise EvidenceError("protocol")
    return match.groups()


def clean_security(target, comments, current, request):
    if not _eligible(target, current):
        return None
    candidates = [row for row in comments if _bot_author(row)
                  and row.get("body", "").startswith(MARKER) and HEADING in row["body"]]
    if not candidates:
        return None
    receipt = max(candidates, key=_order)
    _authenticate(current[0])
    _authenticate(receipt)
    abbreviation, report = _fields(receipt["body"])
    repo, _, sha = target
    if not sha.startswith(abbreviation):
        return None
    if abbreviation != sha:
        resolved = request(f"repos/{repo}/commits/{abbreviation}")
        if not isinstance(resolved, dict) or resolved.get("sha") != sha:
            raise EvidenceError("protocol")
    return dict(state="success", source="native_security_receipt", comment_id=receipt["id"],
                commit_sha=sha, report_url=report)

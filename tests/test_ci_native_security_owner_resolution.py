"""A security finding counts as resolved only when the trusted owner resolved it.

Codex finding session-optimizer PR87 discussion_r4412261213 (P2, 2026-10-29):
once Codex reports security findings, the summary can move to the explicit
verdict has_any_findings=true, has_unresolved_findings=false after a thread is
resolved. That explicit verdict skipped resolve_security(), so a thread a
non-owner resolved still read as success. The fixture is that PR's real
summary at aaf8b6d (2026-10-29T12:24:01Z), repository anonymized, with the
verdict the bot writes after resolution.
"""

import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

READER = (
    Path(__file__).resolve().parents[1]
    / "templates/ci/native/assets/scripts/ci_codex_reviews.py"
)
REPO, PR = "owner/project", 87
SHA = "aaf8b6d67fd2fe9f8bd78a9a16c552999ffbbd84"
FINDING_ID = 4412261213
BOT_ID = "BOT_kgDOC98s_g"
FINDING = "<!-- codex-security-review-finding:v1 -->"


def summary(unresolved):
    state = dict(
        code_review=dict(commit_sha=SHA, has_any_findings=False,
                         has_unresolved_findings=False, status="completed"),
        security_review=dict(commit_sha=SHA, has_any_findings=True,
                             has_unresolved_findings=unresolved, status="completed"),
    )
    metadata = dict(blockingSeverityThreshold="P0", headSha=SHA, mergeGateEnabled=False,
                    pullRequestNumber=PR, repository=REPO, status="completed")
    body = (
        "<!-- codex-pull-request-review-summary -->\n"
        "<!-- codex-review-state:v1 " + json.dumps(state, separators=(",", ":")) + " -->\n"
        "<!-- codex-security-review:v1 " + json.dumps(metadata, separators=(",", ":")) + " -->\n"
        "## Codex Review Summary\n\n"
        "This comment shows the latest Codex review activity on this pull request.\n\n"
        "### Security findings\n\n"
        "#### Advisory findings (1)\n\n"
        f"- 🟡 [Enforce owner attribution for explicit clean verdicts](https://github.com/{REPO}/pull/{PR}#discussion_r{FINDING_ID}) · **Medium**\n"
        "\n<details> <summary>ℹ️ About Codex in GitHub</summary>\n</details>"
    )
    return dict(
        id=1, updated_at="2026-10-29T12:24:01Z", body=body, editor=None, lastEditedAt=None,
        user=dict(login="chatgpt-codex-connector[bot]", type="Bot", node_id=BOT_ID),
    )


def threads(resolver, resolved=True):
    node = {
        "isResolved": resolved,
        "resolvedBy": None if resolver is None else {"login": resolver, "__typename": "User"},
        "comments": {"nodes": [{
            "databaseId": FINDING_ID,
            "body": FINDING + "\n\n### 🛡️ Codex Security Review\n",
            "author": {"login": "chatgpt-codex-connector", "__typename": "Bot"},
        }]},
    }
    connection = {"nodes": [node], "pageInfo": {"hasNextPage": False, "endCursor": None}}
    return [{"data": {"repository": {"pullRequest": {"headRefOid": SHA, "reviewThreads": connection}}}}]


def evidence(unresolved, pages):
    sys.modules.pop("ci_codex_review_comments", None)
    sys.modules.pop("ci_codex_review_runtime", None)
    spec = importlib.util.spec_from_file_location("codex_owner_reader", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.object(module.runtime, "_api", return_value=pages):
        return module.review_evidence([summary(unresolved)], SHA, REPO, PR)


class OwnerResolutionTests(unittest.TestCase):
    def test_explicit_clean_verdict_after_a_contributor_resolution_blocks(self):
        result = evidence(False, threads("contributor"))
        self.assertEqual((result["state"], result["reason"]), ("blocked", "review_unresolved"))
        self.assertEqual(result["security_review"]["resolution"]["finding_ids"], [FINDING_ID])

    def test_explicit_clean_verdict_after_the_owner_resolution_succeeds(self):
        result = evidence(False, threads("owner"))
        self.assertEqual((result["state"], result["reason"]), ("success", "reviews_complete"))
        self.assertEqual(result["security_review"]["resolution"]["source"], "github_review_threads")

    def test_explicit_clean_verdict_with_an_unresolved_thread_blocks(self):
        result = evidence(False, threads(None, resolved=False))
        self.assertEqual((result["state"], result["reason"]), ("blocked", "review_unresolved"))

    def test_explicit_unresolved_verdict_stays_blocked(self):
        result = evidence(True, threads("owner"))
        self.assertEqual((result["state"], result["reason"]), ("blocked", "review_unresolved"))


if __name__ == "__main__":
    unittest.main()

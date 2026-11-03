"""Codex's 👍 is the verdict of a clean security review whose flags stay null.

Observed from 2026-10-31 on (cortex-viz PR218 06:13:28Z, PR219 and PR220
07:38:47Z, PR216 11:13:00Z; Cortex PR838, PR840, PR846, PR847): Codex posts no
no-issues receipt comment any more and reacts 👍 on the PR once both reviews
finish with no findings; the summary keeps security_review flags null. PRs
reviewed before 2026-10-31 (cortex-viz PR207, PR212, PR217) carry neither. Port
of cdeust/Cortex PR847 (resolve_no_findings), 2026-11-03.

Rule: the receipt, when present, stays the verdict. When it is missing, a +1 by
the Codex Bot dated not earlier than both Completed rows of the summary for this
head (seconds; rows carry microseconds), no 👀 left, no finding text in the
summary and no unresolved native finding thread make the review clean. Anything
else keeps `codex_security_verdict_missing`; a malformed reaction payload or
stamp blocks as `protocol`.

| summary rows (head)      | reactions by Codex        | threads    | state, reason                             |
|--------------------------|---------------------------|------------|-------------------------------------------|
| Code + Security, head    | +1 at the Security stamp  | none       | success, reviews_complete (github_reaction)|
| Code + Security, head    | +1 one second earlier     | none       | blocked, codex_security_verdict_missing   |
| Code + Security, head    | +1 and 👀                 | none       | blocked, codex_security_verdict_missing   |
| Code + Security, head    | none / +1 by a person     | none       | blocked, codex_security_verdict_missing   |
| Security row other head  | +1 later                  | none       | blocked, missing; reactions never read    |
| rows + finding text      | +1 later                  | none       | blocked, missing; reactions never read    |
| Code + Security, head    | +1 later                  | one open   | blocked, codex_security_verdict_missing   |
| Code + Security, head    | malformed payload / stamp | none       | blocked, protocol                         |
| rows + no-issues receipt | none                      | none       | success (codex_security_receipt), no API  |
"""

import json
import sys
import unittest
from unittest.mock import patch

from test_ci_native_security_receipt import PR, REPO, VIZ213_SECURITY, VIZ_SHA, reader, row, summary

# source: Codex summary 6600075171 (Cortex PR848) table rows, head fbb77e7.
CODE_AT = "2026-11-03T09:40:53.973713Z"  # source: same summary, Code Review row
SECURITY_AT = "2026-11-03T09:42:30.868568Z"  # source: same summary, Security Review row
TABLE = (
    "\nThis comment shows the latest Codex review activity on this pull request.\n\n"
    "| Review | Status | Commit | Review trigger |\n| --- | --- | --- | --- |\n"
    '| 📝 **Code Review** | ✅ **Completed** <relative-time datetime="{code}">{code}'
    "</relative-time> | `{short}` | New commits |\n"
    '| 🔒 **Security Review** | ✅ **Completed** <relative-time datetime="{security}">{security}'
    "</relative-time> | `{short}` | New commits |\n\n"
)


def completed(sha=VIZ_SHA, short=None, code=CODE_AT, security=SECURITY_AT, extra=""):
    base = summary(sha)
    base["body"] += TABLE.format(code=code, security=security, short=short or sha[:7]) + extra
    return base


def reaction(content="+1", at="2026-11-03T09:42:30Z", login="chatgpt-codex-connector[bot]"):
    # source: GET /repos/{o}/{r}/issues/{n}/reactions row (Cortex PR847): the Codex
    # Bot is reported with type "User", so only the login identifies it.
    return {"content": content, "created_at": at, "user": {"login": login, "type": "User"}}


def thread(resolved, identity=4412420778):
    return {
        "isResolved": resolved,
        "resolvedBy": None,
        "comments": {"nodes": [{
            "databaseId": identity,
            "body": "<!-- codex-security-review-finding:v1 -->\nP2 finding",
            "author": {"login": "chatgpt-codex-connector", "__typename": "Bot"},
        }]},
    }


def threads_page(nodes, sha=VIZ_SHA):
    return {"data": {"repository": {"pullRequest": {
        "headRefOid": sha,
        "reviewThreads": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes},
    }}}}


class ReactionVerdictTests(unittest.TestCase):
    def evidence(self, rows, reactions=(), threads=(), raw=None, sha=VIZ_SHA):
        from test_ci_native_hold_lift import claude_row

        module = reader()
        runtime = sys.modules["ci_codex_review_runtime"]
        calls = []

        def api(endpoint, **options):
            calls.append(endpoint)
            if endpoint.endswith("/reactions"):
                return raw if raw is not None else [list(reactions)]
            if endpoint == "graphql":
                return [threads_page(list(threads), sha)]
            if endpoint.startswith(f"repos/{REPO}/commits/") and sha.startswith(endpoint.rsplit("/", 1)[1]):
                return {"sha": sha}  # the receipt's commit prefix resolves to the head
            raise runtime.APIError("not_found")

        with patch.object(runtime, "_api", side_effect=api):
            result = module.review_evidence([*rows, claude_row(sha)], sha, REPO, PR)
        return result, calls

    def assert_outcome(self, result, state, reason):
        self.assertEqual((result["state"], result["reason"]), (state, reason))
        self.assertEqual(result["reviews_complete"], state == "success")

    def test_thumbs_up_after_both_rows_is_the_verdict(self):
        result, calls = self.evidence([completed()], [reaction()])
        self.assert_outcome(result, "success", "reviews_complete")
        self.assertEqual(
            result["security_review"]["resolution"],
            {"source": "github_reaction", "reacted_at": "2026-11-03T09:42:30Z"},
        )
        self.assertEqual(calls, [f"repos/{REPO}/issues/{PR}/reactions", "graphql"])

    def test_thumbs_up_later_than_the_rows_counts(self):
        result, _ = self.evidence([completed()], [reaction(at="2026-11-03T11:13:00Z")])
        self.assert_outcome(result, "success", "reviews_complete")

    def test_thumbs_up_one_second_before_the_security_row_is_stale(self):
        result, _ = self.evidence([completed()], [reaction(at="2026-11-03T09:42:29Z")])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_eyes_still_present_means_a_review_is_running(self):
        rows = [reaction(), reaction("eyes", "2026-11-03T09:40:00Z")]
        result, _ = self.evidence([completed()], rows)
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_no_reaction_or_a_person_s_thumbs_up_proves_nothing(self):
        for reactions in ([], [reaction(login="someone")], [reaction("heart")]):
            with self.subTest(reactions=reactions):
                result, _ = self.evidence([completed()], reactions)
                self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_rows_for_another_head_never_read_the_reactions(self):
        result, calls = self.evidence([completed(short="1234567")], [reaction()])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")
        self.assertEqual(calls, [])

    def test_a_single_or_duplicated_row_is_not_a_completed_pair(self):
        one = completed()
        one["body"] = one["body"].replace("| 📝 **Code Review**", "| 📝 Code Review")
        result, calls = self.evidence([one], [reaction()])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")
        self.assertEqual(calls, [])

    def test_finding_text_in_the_summary_voids_the_clean_path(self):
        for text in ("\n### Security findings\n", "<!-- codex-security-review-finding:v1 -->"):
            with self.subTest(text=text):
                result, calls = self.evidence([completed(extra=text)], [reaction()])
                self.assert_outcome(result, "blocked", "codex_security_verdict_missing")
                self.assertEqual(calls, [])

    def test_an_unresolved_native_finding_thread_keeps_the_verdict_missing(self):
        result, _ = self.evidence([completed()], [reaction()], threads=[thread(False)])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_a_thread_resolved_by_someone_other_than_the_owner_is_unresolved(self):
        open_thread = thread(True)
        open_thread["resolvedBy"] = {"login": "someone", "__typename": "User"}
        result, _ = self.evidence([completed()], [reaction()], threads=[open_thread])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_malformed_reaction_payloads_block_as_protocol(self):
        for raw in ({"content": "+1"}, [{"content": "+1"}], [[{"content": 1, "user": {}}]],
                    [[{"content": "+1", "user": {"login": 5}}]]):
            with self.subTest(raw=raw):
                result, _ = self.evidence([completed()], raw=raw)
                self.assert_outcome(result, "blocked", "protocol")

    def test_malformed_stamps_block_as_protocol(self):
        for at in (None, 1, "2026-11-03 09:42:30Z", "2026-11-03T09:42:30+00:00", "2026-13-03T09:42:30Z"):
            with self.subTest(reaction_at=at):
                result, _ = self.evidence([completed()], [reaction(at=at)])
                self.assert_outcome(result, "blocked", "protocol")
        result, _ = self.evidence([completed(security="2026-13-03T09:42:30.1Z")], [reaction()])
        self.assert_outcome(result, "blocked", "protocol")

    def test_the_receipt_stays_the_verdict_and_the_reactions_are_not_read(self):
        result, calls = self.evidence([completed(), row(9, VIZ213_SECURITY)], [reaction()])
        self.assert_outcome(result, "success", "reviews_complete")
        self.assertEqual(result["security_review"]["resolution"]["source"], "codex_security_receipt")
        self.assertEqual(calls, [f"repos/{REPO}/commits/{VIZ213_SECURITY.split('`')[1]}"])

    def test_explicit_flags_never_consult_the_reaction(self):
        clean = dict(commit_sha=VIZ_SHA, status="completed", has_any_findings=False,
                     has_unresolved_findings=False)
        explicit = summary(VIZ_SHA, security=clean)
        explicit["body"] += TABLE.format(code=CODE_AT, security=SECURITY_AT, short=VIZ_SHA[:7])
        result, calls = self.evidence([explicit], [])
        self.assert_outcome(result, "success", "reviews_complete")
        self.assertNotIn("resolution", result["security_review"])
        self.assertEqual(calls, [])

    def test_metadata_for_another_head_never_reads_the_reactions(self):
        other = completed()
        other["body"] = other["body"].replace(
            json.dumps(VIZ_SHA)[1:-1] + '", "mergeGateEnabled"', "1" * 40 + '", "mergeGateEnabled"', 1
        )
        result, calls = self.evidence([other], [reaction()])
        self.assertEqual(result["state"], "pending")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

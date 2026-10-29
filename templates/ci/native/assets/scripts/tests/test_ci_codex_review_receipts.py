"""Positive native clean receipts bind unknown security to an exact commit.

Source: zetetic-team-subagents PR219 native comment6491639753 and summary6491366848.
"""

import json
import sys
import unittest
from unittest.mock import patch

from codex_resume_fixtures import SHA, OTHER, comment, state
from test_ci_codex_review_event_fixtures import REPO, load

REPORT = "https://chatgpt.com/codex/cloud/tasks/task_e_6ae300edae988324ab37463c77db3a49"


def receipt(sha=SHA, identity=91):
    row = comment(comment_id=identity, updated="2026-10-29T08:20:43Z")
    row["body"] = (
        "<!-- codex-review-receipt:v1 -->\n\n### 🛡️ Codex Security Review\n\n"
        "Security review completed. No security issues were found in this pull request.\n\n"
        f"**Reviewed commit:** `{sha[:10]}`\n\n"
        f"[View security finding report]({REPORT})\n\n"
        "_Only the user who started this review can view the report in Codex._\n\n"
        "<details> <summary>ℹ️ About Codex security reviews in GitHub</summary>\n"
        "<br/>\nThis is an experimental Codex feature.\n</details>"
    )
    return row


def summary():
    data = state()
    data["security_review"].update(has_any_findings=None, has_unresolved_findings=None)
    row = comment(data, comment_id=9, updated="2026-10-29T08:20:45Z")
    row["body"] += "\n<!-- codex-security-review:v1 " + json.dumps(dict(
        repository=REPO, pullRequestNumber=797, headSha=SHA, status="completed"
    )) + " -->"
    return row


class ExplicitCleanReceiptTests(unittest.TestCase):
    def read(self, rows=None, *, resolved=SHA, expected=SHA):
        load()
        reader = sys.modules["ci_codex_reviews"]
        with patch.object(reader.runtime, "_api", return_value={"sha": resolved}) as api:
            result = reader.review_evidence([summary(), receipt()] if rows is None else rows,
                                            expected, REPO, 797)
        return result, api.call_args_list

    def test_explicit_clean_receipt_resolves_unknown_without_changing_raw_flags(self):
        result, calls = self.read()
        self.assertEqual((result["state"], result["reviews_complete"]), ("success", True))
        security = result["security_review"]
        self.assertIsNone(security["has_any_findings"])
        self.assertIsNone(security["has_unresolved_findings"])
        self.assertEqual(security["resolution"], dict(source="native_security_receipt",
                         comment_id=91, commit_sha=SHA, report_url=REPORT))
        self.assertEqual(calls[0].args, (f"repos/{REPO}/commits/{SHA[:10]}",))

    def test_human_forgery_and_wrong_native_actor_cannot_resolve(self):
        for field, value in (("login", "human"), ("node_id", "other-bot")):
            row = receipt()
            row["user"][field] = value
            result, _ = self.read([summary(), row])
            self.assertFalse(result["reviews_complete"])
            self.assertNotEqual(result["state"], "success")

    def test_human_edited_native_receipt_fails_closed(self):
        row = receipt()
        row.update(editor=dict(login="writer", __typename="User", id="human"),
                   lastEditedAt="2026-10-29T08:20:43Z")
        result, _ = self.read([summary(), row])
        self.assertEqual(result["reason"], "editor")
        self.assertFalse(result["reviews_complete"])

    def test_stale_receipt_cannot_clear_current_head(self):
        result, calls = self.read([summary(), receipt(OTHER)])
        self.assertEqual((result["state"], result["reason"]),
                         ("blocked", "codex_security_verdict_missing"))
        self.assertEqual(calls, [])

    def test_companion_summary_metadata_must_bind_exact_repo_pr_and_sha(self):
        for old, new in ((REPO, "other/repo"), ('"pullRequestNumber": 797', '"pullRequestNumber": 798'),
                         (f'"headSha": "{SHA}"', f'"headSha": "{OTHER}"'),
                         ('"status": "completed"} -->', '"status": "running"} -->')):
            row = summary()
            row["body"] = row["body"].replace(old, new)
            result, calls = self.read([row, receipt()])
            self.assertFalse(result["reviews_complete"])
            self.assertEqual(calls, [])

    def test_truncated_commit_receipt_and_report_are_rejected(self):
        for old, new in ((SHA[:10], SHA[:9]), ("task_e_6ae300edae988324ab37463c77db3a49", "task_e_6ae3"),
                         ("No security issues were found in this pull request.", "No security issues")):
            row = receipt()
            row["body"] = row["body"].replace(old, new)
            result, _ = self.read([summary(), row])
            self.assertFalse(result["reviews_complete"])
            self.assertNotEqual(result["state"], "success")

    def test_multiple_or_foreign_reports_cannot_establish_clean(self):
        for body in (receipt()["body"] + f"\n[View security finding report]({REPORT})",
                     receipt()["body"].replace("https://chatgpt.com/", "https://attacker.invalid/"),
                     receipt()["body"] + f"\n**Reviewed commit:** `{OTHER[:10]}`"):
            row = receipt()
            row["body"] = body
            result, _ = self.read([summary(), row])
            self.assertFalse(result["reviews_complete"])
            self.assertNotEqual(result["state"], "success")

    def test_abbreviated_commit_must_resolve_uniquely_to_expected_full_sha(self):
        result, _ = self.read(resolved=OTHER)
        self.assertFalse(result["reviews_complete"])
        self.assertNotEqual(result["state"], "success")

    def test_commit_lookup_api_error_cannot_clear_the_review(self):
        load()
        reader = sys.modules["ci_codex_reviews"]
        with patch.object(reader.runtime, "_api", side_effect=reader.runtime.APIError("not_found")):
            result = reader.review_evidence([summary(), receipt()], SHA, REPO, 797)
        self.assertEqual(result["reason"], "api")
        self.assertFalse(result["reviews_complete"])

    def test_running_review_cannot_be_overridden_by_older_clean_receipt(self):
        row = summary()
        body, metadata = row["body"].split("<!-- codex-security-review:v1 ", 1)
        body = body.replace('"status": "completed"', '"status": "running"')
        row["body"] = body + "<!-- codex-security-review:v1 " + metadata
        result, calls = self.read([row, receipt()])
        self.assertEqual((result["state"], result["reason"]), ("pending", "review_pending"))
        self.assertEqual(calls, [])

    def test_positive_findings_with_unknown_resolution_cannot_use_clean_receipt(self):
        row = summary()
        row["body"] = row["body"].replace('"has_any_findings": null', '"has_any_findings": true')
        result, calls = self.read([row, receipt()])
        self.assertFalse(result["reviews_complete"])
        self.assertEqual(calls, [])

    def test_current_announced_findings_override_older_clean_receipt_with_null_flags(self):
        row = summary()
        row["body"] += (
            "\n### Security findings\n#### Blocking findings (1)\n"
            f"- [P1 current finding](https://github.com/{REPO}/pull/797#discussion_r123)\n"
        )
        load()
        runtime = sys.modules["ci_codex_review_runtime"]
        self.assertEqual(runtime._announced(row["body"], REPO, 797), {123})
        result, calls = self.read([row, receipt()])
        self.assertFalse(result["reviews_complete"])
        self.assertNotEqual(result["state"], "success")
        self.assertEqual(calls, [])

    def test_malformed_or_incomplete_security_sections_cannot_use_old_clean(self):
        sections = (
            "\n### Security findings\n",
            "\n### Security findings\n#### Blocking findings (2)\n- missing identity\n",
            "\n### Security findings\n#### Blocking findings (0)\n",
            "\n### Security\n- truncated findings section\n",
            "\n#### Blocking findings (1)\n- missing security heading\n",
        )
        for section in sections:
            row = summary()
            row["body"] += section
            result, calls = self.read([row, receipt()])
            self.assertFalse(result["reviews_complete"], section)
            self.assertNotEqual(result["state"], "success", section)
            self.assertEqual(calls, [], section)

    def test_positive_unresolved_verdict_is_never_overridden_by_clean_receipt(self):
        data = state()
        data["security_review"].update(has_any_findings=True, has_unresolved_findings=True)
        row = comment(data, comment_id=9, updated="2026-10-29T08:20:45Z")
        result, calls = self.read([row, receipt()])
        self.assertEqual((result["state"], result["reason"]), ("blocked", "review_unresolved"))
        self.assertEqual(calls, [])

    def test_newer_truncated_native_receipt_prevents_fallback_to_old_clean(self):
        newer = receipt(identity=92)
        newer["updated_at"] = "2026-10-29T08:20:44Z"
        newer["body"] = newer["body"].split("**Reviewed commit:**")[0]
        result, _ = self.read([summary(), receipt(), newer])
        self.assertFalse(result["reviews_complete"])
        self.assertNotEqual(result["state"], "success")

    def test_new_head_cannot_reuse_old_clean_receipt(self):
        result, calls = self.read(expected=OTHER)
        self.assertEqual((result["state"], result["reason"]), ("pending", "review_pending"))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

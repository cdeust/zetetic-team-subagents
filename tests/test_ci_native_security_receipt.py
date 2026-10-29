"""A completed native security review whose verdict flags stay null.

Observed 2026-10-29: Codex posted an authenticated receipt "No security issues
were found" bound to the head commit while the summary kept security_review
has_any_findings/has_unresolved_findings null (cortex-viz PR213 summary6489153112
+ receipt6491350304). A survey of 36 cdeust PRs found 13 security receipts, all
with that sentence; two automatic ones carry "· _Automatically triggered_".
Rule: a no-issues receipt for the head is the verdict; no receipt blocks as
codex_security_verdict_missing; any other security receipt for the head blocks
as codex_security_receipt_unrecognized; explicit flags keep their own path.
"""

import importlib.util
import json
from pathlib import Path
import sys
import unittest

READER = (
    Path(__file__).resolve().parents[1]
    / "templates/ci/native/assets/scripts/ci_codex_reviews.py"
)
REPO, PR = "cdeust/cortex-viz", 213
VIZ_SHA = "522f87761d1bd383bb6869dd861722a8da32dad3"
BOT_ID = "BOT_kgDOC98s_g"
# Real receipts: (constant, head SHA resolved through the commits API).
REAL = (
    ("VIZ213_SECURITY", VIZ_SHA),
    ("CORTEX829_SECURITY", "1eff1fa2ccfa02d886cd264dc71823807033e649"),
    ("CORTEX830_SECURITY", "3d3e4f904136bd795a3f4ed3957cafc5ae12f5cf"),
    ("SPEC163_AUTOMATIC", "cd430769691fab3b9503db5de01a679d0f4fd307"),
    ("MODS52_SECURITY", "236b188bb408a93d90c7fccdcc19c557a2334055"),
    ("MODS51_SECURITY", "ec9bbc76ae9f954570122a0f93f85fb25cde5bdd"),
)

# source: comment 6491350304 (2026-10-29T08:05:20Z)
VIZ213_SECURITY = (
    '<!-- codex-review-receipt:v1 -->\n'
    '\n'
    '### 🛡️ Codex Security Review\n'
    '\n'
    'Security review completed. No security issues were found in this pull request.\n'
    '\n'
    '**Reviewed commit:** `522f87761d`\n'
    '\n'
    '[View security finding report](https://chatgpt.com/codex/cloud/tasks/task_e_6ae2fd3e2a24832494511b474309fb0e)\n'
    '\n'
    '_Only the user who started this review can view the report in Codex._\n'
    '\n'
    '<details> <summary>ℹ️ About Codex security reviews in GitHub</summary>\n'
    '<br/>\n'
    '\n'
    'This is an experimental Codex feature. Security reviews are triggered when:\n'
    '- You comment "@codex security review"\n'
    '- A regular code review gets triggered (for example, "@codex review" or when a PR is opened), and you’re opted in so security review runs alongside code review\n'
    '\n'
    'Once complete, Codex will leave suggestions, or a comment if no findings are found.\n'
    '\n'
    '\n'
    '</details>'
)
# source: comment 6491478435 (2026-10-29T08:12:05Z)
CORTEX829_SECURITY = (
    '<!-- codex-review-receipt:v1 -->\n'
    '\n'
    '### 🛡️ Codex Security Review\n'
    '\n'
    'Security review completed. No security issues were found in this pull request.\n'
    '\n'
    '**Reviewed commit:** `1eff1fa2cc`\n'
    '\n'
    '[View security finding report](https://chatgpt.com/codex/cloud/tasks/task_e_6ae2ff2f9fd48324863445f87629620c)\n'
    '\n'
    '_Only the user who started this review can view the report in Codex._\n'
    '\n'
    '<details> <summary>ℹ️ About Codex security reviews in GitHub</summary>\n'
    '<br/>\n'
    '\n'
    'This is an experimental Codex feature. Security reviews are triggered when:\n'
    '- You comment "@codex security review"\n'
    '- A regular code review gets triggered (for example, "@codex review" or when a PR is opened), and you’re opted in so security review runs alongside code review\n'
    '\n'
    'Once complete, Codex will leave suggestions, or a comment if no findings are found.\n'
    '\n'
    '\n'
    '</details>'
)
# source: comment 6491289198 (2026-10-29T08:02:03Z)
VIZ209_CODE = (
    '<!-- codex-review-receipt:v1 -->\n'
    '\n'
    "Codex Review: Didn't find any major issues. Delightful!\n"
    '\n'
    '**Reviewed commit:** `25ed89d367`\n'
    '\n'
    '<details> <summary>ℹ️ About Codex in GitHub</summary>\n'
    '<br/>\n'
    '\n'
    '[Your team has set up Codex to review pull requests in this repo](https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you\n'
    '- Open a pull request for review\n'
    '- Mark a draft as ready\n'
    '- Comment "@codex review".\n'
    '\n'
    'If Codex has suggestions, it will comment; otherwise it will react with 👍.\n'
    '\n'
    '\n'
    '\n'
    '\n'
    'Codex can also answer questions or update the PR. Try commenting "@codex address that feedback".\n'
    '            \n'
    '</details>'
)
# source: comment 6491660443 (2026-10-29T08:21:52Z)
SPEC163_AUTOMATIC = (
    '<!-- codex-review-receipt:v1 -->\n'
    '\n'
    '### 🛡️ Codex Security Review · _Automatically triggered_\n'
    '\n'
    'Security review completed. No security issues were found in this pull request.\n'
    '\n'
    '**Reviewed commit:** `cd43076969`\n'
    '\n'
    '[View security finding report](https://chatgpt.com/codex/cloud/tasks/task_e_6ae3015e63f083248b7236ad84ab018f)\n'
    '\n'
    '_Only the user who started this review can view the report in Codex._\n'
    '\n'
    '<details> <summary>ℹ️ About Codex security reviews in GitHub</summary>\n'
    '<br/>\n'
    '\n'
    'This is an experimental Codex feature. Security reviews are triggered when:\n'
    '- You comment "@codex security review"\n'
    '- A regular code review gets triggered (for example, "@codex review" or when a PR is opened), and you’re opted in so security review runs alongside code review\n'
    '\n'
    'Once complete, Codex will leave suggestions, or a comment if no findings are found.\n'
    '\n'
    '\n'
    '</details>'
)
# source: comment 6491726092 (2026-10-29T08:25:28Z)
CORTEX830_SECURITY = (
    '<!-- codex-review-receipt:v1 -->\n'
    '\n'
    '### 🛡️ Codex Security Review\n'
    '\n'
    'Security review completed. No security issues were found in this pull request.\n'
    '\n'
    '**Reviewed commit:** `3d3e4f9041`\n'
    '\n'
    '[View security finding report](https://chatgpt.com/codex/cloud/tasks/task_e_6ae3024f122c83248e4f12908c9fb99a)\n'
    '\n'
    '_Only the user who started this review can view the report in Codex._\n'
    '\n'
    '<details> <summary>ℹ️ About Codex security reviews in GitHub</summary>\n'
    '<br/>\n'
    '\n'
    'This is an experimental Codex feature. Security reviews are triggered when:\n'
    '- You comment "@codex security review"\n'
    '- A regular code review gets triggered (for example, "@codex review" or when a PR is opened), and you’re opted in so security review runs alongside code review\n'
    '\n'
    'Once complete, Codex will leave suggestions, or a comment if no findings are found.\n'
    '\n'
    '\n'
    '</details>'
)
# source: comment 6491339392 (2026-10-29T08:04:46Z)
MODS52_SECURITY = (
    '<!-- codex-review-receipt:v1 -->\n'
    '\n'
    '### 🛡️ Codex Security Review\n'
    '\n'
    'Security review completed. No security issues were found in this pull request.\n'
    '\n'
    '**Reviewed commit:** `236b188bb4`\n'
    '\n'
    '[View security finding report](https://chatgpt.com/codex/cloud/tasks/task_e_6ae2fcf54c1c83248da0ecadcb843d91)\n'
    '\n'
    '_Only the user who started this review can view the report in Codex._\n'
    '\n'
    '<details> <summary>ℹ️ About Codex security reviews in GitHub</summary>\n'
    '<br/>\n'
    '\n'
    'This is an experimental Codex feature. Security reviews are triggered when:\n'
    '- You comment "@codex security review"\n'
    '- A regular code review gets triggered (for example, "@codex review" or when a PR is opened), and you’re opted in so security review runs alongside code review\n'
    '\n'
    'Once complete, Codex will leave suggestions, or a comment if no findings are found.\n'
    '\n'
    '\n'
    '</details>'
)
# source: comment 6492031296 (2026-10-29T08:41:05Z)
MODS51_SECURITY = (
    '<!-- codex-review-receipt:v1 -->\n'
    '\n'
    '### 🛡️ Codex Security Review\n'
    '\n'
    'Security review completed. No security issues were found in this pull request.\n'
    '\n'
    '**Reviewed commit:** `ec9bbc76ae`\n'
    '\n'
    '[View security finding report](https://chatgpt.com/codex/cloud/tasks/task_e_6ae305f474ec83248d488404eb5aed7b)\n'
    '\n'
    '_Only the user who started this review can view the report in Codex._\n'
    '\n'
    '<details> <summary>ℹ️ About Codex security reviews in GitHub</summary>\n'
    '<br/>\n'
    '\n'
    'This is an experimental Codex feature. Security reviews are triggered when:\n'
    '- You comment "@codex security review"\n'
    '- A regular code review gets triggered (for example, "@codex review" or when a PR is opened), and you’re opted in so security review runs alongside code review\n'
    '\n'
    'Once complete, Codex will leave suggestions, or a comment if no findings are found.\n'
    '\n'
    '\n'
    '</details>'
)


def reader():
    sys.modules.pop("ci_codex_review_comments", None)
    sys.modules.pop("ci_codex_review_runtime", None)
    spec = importlib.util.spec_from_file_location("codex_receipt_reader", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summary(sha, security=None, metadata=None, stamp="2026-10-29T08:05:22Z"):
    code = dict(
        commit_sha=sha, status="completed", has_any_findings=False,
        has_unresolved_findings=False,
    )
    security = security or dict(
        commit_sha=sha, status="completed", has_any_findings=None,
        has_unresolved_findings=None,
    )
    metadata = metadata or dict(
        blockingSeverityThreshold="P0", headSha=sha, mergeGateEnabled=False,
        pullRequestNumber=PR, repository=REPO, status="completed",
    )
    body = (
        "<!-- codex-pull-request-review-summary -->\n"
        "<!-- codex-review-state:v1 "
        + json.dumps(dict(code_review=code, security_review=security))
        + " -->\n<!-- codex-security-review:v1 "
        + json.dumps(metadata)
        + " -->\n## Codex Review Summary\n"
    )
    return row(1, body, stamp=stamp)


def row(identity, body, **fields):
    """One normalized comment row; fields: stamp, login, kind, editor, edited."""
    return dict(
        id=identity,
        updated_at=fields.get("stamp", "2026-10-29T08:05:20Z"),
        body=body,
        editor=fields.get("editor"),
        lastEditedAt=fields.get("edited"),
        user=dict(
            login=fields.get("login", "chatgpt-codex-connector[bot]"),
            type=fields.get("kind", "Bot"),
            node_id=BOT_ID,
        ),
    )


class SecurityReceiptTests(unittest.TestCase):
    def evidence(self, rows, sha=VIZ_SHA):
        # Owner rule 2026-10-29: a mergeable head also carries Claude's verdict.
        from test_ci_native_hold_lift import claude_row

        return reader().review_evidence([*rows, claude_row(sha)], sha, REPO, PR)

    def assert_outcome(self, result, state, reason):
        self.assertEqual((result["state"], result["reason"]), (state, reason))
        self.assertEqual(result["reviews_complete"], state == "success")

    def test_every_real_no_issues_receipt_is_the_verdict(self):
        for name, sha in REAL:
            with self.subTest(receipt=name):
                result = self.evidence([summary(sha), row(9, globals()[name])], sha)
                self.assert_outcome(result, "success", "reviews_complete")
                self.assertEqual(
                    result["security_review"]["resolution"],
                    {"source": "codex_security_receipt", "receipt_ids": [9]},
                )
                self.assertIsNone(result["security_review"]["has_any_findings"])

    def test_null_verdict_without_receipt_is_named_missing(self):
        result = self.evidence([summary(VIZ_SHA)])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_code_review_receipt_is_not_security_proof(self):
        body = VIZ209_CODE.replace("25ed89d367", VIZ_SHA[:10])
        result = self.evidence([summary(VIZ_SHA), row(9, body)])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_receipt_for_another_commit_is_ignored(self):
        result = self.evidence([summary(VIZ_SHA), row(9, CORTEX829_SECURITY)])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_human_copy_of_the_receipt_is_ignored(self):
        copy = row(9, VIZ213_SECURITY, login="someone", kind="User")
        result = self.evidence([summary(VIZ_SHA), copy])
        self.assert_outcome(result, "blocked", "codex_security_verdict_missing")

    def test_receipt_edited_by_a_human_blocks(self):
        human = dict(login="someone", __typename="User", id="U_1")
        edited = row(9, VIZ213_SECURITY, editor=human, edited="2026-10-29T08:06:00Z")
        result = self.evidence([summary(VIZ_SHA), edited])
        self.assert_outcome(result, "blocked", "editor")

    def test_unconfirmed_metadata_stays_pending(self):
        metadata = dict(
            headSha="1eff1fa2ccfa02d886cd264dc71823807033e649",
            pullRequestNumber=PR, repository=REPO, status="completed",
        )
        rows = [summary(VIZ_SHA, metadata=metadata), row(9, VIZ213_SECURITY)]
        self.assert_outcome(self.evidence(rows), "pending", "review_pending")

    def test_unrecognized_security_receipt_blocks_by_name(self):
        contrary = VIZ213_SECURITY.replace(
            "Security review completed. No security issues were found in this pull request.",
            "Security review completed. 1 security issue was found.",
        )
        rows = [summary(VIZ_SHA), row(8, VIZ213_SECURITY), row(9, contrary)]
        result = self.evidence(rows)
        self.assert_outcome(result, "blocked", "codex_security_receipt_unrecognized")
        self.assertEqual(result["security_review"]["resolution"]["receipt_ids"], [9])

    def test_contradictory_verdict_after_the_sentence_is_unrecognized(self):
        # Codex finding4411675624: presence of the sentence is not the verdict.
        body = VIZ213_SECURITY.replace(
            "found in this pull request.\n",
            "found in this pull request.\n\n1 security issue was found.\n",
            1,
        )
        result = self.evidence([summary(VIZ_SHA), row(9, body)])
        self.assert_outcome(result, "blocked", "codex_security_receipt_unrecognized")

    def test_text_added_anywhere_in_the_receipt_is_unrecognized(self):
        body = VIZ213_SECURITY.replace(
            "</details>", "</details>\n\nA blocking security issue was found.", 1
        )
        result = self.evidence([summary(VIZ_SHA), row(9, body)])
        self.assert_outcome(result, "blocked", "codex_security_receipt_unrecognized")

    def test_receipt_never_overrides_a_running_review(self):
        running = dict(
            commit_sha=VIZ_SHA, status="running", has_any_findings=None,
            has_unresolved_findings=None,
        )
        rows = [summary(VIZ_SHA, security=running), row(9, VIZ213_SECURITY)]
        self.assert_outcome(self.evidence(rows), "pending", "review_pending")

    def test_receipt_never_overrides_explicit_findings(self):
        found = dict(
            commit_sha=VIZ_SHA, status="completed", has_any_findings=True,
            has_unresolved_findings=True,
        )
        rows = [summary(VIZ_SHA, security=found), row(9, VIZ213_SECURITY)]
        result = self.evidence(rows)
        # An explicit unresolved verdict is a complete review (existing contract).
        self.assertEqual(
            (result["state"], result["reason"], result["reviews_complete"]),
            ("blocked", "review_unresolved", True),
        )

    def test_explicit_clean_verdict_needs_no_receipt(self):
        clean = dict(
            commit_sha=VIZ_SHA, status="completed", has_any_findings=False,
            has_unresolved_findings=False,
        )
        result = self.evidence([summary(VIZ_SHA, security=clean)])
        self.assert_outcome(result, "success", "reviews_complete")


EVENT_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "templates/ci/native/assets/scripts/ci_codex_review_event_source.py"
)


class ReceiptEventTests(unittest.TestCase):
    """Codex finding4411383156: a receipt event must reach gate resumption."""

    def canonical(self):
        sys.path.insert(0, str(EVENT_SOURCE.parent))
        try:
            for name in ("ci_codex_review_comments", "ci_codex_review_runtime",
                         "ci_codex_reviews"):
                sys.modules.pop(name, None)
            spec = importlib.util.spec_from_file_location("receipt_event", EVENT_SOURCE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.canonical
        finally:
            sys.path.remove(str(EVENT_SOURCE.parent))

    def test_native_receipt_comment_identifies_the_pr(self):
        rest = dict(login="chatgpt-codex-connector[bot]", type="Bot")
        self.assertTrue(self.canonical()(dict(user=rest, body=VIZ213_SECURITY)))

    def test_human_receipt_copy_does_not(self):
        human = dict(login="someone", type="User")
        self.assertFalse(self.canonical()(dict(user=human, body=VIZ213_SECURITY)))


if __name__ == "__main__":
    unittest.main()

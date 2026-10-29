"""A security receipt proves only the exact head commit it names.

Codex finding Cortex PR 836 discussion_r4412420778 (P2, 2026-10-29): the
receipt names its commit by a 10-hex prefix (40 bits), and security_receipt()
accepted it when the head merely started with that prefix. A branch writer can
precompute a clean and a malicious commit sharing the prefix, obtain the clean
receipt, then force-push the malicious head. The receipt is now bound to the
head by the full SHA: 40 hex compared exactly, or a shorter prefix resolved by
the repository's commits API to a single commit equal to the head; a 404, an
ambiguous prefix or any API failure rejects the receipt. The two colliding SHAs
below are fabricated; the receipt body is the real one of cortex-viz PR 213.
"""

import importlib.util
import sys
import unittest
from unittest.mock import patch

from test_ci_native_hold_lift import claude_row
from test_ci_native_security_receipt import PR, READER, REPO, VIZ213_SECURITY, row, summary

PREFIX = "522f87761d"
CLEAN = PREFIX + "1d383bb6869dd861722a8da32dad30"
EVIL = PREFIX + "ffffffffffffffffffffffffffffff"


def load():
    sys.modules.pop("ci_codex_review_comments", None)
    sys.modules.pop("ci_codex_review_runtime", None)
    spec = importlib.util.spec_from_file_location("codex_head_binding_reader", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReceiptHeadBindingTests(unittest.TestCase):
    def evidence(self, head, body, resolved):
        module = load()
        runtime = sys.modules["ci_codex_review_runtime"]
        calls = []

        def api(endpoint, **_):
            calls.append(endpoint)
            if isinstance(resolved, Exception):
                raise resolved
            if resolved in ("not_found", "unknown"):
                # The loaded runtime's own error, as gh api failures surface (404, 422).
                raise sys.modules["ci_codex_review_runtime"].APIError(resolved)
            return {"sha": resolved}

        with patch.object(runtime, "_api", side_effect=api):
            rows = [summary(head), row(9, body), claude_row(head)]
            result = module.review_evidence(rows, head, REPO, PR)
        return result, calls

    def test_prefix_resolving_to_another_commit_is_not_proof(self):
        # The repository resolves the receipt's prefix to the clean commit; the head is the colliding one.
        result, calls = self.evidence(EVIL, VIZ213_SECURITY, CLEAN)
        self.assertEqual((result["state"], result["reason"]), ("blocked", "codex_security_verdict_missing"))
        self.assertEqual(calls, [f"repos/{REPO}/commits/{PREFIX}"])

    def test_ambiguous_or_unknown_prefix_is_not_proof(self):
        for failure in ("not_found", "unknown"):
            with self.subTest(failure=failure):
                result, _ = self.evidence(EVIL, VIZ213_SECURITY, failure)
                self.assertEqual(result["reason"], "codex_security_verdict_missing")

    def test_prefix_resolving_to_the_head_is_proof(self):
        result, _ = self.evidence(CLEAN, VIZ213_SECURITY, CLEAN)
        self.assertEqual((result["state"], result["reason"]), ("success", "reviews_complete"))

    def test_full_sha_receipt_is_compared_exactly_without_api(self):
        full = VIZ213_SECURITY.replace(f"`{PREFIX}`", f"`{CLEAN}`")
        result, calls = self.evidence(CLEAN, full, AssertionError("no API call expected"))
        self.assertEqual((result["state"], calls), ("success", []))
        result, calls = self.evidence(EVIL, full, AssertionError("no API call expected"))
        self.assertEqual((result["reason"], calls), ("codex_security_verdict_missing", []))


if __name__ == "__main__":
    unittest.main()

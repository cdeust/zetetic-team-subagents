"""Exact security commands have separate authenticated, replay-safe control state."""

import json
import unittest

from codex_resume_fixtures import SHA
from codex_outbox_fixtures import EXACT, MARKER, OutboxHarness
import test_ci_codex_review_recovery as recovery


class SecurityOutboxTests(unittest.TestCase):
    def test_security_command_is_exact_and_metadata_is_separate(self):
        harness = OutboxHarness()
        result = harness.invoke()
        self.assertEqual(result, dict(action="request", kind="security_review", comment_id=92, control_id=91))
        self.assertEqual(len(harness.commands()), 1)
        controls = [body for _, phase, body in harness.writes if phase != "command"]
        self.assertTrue(controls)
        self.assertTrue(all("@codex" not in body for body in controls))
        data = json.loads(controls[-1].split(MARKER + " ", 1)[1].split(" -->", 1)[0])
        self.assertEqual((data["sha"], data["state"], data["command_id"]), (SHA, "submitted", 92))

    def test_replay_never_posts_another_native_command(self):
        harness = OutboxHarness()
        harness.invoke()
        before = len(harness.writes)
        result = harness.invoke()
        self.assertEqual(result["reason"], "review_request_inflight")
        self.assertEqual(len(harness.commands()), 1)
        self.assertEqual(len(harness.writes), before)

    def test_legacy_marked_security_request_does_not_suppress_exact_transport(self):
        harness = OutboxHarness()
        harness.server.data["comments"].append(recovery.receipt())
        result = harness.invoke()
        self.assertEqual(result["action"], "request")
        self.assertEqual(len(harness.commands()), 1)

    def test_untrusted_malformed_control_cannot_block_native_request(self):
        harness = OutboxHarness()
        forged = harness.row("Codex security review control\nmalformed", 90)
        forged["user"] = dict(login="outsider", type="User", node_id="foreign")
        harness.server.data["comments"].append(forged)
        harness.invoke()
        self.assertEqual(len(harness.commands()), 1)

    def test_lost_reservation_response_retries_before_any_command_was_attempted(self):
        harness = OutboxHarness()
        harness.failure = "control_after"
        with self.assertRaises(ValueError):
            harness.invoke()
        self.assertEqual(harness.commands(), [])
        harness.failure = None
        harness.invoke()
        self.assertEqual(len(harness.commands()), 1)

    def test_control_creation_failure_cannot_send_native_command(self):
        harness = OutboxHarness()
        harness.failure = "control_before"
        with self.assertRaises(ValueError):
            harness.invoke()
        self.assertEqual(harness.commands(), [])

    def test_prepared_reservation_can_recover_after_failed_posting_transition(self):
        harness = OutboxHarness()
        harness.failure = "posting_before"
        with self.assertRaises(ValueError):
            harness.invoke()
        self.assertEqual(harness.commands(), [])
        harness.failure = None
        harness.invoke()
        self.assertEqual(len(harness.commands()), 1)

    def test_lost_posting_transition_response_never_sends_a_later_duplicate(self):
        harness = OutboxHarness()
        harness.failure = "posting_after"
        with self.assertRaises(ValueError):
            harness.invoke()
        harness.failure = None
        self.assertEqual(harness.invoke()["reason"], "security_command_uncertain")
        self.assertEqual(harness.commands(), [])

    def test_command_failure_without_response_is_not_automatically_retried(self):
        harness = OutboxHarness()
        harness.failure = "command_before"
        with self.assertRaises(ValueError):
            harness.invoke()
        harness.failure = None
        self.assertEqual(harness.invoke()["reason"], "security_command_uncertain")
        self.assertEqual(harness.commands(), [])

    def test_native_completion_before_command_aborts_the_reservation(self):
        harness = OutboxHarness()
        harness.complete_after_posting = True
        self.assertEqual(harness.invoke()["action"], "none")
        self.assertEqual(harness.commands(), [])
        self.assertIn("aborted", [phase for _, phase, _ in harness.writes])

    def test_lost_command_response_is_uncertain_and_never_reissued(self):
        harness = OutboxHarness()
        harness.failure = "command_after"
        with self.assertRaises(ValueError):
            harness.invoke()
        self.assertEqual(len(harness.commands()), 1)
        harness.failure = None
        result = harness.invoke()
        self.assertEqual(result["reason"], "security_command_uncertain")
        self.assertEqual(len(harness.commands()), 1)

    def test_submission_record_failure_does_not_duplicate_command_on_replay(self):
        harness = OutboxHarness()
        harness.failure = "submitted_before"
        result = harness.invoke()
        self.assertEqual(result["comment_id"], 92)
        self.assertEqual(result["control_state"], "unrecorded")
        harness.failure = None
        self.assertEqual(harness.invoke()["reason"], "security_command_uncertain")
        self.assertEqual(len(harness.commands()), 1)

    def test_head_move_after_posting_transition_aborts_without_native_command(self):
        harness = OutboxHarness()
        harness.move_after_posting = True
        result = harness.invoke()
        self.assertEqual(result["action"], "none")
        self.assertEqual(harness.commands(), [])
        self.assertIn("aborted", [phase for _, phase, _ in harness.writes])

    def test_submitted_control_must_link_exact_command_and_same_actor(self):
        for mutation in ("body", "actor", "editor"):
            harness = OutboxHarness()
            harness.invoke()
            row = harness.commands()[0]
            if mutation == "body":
                row["body"] += " extra instructions"
            elif mutation == "actor":
                row["user"]["node_id"] = "other"
            else:
                row.update(editor=dict(login="writer", __typename="User", id="other"),
                           lastEditedAt="2026-10-29T09:00:01Z")
            result = harness.invoke()
            self.assertEqual(result["reason"], "security_command_unverified")
            self.assertEqual(sum(phase == "command" for _, phase, _ in harness.writes), 1)

    def test_tampered_control_editor_fails_closed_without_duplicate_command(self):
        harness = OutboxHarness()
        harness.invoke()
        row = next(row for row in harness.server.data["comments"] if row["id"] == 91)
        row.update(editor=dict(login="writer", __typename="User", id="other"),
                   lastEditedAt="2026-10-29T09:00:02Z")
        with self.assertRaisesRegex(ValueError, "editor"):
            harness.invoke()
        self.assertEqual(len(harness.commands()), 1)


if __name__ == "__main__":
    unittest.main()

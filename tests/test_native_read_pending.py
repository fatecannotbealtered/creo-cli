"""A begun read is never presented as withdrawn or automatically repeated."""

from tests.test_commands import RECT, Base


class PendingNativeRead(Base):
    def test_started_public_read_has_no_receipt_or_retry(self):
        self.part()
        self.world.events.clear()
        self.world.overrun = "model.show"
        result = self.cli("model", "show", "--model", "block", status=8)
        error = result["error"]
        self.assertEqual(error["code"], "E_NATIVE_READ_PENDING")
        self.assertFalse(error["retryable"])
        self.assertEqual(error["details"]["dispatch_state"], "started")
        self.assertIn("do not issue another CAD request", error["details"]["next_action"])
        self.assertEqual(self.world.ops(), ["model.show"])
        self.assertEqual(self.receipts(), [])

    def test_pending_required_read_after_write_does_not_queue_another_native_read(self):
        self.part()
        dry = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--dry-run",
        )
        # Enable the pending fault only after the real fixture write returned.
        original = self.world.handle

        def after_write(op, request):
            if op == "feature.extrude":
                self.world.overrun = "feature.list"
            return original(op, request)

        self.world.overrun = None
        self.world.handle = after_write
        self.world.events.clear()
        result = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--confirm",
            dry["data"]["confirm_token"],
            status=6,
        )
        self.assertEqual(result["error"]["code"], "E_OUTCOME_UNKNOWN")
        self.assertFalse(result["error"]["retryable"])
        # Construction reports its required check incomplete, preserving the
        # underlying pending read; the guard must prevent its settlement query.
        self.assertEqual(result["error"]["details"]["cause_code"], "E_VERIFY_INCOMPLETE")
        ops = self.world.ops()
        pending = ops.index("feature.list", ops.index("feature.extrude") + 1)
        self.assertEqual(ops[pending + 1 :], [])

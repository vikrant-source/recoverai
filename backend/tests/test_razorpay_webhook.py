"""
Integration tests for the Razorpay real webhook path.

Tests the real Razorpay payment.failed webhook flow, including:
  - Valid Razorpay payload with txn mapping via order notes
  - X-Razorpay-Event-Id header used as idempotency key
  - Duplicate Razorpay event (same event ID header)
  - Malformed Razorpay payload (missing required fields)
  - Invalid HMAC signature when RAZORPAY_WEBHOOK_SECRET is configured
  - Valid HMAC signature
  - Missing local transaction mapping (no recoverai_txn_id in notes)
  - Successful txn mapping + pipeline execution
  - Synthetic path is unaffected by Razorpay signature checks
  - Existing opted-out / policy / idempotency behavior on Razorpay path

Uses the same isolated in-memory SQLite database strategy as
test_webhook_integration.py.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Use the shared engine from conftest to avoid cross-test-file override conflicts
from tests.conftest import SHARED_ENGINE, SharedTestingSessionLocal, shared_override_get_db

from app.main import app
from app.database import Base, get_db
from app.models import Customer, Transaction, WebhookEvent, Intervention
from app.schemas import AIDecision, RecoveryAction

app.dependency_overrides[get_db] = shared_override_get_db
client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_WEBHOOK_SECRET = "test_webhook_secret_do_not_use_in_prod"  # noqa: S105


def _make_signature(body_bytes: bytes, secret: str) -> str:
    """Compute the HMAC-SHA256 signature Razorpay would send."""
    return hmac_lib.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()


def _razorpay_body(
    *,
    event: str = "payment.failed",
    payment_id: str = "pay_test_001",
    order_id: str = "order_test_001",
    amount: int = 49900,
    error_code: str = "BAD_REQUEST_ERROR",
    error_description: str = "Insufficient funds",
    recoverai_txn_id: str | None = "txn_webhook_001",
) -> dict:
    """
    Build a minimal Razorpay payment.failed body.
    Includes recoverai_txn_id in entity.notes when provided.
    """
    notes = {}
    if recoverai_txn_id is not None:
        notes["recoverai_txn_id"] = recoverai_txn_id

    return {
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "INR",
                    "status": "failed",
                    "error_code": error_code,
                    "error_description": error_description,
                    "error_source": "customer",
                    "error_step": "payment_authorization",
                    "error_reason": "insufficient_funds",
                    "notes": notes,
                }
            }
        },
    }


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestRazorpayWebhook(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all(bind=SHARED_ENGINE)
        self.db = SharedTestingSessionLocal()
        self.now = datetime.now(timezone.utc)

        self.test_customer = Customer(
            customer_id="cust_webhook_001",
            lifetime_value=100000,
            opted_out=False,
        )
        self.db.add(self.test_customer)

        self.test_transaction = Transaction(
            txn_id="txn_webhook_001",
            customer_id="cust_webhook_001",
            amount=49900,
            status="FAILED",
            failure_code="INSUFFICIENT_FUNDS",
            failure_description="[recoverable] Low balance",
            attempt_count=1,
            revenue_at_risk=49900,
            recovered_amount=0,
            recovery_window_expires_at=self.now + timedelta(days=1),
        )
        self.db.add(self.test_transaction)
        self.db.commit()
        
        # Prevent real .env secrets from causing signature validation failures in tests
        self.patcher = patch("app.razorpay_sig._get_webhook_secret", return_value=None)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.db.close()
        Base.metadata.drop_all(bind=SHARED_ENGINE)

    def _mock_ai_decision(self, action: RecoveryAction = RecoveryAction.SILENT_RETRY) -> AIDecision:
        return AIDecision(
            recommended_action=action,
            confidence_score=0.90,
            failure_classification="INSUFFICIENT_FUNDS",
            reasoning="Test reasoning",
        )

    # ------------------------------------------------------------------
    # 1. Valid Razorpay payload with correct txn mapping
    # ------------------------------------------------------------------

    @patch("app.pipeline.get_ai_decision")
    def test_valid_razorpay_payload_returns_accepted(self, mock_ai):
        """Real Razorpay body with notes.recoverai_txn_id → ACCEPTED."""
        mock_ai.return_value = self._mock_ai_decision(RecoveryAction.SILENT_RETRY)

        body = _razorpay_body(recoverai_txn_id="txn_webhook_001")
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "rzp_evt_001",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ACCEPTED")
        self.assertEqual(data["txn_id"], "txn_webhook_001")
        self.assertIn(data["execution_status"], ("SUCCESS", "FAILED", "SKIPPED", "ESCALATED"))

        # WebhookEvent must be persisted as COMPLETED
        event = self.db.query(WebhookEvent).filter_by(event_id="rzp_evt_001").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.status, "COMPLETED")

        # Audit payload must contain audit fields but not secrets
        self.assertIn("razorpay_payment_id", event.payload)
        self.assertNotIn("RAZORPAY_WEBHOOK_SECRET", str(event.payload))

    # ------------------------------------------------------------------
    # 2. X-Razorpay-Event-Id header used as idempotency key
    # ------------------------------------------------------------------

    @patch("app.pipeline.get_ai_decision")
    def test_razorpay_event_id_header_used_as_idempotency_key(self, mock_ai):
        """X-Razorpay-Event-Id header becomes the event_id for idempotency."""
        mock_ai.return_value = self._mock_ai_decision()

        body = _razorpay_body(recoverai_txn_id="txn_webhook_001")
        raw = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Razorpay-Event-Id": "rzp_evt_idem_001",
        }

        # First call
        r1 = client.post("/webhooks/payment", content=raw, headers=headers)
        self.assertEqual(r1.json()["status"], "ACCEPTED")

        # Second call — same header → DUPLICATE
        r2 = client.post("/webhooks/payment", content=raw, headers=headers)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "DUPLICATE")

        # Pipeline called only once
        mock_ai.assert_called_once()

    # ------------------------------------------------------------------
    # 3. Duplicate Razorpay event
    # ------------------------------------------------------------------

    @patch("app.pipeline.get_ai_decision")
    def test_duplicate_razorpay_event_not_reprocessed(self, mock_ai):
        """Identical Razorpay event ID → second call is DUPLICATE."""
        mock_ai.return_value = self._mock_ai_decision()

        body = _razorpay_body(recoverai_txn_id="txn_webhook_001")
        raw = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Razorpay-Event-Id": "rzp_evt_dup_001",
        }

        client.post("/webhooks/payment", content=raw, headers=headers)
        r2 = client.post("/webhooks/payment", content=raw, headers=headers)

        self.assertEqual(r2.json()["status"], "DUPLICATE")
        # Only one intervention created
        interventions = self.db.query(Intervention).all()
        self.assertEqual(len(interventions), 1)

    # ------------------------------------------------------------------
    # 4. Malformed Razorpay payload (missing payload.payment.entity)
    # ------------------------------------------------------------------

    def test_malformed_razorpay_payload_missing_entity(self):
        """Payload missing payload.payment.entity → 422."""
        body = {"event": "payment.failed", "payload": {}}
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "rzp_evt_bad_001",
            },
        )
        self.assertEqual(response.status_code, 422)

    # ------------------------------------------------------------------
    # 5. Malformed Razorpay payload (missing event field)
    # ------------------------------------------------------------------

    def test_malformed_razorpay_payload_missing_event_field(self):
        """Payload with no 'event' field at all → 422."""
        body = {"payload": {"payment": {"entity": {"id": "pay_x"}}}}
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 422)

    # ------------------------------------------------------------------
    # 6. Invalid HMAC signature when secret IS configured
    # ------------------------------------------------------------------

    def test_invalid_signature_rejected_when_secret_configured(self):
        """Invalid X-Razorpay-Signature → 400 when webhook secret is set."""
        body = _razorpay_body(recoverai_txn_id="txn_webhook_001")
        raw = json.dumps(body).encode()

        with patch("app.razorpay_sig._get_webhook_secret", return_value=_TEST_WEBHOOK_SECRET):
            response = client.post(
                "/webhooks/payment",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Event-Id": "rzp_evt_sig_bad",
                    "X-Razorpay-Signature": "deadbeef" * 8,  # obviously wrong
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("signature", response.json()["detail"].lower())

    # ------------------------------------------------------------------
    # 7. Missing signature header when secret IS configured
    # ------------------------------------------------------------------

    def test_missing_signature_header_rejected_when_secret_configured(self):
        """Absent X-Razorpay-Signature → 400 when webhook secret is set."""
        body = _razorpay_body(recoverai_txn_id="txn_webhook_001")
        raw = json.dumps(body).encode()

        with patch("app.razorpay_sig._get_webhook_secret", return_value=_TEST_WEBHOOK_SECRET):
            response = client.post(
                "/webhooks/payment",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Event-Id": "rzp_evt_nosig",
                    # No X-Razorpay-Signature
                },
            )

        self.assertEqual(response.status_code, 400)

    # ------------------------------------------------------------------
    # 8. Valid HMAC signature accepted
    # ------------------------------------------------------------------

    @patch("app.pipeline.get_ai_decision")
    def test_valid_hmac_signature_accepted(self, mock_ai):
        """Correct HMAC-SHA256 signature → request accepted."""
        mock_ai.return_value = self._mock_ai_decision()

        body = _razorpay_body(recoverai_txn_id="txn_webhook_001")
        raw = json.dumps(body).encode()
        sig = _make_signature(raw, _TEST_WEBHOOK_SECRET)

        with patch("app.razorpay_sig._get_webhook_secret", return_value=_TEST_WEBHOOK_SECRET):
            response = client.post(
                "/webhooks/payment",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Event-Id": "rzp_evt_valid_sig",
                    "X-Razorpay-Signature": sig,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ACCEPTED")

    # ------------------------------------------------------------------
    # 9. Missing local transaction mapping (no recoverai_txn_id in notes)
    # ------------------------------------------------------------------

    def test_no_txn_mapping_returns_ignored(self):
        """Razorpay event with no recoverai_txn_id in notes → IGNORED."""
        body = _razorpay_body(recoverai_txn_id=None)  # no notes mapping
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "rzp_evt_nmap_001",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "IGNORED")
        self.assertIn("recoverai_txn_id", data["message"])

        # No WebhookEvent row created (IGNORED before DB write)
        event = self.db.query(WebhookEvent).filter_by(event_id="rzp_evt_nmap_001").first()
        self.assertIsNone(event)

    # ------------------------------------------------------------------
    # 10. Notes mapping to a non-existent local transaction → IGNORED
    # ------------------------------------------------------------------

    def test_mapping_to_unknown_local_txn_returns_ignored(self):
        """notes.recoverai_txn_id points to a txn not in DB → IGNORED."""
        body = _razorpay_body(recoverai_txn_id="txn_does_not_exist_9999")
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "rzp_evt_badtxn_001",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "IGNORED")
        self.assertIn("not found", data["message"])

        # WebhookEvent recorded as FAILED (context load failed)
        event = self.db.query(WebhookEvent).filter_by(event_id="rzp_evt_badtxn_001").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.status, "FAILED")

    # ------------------------------------------------------------------
    # 11. Synthetic path is unaffected by Razorpay signature logic
    # ------------------------------------------------------------------

    @patch("app.pipeline.get_ai_decision")
    def test_synthetic_webhook_bypasses_signature_check(self, mock_ai):
        """synthetic=true path never touches signature verification."""
        mock_ai.return_value = self._mock_ai_decision()

        payload = {
            "event_id": "evt_synth_bypass_001",
            "event_type": "payment.failed",
            "txn_id": "txn_webhook_001",
            "synthetic": True,
        }

        # Even with no signature header at all, synthetic path must succeed
        response = client.post("/webhooks/payment", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ACCEPTED")

    # ------------------------------------------------------------------
    # 12. Wrong event type on Razorpay path → IGNORED
    # ------------------------------------------------------------------

    def test_razorpay_wrong_event_type_ignored(self):
        """Razorpay body with event='payment.captured' → IGNORED."""
        body = _razorpay_body(
            event="payment.captured",
            recoverai_txn_id="txn_webhook_001",
        )
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "rzp_evt_captured_001",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "IGNORED")
        # No DB row written for non-payment.failed types
        event = self.db.query(WebhookEvent).filter_by(event_id="rzp_evt_captured_001").first()
        self.assertIsNone(event)

    # ------------------------------------------------------------------
    # 13. Opted-out customer on Razorpay path → policy SKIPS
    # ------------------------------------------------------------------

    @patch("app.pipeline.get_ai_decision")
    def test_razorpay_opted_out_customer_skipped(self, mock_ai):
        """Razorpay event for opted-out customer → policy returns DO_NOTHING."""
        mock_ai.return_value = self._mock_ai_decision()

        cust = self.db.query(Customer).filter_by(customer_id="cust_webhook_001").first()
        cust.opted_out = True
        self.db.commit()

        body = _razorpay_body(recoverai_txn_id="txn_webhook_001")
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "rzp_evt_optout_001",
            },
        )

        data = response.json()
        self.assertEqual(data["status"], "ACCEPTED")
        self.assertEqual(data["execution_status"], "SKIPPED")
        self.assertEqual(data["final_action"], "DO_NOTHING")

    # ------------------------------------------------------------------
    # 14. Razorpay event without header falls back to compound event_id
    # ------------------------------------------------------------------

    @patch("app.pipeline.get_ai_decision")
    def test_razorpay_event_id_derived_from_payment_id_when_header_absent(self, mock_ai):
        """When X-Razorpay-Event-Id absent, event_id derived from payment entity."""
        mock_ai.return_value = self._mock_ai_decision()

        body = _razorpay_body(
            payment_id="pay_fallback_001",
            recoverai_txn_id="txn_webhook_001",
        )
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={"Content-Type": "application/json"},
            # No X-Razorpay-Event-Id header
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ACCEPTED")

        # The event_id in the DB should be the compound fallback key
        event = self.db.query(WebhookEvent).filter_by(
            event_id="rzp_payment.failed_pay_fallback_001"
        ).first()
        self.assertIsNotNone(event)

    # ------------------------------------------------------------------
    # 15. Audit payload contains Razorpay IDs but not secrets
    # ------------------------------------------------------------------

    @patch("app.pipeline.get_ai_decision")
    def test_audit_payload_contains_razorpay_ids_not_secrets(self, mock_ai):
        """WebhookEvent.payload contains audit fields but no secret values."""
        mock_ai.return_value = self._mock_ai_decision()

        body = _razorpay_body(
            payment_id="pay_audit_001",
            order_id="order_audit_001",
            recoverai_txn_id="txn_webhook_001",
        )
        raw = json.dumps(body).encode()

        response = client.post(
            "/webhooks/payment",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "rzp_evt_audit_001",
            },
        )

        self.assertEqual(response.json()["status"], "ACCEPTED")

        event = self.db.query(WebhookEvent).filter_by(event_id="rzp_evt_audit_001").first()
        self.assertIsNotNone(event)

        payload = event.payload
        # Audit fields present
        self.assertEqual(payload.get("razorpay_payment_id"), "pay_audit_001")
        self.assertEqual(payload.get("razorpay_order_id"), "order_audit_001")
        self.assertEqual(payload.get("synthetic"), False)

        # Secrets must never appear
        payload_str = json.dumps(payload)
        self.assertNotIn("RAZORPAY_WEBHOOK_SECRET", payload_str)
        self.assertNotIn("RAZORPAY_KEY_SECRET", payload_str)


if __name__ == "__main__":
    unittest.main()

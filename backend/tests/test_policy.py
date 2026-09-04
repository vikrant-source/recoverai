"""Unit tests for Policy Brakes. Independent of the database."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.policy import PolicyDecision, evaluate_policy
from app.schemas import AIDecision, RecoveryAction


def _customer(**overrides) -> SimpleNamespace:
    values = {
        "customer_id": "cust_0001",
        "opted_out": False,
        "lifetime_value": 500000,
        "ltv_tier": "STANDARD",
        "fraud_score": 0.1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _transaction(**overrides) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    values = {
        "txn_id": "txn_0001",
        "customer_id": "cust_0001",
        "status": "FAILED",
        "amount": 49900,
        "revenue_at_risk": 49900,
        "recovered_amount": 0,
        "attempt_count": 1,
        "recovery_window_expires_at": now + timedelta(hours=24),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _ai(**overrides) -> AIDecision:
    values = {
        "recommended_action": RecoveryAction.SEND_PAYMENT_LINK,
        "confidence_score": 0.92,
        "failure_classification": "INSUFFICIENT_FUNDS",
        "reasoning": "Likely recoverable after a reminder.",
    }
    values.update(overrides)
    return AIDecision(**values)


class PolicyEngineTests(unittest.TestCase):
    def test_successful_transaction_is_blocked(self):
        result = evaluate_policy(
            _transaction(status="SUCCESS", revenue_at_risk=0),
            _customer(),
            _ai(),
        )
        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertEqual(result.final_action, RecoveryAction.DO_NOTHING)
        self.assertIn("already successful", result.reason.lower())

    def test_opted_out_customer_is_blocked(self):
        result = evaluate_policy(
            _transaction(),
            _customer(opted_out=True),
            _ai(),
        )
        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertEqual(result.final_action, RecoveryAction.DO_NOTHING)
        self.assertIn("opted out", result.reason.lower())

    def test_expired_recovery_window_is_blocked(self):
        expired = datetime.now(timezone.utc) - timedelta(hours=2)
        result = evaluate_policy(
            _transaction(recovery_window_expires_at=expired),
            _customer(),
            _ai(),
        )
        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertEqual(result.final_action, RecoveryAction.DO_NOTHING)
        self.assertIn("expired", result.reason.lower())

    def test_retry_limit_reached_escalates(self):
        result = evaluate_policy(
            _transaction(attempt_count=2),
            _customer(),
            _ai(),
        )
        self.assertEqual(result.decision, PolicyDecision.ESCALATE)
        self.assertEqual(result.final_action, RecoveryAction.ESCALATE)
        self.assertIn("retry limit", result.reason.lower())

    def test_no_revenue_at_risk_is_blocked(self):
        result = evaluate_policy(
            _transaction(revenue_at_risk=0),
            _customer(),
            _ai(),
        )
        self.assertEqual(result.decision, PolicyDecision.BLOCK)
        self.assertEqual(result.final_action, RecoveryAction.DO_NOTHING)
        self.assertIn("revenue at risk", result.reason.lower())

    def test_low_confidence_ai_recommendation_escalates(self):
        result = evaluate_policy(
            _transaction(),
            _customer(),
            _ai(confidence_score=0.59),
        )
        self.assertEqual(result.decision, PolicyDecision.ESCALATE)
        self.assertEqual(result.final_action, RecoveryAction.ESCALATE)
        self.assertIn("confidence", result.reason.lower())

    def test_ai_recommends_do_nothing_is_allowed(self):
        result = evaluate_policy(
            _transaction(),
            _customer(),
            _ai(recommended_action=RecoveryAction.DO_NOTHING),
        )
        self.assertEqual(result.decision, PolicyDecision.ALLOW)
        self.assertEqual(result.final_action, RecoveryAction.DO_NOTHING)

    def test_allow_send_payment_link(self):
        result = evaluate_policy(
            _transaction(),
            _customer(),
            _ai(
                recommended_action=RecoveryAction.SEND_PAYMENT_LINK,
                confidence_score=0.88,
            ),
        )
        self.assertEqual(result.decision, PolicyDecision.ALLOW)
        self.assertEqual(result.final_action, RecoveryAction.SEND_PAYMENT_LINK)

    def test_allow_silent_retry(self):
        result = evaluate_policy(
            _transaction(),
            _customer(),
            _ai(
                recommended_action=RecoveryAction.SILENT_RETRY,
                confidence_score=0.81,
            ),
        )
        self.assertEqual(result.decision, PolicyDecision.ALLOW)
        self.assertEqual(result.final_action, RecoveryAction.SILENT_RETRY)


if __name__ == "__main__":
    unittest.main()

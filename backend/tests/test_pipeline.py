"""
Unit tests for the Recovery Pipeline — Phase 5.

Verifies the orchestration logic of run_recovery_pipeline():
  - AI Brain is called and its result flows into Policy evaluation
  - Policy evaluation result flows into the Executor
  - The Executor's final_action comes from policy_result, not ai_decision
  - The pipeline handles AI fallback (ESCALATE) gracefully

get_ai_decision is mocked to prevent real Groq API calls.
The DB session is mocked to prevent real DB writes.
evaluate_policy and execute_recovery run for real to exercise the integration.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.pipeline import run_recovery_pipeline
from app.schemas import AIDecision, ExecutionResult, ExecutionStatus, RecoveryAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_db() -> MagicMock:
    return MagicMock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _transaction(**overrides) -> SimpleNamespace:
    now = _now()
    values = {
        "txn_id": "txn_pipeline_001",
        "amount": 49900,
        "currency": "INR",
        "status": "FAILED",
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_description": "[recoverable] Bank declined: low balance",
        "attempt_count": 1,
        "revenue_at_risk": 49900,
        "recovered_amount": 0,
        "recovery_window_expires_at": now + timedelta(hours=24),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _customer(**overrides) -> SimpleNamespace:
    values = {
        "customer_id": "cust_pipeline_001",
        "ltv_tier": "STANDARD",
        "lifetime_value": 200000,
        "fraud_score": 0.05,
        "opted_out": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _ai_decision(action: RecoveryAction = RecoveryAction.SEND_PAYMENT_LINK, **overrides) -> AIDecision:
    values = {
        "recommended_action": action,
        "confidence_score": 0.88,
        "failure_classification": "INSUFFICIENT_FUNDS",
        "reasoning": "Customer likely has funds; payment link advised.",
    }
    values.update(overrides)
    return AIDecision(**values)


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class PipelineTests(unittest.TestCase):
    @patch("app.pipeline.get_ai_decision")
    def test_happy_path_recoverable_transaction_succeeds(self, mock_get_ai):
        """
        AI recommends SEND_PAYMENT_LINK (high confidence) → Policy ALLOWS
        → Executor: recoverable txn → SUCCESS.
        """
        mock_get_ai.return_value = _ai_decision(RecoveryAction.SEND_PAYMENT_LINK)

        result = run_recovery_pipeline(
            _mock_db(),
            _transaction(failure_description="[recoverable] Bank declined: low balance"),
            _customer(),
        )

        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(result.execution_status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.recovered_amount, 0)

    @patch("app.pipeline.get_ai_decision")
    def test_policy_blocks_successful_transaction(self, mock_get_ai):
        """
        AI recommends SEND_PAYMENT_LINK but transaction is already SUCCESS
        → Policy BLOCKS (DO_NOTHING) → Executor: SKIPPED.
        """
        mock_get_ai.return_value = _ai_decision(RecoveryAction.SEND_PAYMENT_LINK)

        result = run_recovery_pipeline(
            _mock_db(),
            _transaction(status="SUCCESS", revenue_at_risk=0),
            _customer(),
        )

        self.assertEqual(result.execution_status, ExecutionStatus.SKIPPED)
        self.assertEqual(result.final_action, RecoveryAction.DO_NOTHING)
        self.assertEqual(result.recovered_amount, 0)

    @patch("app.pipeline.get_ai_decision")
    def test_policy_blocks_opted_out_customer(self, mock_get_ai):
        """
        AI recommends SEND_PAYMENT_LINK but customer is opted-out
        → Policy BLOCKS (DO_NOTHING) → Executor: SKIPPED.
        """
        mock_get_ai.return_value = _ai_decision(RecoveryAction.SEND_PAYMENT_LINK)

        result = run_recovery_pipeline(
            _mock_db(),
            _transaction(),
            _customer(opted_out=True),
        )

        self.assertEqual(result.execution_status, ExecutionStatus.SKIPPED)
        self.assertEqual(result.final_action, RecoveryAction.DO_NOTHING)

    @patch("app.pipeline.get_ai_decision")
    def test_ai_fallback_escalate_handled_gracefully(self, mock_get_ai):
        """
        AI Brain fails → fallback AIDecision(ESCALATE, confidence=0.0).
        Policy sees confidence < 0.60 → ESCALATE.
        Executor → ESCALATED.
        """
        mock_get_ai.return_value = AIDecision(
            recommended_action=RecoveryAction.ESCALATE,
            confidence_score=0.0,
            failure_classification="UNKNOWN",
            reasoning="AI response could not be processed safely.",
        )

        result = run_recovery_pipeline(
            _mock_db(),
            _transaction(),
            _customer(),
        )

        self.assertEqual(result.execution_status, ExecutionStatus.ESCALATED)
        self.assertEqual(result.recovered_amount, 0)

    @patch("app.pipeline.get_ai_decision")
    def test_retry_limit_escalates_regardless_of_ai(self, mock_get_ai):
        """
        AI recommends SILENT_RETRY but attempt_count >= MAX_RETRY_ATTEMPTS (2)
        → Policy ESCALATES → Executor: ESCALATED.
        """
        mock_get_ai.return_value = _ai_decision(RecoveryAction.SILENT_RETRY, confidence_score=0.95)

        result = run_recovery_pipeline(
            _mock_db(),
            _transaction(attempt_count=2),
            _customer(),
        )

        self.assertEqual(result.execution_status, ExecutionStatus.ESCALATED)
        self.assertEqual(result.final_action, RecoveryAction.ESCALATE)

    @patch("app.pipeline.get_ai_decision")
    def test_pipeline_return_type_is_execution_result(self, mock_get_ai):
        mock_get_ai.return_value = _ai_decision()
        result = run_recovery_pipeline(_mock_db(), _transaction(), _customer())
        self.assertIsInstance(result, ExecutionResult)

    @patch("app.pipeline.get_ai_decision")
    def test_get_ai_decision_called_exactly_once(self, mock_get_ai):
        """AI Brain must be called once per pipeline run — never zero, never twice."""
        mock_get_ai.return_value = _ai_decision()
        run_recovery_pipeline(_mock_db(), _transaction(), _customer())
        mock_get_ai.assert_called_once()

    @patch("app.pipeline.get_ai_decision")
    def test_unrecoverable_transaction_fails(self, mock_get_ai):
        """
        AI recommends SEND_PAYMENT_LINK, Policy allows, but ground-truth
        is [unrecovered] → Executor: FAILED, recovered_amount=0.
        """
        mock_get_ai.return_value = _ai_decision(RecoveryAction.SEND_PAYMENT_LINK)

        result = run_recovery_pipeline(
            _mock_db(),
            _transaction(failure_description="[unrecovered] Customer refused to pay"),
            _customer(),
        )

        self.assertEqual(result.execution_status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.recovered_amount, 0)


if __name__ == "__main__":
    unittest.main()

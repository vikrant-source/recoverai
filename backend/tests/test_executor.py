"""
Unit tests for the Recovery Executor — Phase 5.

All tests use:
  - MagicMock for the DB session (no real DB I/O)
  - SimpleNamespace for transaction / customer (no ORM session required)
  - No real payment API calls

Covers: all four final_actions, attempt_count rules, amount immutability,
        paise-only arithmetic, audit record creation, DB error handling,
        and the critical invariant that the executor uses policy_result.final_action
        — never ai_decision.recommended_action directly.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

from sqlalchemy.exc import SQLAlchemyError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.executor import _is_ground_truth_recoverable, execute_recovery
from app.policy import PolicyDecision, PolicyResult
from app.schemas import AIDecision, ExecutionResult, ExecutionStatus, RecoveryAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_db() -> MagicMock:
    db = MagicMock()
    return db


def _transaction(**overrides) -> SimpleNamespace:
    values = {
        "txn_id": "txn_test_001",
        "amount": 49900,                    # integer paise — must never change
        "currency": "INR",
        "status": "FAILED",
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_description": "[recoverable] Bank declined: low balance",
        "attempt_count": 1,
        "revenue_at_risk": 49900,           # integer paise
        "recovered_amount": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _customer(**overrides) -> SimpleNamespace:
    values = {
        "customer_id": "cust_test_001",
        "ltv_tier": "STANDARD",
        "lifetime_value": 200000,
        "fraud_score": 0.05,
        "opted_out": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _ai(action: RecoveryAction = RecoveryAction.SEND_PAYMENT_LINK, **overrides) -> AIDecision:
    values = {
        "recommended_action": action,
        "confidence_score": 0.87,
        "failure_classification": "INSUFFICIENT_FUNDS",
        "reasoning": "Customer likely has funds; payment link advised.",
    }
    values.update(overrides)
    return AIDecision(**values)


def _policy(
    action: RecoveryAction = RecoveryAction.SEND_PAYMENT_LINK,
    decision: PolicyDecision = PolicyDecision.ALLOW,
    reason: str = "Policy brakes allow the AI recommendation.",
) -> PolicyResult:
    return PolicyResult(decision=decision, reason=reason, final_action=action)


# ---------------------------------------------------------------------------
# Tests: _is_ground_truth_recoverable
# ---------------------------------------------------------------------------


class GroundTruthHelperTests(unittest.TestCase):
    def test_recoverable_prefix_returns_true(self):
        txn = _transaction(failure_description="[recoverable] Bank declined: low balance")
        self.assertTrue(_is_ground_truth_recoverable(txn))

    def test_unrecovered_prefix_returns_false(self):
        txn = _transaction(failure_description="[unrecovered] Customer refused to retry")
        self.assertFalse(_is_ground_truth_recoverable(txn))

    def test_self_healed_prefix_returns_false(self):
        txn = _transaction(failure_description="[self_healed] Acquirer timeout")
        self.assertFalse(_is_ground_truth_recoverable(txn))

    def test_prefix_check_is_case_insensitive(self):
        txn = _transaction(failure_description="[RECOVERABLE] UPI switch error")
        self.assertTrue(_is_ground_truth_recoverable(txn))

    def test_none_description_returns_false(self):
        txn = _transaction(failure_description=None)
        self.assertFalse(_is_ground_truth_recoverable(txn))

    def test_empty_description_returns_false(self):
        txn = _transaction(failure_description="")
        self.assertFalse(_is_ground_truth_recoverable(txn))


# ---------------------------------------------------------------------------
# Tests: execute_recovery — action outcomes
# ---------------------------------------------------------------------------


class ExecutorActionTests(unittest.TestCase):
    def test_do_nothing_returns_skipped(self):
        result = execute_recovery(
            _mock_db(),
            _transaction(),
            _customer(),
            _policy(RecoveryAction.DO_NOTHING, PolicyDecision.ALLOW, "No action needed."),
            _ai(RecoveryAction.DO_NOTHING),
        )
        self.assertEqual(result.execution_status, ExecutionStatus.SKIPPED)
        self.assertEqual(result.recovered_amount, 0)

    def test_do_nothing_does_not_change_transaction(self):
        txn = _transaction()
        execute_recovery(
            _mock_db(),
            txn,
            _customer(),
            _policy(RecoveryAction.DO_NOTHING, PolicyDecision.ALLOW),
            _ai(RecoveryAction.DO_NOTHING),
        )
        self.assertEqual(txn.status, "FAILED")
        self.assertEqual(txn.revenue_at_risk, 49900)
        self.assertEqual(txn.recovered_amount, 0)

    def test_escalate_returns_escalated(self):
        result = execute_recovery(
            _mock_db(),
            _transaction(),
            _customer(),
            _policy(RecoveryAction.ESCALATE, PolicyDecision.ESCALATE, "Retry limit reached."),
            _ai(RecoveryAction.ESCALATE),
        )
        self.assertEqual(result.execution_status, ExecutionStatus.ESCALATED)
        self.assertEqual(result.recovered_amount, 0)

    def test_silent_retry_recoverable_returns_success(self):
        txn = _transaction(failure_description="[recoverable] Bank declined: low balance")
        result = execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SILENT_RETRY),
            _ai(RecoveryAction.SILENT_RETRY),
        )
        self.assertEqual(result.execution_status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.recovered_amount, 49900)

    def test_silent_retry_unrecovered_returns_failed(self):
        txn = _transaction(failure_description="[unrecovered] Customer refused")
        result = execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SILENT_RETRY),
            _ai(RecoveryAction.SILENT_RETRY),
        )
        self.assertEqual(result.execution_status, ExecutionStatus.FAILED)
        self.assertEqual(result.recovered_amount, 0)

    def test_send_payment_link_recoverable_returns_success(self):
        txn = _transaction(failure_description="[recoverable] Low balance")
        result = execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertEqual(result.execution_status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.recovered_amount, 49900)

    def test_send_payment_link_unrecovered_returns_failed(self):
        txn = _transaction(failure_description="[unrecovered] Permanently declined")
        result = execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertEqual(result.execution_status, ExecutionStatus.FAILED)
        self.assertEqual(result.recovered_amount, 0)


# ---------------------------------------------------------------------------
# Tests: attempt_count rules
# ---------------------------------------------------------------------------


class AttemptCountTests(unittest.TestCase):
    def test_silent_retry_increments_attempt_count(self):
        txn = _transaction(attempt_count=1, failure_description="[recoverable] test")
        execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SILENT_RETRY),
            _ai(RecoveryAction.SILENT_RETRY),
        )
        self.assertEqual(txn.attempt_count, 2)

    def test_silent_retry_increments_even_on_failure(self):
        txn = _transaction(attempt_count=1, failure_description="[unrecovered] test")
        execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SILENT_RETRY),
            _ai(RecoveryAction.SILENT_RETRY),
        )
        self.assertEqual(txn.attempt_count, 2)

    def test_send_payment_link_does_not_increment_attempt_count(self):
        txn = _transaction(attempt_count=1, failure_description="[recoverable] test")
        execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertEqual(txn.attempt_count, 1)

    def test_do_nothing_does_not_increment_attempt_count(self):
        txn = _transaction(attempt_count=1)
        execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.DO_NOTHING, PolicyDecision.ALLOW),
            _ai(RecoveryAction.DO_NOTHING),
        )
        self.assertEqual(txn.attempt_count, 1)


# ---------------------------------------------------------------------------
# Tests: financial integrity
# ---------------------------------------------------------------------------


class FinancialIntegrityTests(unittest.TestCase):
    def test_transaction_amount_is_never_modified(self):
        """transaction.amount must be immutable regardless of action or outcome."""
        original_amount = 49900
        for action in RecoveryAction:
            with self.subTest(action=action):
                decision = PolicyDecision.ALLOW if action != RecoveryAction.ESCALATE else PolicyDecision.ESCALATE
                txn = _transaction(amount=original_amount)
                execute_recovery(
                    _mock_db(), txn, _customer(),
                    _policy(action, decision),
                    _ai(action),
                )
                self.assertEqual(txn.amount, original_amount, f"amount changed for action {action}")

    def test_recovered_amount_is_integer_paise(self):
        txn = _transaction(revenue_at_risk=79900, failure_description="[recoverable] test")
        result = execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertIsInstance(result.recovered_amount, int)
        self.assertEqual(result.recovered_amount, 79900)

    def test_recovered_amount_equals_pre_existing_revenue_at_risk(self):
        """On success, recovered_amount must be the pre-existing revenue_at_risk value."""
        revenue = 129900
        txn = _transaction(revenue_at_risk=revenue, failure_description="[recoverable] test")
        result = execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SILENT_RETRY),
            _ai(RecoveryAction.SILENT_RETRY),
        )
        self.assertEqual(result.recovered_amount, revenue)

    def test_revenue_at_risk_zeroed_on_success(self):
        txn = _transaction(revenue_at_risk=49900, failure_description="[recoverable] test")
        execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertEqual(txn.revenue_at_risk, 0)

    def test_revenue_at_risk_unchanged_on_failure(self):
        txn = _transaction(revenue_at_risk=49900, failure_description="[unrecovered] test")
        execute_recovery(
            _mock_db(), txn, _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertEqual(txn.revenue_at_risk, 49900)

    def test_recovered_amount_is_zero_for_skipped(self):
        result = execute_recovery(
            _mock_db(), _transaction(), _customer(),
            _policy(RecoveryAction.DO_NOTHING, PolicyDecision.ALLOW),
            _ai(RecoveryAction.DO_NOTHING),
        )
        self.assertEqual(result.recovered_amount, 0)

    def test_recovered_amount_is_zero_for_escalated(self):
        result = execute_recovery(
            _mock_db(), _transaction(), _customer(),
            _policy(RecoveryAction.ESCALATE, PolicyDecision.ESCALATE),
            _ai(RecoveryAction.ESCALATE),
        )
        self.assertEqual(result.recovered_amount, 0)


# ---------------------------------------------------------------------------
# Tests: policy authority invariant
# ---------------------------------------------------------------------------


class PolicyAuthorityTests(unittest.TestCase):
    def test_executor_uses_policy_final_action_not_ai_recommendation(self):
        """
        When AI recommends SILENT_RETRY but Policy says ESCALATE,
        the executor must perform ESCALATED — not a retry.
        """
        ai = _ai(RecoveryAction.SILENT_RETRY)
        policy = _policy(
            RecoveryAction.ESCALATE,
            PolicyDecision.ESCALATE,
            "Retry limit reached.",
        )
        result = execute_recovery(_mock_db(), _transaction(), _customer(), policy, ai)
        self.assertEqual(result.execution_status, ExecutionStatus.ESCALATED)
        self.assertEqual(result.final_action, RecoveryAction.ESCALATE)

    def test_executor_final_action_matches_policy_not_ai_for_block(self):
        """
        When AI recommends SEND_PAYMENT_LINK but Policy says DO_NOTHING (block),
        the executor must return SKIPPED.
        """
        ai = _ai(RecoveryAction.SEND_PAYMENT_LINK)
        policy = _policy(
            RecoveryAction.DO_NOTHING,
            PolicyDecision.BLOCK,
            "Customer opted out.",
        )
        result = execute_recovery(_mock_db(), _transaction(), _customer(), policy, ai)
        self.assertEqual(result.execution_status, ExecutionStatus.SKIPPED)
        self.assertEqual(result.final_action, RecoveryAction.DO_NOTHING)


# ---------------------------------------------------------------------------
# Tests: audit record and DB interaction
# ---------------------------------------------------------------------------


class AuditAndDbTests(unittest.TestCase):
    def test_intervention_row_always_created(self):
        """db.add() must be called exactly once, with an Intervention object."""
        db = _mock_db()
        execute_recovery(
            db, _transaction(), _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertEqual(db.add.call_count, 1)

    def test_db_commit_called_exactly_once(self):
        db = _mock_db()
        execute_recovery(
            db, _transaction(), _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertEqual(db.commit.call_count, 1)

    def test_db_error_returns_failed_result(self):
        """SQLAlchemyError during commit → controlled FAILED result returned."""
        db = _mock_db()
        db.commit.side_effect = SQLAlchemyError("Connection lost")
        result = execute_recovery(
            db, _transaction(), _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertEqual(result.execution_status, ExecutionStatus.FAILED)
        self.assertEqual(result.recovered_amount, 0)

    def test_db_error_triggers_rollback(self):
        """SQLAlchemyError during commit → db.rollback() called."""
        db = _mock_db()
        db.commit.side_effect = SQLAlchemyError("Constraint violation")
        execute_recovery(
            db, _transaction(), _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        db.rollback.assert_called_once()

    def test_result_is_execution_result_type(self):
        result = execute_recovery(
            _mock_db(), _transaction(), _customer(),
            _policy(RecoveryAction.SEND_PAYMENT_LINK),
            _ai(RecoveryAction.SEND_PAYMENT_LINK),
        )
        self.assertIsInstance(result, ExecutionResult)

    def test_result_txn_id_matches_transaction(self):
        result = execute_recovery(
            _mock_db(), _transaction(txn_id="txn_xyz_123"), _customer(),
            _policy(RecoveryAction.DO_NOTHING, PolicyDecision.ALLOW),
            _ai(RecoveryAction.DO_NOTHING),
        )
        self.assertEqual(result.txn_id, "txn_xyz_123")


if __name__ == "__main__":
    unittest.main()

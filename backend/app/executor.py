"""
Recovery Executor — Phase 5.

Architecture mandate
--------------------
This is the ONLY module authorised to write to the database.

  AI Brain  (ai_brain.py)  — read-only, recommendation only
  Policy Brakes (policy.py) — read-only, deterministic final authority
  Recovery Executor (this) — executes ONLY policy_result.final_action

The executor NEVER:
  - executes ai_decision.recommended_action directly
  - makes real payment API calls
  - modifies transaction.amount (it is immutable)
  - uses floating-point for financial values

Simulated success (synthetic test harness)
------------------------------------------
The [recoverable] prefix in transaction.failure_description encodes the
synthetic ground truth inserted by generate_data.py. This is TEST HARNESS
LOGIC ONLY. In production, a real payment gateway outcome callback replaces
_is_ground_truth_recoverable(). The execute_recovery() interface is unchanged.

DB failure safety
-----------------
SQLAlchemyErrors (I/O, constraint violations) are caught, the session is
rolled back, and a controlled FAILED ExecutionResult is returned.
Programming errors (TypeError, AttributeError, etc.) are NOT caught and
will propagate so bugs surface immediately.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import Intervention, Transaction
from .policy import PolicyResult
from .schemas import AIDecision, ExecutionResult, ExecutionStatus, RecoveryAction

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Ground-truth harness — SYNTHETIC DATA ONLY
# ---------------------------------------------------------------------------


def _is_ground_truth_recoverable(transaction: Transaction) -> bool:
    """
    Read the synthetic ground-truth label from failure_description.

    generate_data.py prefixes every non-success failure_description with one of:
        [recoverable]  — a recovery action will succeed
        [unrecovered]  — the transaction cannot be recovered
        [self_healed]  — it already resolved; Policy Brakes will have blocked this

    Returns True only when the prefix is "[recoverable]".

    PRODUCTION NOTE: Replace this function with a real payment gateway
    outcome callback. The execute_recovery() interface and all surrounding
    logic remain unchanged.
    """
    desc = str(getattr(transaction, "failure_description", "") or "").lower()
    return desc.startswith("[recoverable]")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _apply_success(transaction: Transaction) -> int:
    """
    Update transaction fields to reflect a successful simulated recovery.

    Returns the recovered_amount (integer paise).

    Invariants enforced here:
      - recovered_amount := pre-existing revenue_at_risk (copied, never invented)
      - revenue_at_risk  := 0  (risk is resolved)
      - status           := "SUCCESS"
      - amount is NEVER touched — it is the original charge and is immutable
    """
    recovered: int = int(transaction.revenue_at_risk)  # copy pre-existing integer value
    transaction.status = "SUCCESS"
    transaction.recovered_amount = recovered   # integer paise
    transaction.revenue_at_risk = 0            # risk resolved; no floating-point
    return recovered


def _build_intervention(
    transaction: Transaction,
    ai_decision: AIDecision,
    policy_result: PolicyResult,
    execution_status: ExecutionStatus,
    recovered_amount: int,
) -> Intervention:
    """
    Construct a complete Intervention audit row.

    All string fields are coerced to non-None to satisfy NOT NULL DB constraints.
    recovered_amount is always integer paise.
    """
    return Intervention(
        txn_id=str(transaction.txn_id),
        ai_recommendation=str(ai_decision.recommended_action.value),
        ai_failure_classification=str(ai_decision.failure_classification or ""),
        ai_confidence=float(ai_decision.confidence_score),
        ai_reasoning=str(ai_decision.reasoning or ""),
        policy_decision=str(policy_result.decision.value),
        policy_reason=str(policy_result.reason),
        final_action=str(policy_result.final_action.value),
        execution_status=str(execution_status.value),
        recovered_amount=int(recovered_amount),
        created_at=_utc_now(),
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def execute_recovery(
    db: Session,
    transaction: Transaction,
    customer,           # Customer ORM object or SimpleNamespace — never mutated
    policy_result: PolicyResult,
    ai_decision: AIDecision,
) -> ExecutionResult:
    """
    Execute the final policy-approved action and write the audit record.

    CRITICAL: Executes ONLY policy_result.final_action.
              NEVER executes ai_decision.recommended_action directly.

    Action decision table
    ----------------------
    DO_NOTHING        → SKIPPED;    recovered_amount=0; transaction unchanged
    ESCALATE          → ESCALATED;  recovered_amount=0; transaction unchanged
    SILENT_RETRY      → attempt_count += 1 always
                        [recoverable] → SUCCESS; recovered_amount = revenue_at_risk
                        other         → FAILED;  recovered_amount = 0
    SEND_PAYMENT_LINK → attempt_count NOT incremented (customer-initiated)
                        [recoverable] → SUCCESS; recovered_amount = revenue_at_risk
                        other         → FAILED;  recovered_amount = 0

    On SUCCESS: transaction.status="SUCCESS", revenue_at_risk=0,
                recovered_amount = pre-existing revenue_at_risk (integer paise).
                transaction.amount is NEVER modified.

    DB write: one Intervention row is always created (audit completeness).
    On SQLAlchemyError: session is rolled back; returns FAILED ExecutionResult.
    Programming errors (TypeError etc.) propagate — they are NOT swallowed.
    """
    final_action: RecoveryAction = policy_result.final_action
    recovered_amount: int = 0

    # -----------------------------------------------------------------------
    # Determine execution outcome and apply in-memory transaction changes
    # -----------------------------------------------------------------------

    if final_action == RecoveryAction.DO_NOTHING:
        execution_status = ExecutionStatus.SKIPPED

    elif final_action == RecoveryAction.ESCALATE:
        execution_status = ExecutionStatus.ESCALATED

    elif final_action == RecoveryAction.SILENT_RETRY:
        # The retry was attempted: increment regardless of simulated outcome.
        transaction.attempt_count = int(transaction.attempt_count or 0) + 1
        if _is_ground_truth_recoverable(transaction):
            recovered_amount = _apply_success(transaction)
            execution_status = ExecutionStatus.SUCCESS
        else:
            execution_status = ExecutionStatus.FAILED

    elif final_action == RecoveryAction.SEND_PAYMENT_LINK:
        # Customer-initiated re-attempt: does NOT count against the retry limit.
        if _is_ground_truth_recoverable(transaction):
            recovered_amount = _apply_success(transaction)
            execution_status = ExecutionStatus.SUCCESS
        else:
            execution_status = ExecutionStatus.FAILED

    else:
        # Defensive guard against future enum extensions reaching here.
        logger.error(
            "Unrecognised final_action %r for txn %s — defaulting to ESCALATED.",
            final_action,
            transaction.txn_id,
        )
        execution_status = ExecutionStatus.ESCALATED

    # -----------------------------------------------------------------------
    # Write audit record and commit
    # -----------------------------------------------------------------------

    intervention = _build_intervention(
        transaction, ai_decision, policy_result, execution_status, recovered_amount
    )

    try:
        db.add(intervention)
        db.commit()
    except SQLAlchemyError as exc:
        logger.error(
            "DB write failed for txn %s — rolling back: %s",
            transaction.txn_id,
            exc,
        )
        db.rollback()
        return ExecutionResult(
            txn_id=str(transaction.txn_id),
            final_action=final_action,
            execution_status=ExecutionStatus.FAILED,
            recovered_amount=0,
            policy_decision=str(policy_result.decision.value),
            policy_reason=str(policy_result.reason),
        )

    return ExecutionResult(
        txn_id=str(transaction.txn_id),
        final_action=final_action,
        execution_status=execution_status,
        recovered_amount=int(recovered_amount),
        policy_decision=str(policy_result.decision.value),
        policy_reason=str(policy_result.reason),
    )

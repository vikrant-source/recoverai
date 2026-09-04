"""
Deterministic Policy Brakes.

The AI recommendation is only a suggestion. This module has final
authority and never invents or modifies financial amounts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel

from .schemas import AIDecision, RecoveryAction

MIN_AI_CONFIDENCE = 0.60
MAX_RETRY_ATTEMPTS = 2

SUCCESS_STATUS = "SUCCESS"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


class PolicyResult(BaseModel):
    decision: PolicyDecision
    reason: str
    final_action: RecoveryAction


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _recovery_window_expired(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return False
    return _as_utc(now) >= _as_utc(expires_at)


def _normalize_ai_decision(ai_decision: AIDecision | object) -> AIDecision:
    if isinstance(ai_decision, AIDecision):
        return ai_decision
    if isinstance(ai_decision, dict):
        return AIDecision.model_validate(ai_decision)
    return AIDecision(
        recommended_action=getattr(ai_decision, "recommended_action"),
        confidence_score=getattr(ai_decision, "confidence_score"),
        failure_classification=getattr(ai_decision, "failure_classification", None),
        reasoning=getattr(ai_decision, "reasoning", None),
    )


def evaluate_policy(
    transaction,
    customer,
    ai_decision,
    recent_interventions=None,
) -> PolicyResult:
    """
    Evaluate an AI recovery recommendation before any action is executed.

    Rules run in a fixed order. The first matching brake wins.

    recent_interventions is reserved for a future cooldown check and is
    not enforced yet.
    """
    # Extension point: cooldown / duplicate-intervention checks can use
    # recent_interventions without changing the evaluate_policy signature.
    if recent_interventions:
        pass

    ai = _normalize_ai_decision(ai_decision)
    now = datetime.now(timezone.utc)

    status = str(getattr(transaction, "status", "")).upper()
    if status == SUCCESS_STATUS:
        return PolicyResult(
            decision=PolicyDecision.BLOCK,
            reason="Payment is already successful; no recovery action is required.",
            final_action=RecoveryAction.DO_NOTHING,
        )

    if bool(getattr(customer, "opted_out", False)):
        return PolicyResult(
            decision=PolicyDecision.BLOCK,
            reason="Customer has opted out of recovery communication/actions.",
            final_action=RecoveryAction.DO_NOTHING,
        )

    expires_at = getattr(transaction, "recovery_window_expires_at", None)
    if _recovery_window_expired(expires_at, now):
        return PolicyResult(
            decision=PolicyDecision.BLOCK,
            reason="Recovery window has expired.",
            final_action=RecoveryAction.DO_NOTHING,
        )

    attempt_count = int(getattr(transaction, "attempt_count", 1) or 0)
    if attempt_count >= MAX_RETRY_ATTEMPTS:
        return PolicyResult(
            decision=PolicyDecision.ESCALATE,
            reason="Retry limit reached.",
            final_action=RecoveryAction.ESCALATE,
        )

    revenue_at_risk = int(getattr(transaction, "revenue_at_risk", 0) or 0)
    if revenue_at_risk <= 0:
        return PolicyResult(
            decision=PolicyDecision.BLOCK,
            reason="There is no unresolved revenue at risk.",
            final_action=RecoveryAction.DO_NOTHING,
        )

    if ai.confidence_score < MIN_AI_CONFIDENCE:
        return PolicyResult(
            decision=PolicyDecision.ESCALATE,
            reason="AI confidence is below the intervention threshold.",
            final_action=RecoveryAction.ESCALATE,
        )

    if ai.recommended_action == RecoveryAction.DO_NOTHING:
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason="AI recommended DO_NOTHING; preserving the decision not to intervene.",
            final_action=RecoveryAction.DO_NOTHING,
        )

    return PolicyResult(
        decision=PolicyDecision.ALLOW,
        reason="Policy brakes allow the AI recommendation.",
        final_action=ai.recommended_action,
    )

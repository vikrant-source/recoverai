from enum import Enum

from pydantic import BaseModel, Field


class RecoveryAction(str, Enum):
    DO_NOTHING = "DO_NOTHING"
    SILENT_RETRY = "SILENT_RETRY"
    SEND_PAYMENT_LINK = "SEND_PAYMENT_LINK"
    ESCALATE = "ESCALATE"


class AIDecision(BaseModel):
    """AI Brain suggestion only — Policy Brakes have final authority."""

    recommended_action: RecoveryAction
    confidence_score: float = Field(ge=0.0, le=1.0)
    failure_classification: str | None = None
    reasoning: str | None = None


class ExecutionStatus(str, Enum):
    """Outcome of a single Recovery Executor run."""

    SUCCESS = "SUCCESS"    # simulated recovery attempt succeeded
    FAILED = "FAILED"      # simulated recovery attempt did not recover revenue
    SKIPPED = "SKIPPED"    # Policy Brakes chose DO_NOTHING — no attempt made
    ESCALATED = "ESCALATED"  # marked for human review; no automatic attempt


class ExecutionResult(BaseModel):
    """Produced by the Recovery Executor after the Policy Brakes have approved
    the final action. Never produced by the AI Brain or Policy Brakes directly."""

    txn_id: str
    final_action: RecoveryAction     # the action that was executed (policy-approved)
    execution_status: ExecutionStatus
    # Integer paise only. Always 0 unless simulated recovery succeeded.
    recovered_amount: int
    policy_decision: str             # PolicyDecision.value — kept as str to avoid circular import
    policy_reason: str

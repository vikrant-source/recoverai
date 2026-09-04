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

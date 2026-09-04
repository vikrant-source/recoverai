"""
Webhook API schemas — Phase 6.

Defines request and response shapes for POST /webhooks/payment.

SYNTHETIC / TEST MODE ONLY
---------------------------
This endpoint operates in synthetic mode for the RecoverAI hackathon.
payload.synthetic=True bypasses Razorpay HMAC signature verification.
No real payment API calls are made.
Production Razorpay signature verification is NOT implemented here.

All monetary values use integer paise (never floating-point).
"""

from __future__ import annotations

from pydantic import BaseModel


class WebhookPayload(BaseModel):
    """
    Incoming payment webhook event body.

    event_id  — idempotency key; must be unique per physical event delivery.
    event_type — only "payment.failed" triggers recovery processing.
    txn_id    — maps to Transaction.txn_id in the database.
    synthetic  — True for hackathon/test events; bypasses signature check.
    """

    event_id: str
    event_type: str
    txn_id: str
    synthetic: bool = True  # Set False only when production HMAC verification is added.

    # Unknown fields are accepted and stored in the WebhookEvent payload JSON column
    # for forward-compatibility with richer Razorpay event shapes.
    model_config = {"extra": "allow"}


class WebhookResponse(BaseModel):
    """
    Synchronous HTTP 200 response returned to the webhook caller.

    status values
    -------------
    ACCEPTED  — event processed; recovery pipeline was executed.
    DUPLICATE — event_id already seen; idempotent replay; pipeline NOT re-run.
    IGNORED   — event dropped (wrong event_type, transaction not found, etc.).

    All three status values use HTTP 200. Returning 4xx would cause Razorpay
    to retry delivery, generating more duplicate events for the idempotency
    layer to absorb. We always acknowledge with 200 and encode outcome in status.

    recovered_amount is in integer paise. None means not yet determined
    (DUPLICATE or IGNORED response) or no revenue was recovered.
    """

    event_id: str
    status: str                          # "ACCEPTED" | "DUPLICATE" | "IGNORED"
    txn_id: str | None = None
    message: str                         # human-readable explanation

    # Populated only when status == "ACCEPTED" (synchronous pipeline execution)
    execution_status: str | None = None  # ExecutionStatus.value
    final_action: str | None = None      # RecoveryAction.value
    recovered_amount: int | None = None  # integer paise; 0 if none recovered

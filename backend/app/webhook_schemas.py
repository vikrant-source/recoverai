"""
Webhook API schemas.

Defines request and response shapes for POST /webhooks/payment.

Two accepted request formats
----------------------------
A) Synthetic / existing format (synthetic=True):
   {
     "event_id": "...",
     "event_type": "payment.failed",
     "txn_id": "...",
     "synthetic": true
   }

B) Real Razorpay payment.failed webhook (synthetic=False or absent):
   Standard Razorpay shape with X-Razorpay-Signature and
   X-Razorpay-Event-Id headers. Normalised by razorpay_normaliser.py
   before being passed to the existing pipeline.

All monetary values use integer paise (never floating-point).

Signature verification
----------------------
When RAZORPAY_WEBHOOK_SECRET is set in the environment, the
X-Razorpay-Signature header is verified using HMAC-SHA256 against the raw
request body. If the secret is not configured, verification is skipped
(development / synthetic mode).

RAZORPAY_KEY_SECRET is NEVER read or used here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Original synthetic webhook schema — unchanged
# ---------------------------------------------------------------------------

class WebhookPayload(BaseModel):
    """
    Incoming payment webhook event body — synthetic / existing format.

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


# ---------------------------------------------------------------------------
# Internal canonical event — used by the unified handler path
# ---------------------------------------------------------------------------

class WebhookInternalEvent:
    """
    Internal canonical representation of a webhook event after normalisation.

    This is NOT a Pydantic model — it is a plain Python dataclass-style
    object used only inside the server process. It is never serialised to
    JSON for external consumers.

    Fields
    ------
    event_id   Idempotency key (from header or body, depending on source).
    event_type "payment.failed" or similar.
    txn_id     Local RecoverAI transaction ID. None if mapping is absent.
    synthetic  True for synthetic events (bypass signature check).
    audit_data Dict of additional fields for WebhookEvent.payload (no secrets).
    """

    __slots__ = ("event_id", "event_type", "txn_id", "synthetic", "audit_data")

    def __init__(
        self,
        event_id: str,
        event_type: str,
        txn_id: str | None,
        synthetic: bool,
        audit_data: dict[str, Any] | None = None,
    ) -> None:
        self.event_id = event_id
        self.event_type = event_type
        self.txn_id = txn_id
        self.synthetic = synthetic
        self.audit_data: dict[str, Any] = audit_data or {}


# ---------------------------------------------------------------------------
# Response schema — unchanged
# ---------------------------------------------------------------------------

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

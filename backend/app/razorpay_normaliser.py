"""
Razorpay payload normaliser.

Converts a real Razorpay payment.failed webhook body into the canonical
internal representation used by the existing webhook_handler pipeline.

Transaction mapping strategy (MVP)
------------------------------------
Razorpay does not natively know our local txn_id values (e.g. "txn_0032").
The safe, auditable mapping mechanism for this MVP is:

  Razorpay Order → notes.recoverai_txn_id → local Transaction.txn_id

When creating a Razorpay order for a RecoverAI transaction, store the local
txn_id in the order's `notes` field:

    {"notes": {"recoverai_txn_id": "txn_0032"}}

The webhook then carries this value at:
    payload.payload.payment.entity.notes.recoverai_txn_id

If that key is absent or empty, we cannot safely map the payment to a local
transaction and return None, causing the webhook handler to return IGNORED.

We deliberately do NOT:
  - Match by amount (amounts can collide)
  - Match by Razorpay payment ID alone (no local row for it)
  - Create a synthetic transaction from webhook data

NEVER expose or log secrets. No financial amounts are used for mapping.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# The key inside Razorpay order notes that carries our local txn_id.
_NOTES_TXN_KEY = "recoverai_txn_id"


class RazorpayNormaliseError(Exception):
    """Raised when the payload cannot be parsed into a usable internal event."""


def extract_txn_id_from_razorpay_notes(entity: dict[str, Any]) -> str | None:
    """
    Extract the RecoverAI local txn_id from Razorpay payment entity notes.

    Returns the txn_id string if present and non-empty, else None.
    """
    notes = entity.get("notes") or {}
    if isinstance(notes, dict):
        val = notes.get(_NOTES_TXN_KEY, "")
        return str(val).strip() if val else None
    return None


def normalise_razorpay_payment_failed(
    body: dict[str, Any],
    razorpay_event_id: str | None,
) -> dict[str, Any]:
    """
    Parse a real Razorpay payment.failed webhook body and return a normalised
    internal dict compatible with the fields consumed by handle_payment_webhook.

    Parameters
    ----------
    body               Parsed JSON body of the Razorpay webhook.
    razorpay_event_id  Value of the X-Razorpay-Event-Id header, if present.

    Returns
    -------
    A dict with keys:
        event_id    — idempotency key (header preferred, else body["event"])
        event_type  — always "payment.failed" for this path
        txn_id      — local RecoverAI txn_id from order notes, or None
        synthetic   — always False (real Razorpay event)
        razorpay_payment_id — the Razorpay payment ID, for audit only
        razorpay_order_id   — the Razorpay order ID, for audit only
        failure_code        — from entity.error_code, for audit only
        failure_description — from entity.error_description, for audit only

    Raises
    ------
    RazorpayNormaliseError if the body is structurally invalid (missing required
    top-level fields). txn_id may be None even on success (caller handles it).
    """
    # ── Validate top-level shape ──────────────────────────────────────────────
    event_type = body.get("event", "")
    if not event_type:
        raise RazorpayNormaliseError(
            "Razorpay payload missing required 'event' field."
        )

    # ── Derive idempotency event_id ───────────────────────────────────────────
    # Prefer the X-Razorpay-Event-Id header (set by Razorpay on every delivery).
    # Fall back to body["event_id"] if somehow provided, else use a compound key.
    if razorpay_event_id:
        event_id = str(razorpay_event_id).strip()
    else:
        # Razorpay does not always include event_id in the body, but we need
        # a stable idempotency key. Compose one from payment ID if available.
        payment_id = _safe_get_payment_id(body)
        event_id = body.get("event_id") or (
            f"rzp_{event_type}_{payment_id}" if payment_id else ""
        )
        if not event_id:
            raise RazorpayNormaliseError(
                "Cannot derive a stable idempotency event_id: "
                "X-Razorpay-Event-Id header is absent and payload "
                "contains no usable fallback identifier."
            )

    # ── Extract payment entity ────────────────────────────────────────────────
    try:
        entity: dict[str, Any] = body["payload"]["payment"]["entity"]
    except (KeyError, TypeError):
        raise RazorpayNormaliseError(
            "Razorpay payload missing 'payload.payment.entity'. "
            "Expected standard Razorpay payment.failed structure."
        )

    payment_id: str = entity.get("id", "") or ""
    order_id: str = entity.get("order_id", "") or ""
    failure_code: str = entity.get("error_code", "") or ""
    failure_description: str = entity.get("error_description", "") or ""

    # ── Transaction mapping ───────────────────────────────────────────────────
    txn_id = extract_txn_id_from_razorpay_notes(entity)

    if not txn_id:
        logger.info(
            "Razorpay event '%s': no '%s' found in order notes. "
            "Cannot map to a local transaction. Event will be IGNORED.",
            event_id,
            _NOTES_TXN_KEY,
        )

    return {
        "event_id": event_id,
        "event_type": event_type,      # "payment.failed"
        "txn_id": txn_id,              # None when mapping is absent
        "synthetic": False,
        # Audit fields — stored in WebhookEvent.payload, never used for logic
        "razorpay_payment_id": payment_id,
        "razorpay_order_id": order_id,
        "failure_code": failure_code,
        "failure_description": failure_description,
    }


def _safe_get_payment_id(body: dict[str, Any]) -> str:
    """Extract payment ID without raising."""
    try:
        return body["payload"]["payment"]["entity"].get("id", "") or ""
    except (KeyError, TypeError):
        return ""

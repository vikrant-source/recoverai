"""
Webhook Handler.

Entry point for POST /webhooks/payment. Implements idempotency and drives the
recovery pipeline for payment.failed events.

Accepts both synthetic and real Razorpay webhook events via WebhookInternalEvent.
The normalisation / signature verification is done in main.py before this function
is called, keeping this handler focused solely on idempotency + pipeline logic.

Idempotency state machine
-------------------------
WebhookEvent.status transitions:

    (new) → PROCESSING → COMPLETED
                       ↘ FAILED

PROCESSING is written as the first commit, acting as an idempotency lock.
Any existing row (PROCESSING, COMPLETED, or FAILED) → DUPLICATE response.
Concurrent duplicate delivery raising IntegrityError → DUPLICATE response.
DUPLICATE events never invoke the recovery pipeline.

Two-commit design (accepted MVP trade-off)
------------------------------------------
1. execute_recovery() [inside run_recovery_pipeline()] commits the
   Intervention + Transaction recovery state.
2. This handler then commits the WebhookEvent COMPLETED status update.

If the process crashes between these two commits, the Intervention is durable
but the WebhookEvent remains PROCESSING. The idempotency check treats
PROCESSING as DUPLICATE, so the event is never automatically re-processed.
This is detectable via operations monitoring and acceptable for the hackathon.

Synchronous processing (MVP choice)
-------------------------------------
The full pipeline (AI Brain + Policy Brakes + Executor) runs synchronously.
The HTTP caller waits for the complete result. This gives the cleanest
idempotency guarantee and includes execution details in the response.
For production with strict timeout requirements, move pipeline execution to
a background worker without changing this module's interface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .context_builder import ContextLoadError, load_context
from .models import WebhookEvent
from .pipeline import run_recovery_pipeline
from .webhook_schemas import WebhookInternalEvent, WebhookResponse

logger = logging.getLogger(__name__)

# Only this event type triggers the recovery pipeline.
_PAYMENT_FAILED_EVENT = "payment.failed"

# WebhookEvent.status string constants (match the DB column values).
_STATUS_PROCESSING = "PROCESSING"
_STATUS_COMPLETED = "COMPLETED"
_STATUS_FAILED = "FAILED"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _find_existing(db: Session, event_id: str) -> WebhookEvent | None:
    return (
        db.query(WebhookEvent)
        .filter(WebhookEvent.event_id == event_id)
        .first()
    )


def _mark_completed(db: Session, event: WebhookEvent) -> None:
    """
    Transition WebhookEvent to COMPLETED and commit.
    Called after a successful pipeline run.

    The Intervention + Transaction state is already durably committed (by the
    executor). If this commit fails, we log the error but do not raise —
    the caller still returns ACCEPTED because the recovery is complete.
    """
    event.status = _STATUS_COMPLETED
    event.completed_at = _utc_now()
    try:
        db.commit()
    except SQLAlchemyError as exc:
        logger.error(
            "Failed to mark WebhookEvent '%s' as COMPLETED: %s. "
            "Intervention is durable; event remains PROCESSING in DB.",
            event.event_id,
            exc,
        )


def _mark_failed(db: Session, event: WebhookEvent, error_message: str) -> None:
    """
    Transition WebhookEvent to FAILED and commit.
    Called when context loading fails or the pipeline raises unexpectedly.
    """
    event.status = _STATUS_FAILED
    event.completed_at = _utc_now()
    event.error_message = str(error_message)[:500]
    try:
        db.commit()
    except SQLAlchemyError as exc:
        logger.error(
            "Failed to mark WebhookEvent '%s' as FAILED: %s",
            event.event_id,
            exc,
        )


def handle_payment_webhook(
    db: Session,
    event: WebhookInternalEvent,
) -> WebhookResponse:
    """
    Process a payment webhook event through the full idempotency + pipeline flow.

    Accepts a WebhookInternalEvent — a normalised canonical representation that
    works for both synthetic and real Razorpay payloads. Callers (main.py) are
    responsible for parsing, signature verification, and normalisation before
    calling this function.

    Processing steps
    ----------------
    1.  Filter event_type — wrong type → IGNORED (no DB write).
    2.  Check txn_id — None (no mapping) → IGNORED (no DB write).
    3.  Idempotency check — existing row → DUPLICATE (no pipeline call).
    4.  Write WebhookEvent (status=PROCESSING) — acts as idempotency lock.
        IntegrityError on concurrent duplicate → DUPLICATE.
    5.  Load Transaction + Customer via context_builder.
        ContextLoadError → WebhookEvent=FAILED, return IGNORED.
    6.  run_recovery_pipeline() → AI Brain → Policy Brakes → Executor.
        Executor commits Intervention + Transaction state internally.
        Unexpected exception → rollback, WebhookEvent=FAILED, return IGNORED.
    7.  Mark WebhookEvent=COMPLETED (second commit).
    8.  Return ACCEPTED with full execution details.

    Returns HTTP 200 in all cases. See WebhookResponse.status for outcome.
    """

    # ------------------------------------------------------------------
    # Step 1: Filter by event_type — no DB interaction for wrong types.
    # ------------------------------------------------------------------
    if event.event_type != _PAYMENT_FAILED_EVENT:
        logger.info(
            "Event '%s' ignored: event_type='%s' is not handled.",
            event.event_id,
            event.event_type,
        )
        return WebhookResponse(
            event_id=event.event_id,
            status="IGNORED",
            txn_id=event.txn_id,
            message=(
                f"Event type '{event.event_type}' is not handled by this endpoint. "
                "Only 'payment.failed' events trigger recovery."
            ),
        )

    # ------------------------------------------------------------------
    # Step 2: Reject unmapped events (real Razorpay without notes mapping).
    # ------------------------------------------------------------------
    if event.txn_id is None:
        logger.info(
            "Event '%s' ignored: no local txn_id could be mapped. "
            "Add recoverai_txn_id to the Razorpay order notes.",
            event.event_id,
        )
        return WebhookResponse(
            event_id=event.event_id,
            status="IGNORED",
            txn_id=None,
            message=(
                "No local transaction mapping found for this Razorpay event. "
                "Set notes.recoverai_txn_id on the Razorpay order to enable recovery."
            ),
        )

    # ------------------------------------------------------------------
    # Step 3: Idempotency check — any existing row blocks re-processing.
    # ------------------------------------------------------------------
    existing = _find_existing(db, event.event_id)
    if existing is not None:
        logger.info(
            "Duplicate event '%s' (existing status=%s). Pipeline not re-run.",
            event.event_id,
            existing.status,
        )
        return WebhookResponse(
            event_id=event.event_id,
            status="DUPLICATE",
            txn_id=event.txn_id,
            message=(
                f"Event '{event.event_id}' has already been received "
                f"(status={existing.status}). Recovery pipeline was not re-run."
            ),
        )

    # ------------------------------------------------------------------
    # Step 4: Write WebhookEvent with status=PROCESSING.
    # This is the idempotency lock. The primary key constraint prevents
    # a second concurrent insert for the same event_id.
    # ------------------------------------------------------------------

    # Build the audit payload — include event metadata and any audit_data
    # from the normaliser, but never include secrets.
    audit_payload: dict = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "txn_id": event.txn_id,
        "synthetic": event.synthetic,
    }
    audit_payload.update(event.audit_data)

    webhook_event = WebhookEvent(
        event_id=event.event_id,
        event_type=event.event_type,
        status=_STATUS_PROCESSING,
        payload=audit_payload,
        created_at=_utc_now(),
    )

    try:
        db.add(webhook_event)
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning(
            "IntegrityError inserting event '%s': concurrent duplicate delivery.",
            event.event_id,
        )
        return WebhookResponse(
            event_id=event.event_id,
            status="DUPLICATE",
            txn_id=event.txn_id,
            message=(
                f"Event '{event.event_id}' is already being processed "
                "(concurrent delivery race detected)."
            ),
        )

    # ------------------------------------------------------------------
    # Step 5: Load Transaction and Customer (read-only).
    # ------------------------------------------------------------------
    try:
        transaction, customer = load_context(db, event.txn_id)
    except ContextLoadError as exc:
        logger.warning(
            "Context load failed for event '%s': %s", event.event_id, exc
        )
        _mark_failed(db, webhook_event, str(exc))
        return WebhookResponse(
            event_id=event.event_id,
            status="IGNORED",
            txn_id=event.txn_id,
            message=str(exc),
        )

    # ------------------------------------------------------------------
    # Step 6: Run recovery pipeline.
    #   AI Brain  → AIDecision   (read-only; never raises)
    #   Policy    → PolicyResult  (read-only; deterministic)
    #   Executor  → ExecutionResult (commits Intervention + Transaction)
    # ------------------------------------------------------------------
    try:
        result = run_recovery_pipeline(db, transaction, customer)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Recovery pipeline raised unexpectedly for event '%s': %s",
            event.event_id,
            exc,
        )
        db.rollback()
        _mark_failed(db, webhook_event, f"Pipeline error: {str(exc)[:470]}")
        return WebhookResponse(
            event_id=event.event_id,
            status="IGNORED",
            txn_id=event.txn_id,
            message="Recovery pipeline failed unexpectedly. Event recorded as FAILED.",
        )

    # ------------------------------------------------------------------
    # Step 7: Mark WebhookEvent COMPLETED.
    # The Intervention is already durable (committed by the executor).
    # ------------------------------------------------------------------
    _mark_completed(db, webhook_event)

    return WebhookResponse(
        event_id=event.event_id,
        status="ACCEPTED",
        txn_id=event.txn_id,
        message="Recovery pipeline executed successfully.",
        execution_status=str(result.execution_status.value),
        final_action=str(result.final_action.value),
        recovered_amount=int(result.recovered_amount),  # integer paise
    )

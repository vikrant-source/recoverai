"""
RecoverAI — FastAPI application.

POST /webhooks/payment accepts two formats:
  A) Synthetic: {"event_id":..., "event_type":..., "txn_id":..., "synthetic":true}
  B) Real Razorpay payment.failed webhook body with X-Razorpay-Signature header.

Signature verification (Razorpay path only):
  When RAZORPAY_WEBHOOK_SECRET is configured, the X-Razorpay-Signature header
  is verified via HMAC-SHA256 against the raw request body.
  Invalid signatures are rejected with HTTP 400 (not 200, since a bad signature
  indicates a non-Razorpay caller, not a benign duplicate).
  RAZORPAY_KEY_SECRET is never used or read here.

CORS is configured for the Vite dev server (localhost:5173).
"""

from __future__ import annotations

import json
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from . import models  # noqa: F401 — ensures all ORM models are registered
from .api_routes import router as api_router
from .razorpay_test_router import router as razorpay_test_router
from .razorpay_sig import verify_razorpay_signature
from .razorpay_normaliser import normalise_razorpay_payment_failed, RazorpayNormaliseError
from .webhook_handler import handle_payment_webhook
from .webhook_schemas import WebhookInternalEvent, WebhookResponse

logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="RecoverAI",
    description="AI Revenue Recovery Agent",
    version="0.1.0",
)

# Allow the Vite dev server (localhost:5173) to call the API.
# Restrict to GET + POST and explicit origins only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Register read-only dashboard routes (GET /api/*)
app.include_router(api_router)

# Register isolated Razorpay test route (GET /api/razorpay-test/*)
app.include_router(razorpay_test_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/webhooks/payment", response_model=WebhookResponse)
async def payment_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
) -> WebhookResponse:
    """
    Receive a payment webhook event and run the recovery pipeline.

    Accepts two formats:
    A) Synthetic (existing): JSON body with event_id, event_type, txn_id, synthetic=true.
       Signature verification is skipped for synthetic events.
    B) Real Razorpay payment.failed: Standard Razorpay webhook body.
       When RAZORPAY_WEBHOOK_SECRET is configured, X-Razorpay-Signature is
       verified via HMAC-SHA256. Invalid signatures → HTTP 400.

    Returns HTTP 200 in all cases once accepted. See WebhookResponse.status:
      ACCEPTED  — pipeline executed
      DUPLICATE — event_id already processed; idempotent replay
      IGNORED   — wrong event_type, unmapped transaction, or not found
    """
    # ── Read raw body once (needed for HMAC verification before JSON parsing) ─
    raw_body: bytes = await request.body()

    # ── Parse JSON ────────────────────────────────────────────────────────────
    try:
        body: dict = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=422, detail="Request body is not valid JSON.")

    # ── Determine synthetic vs real Razorpay ──────────────────────────────────
    # A payload is treated as synthetic when it explicitly sets synthetic=true
    # AND supplies the top-level event_id and txn_id fields (existing format).
    is_synthetic = bool(body.get("synthetic", False))

    if is_synthetic:
        # ── Path A: Synthetic / existing format ───────────────────────────────
        # Validate required fields manually (mirrors old Pydantic validation).
        event_id = body.get("event_id", "")
        event_type = body.get("event_type", "")
        txn_id = body.get("txn_id", "")

        if not event_id or not event_type or not txn_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Synthetic payload requires: event_id, event_type, txn_id. "
                    "One or more fields are missing or empty."
                ),
            )

        internal_event = WebhookInternalEvent(
            event_id=event_id,
            event_type=event_type,
            txn_id=txn_id,
            synthetic=True,
            audit_data={k: v for k, v in body.items()
                        if k not in ("event_id", "event_type", "txn_id", "synthetic")},
        )

    else:
        # ── Path B: Real Razorpay webhook ─────────────────────────────────────
        # Step 1: Signature verification (before any processing).
        if not verify_razorpay_signature(raw_body, x_razorpay_signature):
            # Invalid signature from a non-Razorpay caller — reject with 400.
            # We use 400 here (not 200) because a bad signature means the
            # request did not come from Razorpay and must not be silently accepted.
            logger.warning(
                "Rejected webhook: invalid or missing X-Razorpay-Signature."
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "Webhook signature verification failed. "
                    "Ensure RAZORPAY_WEBHOOK_SECRET matches the configured webhook secret."
                ),
            )

        # Step 2: Normalise Razorpay payload to internal event.
        try:
            normalised = normalise_razorpay_payment_failed(body, x_razorpay_event_id)
        except RazorpayNormaliseError as exc:
            logger.warning("Razorpay payload normalisation failed: %s", exc)
            raise HTTPException(status_code=422, detail=str(exc))

        internal_event = WebhookInternalEvent(
            event_id=normalised["event_id"],
            event_type=normalised["event_type"],
            txn_id=normalised["txn_id"],          # may be None
            synthetic=False,
            audit_data={
                k: v for k, v in normalised.items()
                if k not in ("event_id", "event_type", "txn_id", "synthetic")
            },
        )

    # ── Unified handler: idempotency + pipeline ───────────────────────────────
    return handle_payment_webhook(db, internal_event)
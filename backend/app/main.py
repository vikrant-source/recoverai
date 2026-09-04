from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from . import models  # noqa: F401 — ensures all ORM models are registered
from .webhook_schemas import WebhookPayload, WebhookResponse
from .webhook_handler import handle_payment_webhook

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="RecoverAI",
    description="AI Revenue Recovery Agent",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/webhooks/payment", response_model=WebhookResponse)
def payment_webhook(
    payload: WebhookPayload,
    db: Session = Depends(get_db),
) -> WebhookResponse:
    """
    Receive a payment webhook event and run the recovery pipeline.

    SYNTHETIC / TEST MODE ONLY — payload.synthetic=True bypasses all
    Razorpay HMAC signature verification. No real payment API calls are made.

    Returns HTTP 200 in all cases. See WebhookResponse.status for outcome:
      ACCEPTED  — pipeline executed
      DUPLICATE — event_id already processed; idempotent replay
      IGNORED   — wrong event_type or transaction not found
    """
    return handle_payment_webhook(db, payload)
"""
Razorpay Test Mode — isolated endpoint.

HACKATHON TEST MODE ONLY.
Provides endpoints to support the standalone Razorpay Test Checkout page.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .models import Transaction

# Load .env from repo root (same pattern as ai_brain.py)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

router = APIRouter(prefix="/api/razorpay-test", tags=["razorpay-test"])

# Hardcoded fallback for the old GET /config endpoint (just in case)
_TEST_ORDER_ID = "order_TYENvNVAP8Ozj5"
_TEST_AMOUNT_PAISE = 99900   # ₹999 in integer paise
_TEST_CURRENCY = "INR"
_TEST_DESCRIPTION = "RecoverAI Test Mode — Synthetic payment"


@router.get("/config")
def get_razorpay_test_config() -> dict:
    """
    Legacy static config (kept for compatibility).
    RAZORPAY_KEY_SECRET is deliberately NEVER read or returned here.
    """
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    if not key_id:
        raise HTTPException(
            status_code=503,
            detail="RAZORPAY_KEY_ID is not set in the environment."
        )

    return {
        "key_id": key_id,
        "order_id": _TEST_ORDER_ID,
        "amount_paise": _TEST_AMOUNT_PAISE,
        "currency": _TEST_CURRENCY,
        "description": _TEST_DESCRIPTION,
        "mode": "TEST",
    }


class CreateOrderRequest(BaseModel):
    txn_id: str


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str
    txn_id: str


@router.post("/create-order", response_model=CreateOrderResponse)
def create_razorpay_test_order(
    req: CreateOrderRequest,
    db: Session = Depends(get_db)
) -> CreateOrderResponse:
    """
    Creates a real Razorpay Test Mode order mapped to an existing local transaction.
    
    This verifies the txn_id exists locally, then calls the Razorpay API to create
    an order with notes.recoverai_txn_id = txn_id.
    
    RAZORPAY_KEY_SECRET is read here to call the API, but is NEVER returned.
    """
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    
    if not key_id or not key_secret:
        raise HTTPException(
            status_code=503,
            detail="RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET is not set."
        )

    # 1. Validate txn_id exists locally
    transaction = db.query(Transaction).filter(Transaction.txn_id == req.txn_id).first()
    if not transaction:
        raise HTTPException(
            status_code=404,
            detail=f"Transaction '{req.txn_id}' not found in database."
        )

    # 2. Call Razorpay API to create the order
    url = "https://api.razorpay.com/v1/orders"
    payload_dict = {
        "amount": transaction.amount,
        "currency": transaction.currency,
        "receipt": f"recoverai_{transaction.txn_id}_{int(time.time())}",
        "notes": {
            "recoverai_txn_id": transaction.txn_id
        }
    }
    
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    
    auth_str = f"{key_id}:{key_secret}"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    
    request = urllib.request.Request(url, data=payload_bytes, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Basic {b64_auth}")
    
    try:
        with urllib.request.urlopen(request) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            razorpay_order_id = resp_data["id"]
    except urllib.error.URLError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to communicate with Razorpay API: {e}"
        )

    # 3. Return only safe data for the frontend checkout
    return CreateOrderResponse(
        order_id=razorpay_order_id,
        amount=transaction.amount,
        currency=transaction.currency,
        key_id=key_id,
        txn_id=transaction.txn_id
    )


class SimulatePaymentSuccessRequest(BaseModel):
    txn_id: str


@router.post("/simulate-payment-success")
def simulate_payment_success(
    req: SimulatePaymentSuccessRequest,
    db: Session = Depends(get_db)
) -> dict:
    """
    Test Mode Only: Simulates receiving a successful payment outcome (e.g., payment.captured webhook).

    This fulfills the financial invariant that merely executing a recovery action
    (like SEND_PAYMENT_LINK) does not instantly recover money. This endpoint must be
    called to transition the transaction from AWAITING_PAYMENT to SUCCESS and formally
    recognize the revenue as recovered.
    """
    from .models import Intervention

    transaction = db.query(Transaction).filter(Transaction.txn_id == req.txn_id).first()
    if not transaction:
        raise HTTPException(
            status_code=404,
            detail=f"Transaction '{req.txn_id}' not found in database."
        )

    if transaction.status == "SUCCESS":
        return {"status": "already_success", "recovered_amount": transaction.recovered_amount}

    if transaction.status != "AWAITING_PAYMENT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot simulate success. Transaction is in '{transaction.status}' state, not AWAITING_PAYMENT."
        )

    # Recover the revenue
    recovered = int(transaction.revenue_at_risk)
    transaction.status = "SUCCESS"
    transaction.recovered_amount = recovered
    transaction.revenue_at_risk = 0

    # Also update the latest intervention so the dashboard reads the correct recovered amount
    intervention = (
        db.query(Intervention)
        .filter(Intervention.txn_id == req.txn_id)
        .order_by(Intervention.created_at.desc())
        .first()
    )
    if intervention:
        intervention.recovered_amount = recovered

    db.commit()

    return {
        "status": "success",
        "txn_id": transaction.txn_id,
        "recovered_amount": recovered
    }

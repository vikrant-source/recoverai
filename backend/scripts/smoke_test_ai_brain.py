"""
Smoke test — ONE real Groq API call for manual verification of Phase 4.

Usage (from repo root):
    python backend/scripts/smoke_test_ai_brain.py

This script is:
  - Completely read-only: no DB writes, no financial state changes.
  - Intended to be run manually, exactly once, to verify the live Groq
    integration. It is NOT part of the automated test suite.
  - Safe: get_ai_decision() never raises; it falls back to ESCALATE on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai_brain import build_context, get_ai_decision
from app.database import SessionLocal
from app import models


def _pick_failed_transaction(db):
    """Return the first FAILED transaction that has revenue at risk, or None."""
    return (
        db.query(models.Transaction)
        .filter(
            models.Transaction.status == "FAILED",
            models.Transaction.revenue_at_risk > 0,
        )
        .first()
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    db = SessionLocal()
    try:
        txn = _pick_failed_transaction(db)
        if txn is None:
            print("No eligible FAILED transaction found in DB. Aborting smoke test.")
            return

        customer = (
            db.query(models.Customer)
            .filter(models.Customer.customer_id == txn.customer_id)
            .first()
        )
        if customer is None:
            print(f"Customer {txn.customer_id!r} not found. Aborting smoke test.")
            return

        print("=" * 60)
        print("RecoverAI — AI Brain Smoke Test (ONE real Groq call)")
        print("=" * 60)
        print(f"Transaction : {txn.txn_id}")
        print(f"Status      : {txn.status}")
        print(f"Amount      : {txn.amount} paise")
        print(f"Failure code: {txn.failure_code}")
        print(f"Customer    : {txn.customer_id}  (tier={customer.ltv_tier})")
        print()

        context = build_context(txn, customer)
        print("Context sent to Groq:")
        import json
        print(json.dumps(context, indent=2))
        print()

        print("Calling Groq (this is the only real API call)...")
        decision = get_ai_decision(txn, customer)

        print()
        print("AI Decision (recommendation only — Policy Brakes have final authority):")
        print(f"  recommended_action     : {decision.recommended_action.value}")
        print(f"  confidence_score       : {decision.confidence_score:.2f}")
        print(f"  failure_classification : {decision.failure_classification}")
        print(f"  reasoning              : {decision.reasoning}")
        print()
        print("No database state was modified. Smoke test complete.")

    finally:
        db.close()


if __name__ == "__main__":
    main()

"""
Create Demo Transaction

Creates exactly one clean, predictable transaction and customer for the
RecoverAI Razorpay Test Mode demo. It does not overwrite or delete any
existing data, making it safe to run anytime.

This script is idempotent. Running it multiple times will not create duplicates.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the backend root is in the Python path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models import Customer, Transaction

DEMO_CUST_ID = "cust_demo_001"
DEMO_TXN_ID = "txn_demo_001"
DEMO_AMOUNT_PAISE = 19900  # ₹199

def _create_single_demo(db, cust_id: str, txn_id: str) -> tuple[Transaction, Customer]:
    # 1. Idempotently create the demo customer
    customer = db.query(Customer).filter(Customer.customer_id == cust_id).first()
    if not customer:
        customer = Customer(
            customer_id=cust_id,
            lifetime_value=50000,
            opted_out=False
        )
        db.add(customer)
        db.flush()

    # 2. Idempotently create the demo transaction
    transaction = db.query(Transaction).filter(Transaction.txn_id == txn_id).first()
    if not transaction:
        now = datetime.now(timezone.utc)
        transaction = Transaction(
            txn_id=txn_id,
            customer_id=cust_id,
            amount=DEMO_AMOUNT_PAISE,
            currency="INR",
            status="FAILED",
            failure_code="INSUFFICIENT_FUNDS",
            failure_description="[recoverable] Insufficient funds in account",
            attempt_count=1,
            revenue_at_risk=DEMO_AMOUNT_PAISE,
            recovered_amount=0,
            recovery_window_expires_at=now + timedelta(hours=48)
        )
        db.add(transaction)
        db.commit()
    else:
        # DB flush may have occurred, but we don't have new txn data to commit.
        db.commit()

    return transaction, customer

def create_demo_data(db) -> tuple[Transaction, Customer]:
    """
    Creates the demo customers and transactions if they don't exist.
    Returns the first Transaction and Customer objects (txn_demo_001) for backward compatibility.
    """
    txn1, cust1 = _create_single_demo(db, DEMO_CUST_ID, DEMO_TXN_ID)
    txn2, cust2 = _create_single_demo(db, "cust_demo_002", "txn_demo_002")
    return (txn1, cust1), (txn2, cust2)



def main():
    db = SessionLocal()
    try:
        (txn1, cust1), (txn2, cust2) = create_demo_data(db)

        # Print the requested details
        print("--- Demo Data Ready ---")
        for txn, cust in [(txn1, cust1), (txn2, cust2)]:
            print(f"Transaction ID: {txn.txn_id}")
            print(f"Amount:         INR {txn.amount / 100:.2f}")
            print(f"Customer ID:    {txn.customer_id}")
            print(f"Attempt Count:  {txn.attempt_count}")
            print(f"Opted Out:      {cust.opted_out}")
            print(f"Status:         {txn.status}")
            print("-----------------------")
    finally:
        db.close()


if __name__ == "__main__":
    main()

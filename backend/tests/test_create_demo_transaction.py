"""
Tests for the create_demo_transaction.py script.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Customer, Transaction
from scripts.create_demo_transaction import DEMO_AMOUNT_PAISE, DEMO_CUST_ID, DEMO_TXN_ID, create_demo_data
from tests.conftest import SHARED_ENGINE, SharedTestingSessionLocal


def test_create_demo_transaction_is_idempotent():
    """
    Ensures that create_demo_data successfully creates exactly one customer
    and one transaction, and does not duplicate them upon subsequent runs.
    """
    Base.metadata.create_all(bind=SHARED_ENGINE)
    db = SharedTestingSessionLocal()

    try:
        (txn1, cust1), (txn2, cust2) = create_demo_data(db)

        # Assert correct properties for 001
        assert cust1.customer_id == DEMO_CUST_ID
        assert cust1.opted_out is False

        assert txn1.txn_id == DEMO_TXN_ID
        assert txn1.customer_id == DEMO_CUST_ID
        assert txn1.status == "FAILED"
        assert txn1.attempt_count == 1
        assert txn1.failure_code == "INSUFFICIENT_FUNDS"
        assert txn1.amount == DEMO_AMOUNT_PAISE
        assert txn1.revenue_at_risk == DEMO_AMOUNT_PAISE
        assert txn1.recovered_amount == 0
        assert txn1.currency == "INR"

        # Verify exactly 1 of each exists for 001 and 002
        assert db.query(Customer).filter_by(customer_id=DEMO_CUST_ID).count() == 1
        assert db.query(Transaction).filter_by(txn_id=DEMO_TXN_ID).count() == 1
        
        assert db.query(Customer).filter_by(customer_id="cust_demo_002").count() == 1
        
        txn2 = db.query(Transaction).filter_by(txn_id="txn_demo_002").first()
        assert txn2 is not None
        assert txn2.customer_id == "cust_demo_002"
        assert txn2.status == "FAILED"
        assert txn2.attempt_count == 1
        assert txn2.revenue_at_risk == DEMO_AMOUNT_PAISE

        # Run 2: Idempotent execution
        (txn1_run2, cust1_run2), (txn2_run2, cust2_run2) = create_demo_data(db)

        # Returned objects should be identical to DB state
        assert txn1_run2.txn_id == DEMO_TXN_ID
        assert cust1_run2.customer_id == DEMO_CUST_ID

        # Counts must still be exactly 1 for both
        assert db.query(Customer).filter_by(customer_id=DEMO_CUST_ID).count() == 1
        assert db.query(Transaction).filter_by(txn_id=DEMO_TXN_ID).count() == 1
        
        assert db.query(Customer).filter_by(customer_id="cust_demo_002").count() == 1
        assert db.query(Transaction).filter_by(txn_id="txn_demo_002").count() == 1

    finally:
        db.close()
        Base.metadata.drop_all(bind=SHARED_ENGINE)

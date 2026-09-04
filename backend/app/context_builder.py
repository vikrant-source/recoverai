"""
Context Builder — Phase 6.

Loads the Transaction and Customer records required by the Recovery Pipeline.

Read-only contract: no database writes occur here.
The webhook handler calls load_context() and handles ContextLoadError before
the pipeline is ever invoked.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Customer, Transaction


class ContextLoadError(Exception):
    """
    Raised when the required context cannot be loaded from the database.

    The webhook handler catches this, marks the WebhookEvent as FAILED,
    and returns HTTP 200 IGNORED without invoking the recovery pipeline.
    """


def load_context(db: Session, txn_id: str) -> tuple[Transaction, Customer]:
    """
    Load a Transaction and its associated Customer from the database.

    Read-only: no DB state is modified.

    Raises ContextLoadError when:
      - The transaction is not found (unknown txn_id in the webhook payload).
      - The associated customer is not found (data integrity issue).
    """
    transaction = (
        db.query(Transaction)
        .filter(Transaction.txn_id == txn_id)
        .first()
    )
    if transaction is None:
        raise ContextLoadError(
            f"Transaction '{txn_id}' not found in database."
        )

    customer = (
        db.query(Customer)
        .filter(Customer.customer_id == transaction.customer_id)
        .first()
    )
    if customer is None:
        raise ContextLoadError(
            f"Customer '{transaction.customer_id}' for transaction '{txn_id}' not found."
        )

    return transaction, customer

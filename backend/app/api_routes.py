"""
Dashboard Read-Only API Routes — Phase 7.

Provides four GET endpoints for the frontend dashboard.

Architecture constraints
------------------------
- These routes are READ-ONLY. They NEVER write to the database.
- They do NOT import from ai_brain, policy, executor, pipeline,
  webhook_handler, or context_builder.
- They query the existing tables (transactions, interventions, customers)
  via SQLAlchemy ORM.
- All monetary values are returned as integer paise (never float).
- Metrics are computed from the actual database state, not hardcoded.

CORS is configured in main.py for localhost:5173 (Vite dev server).

Metric semantics
----------------
revenue_at_risk_paise:
    SUM of Transaction.revenue_at_risk across all transactions where
    revenue_at_risk > 0 AND the transaction was processed by the
    recovery pipeline (i.e., has at least one Intervention row).
    This represents the total revenue that was at risk when the
    recovery pipeline was first invoked.

revenue_recovered_paise:
    SUM of Intervention.recovered_amount across all interventions.
    This is the total amount successfully recovered (integer paise only,
    as written by the executor).

recovery_rate_bps:
    (revenue_recovered_paise * 10000) // revenue_at_risk_paise.
    Expressed in basis points to avoid floating-point. 5198 = 51.98%.
    Returns 0 when revenue_at_risk_paise is 0.

escalated_count:
    COUNT of Intervention rows where final_action = 'ESCALATE'.

total_interventions:
    COUNT of all Intervention rows.

successful_txns:
    COUNT of Transaction rows where status = 'SUCCESS'.

failed_txns:
    COUNT of Transaction rows where status = 'FAILED'.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from .models import Customer, Intervention, Transaction

router = APIRouter(prefix="/api", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _paise_rate_bps(recovered: int, at_risk: int) -> int:
    """Integer basis-point recovery rate. 10000 bps = 100%."""
    if at_risk == 0:
        return 0
    return (recovered * 10000) // at_risk


# ---------------------------------------------------------------------------
# GET /api/metrics
# ---------------------------------------------------------------------------


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    KPI summary computed live from the database.

    All monetary values are integer paise. recovery_rate_bps is an integer
    (e.g. 5198 represents 51.98%). The frontend divides by 100 to display
    a percentage.
    """
    # Revenue that was at risk at the time of intervention.
    # We read this from the transactions that were processed (have interventions).
    # Because the executor zeroes out revenue_at_risk on success, we cannot
    # recompute the "original" at-risk total from the transactions table alone.
    # Instead, we sum recovered_amount from interventions (actual recovered)
    # and compute at-risk as the pre-intervention revenue_at_risk:
    # For transactions that succeeded → recovered_amount == original revenue_at_risk.
    # For transactions that failed/skipped/escalated → revenue_at_risk still on the txn.

    # Get all transactions that were touched by an intervention.
    processed_txn_ids_q = db.query(Intervention.txn_id).distinct()

    # Revenue recovered: sum of all recovered_amount from interventions.
    recovered_row = db.query(
        func.coalesce(func.sum(Intervention.recovered_amount), 0)
    ).scalar()
    revenue_recovered_paise: int = int(recovered_row or 0)

    # Revenue at risk: sum from transactions that have interventions.
    # For SUCCESS transactions: executor set revenue_at_risk=0, recovered_amount=original.
    # For non-SUCCESS transactions: revenue_at_risk is still the original value.
    # So: total_at_risk = sum(recovered_amount from interventions where status=SUCCESS)
    #                   + sum(txn.revenue_at_risk from txns with interventions)
    # = sum(all recovered) + sum(still-at-risk txns)
    # Simpler: sum all intervention recovered_amounts + sum revenue_at_risk on
    # unrecovered processed transactions.
    still_at_risk_row = (
        db.query(func.coalesce(func.sum(Transaction.revenue_at_risk), 0))
        .filter(Transaction.txn_id.in_(processed_txn_ids_q))
        .scalar()
    )
    still_at_risk_paise: int = int(still_at_risk_row or 0)
    revenue_at_risk_paise: int = revenue_recovered_paise + still_at_risk_paise

    recovery_rate_bps: int = _paise_rate_bps(revenue_recovered_paise, revenue_at_risk_paise)

    # Intervention counts.
    total_interventions: int = int(db.query(func.count(Intervention.id)).scalar() or 0)

    escalated_count: int = int(
        db.query(func.count(Intervention.id))
        .filter(Intervention.final_action == "ESCALATE")
        .scalar()
        or 0
    )

    # Transaction outcome counts.
    successful_txns: int = int(
        db.query(func.count(Transaction.txn_id))
        .filter(Transaction.status == "SUCCESS")
        .scalar()
        or 0
    )
    failed_txns: int = int(
        db.query(func.count(Transaction.txn_id))
        .filter(Transaction.status == "FAILED")
        .scalar()
        or 0
    )

    return {
        "revenue_at_risk_paise": revenue_at_risk_paise,
        "revenue_recovered_paise": revenue_recovered_paise,
        "recovery_rate_bps": recovery_rate_bps,
        "total_interventions": total_interventions,
        "escalated_count": escalated_count,
        "successful_txns": successful_txns,
        "failed_txns": failed_txns,
    }


# ---------------------------------------------------------------------------
# GET /api/action-distribution
# ---------------------------------------------------------------------------


@router.get("/action-distribution")
def get_action_distribution(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """
    Count of interventions grouped by final_action.

    Returns all four possible actions, including those with count=0,
    so the frontend chart always has a consistent shape.
    """
    all_actions = ["SILENT_RETRY", "SEND_PAYMENT_LINK", "ESCALATE", "DO_NOTHING"]

    rows = (
        db.query(Intervention.final_action, func.count(Intervention.id))
        .group_by(Intervention.final_action)
        .all()
    )
    counts = {action: count for action, count in rows}

    return [
        {"action": action, "count": counts.get(action, 0)}
        for action in all_actions
    ]


# ---------------------------------------------------------------------------
# GET /api/interventions
# ---------------------------------------------------------------------------


@router.get("/interventions")
def list_interventions(
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    final_action: str | None = Query(default=None),
    execution_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> dict[str, Any]:
    """
    Paginated list of recovery events (Intervention joined with Transaction).

    Filters:
      final_action     — exact match on Intervention.final_action
      execution_status — exact match on Intervention.execution_status
      search           — prefix match on Intervention.txn_id (case-insensitive)

    Returns:
      total  — total matching rows (for pagination controls)
      page   — current page
      page_size — rows per page
      items  — array of intervention records
    """
    query = db.query(Intervention, Transaction).join(
        Transaction, Intervention.txn_id == Transaction.txn_id
    )

    if final_action:
        query = query.filter(Intervention.final_action == final_action.upper())

    if execution_status:
        query = query.filter(Intervention.execution_status == execution_status.upper())

    if search:
        query = query.filter(
            Intervention.txn_id.ilike(f"%{search}%")
        )

    total: int = query.count()

    offset = (page - 1) * page_size
    rows = (
        query.order_by(Intervention.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = []
    for intervention, txn in rows:
        items.append(
            {
                "intervention_id": intervention.id,
                "txn_id": intervention.txn_id,
                "amount_paise": int(txn.amount),
                "currency": str(txn.currency),
                "failure_code": txn.failure_code,
                "failure_description": txn.failure_description,
                "ai_recommendation": intervention.ai_recommendation,
                "ai_confidence": float(intervention.ai_confidence),
                "ai_failure_classification": intervention.ai_failure_classification,
                "ai_reasoning": intervention.ai_reasoning,
                "policy_decision": intervention.policy_decision,
                "policy_reason": intervention.policy_reason,
                "final_action": intervention.final_action,
                "execution_status": intervention.execution_status,
                "recovered_amount_paise": int(intervention.recovered_amount),
                "created_at": intervention.created_at.isoformat()
                if intervention.created_at
                else None,
            }
        )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


# ---------------------------------------------------------------------------
# GET /api/interventions/{txn_id}
# ---------------------------------------------------------------------------


@router.get("/interventions/{txn_id}")
def get_intervention_detail(
    txn_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Full decision trace for a single transaction.

    Joins Transaction + Customer + Intervention to return everything
    the frontend needs to render the AI → Policy → Executor trace modal.

    Returns HTTP 404 if the transaction is not found or has no intervention.
    """
    txn = db.query(Transaction).filter(Transaction.txn_id == txn_id).first()
    if txn is None:
        raise HTTPException(status_code=404, detail=f"Transaction '{txn_id}' not found.")

    intervention = (
        db.query(Intervention)
        .filter(Intervention.txn_id == txn_id)
        .order_by(Intervention.created_at.desc())
        .first()
    )
    if intervention is None:
        raise HTTPException(
            status_code=404,
            detail=f"No intervention record found for transaction '{txn_id}'.",
        )

    customer = (
        db.query(Customer)
        .filter(Customer.customer_id == txn.customer_id)
        .first()
    )

    return {
        # Transaction context
        "txn_id": str(txn.txn_id),
        "amount_paise": int(txn.amount),
        "currency": str(txn.currency),
        "status": str(txn.status),
        "failure_code": txn.failure_code,
        "failure_description": txn.failure_description,
        "attempt_count": int(txn.attempt_count),
        "revenue_at_risk_paise": int(txn.revenue_at_risk),
        "recovered_amount_paise": int(txn.recovered_amount),
        # Customer context (for dashboard colour/tier hints, no PII)
        "customer_id": str(txn.customer_id),
        "ltv_tier": str(customer.ltv_tier) if customer else "UNKNOWN",
        "fraud_score": float(customer.fraud_score) if customer else 0.0,
        # Full intervention trace
        "intervention": {
            "id": int(intervention.id),
            # AI Brain layer
            "ai_recommendation": intervention.ai_recommendation,
            "ai_confidence": float(intervention.ai_confidence),
            "ai_failure_classification": intervention.ai_failure_classification,
            "ai_reasoning": intervention.ai_reasoning,
            # Policy Brakes layer
            "policy_decision": intervention.policy_decision,
            "policy_reason": intervention.policy_reason,
            # Executor layer
            "final_action": intervention.final_action,
            "execution_status": intervention.execution_status,
            "recovered_amount_paise": int(intervention.recovered_amount),
            "created_at": intervention.created_at.isoformat()
            if intervention.created_at
            else None,
        },
    }

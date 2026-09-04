"""
Batch Recovery Runner — Phase 5.

Processes all eligible failed transactions through the full recovery pipeline
and prints a summary metrics table.

Eligibility criteria (all must be true):
  1. status == "FAILED"
  2. revenue_at_risk > 0
  3. recovery_window not expired
  4. customer not opted-out
  5. No existing Intervention record for this txn_id (prevents double processing)

Run from repo root:
    python backend/scripts/run_recovery.py

Safety guarantees:
  - No real payment API calls are made.
  - Recovery outcomes are simulated using the synthetic ground-truth
    [recoverable] prefix in failure_description (test harness only).
  - In production, real payment gateway callbacks replace that prefix logic;
    this script's interface and metrics output remain unchanged.
  - Transactions already in the interventions table are skipped entirely.

Do NOT run this against the production database.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models import Customer, Intervention, Transaction
from app.pipeline import run_recovery_pipeline
from app.schemas import ExecutionStatus, RecoveryAction


def _paise_to_inr(paise: int) -> str:
    """Format integer paise as an INR display string. Display only — not a financial value."""
    rupees = paise // 100
    paise_part = paise % 100
    return f"Rs.{rupees:,}.{paise_part:02d}"


def _recovery_rate_display(recovered: int, at_risk: int) -> str:
    """Compute recovery rate using integer arithmetic. Display only."""
    if at_risk == 0:
        return "N/A"
    # basis points (1 bp = 0.01%)
    bps = (recovered * 10000) // at_risk
    return f"{bps // 100}.{bps % 100:02d}%"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_window_open(txn: Transaction, now: datetime) -> bool:
    """Return True if the recovery window has not yet expired."""
    if txn.recovery_window_expires_at is None:
        return True
    expires = txn.recovery_window_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return now < expires.astimezone(timezone.utc)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    db = SessionLocal()
    try:
        now = _utc_now()

        # --- Build exclusion sets ---

        # Transactions already processed (have at least one Intervention row)
        processed_txn_ids: set[str] = {
            row.txn_id for row in db.query(Intervention.txn_id).all()
        }

        # Opted-out customer IDs
        opted_out_ids: set[str] = {
            row.customer_id
            for row in db.query(Customer.customer_id)
            .filter(Customer.opted_out == True)  # noqa: E712
            .all()
        }

        # --- Candidate transactions (FAILED + revenue_at_risk > 0) ---
        candidates = (
            db.query(Transaction)
            .filter(
                Transaction.status == "FAILED",
                Transaction.revenue_at_risk > 0,
            )
            .all()
        )

        # --- Filter to eligible ---
        eligible = [
            t for t in candidates
            if t.txn_id not in processed_txn_ids
            and t.customer_id not in opted_out_ids
            and _is_window_open(t, now)
        ]

        skipped_already_processed = sum(
            1 for t in candidates if t.txn_id in processed_txn_ids
        )
        skipped_opted_out = sum(
            1 for t in candidates
            if t.txn_id not in processed_txn_ids
            and t.customer_id in opted_out_ids
        )
        skipped_window_expired = sum(
            1 for t in candidates
            if t.txn_id not in processed_txn_ids
            and t.customer_id not in opted_out_ids
            and not _is_window_open(t, now)
        )

        # --- Pre-load customers for eligible transactions (avoid N+1 queries) ---
        needed_ids = {t.customer_id for t in eligible}
        customer_map: dict[str, Customer] = {
            c.customer_id: c
            for c in db.query(Customer)
            .filter(Customer.customer_id.in_(needed_ids))
            .all()
        }

        total_at_risk: int = sum(t.revenue_at_risk for t in eligible)

        # --- Metrics accumulators (all integer paise) ---
        status_counts: dict[ExecutionStatus, int] = defaultdict(int)
        action_counts: dict[RecoveryAction, int] = defaultdict(int)
        total_recovered: int = 0
        missing_customer_count: int = 0

        print()
        print("RecoverAI -- Batch Recovery Run")
        print("=" * 44)
        print(f"Candidates (FAILED + at-risk):  {len(candidates)}")
        print(f"  Already processed (skipped):  {skipped_already_processed}")
        print(f"  Opted-out (skipped):          {skipped_opted_out}")
        print(f"  Window expired (skipped):     {skipped_window_expired}")
        print(f"Eligible for processing:        {len(eligible)}")
        print()

        # --- Process eligible transactions ---
        for txn in eligible:
            customer = customer_map.get(txn.customer_id)
            if customer is None:
                missing_customer_count += 1
                continue

            result = run_recovery_pipeline(db, txn, customer)

            status_counts[result.execution_status] += 1
            action_counts[result.final_action] += 1
            total_recovered += int(result.recovered_amount)

        # --- Print results ---
        print("Execution results:")
        print(f"  Recovered (SUCCESS):          {status_counts[ExecutionStatus.SUCCESS]}")
        print(f"  Not recovered (FAILED):       {status_counts[ExecutionStatus.FAILED]}")
        print(f"  Escalated:                    {status_counts[ExecutionStatus.ESCALATED]}")
        print(f"  Skipped (DO_NOTHING):         {status_counts[ExecutionStatus.SKIPPED]}")
        if missing_customer_count:
            print(f"  Skipped (missing customer):   {missing_customer_count}")
        print()
        print("Final actions taken:")
        for action in RecoveryAction:
            print(f"  {action.value:25s}  {action_counts[action]}")
        print()
        print("Revenue metrics (integer paise):")
        print(f"  At risk (this batch):         {_paise_to_inr(total_at_risk)}")
        print(f"  Recovered:                    {_paise_to_inr(total_recovered)}")
        print(f"  Recovery rate:                {_recovery_rate_display(total_recovered, total_at_risk)}")
        print()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""
RecoverAI Phase 2 — synthetic payment data generator.

Creates a deterministic INR dataset for the revenue-recovery demo:
~250 customers and exactly 1,000 transactions, with ground-truth
labels encoded in existing Transaction columns (no schema change).

Run from anywhere:
    python backend/scripts/generate_data.py
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base, DB_PATH, SessionLocal, engine  # noqa: E402
from app.models import Customer, Intervention, Transaction  # noqa: E402

SEED = 42
CUSTOMER_COUNT = 250
TRANSACTION_COUNT = 1000

# Outcome mix for exactly 1,000 transactions.
N_SELF_HEALED = 110
N_RECOVERABLE = 160
N_UNRECOVERED = 90
N_IMMEDIATE_SUCCESS = TRANSACTION_COUNT - N_SELF_HEALED - N_RECOVERABLE - N_UNRECOVERED

# Typical Indian checkout / subscription ticket sizes, in paise.
AMOUNT_PAISE = [
    9900,  # ₹99
    14900,
    19900,
    29900,
    49900,
    79900,
    99900,  # ₹999
    129900,
    149900,
    199900,
    249900,
    399900,
    499900,  # ₹4,999
    799900,
    999900,  # ₹9,999
    1499900,
    1999900,
    2499900,
]

AMOUNT_WEIGHTS = [
    14,
    10,
    12,
    9,
    10,
    7,
    12,
    6,
    6,
    5,
    3,
    2,
    2,
    1,
    1,
    1,
    1,
    1,
]

FAILURE_DETAILS = {
    "USER_ERROR": [
        "Payment cancelled by customer",
        "Incorrect CVV entered",
        "Incorrect UPI PIN",
        "3DS authentication failed",
        "Customer closed the checkout",
    ],
    "INSUFFICIENT_FUNDS": [
        "Insufficient funds in account",
        "Bank declined: low balance",
        "UPI daily limit exceeded",
        "Card spend limit reached",
    ],
    "EXPIRED_CREDENTIALS": [
        "Card expired",
        "Saved VPA is no longer valid",
        "Tokenized card expired",
        "Mandate credentials expired",
    ],
    "TECHNICAL_GLITCH": [
        "Acquirer timeout",
        "Bank gateway unavailable",
        "UPI switch error",
        "Temporary issuer network failure",
    ],
    "UNKNOWN": [
        "Issuer declined with no reason code",
        "Unknown processor error",
        "Payment status could not be confirmed",
    ],
}

# Self-heals are dominated by glitches; recoverable failures by funds/credentials.
SELF_HEAL_FAILURE_WEIGHTS = {
    "TECHNICAL_GLITCH": 0.50,
    "INSUFFICIENT_FUNDS": 0.20,
    "EXPIRED_CREDENTIALS": 0.10,
    "UNKNOWN": 0.12,
    "USER_ERROR": 0.08,
}
RECOVERABLE_FAILURE_WEIGHTS = {
    "INSUFFICIENT_FUNDS": 0.40,
    "EXPIRED_CREDENTIALS": 0.25,
    "TECHNICAL_GLITCH": 0.20,
    "UNKNOWN": 0.10,
    "USER_ERROR": 0.05,
}
UNRECOVERED_FAILURE_WEIGHTS = {
    "USER_ERROR": 0.45,
    "UNKNOWN": 0.20,
    "INSUFFICIENT_FUNDS": 0.15,
    "EXPIRED_CREDENTIALS": 0.12,
    "TECHNICAL_GLITCH": 0.08,
}

GROUND_TRUTH_SELF_HEALED = "self_healed"
GROUND_TRUTH_RECOVERABLE = "recoverable"
GROUND_TRUTH_UNRECOVERED = "unrecovered"


def paise_to_inr(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def pick_weighted(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights)
    values = [weights[k] for k in keys]
    return rng.choices(keys, weights=values, k=1)[0]


def describe_failure(rng: random.Random, category: str, ground_truth: str) -> str:
    detail = rng.choice(FAILURE_DETAILS[category])
    return f"[{ground_truth}] {detail}"


def ltv_tier_for(lifetime_value: int) -> str:
    if lifetime_value >= 1_000_000:  # ₹10,000
        return "HIGH"
    if lifetime_value >= 200_000:  # ₹2,000
        return "STANDARD"
    return "LOW"


def reset_synthetic_tables(db) -> None:
    """Safe re-runs: drop dependent rows, then regenerate from scratch."""
    db.query(Intervention).delete()
    db.query(Transaction).delete()
    db.query(Customer).delete()
    db.commit()


def build_customers(rng: random.Random, now: datetime) -> list[Customer]:
    customers: list[Customer] = []
    opted_out_count = 20  # 8% — RecoverAI must skip these later.

    for i in range(1, CUSTOMER_COUNT + 1):
        created = now - timedelta(days=rng.randint(60, 400))
        # Most customers are low-risk; a thin tail is high-risk.
        fraud_score = round(min(0.99, rng.betavariate(1.4, 8.0)), 3)
        customers.append(
            Customer(
                customer_id=f"cust_{i:04d}",
                lifetime_value=0,
                ltv_tier="STANDARD",
                fraud_score=fraud_score,
                opted_out=(i <= opted_out_count),
                created_at=created,
            )
        )
    rng.shuffle(customers)
    return customers


def assign_customers(
    rng: random.Random,
    customer_ids: list[str],
) -> list[str]:
    """Every customer gets ≥1 txn; extras follow a skewed spend pattern."""
    assigned = list(customer_ids)
    remaining = TRANSACTION_COUNT - len(assigned)
    weights = [rng.gammavariate(1.6, 1.2) for _ in customer_ids]
    assigned.extend(rng.choices(customer_ids, weights=weights, k=remaining))
    rng.shuffle(assigned)
    return assigned


def build_outcome_plan(rng: random.Random) -> list[str]:
    plan = (
        ["immediate_success"] * N_IMMEDIATE_SUCCESS
        + ["self_healed"] * N_SELF_HEALED
        + ["recoverable"] * N_RECOVERABLE
        + ["unrecovered"] * N_UNRECOVERED
    )
    rng.shuffle(plan)
    return plan


def make_transaction(
    rng: random.Random,
    txn_id: str,
    customer_id: str,
    outcome: str,
    now: datetime,
) -> Transaction:
    amount = rng.choices(AMOUNT_PAISE, weights=AMOUNT_WEIGHTS, k=1)[0]

    if outcome == "immediate_success":
        created = now - timedelta(
            days=rng.randint(0, 45),
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )
        return Transaction(
            txn_id=txn_id,
            customer_id=customer_id,
            amount=amount,
            currency="INR",
            status="SUCCESS",
            failure_code=None,
            failure_description=None,
            attempt_count=1,
            revenue_at_risk=0,
            recovered_amount=0,
            recovery_window_expires_at=None,
            created_at=created,
            updated_at=created,
        )

    if outcome == "self_healed":
        created = now - timedelta(
            days=rng.randint(2, 30),
            hours=rng.randint(0, 23),
        )
        healed_after = created + timedelta(
            hours=rng.randint(1, 36),
            minutes=rng.randint(0, 59),
        )
        category = pick_weighted(rng, SELF_HEAL_FAILURE_WEIGHTS)
        return Transaction(
            txn_id=txn_id,
            customer_id=customer_id,
            amount=amount,
            currency="INR",
            status="SUCCESS",
            failure_code=category,
            failure_description=describe_failure(
                rng, category, GROUND_TRUTH_SELF_HEALED
            ),
            attempt_count=rng.randint(2, 4),
            revenue_at_risk=0,
            recovered_amount=amount,
            recovery_window_expires_at=created + timedelta(hours=48),
            created_at=created,
            updated_at=healed_after,
        )

    if outcome == "recoverable":
        # Still inside a 48h recovery window — unresolved, not yet lost.
        created = now - timedelta(
            hours=rng.randint(1, 36),
            minutes=rng.randint(0, 59),
        )
        category = pick_weighted(rng, RECOVERABLE_FAILURE_WEIGHTS)
        return Transaction(
            txn_id=txn_id,
            customer_id=customer_id,
            amount=amount,
            currency="INR",
            status="FAILED",
            failure_code=category,
            failure_description=describe_failure(
                rng, category, GROUND_TRUTH_RECOVERABLE
            ),
            attempt_count=rng.randint(1, 2),
            revenue_at_risk=amount,
            recovered_amount=0,
            recovery_window_expires_at=created + timedelta(hours=48),
            created_at=created,
            updated_at=created,
        )

    created = now - timedelta(
        days=rng.randint(5, 40),
        hours=rng.randint(0, 23),
    )
    category = pick_weighted(rng, UNRECOVERED_FAILURE_WEIGHTS)
    return Transaction(
        txn_id=txn_id,
        customer_id=customer_id,
        amount=amount,
        currency="INR",
        status="FAILED",
        failure_code=category,
        failure_description=describe_failure(
            rng, category, GROUND_TRUTH_UNRECOVERED
        ),
        attempt_count=rng.randint(1, 5),
        revenue_at_risk=0,
        recovered_amount=0,
        recovery_window_expires_at=created + timedelta(hours=48),
        created_at=created,
        updated_at=created + timedelta(hours=rng.randint(1, 48)),
    )


def apply_lifetime_values(customers: list[Customer], transactions: list[Transaction]) -> None:
    totals: dict[str, int] = {c.customer_id: 0 for c in customers}
    for txn in transactions:
        if txn.status == "SUCCESS":
            # Immediate success uses amount; self-healed uses recovered_amount.
            totals[txn.customer_id] += txn.recovered_amount or txn.amount

    for customer in customers:
        customer.lifetime_value = totals[customer.customer_id]
        customer.ltv_tier = ltv_tier_for(customer.lifetime_value)


def print_summary(customers: list[Customer], transactions: list[Transaction]) -> None:
    successful = [t for t in transactions if t.status == "SUCCESS"]
    failed = [t for t in transactions if t.status == "FAILED"]
    self_healed = [t for t in successful if t.failure_code is not None]
    recoverable = [t for t in failed if t.revenue_at_risk > 0]
    unrecovered = [t for t in failed if t.revenue_at_risk == 0]
    opted_out = [c for c in customers if c.opted_out]
    opted_out_ids = {c.customer_id for c in opted_out}
    opted_out_failures = [t for t in failed if t.customer_id in opted_out_ids]

    total_value = sum(t.amount for t in transactions)
    initial_at_risk = sum(t.revenue_at_risk for t in transactions)
    recovered = sum(t.recovered_amount for t in transactions)

    print()
    print("RecoverAI synthetic dataset")
    print("---------------------------")
    print(f"Customers created:          {len(customers)}")
    print(f"  Opted out:                {len(opted_out)}")
    print(f"Transactions created:       {len(transactions)}")
    print(f"Successful payments:        {len(successful)}")
    print(f"Failed payments:            {len(failed)}")
    print(f"Self-healed payments:       {len(self_healed)}")
    print(f"Recoverable failures:       {len(recoverable)}")
    print(f"Unrecovered failures:       {len(unrecovered)}")
    print(f"Failed txns on opted-out:   {len(opted_out_failures)}")
    print(f"Total transaction value:    {paise_to_inr(total_value)}")
    print(f"Initial revenue at risk:    {paise_to_inr(initial_at_risk)}")
    print(f"Already recovered (organic): {paise_to_inr(recovered)}")
    print()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rng = random.Random(SEED)
    now = utc_now()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        reset_synthetic_tables(db)

        customers = build_customers(rng, now)
        customer_ids = [c.customer_id for c in customers]
        owners = assign_customers(rng, customer_ids)
        outcomes = build_outcome_plan(rng)

        transactions = [
            make_transaction(
                rng,
                txn_id=f"txn_{i:04d}",
                customer_id=owners[i - 1],
                outcome=outcomes[i - 1],
                now=now,
            )
            for i in range(1, TRANSACTION_COUNT + 1)
        ]

        apply_lifetime_values(customers, transactions)

        db.add_all(customers)
        db.add_all(transactions)
        db.commit()

        print_summary(customers, transactions)
        print(f"Database: {DB_PATH}")
        print(f"Seed: {SEED}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

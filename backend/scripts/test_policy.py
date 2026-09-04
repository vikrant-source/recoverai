"""Print Policy Brakes decisions for a few representative scenarios."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.policy import evaluate_policy
from app.schemas import AIDecision, RecoveryAction


def _customer(opted_out: bool = False) -> SimpleNamespace:
    return SimpleNamespace(customer_id="cust_demo", opted_out=opted_out)


def _txn(**overrides) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    values = {
        "txn_id": "txn_demo",
        "status": "FAILED",
        "attempt_count": 1,
        "revenue_at_risk": 49900,
        "recovery_window_expires_at": now + timedelta(hours=24),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _show(title: str, transaction, customer, ai: AIDecision) -> None:
    result = evaluate_policy(transaction, customer, ai)
    print(title)
    print(f"  AI recommendation: {ai.recommended_action.value}")
    print(f"  Policy decision:   {result.decision.value}")
    print(f"  Final action:      {result.final_action.value}")
    print(f"  Policy reason:     {result.reason}")
    print()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    now = datetime.now(timezone.utc)
    high = AIDecision(
        recommended_action=RecoveryAction.SEND_PAYMENT_LINK,
        confidence_score=0.91,
    )

    _show(
        "1. Already successful",
        _txn(status="SUCCESS", revenue_at_risk=0),
        _customer(),
        high,
    )
    _show(
        "2. Opted-out customer",
        _txn(),
        _customer(opted_out=True),
        high,
    )
    _show(
        "3. Expired recovery window",
        _txn(recovery_window_expires_at=now - timedelta(hours=3)),
        _customer(),
        high,
    )
    _show(
        "4. Retry limit reached",
        _txn(attempt_count=2),
        _customer(),
        high,
    )
    _show(
        "5. No revenue at risk",
        _txn(revenue_at_risk=0),
        _customer(),
        high,
    )
    _show(
        "6. Low-confidence AI",
        _txn(),
        _customer(),
        AIDecision(
            recommended_action=RecoveryAction.SILENT_RETRY,
            confidence_score=0.41,
        ),
    )
    _show(
        "7. AI recommends DO_NOTHING",
        _txn(),
        _customer(),
        AIDecision(
            recommended_action=RecoveryAction.DO_NOTHING,
            confidence_score=0.95,
        ),
    )
    _show(
        "8. Allow SEND_PAYMENT_LINK",
        _txn(),
        _customer(),
        high,
    )
    _show(
        "9. Allow SILENT_RETRY",
        _txn(),
        _customer(),
        AIDecision(
            recommended_action=RecoveryAction.SILENT_RETRY,
            confidence_score=0.84,
        ),
    )


if __name__ == "__main__":
    main()

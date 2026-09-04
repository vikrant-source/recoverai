from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    lifetime_value: Mapped[int] = mapped_column(Integer, default=0)
    ltv_tier: Mapped[str] = mapped_column(String(20), default="STANDARD")
    fraud_score: Mapped[float] = mapped_column(default=0.0)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )


class Transaction(Base):
    __tablename__ = "transactions"

    txn_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.customer_id"),
        nullable=False,
    )

    # All money values are stored in paise.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")

    status: Mapped[str] = mapped_column(String(30), nullable=False)

    failure_code: Mapped[str | None] = mapped_column(String(50))
    failure_description: Mapped[str | None] = mapped_column(String(255))

    attempt_count: Mapped[int] = mapped_column(Integer, default=1)

    revenue_at_risk: Mapped[int] = mapped_column(Integer, default=0)
    recovered_amount: Mapped[int] = mapped_column(Integer, default=0)

    recovery_window_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    # Primary key gives us database-level idempotency.
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED")

    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    error_message: Mapped[str | None] = mapped_column(String(500))


class Intervention(Base):
    __tablename__ = "interventions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    txn_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.txn_id"),
        nullable=False,
    )

    ai_recommendation: Mapped[str] = mapped_column(String(50))
    ai_failure_classification: Mapped[str] = mapped_column(String(50))
    ai_confidence: Mapped[float] = mapped_column(default=0.0)
    ai_reasoning: Mapped[str] = mapped_column(String(500))

    policy_decision: Mapped[str] = mapped_column(String(30))
    policy_reason: Mapped[str] = mapped_column(String(500))

    final_action: Mapped[str] = mapped_column(String(50))
    execution_status: Mapped[str] = mapped_column(String(30))

    recovered_amount: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
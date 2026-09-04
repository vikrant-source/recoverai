"""
Recovery Pipeline — Phase 5.

Thin orchestrator that connects the three recovery layers for one transaction:

    AI Brain   (ai_brain.py)  — read-only, recommendation, never raises
    Policy     (policy.py)    — read-only, deterministic, final authority
    Executor   (executor.py)  — sole DB writer, executes policy decision only

Each layer is completely decoupled:
  - AI Brain has no knowledge of policy logic or the database.
  - Policy Brakes have no knowledge of AI internals or DB state.
  - Executor has no knowledge of how the AI or policy reached their conclusions.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .ai_brain import get_ai_decision
from .executor import execute_recovery
from .models import Customer, Transaction
from .policy import evaluate_policy
from .schemas import ExecutionResult


def run_recovery_pipeline(
    db: Session,
    transaction: Transaction,
    customer: Customer,
) -> ExecutionResult:
    """
    Run the full recovery pipeline for a single transaction.

    Steps (in strict order):
      1. AI Brain  → AIDecision   (read-only; never raises; falls back to ESCALATE)
      2. Policy    → PolicyResult (read-only; deterministic)
      3. Executor  → ExecutionResult (writes DB; executes ONLY policy_result.final_action)

    The executor receives policy_result — it NEVER receives the raw ai_decision
    recommended_action to execute. Policy Brakes have absolute final authority.
    """
    # Step 1 — AI recommendation (read-only; never raises)
    ai_decision = get_ai_decision(transaction, customer)

    # Step 2 — Policy evaluation (read-only; deterministic)
    policy_result = evaluate_policy(transaction, customer, ai_decision)

    # Step 3 — Execute the policy-approved action (sole DB writer)
    return execute_recovery(db, transaction, customer, policy_result, ai_decision)

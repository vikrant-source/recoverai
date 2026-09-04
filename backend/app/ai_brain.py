"""
AI Brain — Phase 4.

Read-only contract
------------------
This module NEVER:
  - writes to the database
  - modifies transaction status or financial amounts
  - executes recovery actions
  - exposes chain-of-thought reasoning

It produces an AIDecision *recommendation* that is subsequently evaluated
by the deterministic Policy Brakes (policy.py) before any action is taken.

Fallback guarantee
------------------
get_ai_decision() never raises. Any failure (network, parse error, bad schema,
missing API key) causes a safe ESCALATE fallback with confidence_score=0.0.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

from .schemas import AIDecision, RecoveryAction

logger = logging.getLogger(__name__)

# Load .env from repo root (two levels above this file: app/ → backend/ → root)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "openai/gpt-oss-20b"
_TEMPERATURE = 0
_MAX_REASONING_CHARS = 200

# Fallback returned when the AI response cannot be safely parsed.
# failure_classification="UNKNOWN" is a valid domain label for unclassifiable
# failures; "AI_FALLBACK" is not a recognised domain classification.
_FALLBACK_DECISION = AIDecision(
    recommended_action=RecoveryAction.ESCALATE,
    confidence_score=0.0,
    failure_classification="UNKNOWN",
    reasoning="AI response could not be processed safely.",
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a payment recovery advisor for an automated revenue-recovery system.
Analyse a failed payment and recommend exactly ONE recovery action.

Rules:
- Output ONLY valid JSON matching the required schema. No extra text.
- Do NOT invent, estimate, or modify financial amounts.
- Do NOT claim that a payment was or will be recovered.
- Do NOT include chain-of-thought. The "reasoning" field must be a concise
  business explanation of at most 200 characters.
- recommended_action must be one of:
    DO_NOTHING | SILENT_RETRY | SEND_PAYMENT_LINK | ESCALATE
- confidence_score must be a number between 0.0 and 1.0.
- failure_classification should be a short domain label such as:
    INSUFFICIENT_FUNDS | CARD_DECLINED | NETWORK_ERROR | EXPIRED_CARD | UNKNOWN
"""

# ---------------------------------------------------------------------------
# Strict JSON schema response_format
# ---------------------------------------------------------------------------

_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "AIDecision",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "recommended_action": {
                    "type": "string",
                    "enum": [
                        "DO_NOTHING",
                        "SILENT_RETRY",
                        "SEND_PAYMENT_LINK",
                        "ESCALATE",
                    ],
                },
                "confidence_score": {"type": "number"},
                "failure_classification": {"type": "string"},
                "reasoning": {"type": "string"},
            },
            "required": [
                "recommended_action",
                "confidence_score",
                "failure_classification",
                "reasoning",
            ],
            "additionalProperties": False,
        },
    },
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def build_context(transaction: Any, customer: Any) -> dict:
    """Assemble a read-only context dict from ORM or SimpleNamespace objects.

    - Money values are left as integer paise exactly as stored; they are never
      converted to float or modified in any way.
    - No database writes occur here.
    - No secrets are included in the returned dict.
    """
    return {
        "txn_id": str(getattr(transaction, "txn_id", "")),
        # Integer paise — never floating-point
        "amount_paise": int(getattr(transaction, "amount", 0) or 0),
        "currency": str(getattr(transaction, "currency", "INR")),
        "status": str(getattr(transaction, "status", "")),
        "failure_code": str(getattr(transaction, "failure_code", "") or ""),
        "failure_description": str(
            getattr(transaction, "failure_description", "") or ""
        ),
        "attempt_count": int(getattr(transaction, "attempt_count", 1) or 1),
        # Integer paise — never floating-point
        "revenue_at_risk_paise": int(
            getattr(transaction, "revenue_at_risk", 0) or 0
        ),
        "customer_id": str(getattr(customer, "customer_id", "")),
        "ltv_tier": str(getattr(customer, "ltv_tier", "STANDARD")),
        # Integer paise — never floating-point
        "lifetime_value_paise": int(
            getattr(customer, "lifetime_value", 0) or 0
        ),
        "fraud_score": float(getattr(customer, "fraud_score", 0.0) or 0.0),
    }


def _parse_ai_response(raw_json: str) -> AIDecision:
    """Parse, validate, and sanitise the raw JSON string from Groq.

    Raises on any parse or validation error so the caller can apply the
    fallback. Never modifies financial data.
    """
    data = json.loads(raw_json)
    decision = AIDecision.model_validate(data)

    # Enforce reasoning length limit — no chain-of-thought leaks.
    if decision.reasoning and len(decision.reasoning) > _MAX_REASONING_CHARS:
        decision = decision.model_copy(
            update={"reasoning": decision.reasoning[:_MAX_REASONING_CHARS]}
        )

    return decision


def call_groq(context: dict) -> AIDecision:
    """Send context to Groq and return a parsed AIDecision.

    Raises on any network, authentication, or parse failure so that
    get_ai_decision() can apply the safe fallback.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured.")

    client = Groq(api_key=api_key)

    user_message = (
        "Analyse this failed payment context and recommend a recovery action.\n\n"
        f"Payment context (monetary amounts are in paise):\n"
        f"{json.dumps(context, indent=2)}"
    )

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=_TEMPERATURE,
        response_format=_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )

    raw = response.choices[0].message.content
    if not raw:
        raise ValueError("Groq returned an empty response body.")

    return _parse_ai_response(raw)


def get_ai_decision(transaction: Any, customer: Any) -> AIDecision:
    """Public entry point. Returns an AIDecision. Never raises.

    Completely read-only:
      - Does not write to the database.
      - Does not modify transaction status or financial amounts.
      - Does not execute any recovery action.

    Falls back to ESCALATE (confidence 0.0, failure_classification=UNKNOWN)
    if the AI call fails or the response cannot be safely processed.
    """
    context = build_context(transaction, customer)
    try:
        return call_groq(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI Brain fallback triggered: %s", exc)
        return _FALLBACK_DECISION

"""
Unit tests for the AI Brain (Phase 4).

All tests use mocked Groq responses — no real API calls are made.
No database state is read or modified by these tests.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai_brain import (
    _FALLBACK_DECISION,
    _MAX_REASONING_CHARS,
    _parse_ai_response,
    build_context,
    get_ai_decision,
)
from app.schemas import AIDecision, RecoveryAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _transaction(**overrides) -> SimpleNamespace:
    values = {
        "txn_id": "txn_test_001",
        "amount": 49900,
        "currency": "INR",
        "status": "FAILED",
        "failure_code": "INSUFFICIENT_FUNDS",
        "failure_description": "Card has insufficient funds",
        "attempt_count": 1,
        "revenue_at_risk": 49900,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _customer(**overrides) -> SimpleNamespace:
    values = {
        "customer_id": "cust_test_001",
        "ltv_tier": "PREMIUM",
        "lifetime_value": 500000,
        "fraud_score": 0.05,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _make_groq_response(content: str) -> MagicMock:
    """Build a minimal mock that mimics groq.ChatCompletion structure."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _valid_payload(**overrides) -> dict:
    base = {
        "recommended_action": "SEND_PAYMENT_LINK",
        "confidence_score": 0.87,
        "failure_classification": "INSUFFICIENT_FUNDS",
        "reasoning": "Customer likely has funds later; a payment link often recovers these.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests: build_context
# ---------------------------------------------------------------------------


class BuildContextTests(unittest.TestCase):
    def test_all_required_keys_present(self):
        ctx = build_context(_transaction(), _customer())
        for key in (
            "txn_id",
            "amount_paise",
            "currency",
            "status",
            "failure_code",
            "failure_description",
            "attempt_count",
            "revenue_at_risk_paise",
            "customer_id",
            "ltv_tier",
            "lifetime_value_paise",
            "fraud_score",
        ):
            self.assertIn(key, ctx, f"Missing key: {key}")

    def test_money_fields_are_integers(self):
        ctx = build_context(_transaction(), _customer())
        self.assertIsInstance(ctx["amount_paise"], int)
        self.assertIsInstance(ctx["revenue_at_risk_paise"], int)
        self.assertIsInstance(ctx["lifetime_value_paise"], int)

    def test_money_values_are_correct_paise(self):
        ctx = build_context(_transaction(amount=99900, revenue_at_risk=99900), _customer())
        self.assertEqual(ctx["amount_paise"], 99900)
        self.assertEqual(ctx["revenue_at_risk_paise"], 99900)

    def test_none_fields_default_to_safe_values(self):
        ctx = build_context(
            _transaction(failure_code=None, failure_description=None),
            _customer(),
        )
        self.assertEqual(ctx["failure_code"], "")
        self.assertEqual(ctx["failure_description"], "")

    def test_no_secrets_in_context(self):
        ctx = build_context(_transaction(), _customer())
        # Confirm API key, passwords, or raw DB objects are not present
        for key in ctx:
            self.assertNotIn("key", key.lower())
            self.assertNotIn("secret", key.lower())
            self.assertNotIn("password", key.lower())


# ---------------------------------------------------------------------------
# Tests: _parse_ai_response
# ---------------------------------------------------------------------------


class ParseAiResponseTests(unittest.TestCase):
    def test_valid_response_parsed_correctly(self):
        raw = json.dumps(_valid_payload())
        decision = _parse_ai_response(raw)
        self.assertIsInstance(decision, AIDecision)
        self.assertEqual(decision.recommended_action, RecoveryAction.SEND_PAYMENT_LINK)
        self.assertAlmostEqual(decision.confidence_score, 0.87)
        self.assertEqual(decision.failure_classification, "INSUFFICIENT_FUNDS")

    def test_reasoning_truncated_at_max_chars(self):
        long_reasoning = "A" * (_MAX_REASONING_CHARS + 50)
        raw = json.dumps(_valid_payload(reasoning=long_reasoning))
        decision = _parse_ai_response(raw)
        self.assertEqual(len(decision.reasoning), _MAX_REASONING_CHARS)

    def test_reasoning_not_truncated_when_within_limit(self):
        short = "Short reason."
        raw = json.dumps(_valid_payload(reasoning=short))
        decision = _parse_ai_response(raw)
        self.assertEqual(decision.reasoning, short)

    def test_malformed_json_raises(self):
        with self.assertRaises(Exception):
            _parse_ai_response("NOT JSON AT ALL {{{")

    def test_invalid_enum_value_raises(self):
        raw = json.dumps(_valid_payload(recommended_action="NUKE_IT"))
        with self.assertRaises(Exception):
            _parse_ai_response(raw)

    def test_missing_required_field_raises(self):
        payload = _valid_payload()
        del payload["recommended_action"]
        with self.assertRaises(Exception):
            _parse_ai_response(json.dumps(payload))

    def test_confidence_out_of_range_raises(self):
        raw = json.dumps(_valid_payload(confidence_score=1.5))
        with self.assertRaises(Exception):
            _parse_ai_response(raw)


# ---------------------------------------------------------------------------
# Tests: get_ai_decision (mocked Groq)
# ---------------------------------------------------------------------------


class GetAiDecisionTests(unittest.TestCase):
    @patch("app.ai_brain.Groq")
    def test_valid_groq_response_returns_ai_decision(self, MockGroq):
        """Happy path: Groq returns valid JSON → AIDecision returned."""
        raw = json.dumps(_valid_payload())
        MockGroq.return_value.chat.completions.create.return_value = (
            _make_groq_response(raw)
        )

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            decision = get_ai_decision(_transaction(), _customer())

        self.assertIsInstance(decision, AIDecision)
        self.assertEqual(decision.recommended_action, RecoveryAction.SEND_PAYMENT_LINK)
        self.assertAlmostEqual(decision.confidence_score, 0.87)

    @patch("app.ai_brain.Groq")
    def test_malformed_json_falls_back_to_escalate(self, MockGroq):
        """Groq returns garbage JSON → fallback ESCALATE returned."""
        MockGroq.return_value.chat.completions.create.return_value = (
            _make_groq_response("GARBAGE }{{ NOT JSON")
        )

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            decision = get_ai_decision(_transaction(), _customer())

        self._assert_fallback(decision)

    @patch("app.ai_brain.Groq")
    def test_invalid_enum_falls_back_to_escalate(self, MockGroq):
        """Groq returns unrecognised action → fallback ESCALATE returned."""
        raw = json.dumps(_valid_payload(recommended_action="NUKE_IT"))
        MockGroq.return_value.chat.completions.create.return_value = (
            _make_groq_response(raw)
        )

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            decision = get_ai_decision(_transaction(), _customer())

        self._assert_fallback(decision)

    @patch("app.ai_brain.Groq")
    def test_confidence_out_of_range_falls_back(self, MockGroq):
        """Groq returns confidence_score > 1.0 → fallback ESCALATE returned."""
        raw = json.dumps(_valid_payload(confidence_score=2.5))
        MockGroq.return_value.chat.completions.create.return_value = (
            _make_groq_response(raw)
        )

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            decision = get_ai_decision(_transaction(), _customer())

        self._assert_fallback(decision)

    @patch("app.ai_brain.Groq")
    def test_missing_field_falls_back_to_escalate(self, MockGroq):
        """Groq omits required field → fallback ESCALATE returned."""
        payload = _valid_payload()
        del payload["recommended_action"]
        MockGroq.return_value.chat.completions.create.return_value = (
            _make_groq_response(json.dumps(payload))
        )

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            decision = get_ai_decision(_transaction(), _customer())

        self._assert_fallback(decision)

    @patch("app.ai_brain.Groq")
    def test_empty_response_body_falls_back(self, MockGroq):
        """Groq returns empty content string → fallback ESCALATE returned."""
        MockGroq.return_value.chat.completions.create.return_value = (
            _make_groq_response("")
        )

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            decision = get_ai_decision(_transaction(), _customer())

        self._assert_fallback(decision)

    @patch("app.ai_brain.Groq")
    def test_groq_api_exception_falls_back(self, MockGroq):
        """Groq SDK raises an exception → fallback ESCALATE returned."""
        MockGroq.return_value.chat.completions.create.side_effect = RuntimeError(
            "Connection refused"
        )

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            decision = get_ai_decision(_transaction(), _customer())

        self._assert_fallback(decision)

    def test_missing_api_key_falls_back(self):
        """Missing GROQ_API_KEY → fallback ESCALATE returned (no crash)."""
        env = {k: v for k, v in __import__("os").environ.items() if k != "GROQ_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            decision = get_ai_decision(_transaction(), _customer())
        self._assert_fallback(decision)

    @patch("app.ai_brain.Groq")
    def test_decision_is_read_only_no_db_writes(self, MockGroq):
        """get_ai_decision must not modify transaction or customer objects."""
        raw = json.dumps(_valid_payload())
        MockGroq.return_value.chat.completions.create.return_value = (
            _make_groq_response(raw)
        )
        txn = _transaction()
        cust = _customer()
        original_amount = txn.amount
        original_status = txn.status
        original_ltv = cust.lifetime_value

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            get_ai_decision(txn, cust)

        self.assertEqual(txn.amount, original_amount)
        self.assertEqual(txn.status, original_status)
        self.assertEqual(cust.lifetime_value, original_ltv)

    @patch("app.ai_brain.Groq")
    def test_all_valid_recovery_actions_accepted(self, MockGroq):
        """All four valid RecoveryAction values should parse without fallback."""
        for action in ("DO_NOTHING", "SILENT_RETRY", "SEND_PAYMENT_LINK", "ESCALATE"):
            raw = json.dumps(_valid_payload(recommended_action=action))
            MockGroq.return_value.chat.completions.create.return_value = (
                _make_groq_response(raw)
            )

            with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
                decision = get_ai_decision(_transaction(), _customer())

            self.assertEqual(decision.recommended_action.value, action, f"Failed for {action}")

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _assert_fallback(self, decision: AIDecision) -> None:
        self.assertEqual(decision.recommended_action, RecoveryAction.ESCALATE)
        self.assertEqual(decision.confidence_score, 0.0)
        self.assertEqual(decision.failure_classification, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()

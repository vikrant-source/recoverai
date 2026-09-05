"""
Razorpay webhook signature verification.

SECURITY RULES:
- RAZORPAY_WEBHOOK_SECRET is loaded from the root .env.
- This is the Razorpay *Webhook* secret, NOT the API Key Secret.
- The secret is NEVER logged, printed, or included in any response.
- Comparison uses hmac.compare_digest (constant-time) to prevent timing attacks.

Behaviour
---------
- If RAZORPAY_WEBHOOK_SECRET is set in the environment:
    Valid signature   → returns True
    Invalid/missing   → returns False (caller must reject with 400)
- If RAZORPAY_WEBHOOK_SECRET is NOT set:
    → returns True unconditionally (dev/synthetic mode; no secret configured)

This allows local development and synthetic webhooks to work without
configuring a webhook secret, while enforcing verification when deployed
with a real Razorpay webhook endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env from repo root (two levels above: app/ → backend/ → root)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

_ENV_KEY = "RAZORPAY_WEBHOOK_SECRET"


def _get_webhook_secret() -> str | None:
    """
    Return the configured webhook secret, or None if not configured.
    Never logs the secret value.
    """
    secret = os.environ.get(_ENV_KEY, "").strip()
    return secret if secret else None


def verify_razorpay_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """
    Verify a Razorpay webhook HMAC-SHA256 signature.

    Parameters
    ----------
    raw_body        Raw request body bytes (before any parsing).
    signature_header  Value of the X-Razorpay-Signature HTTP header, or None.

    Returns
    -------
    True  — signature is valid, or webhook secret is not configured (dev mode).
    False — secret IS configured but signature is missing or invalid.

    The caller is responsible for rejecting the request when this returns False.
    """
    secret = _get_webhook_secret()

    if secret is None:
        # No webhook secret configured — allow all (dev/synthetic mode).
        return True

    if not signature_header:
        logger.warning(
            "RAZORPAY_WEBHOOK_SECRET is configured but X-Razorpay-Signature "
            "header is absent. Rejecting request."
        )
        return False

    # Compute expected HMAC-SHA256 over raw body using the webhook secret.
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison — prevents timing-based secret extraction.
    valid = hmac.compare_digest(expected, signature_header)
    if not valid:
        logger.warning(
            "X-Razorpay-Signature verification failed. "
            "Signature header did not match computed HMAC."
            # Do NOT log the actual values — that would expose them.
        )
    return valid

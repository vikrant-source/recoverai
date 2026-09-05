"""
Tests for the Razorpay Test Mode router.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.conftest import SHARED_ENGINE, SharedTestingSessionLocal, shared_override_get_db

from app.main import app
from app.database import Base, get_db
from app.models import Transaction, Customer
from datetime import datetime, timezone, timedelta

app.dependency_overrides[get_db] = shared_override_get_db
client = TestClient(app)

class TestRazorpayTestRouter:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        Base.metadata.create_all(bind=SHARED_ENGINE)
        self.db = SharedTestingSessionLocal()
        
        self.now = datetime.now(timezone.utc)
        self.test_customer = Customer(
            customer_id="cust_test_router_001",
            lifetime_value=100000,
            opted_out=False,
        )
        self.db.add(self.test_customer)
        
        self.test_transaction = Transaction(
            txn_id="txn_test_router_001",
            customer_id="cust_test_router_001",
            amount=75000,
            currency="INR",
            status="FAILED",
            failure_code="INSUFFICIENT_FUNDS",
            attempt_count=1,
            revenue_at_risk=75000,
            recovery_window_expires_at=self.now + timedelta(days=1),
        )
        self.db.add(self.test_transaction)
        self.db.commit()
        
        yield
        
        self.db.close()
        Base.metadata.drop_all(bind=SHARED_ENGINE)

    @patch("app.razorpay_test_router.urllib.request.urlopen")
    @patch("app.razorpay_test_router.os.environ.get")
    def test_create_order_valid_txn(self, mock_env_get, mock_urlopen):
        # Mock environment variables
        def env_get_side_effect(key, default=""):
            if key == "RAZORPAY_KEY_ID": return "rzp_test_mock_id"
            if key == "RAZORPAY_KEY_SECRET": return "rzp_test_mock_secret"
            return default
        mock_env_get.side_effect = env_get_side_effect

        # Mock urllib response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"id": "order_mock_001"}).encode("utf-8")
        # Ensure it acts as a context manager
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        payload = {"txn_id": "txn_test_router_001"}
        response = client.post("/api/razorpay-test/create-order", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["order_id"] == "order_mock_001"
        assert data["txn_id"] == "txn_test_router_001"
        assert data["amount"] == 75000  # Amount comes from local transaction
        assert data["currency"] == "INR"
        assert data["key_id"] == "rzp_test_mock_id"
        assert "rzp_test_mock_secret" not in json.dumps(data)  # API secret is never returned

        # Verify the request payload to Razorpay
        mock_urlopen.assert_called_once()
        req_obj = mock_urlopen.call_args[0][0]
        assert req_obj.method == "POST"
        
        sent_payload = json.loads(req_obj.data.decode("utf-8"))
        assert sent_payload["amount"] == 75000
        assert sent_payload["currency"] == "INR"
        assert sent_payload["notes"]["recoverai_txn_id"] == "txn_test_router_001"

    @patch("app.razorpay_test_router.os.environ.get")
    def test_create_order_unknown_txn_returns_404(self, mock_env_get):
        def env_get_side_effect(key, default=""):
            if key == "RAZORPAY_KEY_ID": return "rzp_test_mock_id"
            if key == "RAZORPAY_KEY_SECRET": return "rzp_test_mock_secret"
            return default
        mock_env_get.side_effect = env_get_side_effect
        
        payload = {"txn_id": "txn_unknown_999"}
        response = client.post("/api/razorpay-test/create-order", json=payload)
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

"""
Integration tests for the Webhook Handler — Phase 6.

Uses FastAPI TestClient to test the /webhooks/payment endpoint.
Overrides the database dependency to use an isolated in-memory SQLite database.
Mocks the AI Brain to prevent real Groq API calls.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app
from app.database import Base, get_db
from app.models import Customer, Transaction, WebhookEvent, Intervention
from app.schemas import AIDecision, RecoveryAction

from sqlalchemy.pool import StaticPool

# Isolated test database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

class TestWebhookIntegration(unittest.TestCase):
    def setUp(self):
        # Recreate the tables for every test
        Base.metadata.create_all(bind=engine)
        self.db = TestingSessionLocal()
        
        # Setup common test data
        self.now = datetime.now(timezone.utc)
        
        self.test_customer = Customer(
            customer_id="cust_webhook_001",
            lifetime_value=100000,
            opted_out=False
        )
        self.db.add(self.test_customer)
        
        self.test_transaction = Transaction(
            txn_id="txn_webhook_001",
            customer_id="cust_webhook_001",
            amount=49900,
            status="FAILED",
            failure_code="INSUFFICIENT_FUNDS",
            failure_description="[recoverable] Low balance",
            attempt_count=1,
            revenue_at_risk=49900,
            recovered_amount=0,
            recovery_window_expires_at=self.now + timedelta(days=1)
        )
        self.db.add(self.test_transaction)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        # Drop all tables after the test
        Base.metadata.drop_all(bind=engine)

    def _mock_ai_decision(self, action=RecoveryAction.SILENT_RETRY):
        return AIDecision(
            recommended_action=action,
            confidence_score=0.90,
            failure_classification="TEST_ERROR",
            reasoning="Test reasoning"
        )

    @patch("app.pipeline.get_ai_decision")
    def test_valid_payment_failed_event_returns_accepted(self, mock_ai):
        mock_ai.return_value = self._mock_ai_decision(RecoveryAction.SILENT_RETRY)
        
        payload = {
            "event_id": "evt_001",
            "event_type": "payment.failed",
            "txn_id": "txn_webhook_001",
            "synthetic": True
        }
        
        response = client.post("/webhooks/payment", json=payload)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ACCEPTED")
        self.assertEqual(data["txn_id"], "txn_webhook_001")
        self.assertEqual(data["execution_status"], "SUCCESS")
        self.assertEqual(data["final_action"], "SILENT_RETRY")
        self.assertIsInstance(data["recovered_amount"], int)
        self.assertEqual(data["recovered_amount"], 49900)
        
        # Verify WebhookEvent was saved and COMPLETED
        event = self.db.query(WebhookEvent).filter_by(event_id="evt_001").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.status, "COMPLETED")
        
        # Verify Intervention was created
        intervention = self.db.query(Intervention).filter_by(txn_id="txn_webhook_001").first()
        self.assertIsNotNone(intervention)
        self.assertEqual(intervention.execution_status, "SUCCESS")

    @patch("app.pipeline.get_ai_decision")
    def test_duplicate_post_with_same_event_id(self, mock_ai):
        mock_ai.return_value = self._mock_ai_decision()
        
        payload = {
            "event_id": "evt_002",
            "event_type": "payment.failed",
            "txn_id": "txn_webhook_001",
            "synthetic": True
        }
        
        # First call should succeed
        resp1 = client.post("/webhooks/payment", json=payload)
        self.assertEqual(resp1.json()["status"], "ACCEPTED")
        
        # Second call should return DUPLICATE
        resp2 = client.post("/webhooks/payment", json=payload)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "DUPLICATE")
        
        # Pipeline should only be called once
        mock_ai.assert_called_once()
        
        # Only one intervention should exist
        interventions = self.db.query(Intervention).filter_by(txn_id="txn_webhook_001").all()
        self.assertEqual(len(interventions), 1)

    def test_malformed_payload_returns_422(self):
        # Missing required 'event_id'
        payload = {
            "event_type": "payment.failed",
            "txn_id": "txn_webhook_001"
        }
        
        response = client.post("/webhooks/payment", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_unknown_transaction(self):
        payload = {
            "event_id": "evt_003",
            "event_type": "payment.failed",
            "txn_id": "txn_unknown_123",
            "synthetic": True
        }
        
        response = client.post("/webhooks/payment", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Internal processing fails, but API returns IGNORED
        self.assertEqual(data["status"], "IGNORED")
        self.assertIn("not found", data["message"])
        
        # The webhook event should be recorded as FAILED internally
        event = self.db.query(WebhookEvent).filter_by(event_id="evt_003").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.status, "FAILED")
        self.assertIsNotNone(event.error_message)

    def test_wrong_event_type(self):
        payload = {
            "event_id": "evt_004",
            "event_type": "payment.captured",
            "txn_id": "txn_webhook_001",
            "synthetic": True
        }
        
        response = client.post("/webhooks/payment", json=payload)
        self.assertEqual(response.status_code, 200)
        
        self.assertEqual(response.json()["status"], "IGNORED")
        
        # No webhook event should be created for unhandled event types
        event = self.db.query(WebhookEvent).filter_by(event_id="evt_004").first()
        self.assertIsNone(event)

    @patch("app.pipeline.get_ai_decision")
    def test_already_successful_transaction(self, mock_ai):
        mock_ai.return_value = self._mock_ai_decision()
        
        # Change transaction to SUCCESS
        txn = self.db.query(Transaction).filter_by(txn_id="txn_webhook_001").first()
        txn.status = "SUCCESS"
        self.db.commit()
        
        payload = {
            "event_id": "evt_005",
            "event_type": "payment.failed",
            "txn_id": "txn_webhook_001",
            "synthetic": True
        }
        
        response = client.post("/webhooks/payment", json=payload)
        data = response.json()
        
        self.assertEqual(data["status"], "ACCEPTED")
        self.assertEqual(data["execution_status"], "SKIPPED")
        self.assertEqual(data["final_action"], "DO_NOTHING")
        self.assertEqual(data["recovered_amount"], 0)

    @patch("app.pipeline.get_ai_decision")
    def test_opted_out_customer(self, mock_ai):
        mock_ai.return_value = self._mock_ai_decision()
        
        # Change customer to opted_out
        cust = self.db.query(Customer).filter_by(customer_id="cust_webhook_001").first()
        cust.opted_out = True
        self.db.commit()
        
        payload = {
            "event_id": "evt_006",
            "event_type": "payment.failed",
            "txn_id": "txn_webhook_001",
            "synthetic": True
        }
        
        response = client.post("/webhooks/payment", json=payload)
        data = response.json()
        
        self.assertEqual(data["status"], "ACCEPTED")
        self.assertEqual(data["execution_status"], "SKIPPED")
        self.assertEqual(data["final_action"], "DO_NOTHING")

    @patch("app.pipeline.get_ai_decision")
    def test_policy_override(self, mock_ai):
        # AI recommends SILENT_RETRY
        mock_ai.return_value = self._mock_ai_decision(RecoveryAction.SILENT_RETRY)
        
        # Set max retries reached so policy overrides to ESCALATE
        txn = self.db.query(Transaction).filter_by(txn_id="txn_webhook_001").first()
        txn.attempt_count = 2 # Assuming MAX_RETRY_ATTEMPTS = 2
        self.db.commit()
        
        payload = {
            "event_id": "evt_007",
            "event_type": "payment.failed",
            "txn_id": "txn_webhook_001",
            "synthetic": True
        }
        
        response = client.post("/webhooks/payment", json=payload)
        data = response.json()
        
        self.assertEqual(data["status"], "ACCEPTED")
        self.assertEqual(data["execution_status"], "ESCALATED")
        self.assertEqual(data["final_action"], "ESCALATE")

    @patch("app.webhook_handler.run_recovery_pipeline")
    def test_pipeline_failure_behavior(self, mock_pipeline):
        # Simulate an unexpected error in the pipeline
        mock_pipeline.side_effect = Exception("Unexpected simulated explosion")
        
        payload = {
            "event_id": "evt_008",
            "event_type": "payment.failed",
            "txn_id": "txn_webhook_001",
            "synthetic": True
        }
        
        response = client.post("/webhooks/payment", json=payload)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data["status"], "IGNORED")
        self.assertIn("failed unexpectedly", data["message"])
        
        # The webhook event should be recorded as FAILED internally
        event = self.db.query(WebhookEvent).filter_by(event_id="evt_008").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.status, "FAILED")
        self.assertIn("Unexpected simulated explosion", event.error_message)

if __name__ == '__main__':
    unittest.main()

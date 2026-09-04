"""
Unit tests for the Context Builder — Phase 6.

Tests the load_context function which retrieves a Transaction and Customer
from the database. Uses a mocked database session to avoid interacting
with the real database.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.context_builder import ContextLoadError, load_context
from app.models import Customer, Transaction


class TestContextBuilder(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()

    def test_load_context_returns_transaction_and_customer(self):
        # Mock transaction query
        mock_txn_query = MagicMock()
        mock_txn = Transaction(txn_id="txn_123", customer_id="cust_456")
        mock_txn_query.filter.return_value.first.return_value = mock_txn
        
        # Mock customer query
        mock_cust_query = MagicMock()
        mock_cust = Customer(customer_id="cust_456")
        mock_cust_query.filter.return_value.first.return_value = mock_cust
        
        # Hook up db.query to return the correct query mock based on model
        def mock_query(model):
            if model == Transaction:
                return mock_txn_query
            elif model == Customer:
                return mock_cust_query
            return MagicMock()
            
        self.db.query.side_effect = mock_query

        # Execute
        transaction, customer = load_context(self.db, "txn_123")

        # Verify
        self.assertEqual(transaction, mock_txn)
        self.assertEqual(customer, mock_cust)
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()

    def test_load_context_transaction_not_found_raises(self):
        # Mock transaction query returning None
        mock_txn_query = MagicMock()
        mock_txn_query.filter.return_value.first.return_value = None
        
        def mock_query(model):
            if model == Transaction:
                return mock_txn_query
            return MagicMock()
            
        self.db.query.side_effect = mock_query

        # Execute and verify
        with self.assertRaises(ContextLoadError) as context:
            load_context(self.db, "txn_missing")
            
        self.assertIn("Transaction 'txn_missing' not found", str(context.exception))
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()

    def test_load_context_customer_not_found_raises(self):
        # Mock transaction query finding the transaction
        mock_txn_query = MagicMock()
        mock_txn = Transaction(txn_id="txn_123", customer_id="cust_missing")
        mock_txn_query.filter.return_value.first.return_value = mock_txn
        
        # Mock customer query returning None
        mock_cust_query = MagicMock()
        mock_cust_query.filter.return_value.first.return_value = None
        
        def mock_query(model):
            if model == Transaction:
                return mock_txn_query
            elif model == Customer:
                return mock_cust_query
            return MagicMock()
            
        self.db.query.side_effect = mock_query

        # Execute and verify
        with self.assertRaises(ContextLoadError) as context:
            load_context(self.db, "txn_123")
            
        self.assertIn("Customer 'cust_missing' for transaction 'txn_123' not found", str(context.exception))
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()

if __name__ == '__main__':
    unittest.main()

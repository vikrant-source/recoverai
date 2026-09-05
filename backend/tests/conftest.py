"""
Shared pytest configuration for the backend test suite.

Provides a single in-memory SQLite engine and session factory used by all
webhook integration tests. This prevents test isolation failures when multiple
test files share the same `app` singleton and `dependency_overrides[get_db]`.

Each test class's setUp/tearDown calls create_all/drop_all on SHARED_ENGINE,
which is the engine the app's get_db override actually uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Single shared in-memory engine for all webhook integration tests.
SHARED_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SharedTestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=SHARED_ENGINE
)


def shared_override_get_db():
    try:
        db = SharedTestingSessionLocal()
        yield db
    finally:
        db.close()

"""Integration test fixtures using testcontainers-python.

Spins up ephemeral Postgres 18 and Redis 7, runs migrations, provides per-test sessions.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
import redis as redis_module
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

try:
    from testcontainers.community.postgres import PostgresContainer
    from testcontainers.community.redis import RedisContainer
except ModuleNotFoundError:
    from testcontainers.postgres import PostgresContainer  # type: ignore[no-redef]
    from testcontainers.redis import RedisContainer  # type: ignore[no-redef]

from core.events.encryption import create_user_key, encrypt_payload
from core.events.models import IngestionEvent, User

BACKEND_DIR = Path(__file__).parents[2]  # backend/


def run_migrations(database_url: str) -> None:
    """Run Alembic migrations against the given database URL."""
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "head"],
        env=env,
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Migration failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="session")
def pg_container() -> Generator[PostgresContainer, None, None]:
    """Session-scoped ephemeral Postgres 18 container with migrations applied."""
    with PostgresContainer("postgres:18", driver="psycopg") as pg:
        url = pg.get_connection_url()
        run_migrations(url)
        yield pg


@pytest.fixture
def pg_engine(pg_container: PostgresContainer) -> Engine:
    """Per-test SQLAlchemy engine."""
    return create_engine(pg_container.get_connection_url())


@pytest.fixture
def pg_session(pg_engine: Engine) -> Generator[Session, None, None]:
    """Per-test session. Rolls back after each test for isolation."""
    with Session(pg_engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def test_user(pg_session: Session) -> User:
    """Create a test user with an active encryption key.

    The ORM model now declares server_default on id and created_at so
    SQLAlchemy omits them from INSERT and lets the DB fill them via uuidv7()
    and NOW().
    """
    user = User(
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        google_sub=f"sub_{uuid.uuid4().hex[:8]}",
    )
    pg_session.add(user)
    pg_session.flush()
    create_user_key(pg_session, user.id)
    pg_session.flush()
    return user


@pytest.fixture
def test_ingestion_event(pg_session: Session, test_user: User) -> IngestionEvent:
    """Create a minimal ingestion event (required FK for transaction_events)."""
    encrypted, key_id = encrypt_payload(pg_session, test_user.id, {"source": "test"})

    ingestion = IngestionEvent(
        user_id=test_user.id,
        source="manual",
        status="success",
        records_added=0,
        records_skipped=0,
        records_flagged=0,
        payload=encrypted,
        encryption_key_id=key_id,
    )
    pg_session.add(ingestion)
    pg_session.flush()
    return ingestion


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, None, None]:
    """Session-scoped ephemeral Redis 7 container for integration tests."""
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture
def redis_client(redis_container: RedisContainer) -> Generator[redis_module.Redis, None, None]:
    """Per-test Redis client connected to the session-scoped container.

    Flushes the DB after each test so tests don't share key state.
    """
    client: redis_module.Redis = redis_container.get_client()
    yield client
    client.flushdb()

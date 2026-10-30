"""Shared FastAPI database-session dependency. Implements TRD §1 (API layer).

One engine and sessionmaker per process, created lazily from DATABASE_URL. Routers depend on
get_db rather than defining their own copy (PHASE_PROTOCOL §2); tests override this function
via app.dependency_overrides.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://localhost/finance")
_session_factory: sessionmaker[Session] | None = None


def _get_session_factory() -> sessionmaker[Session]:
    global _session_factory  # noqa: PLW0603
    if _session_factory is None:
        _session_factory = sessionmaker(bind=create_engine(DATABASE_URL))
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()

"""M9: PITR readiness test.

Verifies that the running Postgres has wal_level = replica, which is required
for point-in-time recovery. This test documents the PITR requirement and will
fail loudly if the Postgres config is wrong.

Note: A full restore test must be run manually before beta.
See docs/DECISIONS.md ADR-011 for the restore procedure.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration
@pytest.mark.integration_pitr
def test_wal_level_is_replica() -> None:
    """Postgres must have wal_level = replica for PITR readiness (M9)."""
    import psycopg

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://finance:finance@db:5432/finance",
    )
    # psycopg uses conninfo format; strip the SQLAlchemy driver prefix if present
    conninfo = database_url.replace("postgresql+psycopg://", "postgresql://")

    conn = psycopg.connect(conninfo)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW wal_level;")
            row = cur.fetchone()
            assert row is not None
            wal_level = row[0]
            assert wal_level == "replica", (
                f"Postgres wal_level is '{wal_level}', expected 'replica'. "
                "PITR backups will not work. Check docker-compose.yml DB command args."
            )
    finally:
        conn.close()

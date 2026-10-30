"""Every ORM column exists in the migrated schema (guards B-7: account_ref was never migrated).

Unit tests use mock sessions, so an ORM column with no migration passes CI and fails on the
first real INSERT. This compares Base.metadata against the database after `alembic upgrade head`.
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

import core.models  # noqa: F401  (registers the mutable tables on Base.metadata)
from core.events.models import Base


def test_every_orm_column_is_migrated(pg_engine: Engine) -> None:
    inspector = inspect(pg_engine)
    db_tables = set(inspector.get_table_names())
    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in db_tables:
            missing.append(f"table {table.name}")
            continue
        db_columns = {c["name"] for c in inspector.get_columns(table.name)}
        missing.extend(f"{table.name}.{c.name}" for c in table.columns if c.name not in db_columns)
    assert missing == [], f"ORM columns/tables with no migration: {missing}"

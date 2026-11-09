"""ingestion_events.balance_check: VARCHAR(8) → VARCHAR(16) for "not_applicable" (C2).

An empty statement whose balances are unknown is accepted with balance_check =
"not_applicable" (never "pass"). Widening a VARCHAR is DDL only: no row is updated or
deleted, and no constraint on the immutable table is weakened.
"""

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ingestion_events",
        "balance_check",
        type_=sa.String(16),
        existing_type=sa.String(8),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Forward-only (CLAUDE.md §5): once a "not_applicable" row exists on the immutable table,
    # narrowing back to VARCHAR(8) would fail or require rewriting rows. Never downgrade.
    raise NotImplementedError("005 is forward-only: ingestion_events rows may hold 14-char values")

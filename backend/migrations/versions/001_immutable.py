"""Immutable event tables: ingestion_events, raw_artifacts, transaction_events, document_events.

Append-only: enforced by DB-level trigger on each table.
Implements TRD §3.1, invariants I1-I3.
"""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = "000"
branch_labels = None
depends_on = None

APPEND_ONLY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION enforce_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only: UPDATE and DELETE are forbidden', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""


def _create_append_only_trigger(table_name: str) -> None:
    op.execute(f"""
        CREATE TRIGGER {table_name}_append_only
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION enforce_append_only();
    """)


def upgrade() -> None:
    # Create the trigger function once
    op.execute(APPEND_ONLY_TRIGGER_SQL)

    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_detail", sa.JSON(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("records_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_flagged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_check", sa.String(8), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["encryption_key_id"], ["user_encryption_keys.id"]),
    )
    _create_append_only_trigger("ingestion_events")

    op.create_table(
        "raw_artifacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("ingestion_event_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("retained", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
        sa.UniqueConstraint("user_id", "content_hash", name="uq_raw_artifacts_user_content_hash"),
        sa.ForeignKeyConstraint(["ingestion_event_id"], ["ingestion_events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    _create_append_only_trigger("raw_artifacts")

    op.create_table(
        "transaction_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("ingestion_event_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("account_ref", sa.String(128), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_hash", sa.String(64), nullable=False),
        sa.Column("occurrence_index", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("transaction_type", sa.String(16), nullable=False),
        sa.Column("narration", sa.Text(), nullable=False),
        sa.Column("canonical_narration", sa.Text(), nullable=True),
        sa.Column("running_balance_paise", sa.BigInteger(), nullable=True),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
        sa.UniqueConstraint(
            "user_id", "idempotency_hash", name="uq_transaction_events_user_idempotency_hash"
        ),
        sa.ForeignKeyConstraint(["ingestion_event_id"], ["ingestion_events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["encryption_key_id"], ["user_encryption_keys.id"]),
    )
    # M10: indexes for known access paths
    op.create_index(
        "ix_transaction_events_user_date", "transaction_events", ["user_id", "value_date"]
    )
    op.create_index(
        "ix_transaction_events_user_date_type",
        "transaction_events",
        ["user_id", "value_date", "transaction_type"],
    )
    _create_append_only_trigger("transaction_events")

    op.create_table(
        "document_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["encryption_key_id"], ["user_encryption_keys.id"]),
    )
    _create_append_only_trigger("document_events")


def downgrade() -> None:
    op.drop_table("document_events")
    op.drop_index("ix_transaction_events_user_date_type", "transaction_events")
    op.drop_index("ix_transaction_events_user_date", "transaction_events")
    op.drop_table("transaction_events")
    op.drop_table("raw_artifacts")
    op.drop_table("ingestion_events")
    op.execute("DROP FUNCTION IF EXISTS enforce_append_only CASCADE;")

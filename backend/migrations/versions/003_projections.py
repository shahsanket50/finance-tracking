"""Projection snapshots table — mutable, disposable derived data.

Stores periodic snapshots so replay only processes events after last_seq.
H1: snapshot every 1000 events.
"""

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projection_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("projection_type", sa.String(64), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), nullable=False),
        sa.Column(
            "snapshot_data",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_projection_snapshots_user_type",
        "projection_snapshots",
        ["user_id", "projection_type", "last_seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_projection_snapshots_user_type")
    op.drop_table("projection_snapshots")

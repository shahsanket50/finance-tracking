"""Identity tables: users, invite_allowlist, user_encryption_keys.

Created before immutable event tables because ingestion_events has a FK to users(id).
Implements TRD §3.2 (partial — identity subset).
"""

import sqlalchemy as sa
from alembic import op

revision = "000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("google_sub", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("google_sub"),
    )

    op.create_table(
        "invite_allowlist",
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("invited_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("email"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
    )

    op.create_table(
        "user_encryption_keys",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("key_material", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("deactivated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )


def downgrade() -> None:
    op.drop_table("user_encryption_keys")
    op.drop_table("invite_allowlist")
    op.drop_table("users")

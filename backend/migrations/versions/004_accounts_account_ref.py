"""accounts.account_ref — the column Wave 4 added to the ORM but never migrated (B-7).

account_ref links the mutable accounts row to the immutable event log
(transaction_events.account_ref). Mutable table; additive, nullable, forward-only.
"""

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("account_ref", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "account_ref")

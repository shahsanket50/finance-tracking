"""Repair: transaction_events.canonical_narration on databases migrated before 2026-08-02.

001_immutable.py was edited in place (0a1524f) after some databases had applied it, so those
databases lack this column while fresh ones have it. This forward-only repair adds it where
missing (nullable, additive) and is a no-op on fresh databases. Found during the Wave 5
local-stack verification: confirm() failed with UndefinedColumn on the dev database.
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transaction_events ADD COLUMN IF NOT EXISTS canonical_narration TEXT")


def downgrade() -> None:
    raise NotImplementedError("006 is forward-only: it repairs drift, there is nothing to undo")

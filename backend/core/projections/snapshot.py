"""H1: Projection snapshots — checkpoint every 1000 events.

Snapshots make replay efficient: instead of replaying from seq=0,
load the latest snapshot and replay only newer events.

Phase 0 scaffold. Uses raw SQL via text() to avoid ORM model for disposable
derived data. Full ORM model can be added in Phase 1 if needed.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

# Snapshot interval: save snapshot every N events (H1).
SNAPSHOT_INTERVAL = 1000


def load_snapshot(
    session: Session,
    user_id: uuid.UUID,
    projection_type: str,
) -> tuple[dict[str, object], int] | None:
    """Load the latest snapshot for (user_id, projection_type).

    Returns (snapshot_data, last_seq) or None if no snapshot exists.
    """
    result = session.execute(
        text(
            """
            SELECT snapshot_data, last_seq
            FROM projection_snapshots
            WHERE user_id = :user_id
              AND projection_type = :projection_type
            ORDER BY last_seq DESC
            LIMIT 1
            """
        ),
        {"user_id": str(user_id), "projection_type": projection_type},
    )
    row = result.first()
    if row is None:
        return None
    raw = row[0]
    # snapshot_data may come back as a dict (JSONB column) or a string
    if isinstance(raw, str):
        data: dict[str, object] = json.loads(raw)
    elif isinstance(raw, dict):
        data = raw
    else:
        # Unexpected type — corrupt or migrated row; signal caller to do full rebuild
        return None
    return data, int(row[1])


def save_snapshot(
    session: Session,
    user_id: uuid.UUID,
    projection_type: str,
    state: dict[str, object],
    last_seq: int,
) -> None:
    """Persist a snapshot of the current projection state."""
    session.execute(
        text(
            """
            INSERT INTO projection_snapshots
                (user_id, projection_type, snapshot_data, last_seq)
            VALUES
                (:user_id, :projection_type, :snapshot_data::jsonb, :last_seq)
            """
        ),
        {
            "user_id": str(user_id),
            "projection_type": projection_type,
            "snapshot_data": json.dumps(state),
            "last_seq": last_seq,
        },
    )

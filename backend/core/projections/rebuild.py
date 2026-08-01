"""M2: Shadow table + atomic swap for zero-downtime projection rebuilds.

When projection code changes, rebuild by:
1. Replaying all events into a shadow table
2. Atomically renaming shadow → live table

Phase 0 scaffold: the full implementation requires DDL operations specific to
each projection table type. This module provides the interface and a generic
implementation using JSON snapshots.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from core.projections.builder import build_projection
from core.projections.snapshot import save_snapshot


def rebuild_projection(
    session: Session,
    user_id: uuid.UUID,
    projection_type: str,
) -> dict[str, object]:
    """Rebuild a projection from scratch by replaying all events.

    Phase 0: full replay from seq=0, save result as snapshot.
    Phase 1+: implement shadow table DDL per projection type.

    Returns the rebuilt projection state.
    """
    state = build_projection(session, user_id, projection_type, since_seq=0)
    # Save the rebuilt state as a snapshot (last_seq = max seq in the projection)
    events_count = state.get("count", 0)
    if isinstance(events_count, int) and events_count > 0:
        events = state.get("events", [])
        if isinstance(events, list) and events:
            last_event = events[-1]
            if isinstance(last_event, dict):
                last_seq = int(last_event.get("seq", 0))
                save_snapshot(session, user_id, projection_type, state, last_seq)
    return state

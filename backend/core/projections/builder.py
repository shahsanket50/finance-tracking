"""Projection builder: reads events and applies reducers.

Phase 0 scaffold: only the 'events_list' projection type is implemented.
Future projection types (transactions_current, budget_status, etc.) will register
their reducers via register_reducer().

Implements I3 (replay determinism): build_projection_from_events() is a pure
function — same input always produces byte-identical output.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import cast

from sqlalchemy.orm import Session

from core.events.store import Event, read_since_seq

# ── Reducer registry ───────────────────────────────────────────────────────────

# Maps projection_type → (initial_state_factory, reducer_fn)
# reducer_fn: (state: dict, event: Event) -> dict
_REDUCERS: dict[
    str,
    tuple[
        Callable[[], dict[str, object]],
        Callable[[dict[str, object], Event], dict[str, object]],
    ],
] = {}


def register_reducer(
    projection_type: str,
    initial_state: Callable[[], dict[str, object]],
    reducer: Callable[[dict[str, object], Event], dict[str, object]],
) -> None:
    """Register a projection type with its initial state factory and reducer."""
    _REDUCERS[projection_type] = (initial_state, reducer)


# ── Built-in: events_list projection ──────────────────────────────────────────


def _events_list_initial() -> dict[str, object]:
    return {"events": [], "count": 0}


def _events_list_reducer(state: dict[str, object], event: Event) -> dict[str, object]:
    existing = cast(list[dict[str, object]], state["events"])
    events_list = [
        *existing,
        {
            "seq": event.seq,
            "event_type": event.event_type,
            "event_version": event.event_version,
            "aggregate_id": event.aggregate_id,
            "payload": event.payload,
        },
    ]
    return {"events": events_list, "count": len(events_list)}


register_reducer("events_list", _events_list_initial, _events_list_reducer)

# Register transactions_view reducer (side-effect import — must stay at module level)
import processing.resolver.reducer  # noqa: F401, E402

# ── Public API ─────────────────────────────────────────────────────────────────


def build_projection_from_events(
    events: list[Event],
    projection_type: str = "events_list",
) -> dict[str, object]:
    """Pure function: build a projection from an in-memory event list (I3).

    No DB access. Used for replay determinism testing.
    """
    if projection_type not in _REDUCERS:
        raise ValueError(f"Unknown projection type: {projection_type!r}")
    initial_state_fn, reducer = _REDUCERS[projection_type]
    state: dict[str, object] = initial_state_fn()
    for event in events:
        state = reducer(state, event)
    return state


def build_projection(
    session: Session,
    user_id: uuid.UUID,
    projection_type: str,
    since_seq: int = 0,
) -> dict[str, object]:
    """Build a projection for user_id by reading events from the DB.

    Reads all events after since_seq, applies the registered reducer,
    returns projected state. Deterministic: same events → same result (I3).
    """
    events = read_since_seq(session, user_id, since_seq=since_seq)
    return build_projection_from_events(events, projection_type)


def replay_from_seq(
    session: Session,
    user_id: uuid.UUID,
    projection_type: str,
    from_seq: int = 0,
) -> dict[str, object]:
    """Alias for build_projection starting from a specific seq number."""
    return build_projection(session, user_id, projection_type, since_seq=from_seq)

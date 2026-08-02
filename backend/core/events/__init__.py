"""Event-log read/write primitives."""

from core.events.store import Event, append_event, read_since_seq, read_stream

__all__ = ["Event", "append_event", "read_since_seq", "read_stream"]

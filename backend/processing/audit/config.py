"""Audit configuration constants. Implements PRD §15."""

# An ingestion event is considered stalled if its created_at is older than this
# many days and no newer event exists for the same account_ref.
SYNC_STALL_THRESHOLD_DAYS: int = 35

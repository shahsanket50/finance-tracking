"""Resolver exclusion set: the single source of exclusion truth. Implements PRD §7.1, ADR-022/023.

Contract:
- The set of excluded transaction hashes is read ONLY from the resolver projection
  (`transactions_view` state["excluded_hashes"]). That projection reads the leg hashes from
  each resolver event's payload (debit_hash/credit_hash, savings_debit_hash/cc_credit_hash,
  savings_debit_hash/fd_credit_hash, original_hash/reversal_hash).
- A resolver event's own idempotency_hash names the resolver event, never a leg (ADR-023).
  No caller may build an exclusion set by querying resolver rows' idempotency_hash column.
- Exclusion applies to flow totals (spend, income, budgets) only, never to account balances
  or card liabilities (ADR-022).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import cast

from sqlalchemy.orm import Session

from core.events.store import Event
from core.projections.builder import build_projection, build_projection_from_events

_PROJECTION = "transactions_view"


def excluded_hashes_from_events(events: Sequence[Event]) -> frozenset[str]:
    """DERIVATION: leg hashes excluded by resolver events, from an in-memory event list."""
    state = build_projection_from_events(list(events), _PROJECTION)
    return frozenset(cast(list[str], state["excluded_hashes"]))


def load_excluded_hashes(session: Session, user_id: uuid.UUID) -> frozenset[str]:
    """Leg hashes excluded by resolver events for user_id, replayed from the event log."""
    state = build_projection(session, user_id, _PROJECTION)
    return frozenset(cast(list[str], state["excluded_hashes"]))

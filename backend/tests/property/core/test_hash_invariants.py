"""Property-based tests for hash invariants (C1, C2) using Hypothesis."""
from __future__ import annotations

from datetime import date

from hypothesis import given, strategies as st

from core.hashing.hash import compute_idempotency_hash
from core.hashing.rounding import largest_remainder
from core.hashing.serialization import json_str_to_paise, money_to_json_str
from core.hashing.types import Paise


# ── Hash determinism ───────────────────────────────────────────────────────────


@given(
    account_ref=st.text(min_size=1, max_size=128),
    year=st.integers(min_value=2000, max_value=2099),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    amount=st.integers(min_value=-10_000_000, max_value=10_000_000),
    narration=st.text(max_size=256),
    idx=st.integers(min_value=0, max_value=100),
)
def test_hash_is_deterministic(
    account_ref: str, year: int, month: int, day: int, amount: int, narration: str, idx: int
) -> None:
    d = date(year, month, day)
    h1 = compute_idempotency_hash(account_ref, d, amount, narration, idx)
    h2 = compute_idempotency_hash(account_ref, d, amount, narration, idx)
    assert h1 == h2


@given(
    account_ref=st.text(min_size=1, max_size=128),
    year=st.integers(min_value=2000, max_value=2099),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    amount=st.integers(min_value=-10_000_000, max_value=10_000_000),
    narration=st.text(max_size=256),
    idx1=st.integers(min_value=0, max_value=50),
    idx2=st.integers(min_value=51, max_value=100),
)
def test_different_occurrence_index_different_hash(
    account_ref: str,
    year: int,
    month: int,
    day: int,
    amount: int,
    narration: str,
    idx1: int,
    idx2: int,
) -> None:
    d = date(year, month, day)
    h1 = compute_idempotency_hash(account_ref, d, amount, narration, idx1)
    h2 = compute_idempotency_hash(account_ref, d, amount, narration, idx2)
    assert h1 != h2


# ── JSON serialization round-trip ──────────────────────────────────────────────


@given(amount=st.integers(min_value=-10**15, max_value=10**15))
def test_json_roundtrip_preserves_exact_value(amount: int) -> None:
    p = Paise(amount)
    s = money_to_json_str(p)
    result = json_str_to_paise(s)
    assert int(result) == int(p)


# ── largest_remainder invariant ────────────────────────────────────────────────


@given(
    total=st.integers(min_value=-10_000_000, max_value=10_000_000),
    weights=st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=20),
)
def test_largest_remainder_always_sums_to_total(total: int, weights: list[int]) -> None:
    # Skip if all weights are zero
    if all(w == 0 for w in weights):
        return
    parts = largest_remainder(total, weights)
    assert sum(parts) == total

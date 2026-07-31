"""Unit tests for largest_remainder and round_to_nearest_10."""
from __future__ import annotations

import pytest

from core.hashing.rounding import largest_remainder, round_to_nearest_10


# ── largest_remainder ──────────────────────────────────────────────────────────


def test_largest_remainder_sums_to_total() -> None:
    parts = largest_remainder(1000, [1, 1, 1])
    assert sum(parts) == 1000


def test_largest_remainder_equal_weights() -> None:
    # 100 split 3 ways: [34, 33, 33] or similar — must sum to 100
    parts = largest_remainder(100, [1, 1, 1])
    assert sum(parts) == 100
    assert len(parts) == 3


def test_largest_remainder_proportional() -> None:
    # 60 split [3, 1]: [45, 15]
    parts = largest_remainder(60, [3, 1])
    assert sum(parts) == 60
    assert parts[0] == 45
    assert parts[1] == 15


def test_largest_remainder_single_weight() -> None:
    parts = largest_remainder(999, [1])
    assert parts == [999]


def test_largest_remainder_zero_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        largest_remainder(100, [0, 0])


def test_largest_remainder_empty_weights() -> None:
    assert largest_remainder(100, []) == []


def test_largest_remainder_negative_total() -> None:
    parts = largest_remainder(-100, [1, 1])
    assert sum(parts) == -100


# ── round_to_nearest_10 ────────────────────────────────────────────────────────


def test_round_to_nearest_10_exact() -> None:
    assert round_to_nearest_10(100) == 100


def test_round_to_nearest_10_rounds_down() -> None:
    assert round_to_nearest_10(104) == 100


def test_round_to_nearest_10_rounds_up_at_5() -> None:
    assert round_to_nearest_10(105) == 110


def test_round_to_nearest_10_rounds_up() -> None:
    assert round_to_nearest_10(108) == 110


def test_round_to_nearest_10_large_amount() -> None:
    # ₹10,000 = 1,000,000 paise
    assert round_to_nearest_10(1_000_003) == 1_000_000
    assert round_to_nearest_10(1_000_007) == 1_000_010

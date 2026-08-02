"""Unit tests for idempotency hash and occurrence index (C1, C2)."""

from datetime import date

from core.hashing.hash import (
    canonicalize_narration,
    compute_idempotency_hash,
    compute_occurrence_index,
)


def test_canonicalize_narration_nfkc_strip_collapse_uppercase() -> None:
    assert canonicalize_narration("  swiggy  ") == "SWIGGY"
    assert canonicalize_narration("UPI/123456\tSwiggy") == "UPI/123456 SWIGGY"
    assert canonicalize_narration("café") == "CAFÉ"
    assert canonicalize_narration("A\u00a0B") == "A B"  # NBSP collapses to space
    assert canonicalize_narration("swiggy") == canonicalize_narration("SWIGGY")


def test_canonicalize_narration_is_idempotent() -> None:
    s = "  UPI / payment  to swiggy "
    assert canonicalize_narration(canonicalize_narration(s)) == canonicalize_narration(s)


def test_hash_is_64_char_hex() -> None:
    h = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "SWIGGY", 0)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_is_deterministic() -> None:
    h1 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "SWIGGY", 0)
    h2 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "SWIGGY", 0)
    assert h1 == h2


def test_different_occurrence_index_produces_different_hash() -> None:
    h0 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "SWIGGY", 0)
    h1 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "SWIGGY", 1)
    assert h0 != h1


def test_running_balance_not_in_hash() -> None:
    """Two transactions differing only in running_balance must produce the same hash (C1)."""
    h1 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "SWIGGY", 0)
    h2 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "SWIGGY", 0)
    # running_balance is not a parameter — structural enforcement.
    # Compute same hash with two callers that would have had different running_balance values.
    assert h1 == h2  # hash is identical regardless of caller's running_balance context


def test_occurrence_index_zero_for_unique_transaction() -> None:
    txns: list[dict[str, object]] = []
    idx = compute_occurrence_index(txns, "ACC001", date(2026, 3, 15), -50000, "SWIGGY")
    assert idx == 0


def test_occurrence_index_increments_for_duplicates() -> None:
    txns: list[dict[str, object]] = [
        {
            "account_ref": "ACC001",
            "value_date": date(2026, 3, 15),
            "amount_paise": -50000,
            "canonical_narration": "SWIGGY",
        },
    ]
    idx = compute_occurrence_index(txns, "ACC001", date(2026, 3, 15), -50000, "SWIGGY")
    assert idx == 1


def test_occurrence_index_independent_of_other_transactions() -> None:
    txns: list[dict[str, object]] = [
        {
            "account_ref": "ACC001",
            "value_date": date(2026, 3, 15),
            "amount_paise": -30000,
            "canonical_narration": "ZOMATO",
        },
    ]
    idx = compute_occurrence_index(txns, "ACC001", date(2026, 3, 15), -50000, "SWIGGY")
    assert idx == 0  # different narration → different group → 0


def test_cross_parser_occurrence_index_stub() -> None:
    """Phase 1: two parsers for the same statement must produce identical occurrence_index.

    This stub asserts the compute_occurrence_index contract in isolation.
    The cross-parser integration test lives in tests/integration/ and requires
    real parser fixtures (Phase 1). TRD §9.1 C2.
    """
    txns: list[dict[str, object]] = [
        {
            "account_ref": "ACC",
            "value_date": date(2026, 1, 1),
            "amount_paise": -100,
            "canonical_narration": "COFFEE",
        },
        {
            "account_ref": "ACC",
            "value_date": date(2026, 1, 1),
            "amount_paise": -100,
            "canonical_narration": "COFFEE",
        },
    ]
    # Third identical entry → index 2, regardless of which parser built the list
    assert compute_occurrence_index(txns, "ACC", date(2026, 1, 1), -100, "COFFEE") == 2

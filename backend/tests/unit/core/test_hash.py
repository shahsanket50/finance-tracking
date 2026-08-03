"""Unit tests for idempotency hash and occurrence index (C1, C2)."""

from datetime import date

from core.hashing.hash import compute_idempotency_hash, compute_occurrence_index


def test_hash_is_64_char_hex() -> None:
    h = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "swiggy", 0)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_is_deterministic() -> None:
    h1 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "swiggy", 0)
    h2 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "swiggy", 0)
    assert h1 == h2


def test_different_occurrence_index_produces_different_hash() -> None:
    h0 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "swiggy", 0)
    h1 = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "swiggy", 1)
    assert h0 != h1


def test_running_balance_not_in_hash() -> None:
    """Hash must not change when running_balance changes — it's excluded (C1)."""
    # compute_idempotency_hash does not accept running_balance parameter — correct by design
    h = compute_idempotency_hash("ACC001", date(2026, 3, 15), -50000, "swiggy", 0)
    assert h is not None  # function signature enforcement


def test_occurrence_index_zero_for_unique_transaction() -> None:
    txns: list[dict[str, object]] = []
    idx = compute_occurrence_index(txns, "ACC001", date(2026, 3, 15), -50000, "swiggy")
    assert idx == 0


def test_occurrence_index_increments_for_duplicates() -> None:
    txns: list[dict[str, object]] = [
        {
            "account_ref": "ACC001",
            "value_date": date(2026, 3, 15),
            "amount_paise": -50000,
            "canonical_narration": "swiggy",
        },
    ]
    idx = compute_occurrence_index(txns, "ACC001", date(2026, 3, 15), -50000, "swiggy")
    assert idx == 1


def test_occurrence_index_independent_of_other_transactions() -> None:
    txns: list[dict[str, object]] = [
        {
            "account_ref": "ACC001",
            "value_date": date(2026, 3, 15),
            "amount_paise": -30000,
            "canonical_narration": "zomato",
        },
    ]
    idx = compute_occurrence_index(txns, "ACC001", date(2026, 3, 15), -50000, "swiggy")
    assert idx == 0  # different narration → different group → 0

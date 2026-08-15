"""Unit tests for build_audit_view (PRD §15 Level B seen/counted ledger)."""

from typing import cast

from processing.resolver.audit import build_audit_view


def _state(
    transactions: list[dict[str, object]] | None = None,
    excluded_hashes: list[str] | None = None,
    exclusion_reasons: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "transactions": transactions or [],
        "excluded_hashes": excluded_hashes or [],
        "exclusion_reasons": exclusion_reasons or {},
        "totals": {"income_paise": 0, "expense_paise": 0, "excluded_count": 0},
    }


def test_empty_state() -> None:
    result = build_audit_view(_state())
    assert result["total_seen"] == 0
    assert result["total_counted"] == 0
    assert result["total_excluded"] == 0
    assert result["entries"] == []


def test_one_counted_transaction() -> None:
    txn: dict[str, object] = {
        "idempotency_hash": "aaa",
        "amount_paise": -10000,
        "value_date": "2026-01-01",
        "account_ref": "HDFC_SAVINGS",
        "transaction_type": "expense",
    }
    result = build_audit_view(_state(transactions=[txn]))
    assert result["total_seen"] == 1
    assert result["total_counted"] == 1
    assert result["total_excluded"] == 0
    entries = cast(list[dict[str, object]], result["entries"])
    assert entries[0]["is_counted"] is True
    assert entries[0]["exclusion_reason"] is None


def test_one_excluded_internal_transfer() -> None:
    h = "bbb"
    txn: dict[str, object] = {
        "idempotency_hash": h,
        "amount_paise": -50000,
        "value_date": "2026-01-05",
        "account_ref": "HDFC_SAVINGS",
        "transaction_type": "expense",
    }
    result = build_audit_view(
        _state(
            transactions=[txn],
            excluded_hashes=[h],
            exclusion_reasons={h: "internal_transfer"},
        )
    )
    assert result["total_seen"] == 1
    assert result["total_counted"] == 0
    assert result["total_excluded"] == 1
    entries = cast(list[dict[str, object]], result["entries"])
    assert entries[0]["is_counted"] is False
    assert entries[0]["exclusion_reason"] == "internal_transfer"


def test_one_excluded_cc_payment_one_counted() -> None:
    h_excluded = "ccc"
    h_counted = "ddd"
    transactions: list[dict[str, object]] = [
        {
            "idempotency_hash": h_excluded,
            "amount_paise": -30000,
            "value_date": "2026-01-10",
            "account_ref": "HDFC_SAVINGS",
            "transaction_type": "expense",
        },
        {
            "idempotency_hash": h_counted,
            "amount_paise": -5000,
            "value_date": "2026-01-11",
            "account_ref": "HDFC_SAVINGS",
            "transaction_type": "expense",
        },
    ]
    result = build_audit_view(
        _state(
            transactions=transactions,
            excluded_hashes=[h_excluded],
            exclusion_reasons={h_excluded: "cc_payment"},
        )
    )
    assert result["total_counted"] == 1
    assert result["total_excluded"] == 1


def test_entries_sorted_by_value_date() -> None:
    transactions: list[dict[str, object]] = [
        {
            "idempotency_hash": "z1",
            "amount_paise": -100,
            "value_date": "2026-03-01",
            "account_ref": "X",
            "transaction_type": "expense",
        },
        {
            "idempotency_hash": "z2",
            "amount_paise": -200,
            "value_date": "2026-01-01",
            "account_ref": "X",
            "transaction_type": "expense",
        },
        {
            "idempotency_hash": "z3",
            "amount_paise": -300,
            "value_date": "2026-02-15",
            "account_ref": "X",
            "transaction_type": "expense",
        },
    ]
    result = build_audit_view(_state(transactions=transactions))
    entries = cast(list[dict[str, object]], result["entries"])
    dates = [str(e["value_date"]) for e in entries]
    assert dates == sorted(dates)


def test_all_four_exclusion_reason_values() -> None:
    reasons_map: dict[str, str] = {
        "h1": "internal_transfer",
        "h2": "cc_payment",
        "h3": "fd_booking",
        "h4": "reversal",
    }
    transactions: list[dict[str, object]] = [
        {
            "idempotency_hash": h,
            "amount_paise": -1000,
            "value_date": "2026-01-01",
            "account_ref": "X",
            "transaction_type": "expense",
        }
        for h in reasons_map
    ]
    result = build_audit_view(
        _state(
            transactions=transactions,
            excluded_hashes=list(reasons_map.keys()),
            exclusion_reasons=reasons_map,
        )
    )
    entries = cast(list[dict[str, object]], result["entries"])
    returned_reasons = {str(e["idempotency_hash"]): e["exclusion_reason"] for e in entries}
    for h, expected_reason in reasons_map.items():
        assert returned_reasons[h] == expected_reason


def test_backwards_compat_no_exclusion_reasons_key() -> None:
    """State without exclusion_reasons key should not raise (backwards compat)."""
    state: dict[str, object] = {
        "transactions": [
            {
                "idempotency_hash": "eee",
                "amount_paise": -1000,
                "value_date": "2026-01-01",
                "account_ref": "X",
                "transaction_type": "expense",
            }
        ],
        "excluded_hashes": [],
        "totals": {"income_paise": 0, "expense_paise": 0, "excluded_count": 0},
        # Note: no "exclusion_reasons" key
    }
    result = build_audit_view(state)
    assert result["total_seen"] == 1
    entries = cast(list[dict[str, object]], result["entries"])
    assert entries[0]["exclusion_reason"] is None


def test_duplicate_resolver_event_does_not_inflate_total_excluded() -> None:
    """Item 3: duplicate resolver events add duplicates to excluded_hashes (list),
    but total_excluded derives from set-based is_counted — no double-counting.

    Scenario: same MarkedInternalTransfer pair appended twice produces
    excluded_hashes = [h1, h2, h1, h2]. excluded_set = {h1, h2} (deduplicated).
    total_excluded must be 2 (the number of affected transactions), not 4.
    """
    h1, h2 = "pair_debit_hash", "pair_credit_hash"
    transactions: list[dict[str, object]] = [
        {
            "idempotency_hash": h1,
            "amount_paise": -50000,
            "value_date": "2026-01-01",
            "account_ref": "HDFC_SAVINGS",
            "transaction_type": "expense",
        },
        {
            "idempotency_hash": h2,
            "amount_paise": 50000,
            "value_date": "2026-01-02",
            "account_ref": "SBI_SAVINGS",
            "transaction_type": "income",
        },
    ]
    # Simulate duplicate resolver event: each hash appears twice in excluded_hashes
    result = build_audit_view(
        _state(
            transactions=transactions,
            excluded_hashes=[h1, h2, h1, h2],
            exclusion_reasons={h1: "internal_transfer", h2: "internal_transfer"},
        )
    )
    assert result["total_seen"] == 2
    assert result["total_counted"] == 0
    assert result["total_excluded"] == 2  # not 4 — derived from transactions, not list length
    entries = cast(list[dict[str, object]], result["entries"])
    assert all(e["is_counted"] is False for e in entries)

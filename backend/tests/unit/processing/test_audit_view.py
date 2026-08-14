"""Unit tests for build_audit_view (PRD §15 Level B seen/counted ledger)."""

import pytest
from processing.resolver.audit import build_audit_view


def _state(transactions=None, excluded_hashes=None, exclusion_reasons=None):
    return {
        "transactions": transactions or [],
        "excluded_hashes": excluded_hashes or [],
        "exclusion_reasons": exclusion_reasons or {},
        "totals": {"income_paise": 0, "expense_paise": 0, "excluded_count": 0},
    }


def test_empty_state():
    result = build_audit_view(_state())
    assert result["total_seen"] == 0
    assert result["total_counted"] == 0
    assert result["total_excluded"] == 0
    assert result["entries"] == []


def test_one_counted_transaction():
    txn = {
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
    entry = result["entries"][0]
    assert entry["is_counted"] is True
    assert entry["exclusion_reason"] is None


def test_one_excluded_internal_transfer():
    h = "bbb"
    txn = {
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
    entry = result["entries"][0]
    assert entry["is_counted"] is False
    assert entry["exclusion_reason"] == "internal_transfer"


def test_one_excluded_cc_payment_one_counted():
    h_excluded = "ccc"
    h_counted = "ddd"
    transactions = [
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


def test_entries_sorted_by_value_date():
    transactions = [
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
    dates = [e["value_date"] for e in result["entries"]]
    assert dates == sorted(dates)


def test_all_four_exclusion_reason_values():
    reasons_map = {
        "h1": "internal_transfer",
        "h2": "cc_payment",
        "h3": "fd_booking",
        "h4": "reversal",
    }
    transactions = [
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
    returned_reasons = {e["idempotency_hash"]: e["exclusion_reason"] for e in result["entries"]}
    for h, expected_reason in reasons_map.items():
        assert returned_reasons[h] == expected_reason


def test_backwards_compat_no_exclusion_reasons_key():
    """State without exclusion_reasons key should not raise (backwards compat)."""
    state = {
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
    assert result["entries"][0]["exclusion_reason"] is None

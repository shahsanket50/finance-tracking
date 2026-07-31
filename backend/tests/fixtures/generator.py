"""Synthetic bank statement fixture generator.

All test data is synthetic — real bank statements must never be committed.
Generators produce statements where opening + credits - debits == closing exactly,
which exercises Invariant I2 (balance check).

Usage:
    from tests.fixtures.generator import generate_statement
    stmt = generate_statement(
        bank="hdfc_savings",
        account_ref="HDFC_SAVINGS_1234",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        transactions=[
            {
                "narration": "Salary credit",
                "amount_paise": 500_000_00,
                "value_date": date(2026, 1, 1),
                "type": "income",
            },
            {
                "narration": "Swiggy food order",
                "amount_paise": -50000,
                "value_date": date(2026, 1, 5),
                "type": "expense",
            },
        ],
        seed=42,
    )
    # stmt["balance_check"] == "pass" guaranteed
"""

from __future__ import annotations

from datetime import date

from core.hashing.hash import compute_idempotency_hash, compute_occurrence_index

# Registry of bank templates
_TEMPLATES: dict[str, object] = {}


def register_template(name: str, template: object) -> None:
    """Register a bank statement template by name."""
    _TEMPLATES[name] = template


def generate_statement(
    bank: str,
    account_ref: str,
    period_start: date,
    period_end: date,
    transactions: list[dict[str, object]],
    seed: int = 42,
) -> dict[str, object]:
    """Generate a synthetic bank statement dict.

    Computes occurrence_index and idempotency_hash per transaction.
    Computes opening/closing balance so balance_check passes (I2).

    Args:
        bank: Template name (e.g. "hdfc_savings", "sbi_savings")
        account_ref: Unique account identifier (e.g. "HDFC_SAVINGS_1234")
        period_start: Statement period start date
        period_end: Statement period end date
        transactions: List of dicts with keys:
            - narration: str
            - amount_paise: int (positive = credit, negative = debit)
            - value_date: date
            - type: str ("income" | "expense" | "transfer" | "investment")
        seed: Random seed (for reproducibility)

    Returns:
        Statement dict with:
            - bank: str
            - account_ref: str
            - period_start: date
            - period_end: date
            - opening_balance_paise: int
            - closing_balance_paise: int
            - transactions: list of enriched transaction dicts
            - balance_check: "pass"  # always pass for valid synthetic data
            - credits_total_paise: int
            - debits_total_paise: int  # sum of absolute debit amounts (positive)
    """
    if bank not in _TEMPLATES:
        raise ValueError(f"Unknown bank template: {bank!r}. Registered: {list(_TEMPLATES)}")

    # Enrich transactions: add occurrence_index and idempotency_hash
    enriched: list[dict[str, object]] = []
    for txn in transactions:
        narration = str(txn.get("narration", ""))
        normalized_narration = narration.lower().strip()
        amount_paise_obj = txn.get("amount_paise", 0)
        if not isinstance(amount_paise_obj, int):
            raise ValueError(f"amount_paise must be an int, got {type(amount_paise_obj)}")
        amount_paise = amount_paise_obj
        value_date = txn.get("value_date")
        if not isinstance(value_date, date):
            raise ValueError(f"value_date must be a date, got {type(value_date)}")

        occurrence_index = compute_occurrence_index(
            enriched, account_ref, value_date, amount_paise, normalized_narration
        )
        idempotency_hash = compute_idempotency_hash(
            account_ref, value_date, amount_paise, normalized_narration, occurrence_index
        )

        enriched.append(
            {
                **txn,
                "normalized_narration": normalized_narration,
                "occurrence_index": occurrence_index,
                "idempotency_hash": idempotency_hash,
                "account_ref": account_ref,
            }
        )

    # Compute balance: use seed as deterministic opening balance
    # Opening balance is seed * 100 paise (so seed=42 → ₹42 opening)
    opening_balance_paise = seed * 100

    credits_total = 0
    debits_total = 0
    for t in enriched:
        amount = t.get("amount_paise", 0)
        if not isinstance(amount, int):
            raise ValueError(f"amount_paise must be an int, got {type(amount)}")
        if amount > 0:
            credits_total += amount
        elif amount < 0:
            debits_total += amount

    # closing = opening + credits + debits (debits are negative)
    closing_balance_paise = opening_balance_paise + credits_total + debits_total

    # Verify balance check (I2): opening + credits - debits == closing
    # credits is already positive, debits is already negative, so:
    # opening + credits + debits = closing ✓
    assert opening_balance_paise + credits_total + debits_total == closing_balance_paise

    return {
        "bank": bank,
        "account_ref": account_ref,
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance_paise": opening_balance_paise,
        "closing_balance_paise": closing_balance_paise,
        "credits_total_paise": credits_total,
        "debits_total_paise": abs(debits_total),  # positive for readability
        "transactions": enriched,
        "balance_check": "pass",  # guaranteed by construction
        "seed": seed,
    }

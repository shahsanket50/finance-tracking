"""Slice Savings account statement template (Northeast Small Finance Bank).

Registers the 'slice_savings' bank template with the generator.
Slice statements are text-based (not table), amounts as "₹X.XX".
Direction is determined from DETAILS field keywords (Credit/Debit).
"""

from __future__ import annotations

from tests.fixtures.generator import register_template

SLICE_SAVINGS_TEMPLATE = {
    "bank_display_name": "Slice Small Finance Bank Savings Account",
    "account_type": "savings",
    "statement_format": "slice_v1",
    "narration_pattern": "{description}",
}

register_template("slice_savings", SLICE_SAVINGS_TEMPLATE)

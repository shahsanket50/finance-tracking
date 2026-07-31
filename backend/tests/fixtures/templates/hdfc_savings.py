"""HDFC Savings account statement template.

Registers the 'hdfc_savings' bank template with the generator.
HDFC statement format: narration is cleaned of branch codes and ref numbers.
"""

from __future__ import annotations

from tests.fixtures.generator import register_template

HDFC_SAVINGS_TEMPLATE = {
    "bank_display_name": "HDFC Bank Savings Account",
    "account_type": "savings",
    "statement_format": "hdfc_v1",
    "narration_pattern": "{description}",  # template placeholder
}

register_template("hdfc_savings", HDFC_SAVINGS_TEMPLATE)

"""SBI Savings account statement template.

Registers the 'sbi_savings' bank template with the generator.
"""

from __future__ import annotations

from tests.fixtures.generator import register_template

SBI_SAVINGS_TEMPLATE = {
    "bank_display_name": "SBI Savings Account",
    "account_type": "savings",
    "statement_format": "sbi_v1",
    "narration_pattern": "{description}",
}

register_template("sbi_savings", SBI_SAVINGS_TEMPLATE)

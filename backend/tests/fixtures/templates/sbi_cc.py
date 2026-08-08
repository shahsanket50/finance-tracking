"""SBI Credit Card statement template.

Registers the 'sbi_cc' bank template with the generator.
Column layout: Date | Transaction Details | Amount
Amount format: "1,234.56 Cr" / "567.89 Dr"
"""

from __future__ import annotations

from tests.fixtures.generator import register_template

SBI_CC_TEMPLATE = {
    "bank_display_name": "State Bank of India Credit Card",
    "account_type": "credit_card",
    "statement_format": "sbi_cc_v1",
    "columns": ["Date", "Transaction Details", "Amount"],
    "amount_format": "cr_dr_suffix",
    "has_per_row_balance": False,
    "opening_label": "Previous Balance",
    "closing_label": "New Balance",
}

register_template("sbi_cc", SBI_CC_TEMPLATE)

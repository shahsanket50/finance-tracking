"""HDFC Swiggy Credit Card statement template.

Registers the 'hdfc_cc' bank template with the generator.
Column layout: DATE & TIME | TRANSACTION | DESCRIPTION | AMOUNT | PI
Amount format: "1,234.56 Cr" / "567.89 Dr"
"""

from __future__ import annotations

from tests.fixtures.generator import register_template

HDFC_CC_TEMPLATE = {
    "bank_display_name": "HDFC Bank Swiggy Credit Card",
    "account_type": "credit_card",
    "statement_format": "hdfc_cc_v1",
    "columns": ["DATE & TIME", "TRANSACTION", "DESCRIPTION", "AMOUNT", "PI"],
    "amount_format": "cr_dr_suffix",  # "1,234.56 Cr" / "567.89 Dr"
    "has_per_row_balance": False,
    "opening_label": "Previous Balance",
    "closing_label": "New Balance",
}

register_template("hdfc_cc", HDFC_CC_TEMPLATE)

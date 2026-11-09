"""Keyword/pattern rule engine for merchant normalization. Implements PRD §4 Step 4."""

from __future__ import annotations


def match_rule(narration: str) -> tuple[str, str] | None:
    """Return (canonical_name, rule_id) if a rule matches, else None.

    Rules are evaluated in order; first match wins.
    Matching is case-insensitive on the upper-cased narration.
    """
    upper = narration.upper()

    if "SWIGGY" in upper:
        return ("Swiggy", "rule:swiggy")
    if "ZOMATO" in upper:
        return ("Zomato", "rule:zomato")
    if "AMAZON" in upper:
        return ("Amazon", "rule:amazon")
    if "ATM" in upper:
        return ("ATM Withdrawal", "rule:atm")
    if "NEFT CR" in upper or "NEFT-CR" in upper:
        return ("NEFT Credit", "rule:neft_credit")
    if "IMPS" in upper:
        return ("IMPS Transfer", "rule:imps")

    return None

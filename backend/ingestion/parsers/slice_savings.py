"""Slice Savings (Northeast Small Finance Bank) statement parser.

Implements PRD §14.2, TRD §9.1.
Extraction method: page.extract_text() — no table structure, fixed-column text.
Handles both ₹ (real PDF) and Rs. (synthetic PDF fixture) currency prefixes.
"""

from __future__ import annotations

import re
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

import pdfplumber

from core.hashing.hash import (
    canonicalize_narration,
    compute_idempotency_hash,
    compute_occurrence_index,
)
from ingestion.parsers.base import AbstractParser, ParsedStatement, ParsedTransaction

# Matches a transaction line:
#   DATE  DETAILS  REF_NO  AMOUNT  BALANCE
#
# DATE: "DD Mon 'YY"
# DETAILS: anything (non-greedy)
# REF_NO: alphanumeric token (letters + digits, no spaces) — real PDFs use numeric strings
#         but synthetic fixture uses "REFxxxxxxxxx"-style alphanumeric refs
# AMOUNT: Rs.X,XXX.XX or ₹X,XXX.XX
# BALANCE: same format
_TXN_RE = re.compile(
    r"(\d{1,2} \w{3} '\d{2})\s+"  # date: "DD Mon 'YY"
    r"(.+?)\s+"  # details (non-greedy)
    r"(\S+)\s+"  # ref number (any non-space token)
    r"(?:₹|Rs\.)\s*([\d,]+\.?\d*)\s+"  # amount
    r"(?:₹|Rs\.)\s*([\d,]+\.?\d*)"  # balance
)

# Matches the period header line: "Statement Period: DD Mon 'YY - DD Mon 'YY"
_PERIOD_RE = re.compile(r"Statement Period:\s*(\d{1,2} \w{3} '\d{2})\s*-\s*(\d{1,2} \w{3} '\d{2})")

# Matches the opening balance line: "Opening balance Rs.X,XXX.XX" or "Opening balance ₹X,XXX.XX"
_OPENING_RE = re.compile(r"Opening balance\s+(?:₹|Rs\.)\s*([\d,]+\.?\d*)")

# Matches the closing balance line: "Closing balance Rs.X,XXX.XX" or "Closing balance ₹X,XXX.XX"
_CLOSING_RE = re.compile(r"Closing balance\s+(?:₹|Rs\.)\s*([\d,]+\.?\d*)")

# Matches the account number line: "Account Number : XXXXXXXXXXX"
_ACCOUNT_RE = re.compile(r"Account Number\s*:\s*(\S+)")


class SliceSavingsParser(AbstractParser):
    """Parser for Slice Savings (Northeast Small Finance Bank) PDF statements.

    Extraction strategy: page.extract_text() over all pages.
    Each transaction is on one line with columns: DATE | DETAILS | REF NO. | AMOUNT | BALANCE.
    Direction (credit/debit) is derived from keywords in the DETAILS field.
    """

    def can_parse(self, text: str) -> bool:
        """Return True if text contains 'slice small finance bank' (case-insensitive)."""
        return "slice small finance bank" in text.lower()

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement:  # type: ignore[name-defined]
        """Parse the Slice Savings PDF and return a ParsedStatement."""
        raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        account_ref = self._extract_account_ref(raw_text)
        period_start, period_end = self._extract_period(raw_text)
        opening_balance_paise = self._extract_opening_balance(raw_text)
        closing_balance_paise = self._extract_closing_balance(raw_text)

        transactions: list[ParsedTransaction] = []
        for line in raw_text.splitlines():
            txn = self._parse_transaction_line(line, account_ref, transactions)
            if txn is not None:
                transactions.append(txn)

        return ParsedStatement(
            bank="slice_savings",
            account_ref=account_ref,
            period_start=period_start,
            period_end=period_end,
            opening_balance_paise=opening_balance_paise,
            closing_balance_paise=closing_balance_paise,
            transactions=transactions,
            confidence=9000,
            raw_text=raw_text,
        )

    # ------------------------------------------------------------------ #
    # Header extraction
    # ------------------------------------------------------------------ #

    def _extract_account_ref(self, text: str) -> str:
        """Extract 'Account Number : XXXX' → 'SLICE_SAV_XXXX' (last 4 digits of account number)."""
        match = _ACCOUNT_RE.search(text)
        if not match:
            raise ValueError("Account number not found in Slice Savings statement")
        raw_account = match.group(1).strip()
        last4 = raw_account[-4:]
        return f"SLICE_SAV_{last4}"

    def _extract_period(self, text: str) -> tuple[date_type, date_type]:
        """Extract period from 'Statement Period: DD Mon 'YY - DD Mon 'YY'."""
        match = _PERIOD_RE.search(text)
        if not match:
            raise ValueError("Statement period not found in Slice Savings statement")
        start = self._parse_date(match.group(1))
        end = self._parse_date(match.group(2))
        return start, end

    def _extract_opening_balance(self, text: str) -> int:
        """Extract opening balance from 'Opening balance Rs.X,XXX.XX' or '₹X,XXX.XX'."""
        match = _OPENING_RE.search(text)
        if not match:
            raise ValueError("Opening balance not found in Slice Savings statement")
        return self._parse_paise(match.group(1))

    def _extract_closing_balance(self, text: str) -> int:
        """Extract closing balance from 'Closing balance Rs.X,XXX.XX' or '₹X,XXX.XX'."""
        match = _CLOSING_RE.search(text)
        if not match:
            raise ValueError("Closing balance not found in Slice Savings statement")
        return self._parse_paise(match.group(1))

    # ------------------------------------------------------------------ #
    # Transaction parsing
    # ------------------------------------------------------------------ #

    def _parse_transaction_line(
        self,
        line: str,
        account_ref: str,
        prior: list[ParsedTransaction],
    ) -> ParsedTransaction | None:
        """Try to parse a single text line as a transaction.

        Returns None if the line does not match the transaction pattern.
        Direction is determined from keywords in DETAILS:
          - "Credit" or "Cr." → positive paise
          - "Debit" or "Dr." → negative paise
        If neither keyword is found, returns None (not a transaction line).
        """
        match = _TXN_RE.search(line)
        if not match:
            return None

        date_str, details, _ref, amount_str, balance_str = match.groups()

        # Determine sign from details keywords
        details_lower = details.lower()
        if "credit" in details_lower or "cr." in details_lower:
            sign = 1
        elif "debit" in details_lower or "dr." in details_lower:
            sign = -1
        else:
            return None

        try:
            value_date = self._parse_date(date_str)
        except ValueError:
            return None

        amount_paise = sign * self._parse_paise(amount_str)
        running_balance_paise = self._parse_paise(balance_str)

        narration = re.sub(r"\s+", " ", details).strip()
        canonical = canonicalize_narration(narration)

        prior_dicts: list[dict[str, object]] = [
            {
                "account_ref": t.account_ref,
                "value_date": t.value_date,
                "amount_paise": t.amount_paise,
                "canonical_narration": t.canonical_narration,
            }
            for t in prior
        ]
        occ_idx = compute_occurrence_index(
            prior_dicts, account_ref, value_date, amount_paise, canonical
        )
        hash_val = compute_idempotency_hash(
            account_ref, value_date, amount_paise, canonical, occ_idx
        )

        return ParsedTransaction(
            account_ref=account_ref,
            value_date=value_date,
            amount_paise=amount_paise,
            narration=narration,
            canonical_narration=canonical,
            occurrence_index=occ_idx,
            idempotency_hash=hash_val,
            running_balance_paise=running_balance_paise,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_paise(amount_str: str) -> int:
        """Parse '13,081.2' or '1,234.56' → paise.

        Handles both 1 and 2 decimal places. Decimal multiplication ensures no float precision loss.
        """
        clean = amount_str.replace(",", "")
        return int(Decimal(clean) * 100)

    @staticmethod
    def _parse_date(date_str: str) -> date_type:
        """Parse "DD Mon 'YY" → date. Apostrophe-prefixed 2-digit year → 4-digit year.

        Example: "05 May '26" → date(2026, 5, 5).
        21st-century assumption: '26 → 2026.
        """
        expanded = date_str.replace("'", "20")
        return datetime.strptime(expanded, "%d %b %Y").date()

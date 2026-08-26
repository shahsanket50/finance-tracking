"""SBI Savings Bank statement parser. Implements PRD §14.2, TRD §9.1."""

from __future__ import annotations

import re
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

import pdfplumber

from core.events.types import ACCOUNT_TYPE_SAVINGS
from core.hashing.hash import (
    canonicalize_narration,
    compute_idempotency_hash,
    compute_occurrence_index,
)
from ingestion.parsers.base import AbstractParser, ParsedStatement, ParsedTransaction


class SbiSavingsParser(AbstractParser):
    """Parser for SBI Savings Bank PDF statements.

    Extraction strategy:
    - Uses page.extract_text() for header fields (account_ref, period, opening balance).
    - Uses page.extract_tables() for transaction rows — SBI Savings emits clean one-row-per-txn
      tables with columns: Txn Date | Value Date | Description | Ref No./Cheque No. |
      Debit | Credit | Balance
    """

    def can_parse(self, text: str) -> bool:
        """Return True if text contains 'account statement from' AND 'txn date'/'balance as on'.

        Both tokens are distinctive SBI Savings markers. HDFC Savings uses 'StatementFrom'
        and 'WithdrawalAmt' — neither appears in SBI Savings statements.
        """
        lower = text.lower()
        return "account statement from" in lower and (
            "txn date" in lower or "balance as on" in lower
        )

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement:  # type: ignore[name-defined]
        """Parse the SBI Savings PDF and return a ParsedStatement."""
        # 1. Extract all page text for header parsing and raw_text
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        # 2. Extract header fields from full text
        account_ref = self._extract_account_ref(full_text)
        period_start, period_end = self._extract_period(full_text)
        opening_balance_paise = self._extract_opening_balance(full_text)

        # 3. Extract transactions from tables across all pages
        transactions: list[ParsedTransaction] = []
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row is None or not any(row):
                        continue
                    cells = [str(c or "").strip() for c in row]
                    # Skip header rows
                    if cells[0].lower() in ("txn date", "date", ""):
                        continue
                    txn = self._build_transaction(cells, account_ref, transactions)
                    if txn:
                        transactions.append(txn)

        # 4. Closing balance = last transaction's running balance
        if not transactions:
            raise ValueError("No transactions found in SBI savings statement")
        last_rb = transactions[-1].running_balance_paise
        if last_rb is None:
            raise ValueError(
                "Last transaction has no running balance — cannot determine closing balance"
            )
        closing_balance_paise = last_rb

        return ParsedStatement(
            bank="sbi_savings",
            account_ref=account_ref,
            account_type=ACCOUNT_TYPE_SAVINGS,
            period_start=period_start,
            period_end=period_end,
            opening_balance_paise=opening_balance_paise,
            closing_balance_paise=closing_balance_paise,
            transactions=transactions,
            confidence=9000,
            raw_text=full_text,
        )

    # ------------------------------------------------------------------ #
    # Header extraction
    # ------------------------------------------------------------------ #

    def _extract_account_ref(self, text: str) -> str:
        """Extract account ref from 'Account Number : XXXXXXXXX' line."""
        match = re.search(r"Account Number\s*:\s*(\S+)", text)
        return match.group(1) if match else ""

    def _extract_period(self, text: str) -> tuple[date_type, date_type]:
        """Extract period from 'Account Statement from DD Mon YYYY to DD Mon YYYY'."""
        match = re.search(
            r"Account Statement from (\d{1,2} \w{3} \d{4}) to (\d{1,2} \w{3} \d{4})", text
        )
        if match:
            start = datetime.strptime(match.group(1).strip(), "%d %b %Y").date()
            end = datetime.strptime(match.group(2).strip(), "%d %b %Y").date()
            return start, end
        raise ValueError("Statement period not found in PDF text")

    def _extract_opening_balance(self, text: str) -> int:
        """Extract opening balance from 'Balance as on DD Mon YYYY : X,XXX.XX'."""
        match = re.search(r"Balance as on .+? : ([\d,]+\.?\d*)", text)
        if not match:
            raise ValueError("Opening balance not found in SBI savings statement text")
        return self._parse_paise(match.group(1))

    # ------------------------------------------------------------------ #
    # Transaction building
    # ------------------------------------------------------------------ #

    def _build_transaction(
        self,
        cells: list[str],
        account_ref: str,
        prior_transactions: list[ParsedTransaction],
    ) -> ParsedTransaction | None:
        """Build a ParsedTransaction from a table row (7 cells).

        cells[0] = Txn Date ("DD Mon\\nYYYY")
        cells[1] = Value Date ("DD Mon\\nYYYY")
        cells[2] = Description / narration
        cells[3] = Ref No./Cheque No. (skipped)
        cells[4] = Debit (empty string if credit)
        cells[5] = Credit (empty string if debit)
        cells[6] = Balance
        """
        if len(cells) < 7:
            return None

        debit_str = cells[4].strip()
        credit_str = cells[5].strip()

        # Skip rows with no amount — not a real transaction
        if not debit_str and not credit_str:
            return None

        # Parse value date (cells[1]) — may be "DD Mon\nYYYY" or "DD Mon YYYY"
        value_date_raw = cells[1].replace("\n", " ").strip()
        try:
            value_date = datetime.strptime(value_date_raw, "%d %b %Y").date()
        except ValueError:
            return None

        # Parse amount — debit → negative, credit → positive
        if credit_str:
            amount_paise = self._parse_paise(credit_str)
        else:
            amount_paise = -self._parse_paise(debit_str)

        # Parse running balance
        balance_str = cells[6].strip()
        running_balance_paise = self._parse_paise(balance_str) if balance_str else None

        narration = re.sub(r"\s+", " ", cells[2]).strip()
        if not narration:
            return None

        canonical = canonicalize_narration(narration)

        prior_dicts: list[dict[str, object]] = [
            {
                "account_ref": t.account_ref,
                "value_date": t.value_date,
                "amount_paise": t.amount_paise,
                "canonical_narration": t.canonical_narration,
            }
            for t in prior_transactions
        ]
        occ_idx = compute_occurrence_index(
            prior_dicts,
            account_ref,
            value_date,
            amount_paise,
            canonical,
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

    @staticmethod
    def _parse_paise(s: str) -> int:
        """Parse '1,234.56' → 123456 paise. Strip commas, Decimal × 100."""
        return int(Decimal(s.replace(",", "")) * 100)

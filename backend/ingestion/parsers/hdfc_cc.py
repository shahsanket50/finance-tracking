"""HDFC Swiggy Credit Card statement parser. Implements PRD §14.2, TRD §9.1."""

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
from core.events.types import ACCOUNT_TYPE_CREDIT_CARD
from ingestion.parsers.base import AbstractParser, ParsedStatement, ParsedTransaction


class HdfcCcParser(AbstractParser):
    """Parser for HDFC Swiggy Credit Card PDF statements."""

    def can_parse(self, text: str) -> bool:
        """Return True iff text contains both 'HDFC Bank' and 'Swiggy' (case-insensitive)."""
        lower = text.lower()
        return "hdfc bank" in lower and "swiggy" in lower

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement:  # type: ignore[name-defined]
        """Parse the HDFC Swiggy CC PDF and return a ParsedStatement."""
        # 1. Extract all text from all pages
        raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        # 2. Parse header / footer fields
        account_ref = self._extract_account_ref(raw_text)
        period_start, period_end = self._extract_period(raw_text)
        opening_balance_paise = self._extract_opening_balance(raw_text)
        closing_balance_paise = self._extract_closing_balance(raw_text)

        # 3. Extract transaction rows from each page
        transactions: list[ParsedTransaction] = []
        for page in pdf.pages:
            rows = self._extract_rows(page)
            for row in rows:
                txn = self._build_transaction(row, account_ref, transactions)
                if txn is not None:
                    transactions.append(txn)

        return ParsedStatement(
            bank="hdfc_cc",
            account_ref=account_ref,
            account_type=ACCOUNT_TYPE_CREDIT_CARD,
            period_start=period_start,
            period_end=period_end,
            opening_balance_paise=opening_balance_paise,
            closing_balance_paise=closing_balance_paise,
            transactions=transactions,
            confidence=9000,
            raw_text=raw_text,
        )

    # ------------------------------------------------------------------ #
    # Header / footer extraction
    # ------------------------------------------------------------------ #

    def _extract_account_ref(self, text: str) -> str:
        """Extract account ref from 'Account: HDFC_CC_4321' line."""
        match = re.search(r"Account:\s*(\S+)", text)
        return match.group(1) if match else ""

    def _extract_period(self, text: str) -> tuple[date_type, date_type]:
        """Extract period from 'Statement Period: DD/MM/YYYY to DD/MM/YYYY'."""
        match = re.search(
            r"Statement Period:\s*(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})",
            text,
        )
        if match:
            start = datetime.strptime(match.group(1), "%d/%m/%Y").date()
            end = datetime.strptime(match.group(2), "%d/%m/%Y").date()
            return start, end
        raise ValueError("Statement period not found in PDF text")

    def _extract_opening_balance(self, text: str) -> int:
        """Extract 'Previous Balance: X,XXX.XX Cr/Dr' → paise."""
        match = re.search(
            r"Previous Balance:\s*([\d,]+\.\d{2}\s+(?:Cr|Dr))",
            text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("Could not locate opening balance in HDFC CC statement header")
        return self._parse_amount(match.group(1))

    def _extract_closing_balance(self, text: str) -> int:
        """Extract 'New Balance: X,XXX.XX Cr/Dr' → paise."""
        match = re.search(
            r"New Balance:\s*([\d,]+\.\d{2}\s+(?:Cr|Dr))",
            text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("Could not locate closing balance in HDFC CC statement header")
        return self._parse_amount(match.group(1))

    # ------------------------------------------------------------------ #
    # Table extraction
    # ------------------------------------------------------------------ #

    def _extract_rows(self, page: pdfplumber.page.PageBase) -> list[list[str]]:  # type: ignore[name-defined]
        """Extract transaction rows from a page, skipping header and empty rows."""
        table = page.extract_table()
        if not table:
            return []
        rows: list[list[str]] = []
        for row in table:
            if row is None:
                continue
            cells = [str(c or "").strip() for c in row]
            # Skip header row
            if cells and cells[0].upper() in ("DATE & TIME", "DATE"):
                continue
            # Skip fully empty rows
            if not any(cells):
                continue
            rows.append(cells)
        return rows

    def _build_transaction(
        self,
        row: list[str],
        account_ref: str,
        prior_transactions: list[ParsedTransaction],
    ) -> ParsedTransaction | None:
        """Build a ParsedTransaction from a table row.

        Columns: DATE & TIME | TRANSACTION | DESCRIPTION | AMOUNT | PI
        """
        if len(row) < 4:
            return None

        date_str = row[0].strip()
        # Use DESCRIPTION (col 2) as narration; fall back to TRANSACTION (col 1)
        raw_description = row[2].strip() if len(row) > 2 else ""
        raw_transaction = row[1].strip() if len(row) > 1 else ""
        amount_str = row[3].strip()

        if not date_str or not amount_str:
            return None

        try:
            value_date = self._parse_date(date_str)
            amount_paise = self._parse_amount(amount_str)
        except (ValueError, IndexError, ArithmeticError):
            return None

        # Normalise whitespace in narration — pdfplumber can produce extra spaces
        narration_raw = raw_description if raw_description else raw_transaction
        narration = re.sub(r"\s+", " ", narration_raw).strip()

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
            running_balance_paise=None,
        )

    # ------------------------------------------------------------------ #
    # Scalar parsers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_amount(amount_str: str) -> int:
        """Parse '1,234.56 Cr' → positive paise, '180.00 Dr' → negative paise.

        Steps:
        1. Strip whitespace
        2. Split on last space → (numeric_part, suffix)
        3. Remove commas from numeric_part
        4. Convert to Decimal, multiply by 100, round to int
        5. Negate if suffix is 'Dr'
        """
        s = amount_str.strip()
        parts = s.rsplit(" ", 1)
        numeric = parts[0].replace(",", "")
        suffix = parts[1].upper() if len(parts) > 1 else "CR"
        paise = int(Decimal(numeric) * 100)
        return paise if suffix == "CR" else -paise

    @staticmethod
    def _parse_date(date_str: str) -> date_type:
        """Parse 'DD/MM/YYYY HH:MM:SS' or 'DD/MM/YYYY' → date."""
        s = date_str.strip().split()[0]
        return datetime.strptime(s, "%d/%m/%Y").date()

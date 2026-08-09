"""HDFC Savings Bank statement parser. Implements PRD §14.2, TRD §9.1."""

from __future__ import annotations

import re
from collections import defaultdict
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

# Matches a DD/MM/YY date (two-digit year, used in transaction rows).
_ROW_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")

# Matches a decimal amount like 1,234.56 or 50,000.00
_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}$")

# Matches synthetic reference numbers (e.g. REF001) — skipped in narration
_REF_RE = re.compile(r"^REF\d+$")


class HdfcSavingsParser(AbstractParser):
    """Parser for HDFC Savings Bank PDF statements.

    Extraction strategy:
    - Uses page.extract_text() for header fields (account_ref, period).
    - Uses page.extract_words() for transaction rows to classify amounts by
      x-position (withdrawal vs deposit column), since extract_text() collapses
      all inter-column whitespace to a single space.
    """

    def can_parse(self, text: str) -> bool:
        """Return True if text contains 'statementfrom' AND 'withdrawalamt' (case-insensitive).

        These two tokens are the definitive markers for an HDFC Savings statement.
        HDFC CC statements contain neither; SBI CC statements contain neither.
        """
        lower = text.lower()
        return "statementfrom" in lower and "withdrawalamt" in lower

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement:  # type: ignore[name-defined]
        """Parse the HDFC Savings PDF and return a ParsedStatement."""
        # 1. Extract all text for header fields and raw_text
        raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        # 2. Extract header fields
        account_ref = self._extract_account_ref(raw_text)
        period_start, period_end = self._extract_period(raw_text)

        # 3. Extract column boundaries and transaction rows from each page
        transactions: list[ParsedTransaction] = []
        for page in pdf.pages:
            rows = self._extract_transaction_rows(page)
            for row in rows:
                txn = self._build_transaction(row, account_ref, transactions)
                if txn is not None:
                    transactions.append(txn)

        # 4. Derive opening and closing balances
        if transactions:
            first = transactions[0]
            opening_balance_paise = first.running_balance_paise - first.amount_paise  # type: ignore[operator]
            closing_balance_paise = transactions[-1].running_balance_paise or 0
        else:
            opening_balance_paise = 0
            closing_balance_paise = 0

        return ParsedStatement(
            bank="hdfc_savings",
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
    # Header extraction (uses extract_text output)
    # ------------------------------------------------------------------ #

    def _extract_account_ref(self, text: str) -> str:
        """Extract account ref from 'AccountNo : VALUE' line."""
        match = re.search(r"AccountNo\s*:\s*(\S+)", text)
        return match.group(1) if match else ""

    def _extract_period(self, text: str) -> tuple[date_type, date_type]:
        """Extract period from 'StatementFrom : DD/MM/YYYY To : DD/MM/YYYY'."""
        match = re.search(
            r"StatementFrom\s*:\s*(\d{2}/\d{2}/\d{4})\s+To\s*:\s*(\d{2}/\d{2}/\d{4})",
            text,
        )
        if match:
            start = datetime.strptime(match.group(1), "%d/%m/%Y").date()
            end = datetime.strptime(match.group(2), "%d/%m/%Y").date()
            return start, end
        raise ValueError("Statement period not found in PDF text")

    # ------------------------------------------------------------------ #
    # Transaction row extraction (uses extract_words for column detection)
    # ------------------------------------------------------------------ #

    def _extract_transaction_rows(
        self, page: pdfplumber.page.PageBase  # type: ignore[name-defined]
    ) -> list[dict[str, object]]:
        """Extract structured transaction rows from a page using extract_words.

        Word x-positions are used to classify amounts into withdrawal, deposit,
        and closing-balance columns.  This is necessary because extract_text()
        collapses all inter-column whitespace to a single space, making it
        impossible to distinguish an empty withdrawal column from an empty
        deposit column by spacing alone.
        """
        words = page.extract_words(x_tolerance=3, y_tolerance=3)
        if not words:
            return []

        # Group words by their vertical position (row)
        by_row: dict[int, list[dict[str, object]]] = defaultdict(list)
        for w in words:
            row_key = round(float(w["top"]))
            by_row[row_key].append(w)

        # Locate column x-boundaries from the header row
        wd_dep_boundary, dep_clos_boundary = self._detect_column_boundaries(by_row)

        rows: list[dict[str, object]] = []
        for row_key in sorted(by_row.keys()):
            row_words = by_row[row_key]
            first_text = str(row_words[0]["text"])
            if not _ROW_DATE_RE.match(first_text):
                continue

            row = self._parse_row_words(row_words, wd_dep_boundary, dep_clos_boundary)
            if row is not None:
                rows.append(row)

        return rows

    def _detect_column_boundaries(
        self,
        by_row: dict[int, list[dict[str, object]]],
    ) -> tuple[float, float]:
        """Return (wd_dep_boundary, dep_clos_boundary) x-thresholds from the header row.

        Falls back to empirically-derived defaults if the header row is absent.
        """
        wd_x: float | None = None
        dep_x: float | None = None
        clos_x: float | None = None

        for row_key in sorted(by_row.keys()):
            row_words = by_row[row_key]
            texts = [str(w["text"]) for w in row_words]
            if any("WithdrawalAmt" in t for t in texts):
                for w in row_words:
                    t = str(w["text"])
                    if "WithdrawalAmt" in t:
                        wd_x = float(w["x0"])
                    elif "DepositAmt" in t:
                        dep_x = float(w["x0"])
                    elif "ClosingBalance" in t:
                        clos_x = float(w["x0"])
                break

        wd_dep_boundary = (wd_x + dep_x) / 2 if wd_x and dep_x else 400.0
        dep_clos_boundary = (dep_x + clos_x) / 2 if dep_x and clos_x else 480.0
        return wd_dep_boundary, dep_clos_boundary

    def _parse_row_words(
        self,
        row_words: list[dict[str, object]],
        wd_dep_boundary: float,
        dep_clos_boundary: float,
    ) -> dict[str, object] | None:
        """Parse a list of words from one transaction row into a structured dict."""
        withdrawal_str: str | None = None
        deposit_str: str | None = None
        closing_str: str | None = None
        narration_parts: list[str] = []
        value_dt_str: str | None = None
        seen_dates = 0

        for w in row_words:
            text = str(w["text"])
            x = float(w["x0"])

            if _ROW_DATE_RE.match(text):
                seen_dates += 1
                if seen_dates == 2:
                    value_dt_str = text
                continue

            if _AMOUNT_RE.match(text):
                if x < wd_dep_boundary:
                    withdrawal_str = text
                elif x < dep_clos_boundary:
                    deposit_str = text
                else:
                    closing_str = text
                continue

            if _REF_RE.match(text):
                continue

            narration_parts.append(text)

        narration = " ".join(narration_parts)

        # Determine signed amount: deposit → positive, withdrawal → negative
        if deposit_str:
            amount_str = deposit_str
            sign = 1
        elif withdrawal_str:
            amount_str = withdrawal_str
            sign = -1
        else:
            return None  # no transaction amount found — skip row

        if closing_str is None:
            return None  # no closing balance — skip row

        amount_paise = sign * int(Decimal(amount_str.replace(",", "")) * 100)
        running_balance_paise = int(Decimal(closing_str.replace(",", "")) * 100)

        value_date: date_type | None = None
        if value_dt_str:
            value_date = datetime.strptime(value_dt_str, "%d/%m/%y").date()

        return {
            "narration": narration,
            "amount_paise": amount_paise,
            "running_balance_paise": running_balance_paise,
            "value_date": value_date,
        }

    # ------------------------------------------------------------------ #
    # Transaction building (hashing, occurrence index)
    # ------------------------------------------------------------------ #

    def _build_transaction(
        self,
        row: dict[str, object],
        account_ref: str,
        prior_transactions: list[ParsedTransaction],
    ) -> ParsedTransaction | None:
        """Build a ParsedTransaction from a parsed row dict."""
        narration_raw = str(row.get("narration", ""))
        amount_paise = int(row.get("amount_paise", 0))  # type: ignore[arg-type]
        running_balance_paise = row.get("running_balance_paise")
        value_date = row.get("value_date")

        if not narration_raw or value_date is None:
            return None

        assert isinstance(value_date, date_type)
        assert running_balance_paise is None or isinstance(running_balance_paise, int)

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
            running_balance_paise=running_balance_paise,
        )

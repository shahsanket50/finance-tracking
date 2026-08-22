"""SBI Credit Card statement parser. Implements PRD §14.2, TRD §9.1."""

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


class SbiCcParser(AbstractParser):
    """Parser for SBI Credit Card PDF statements."""

    def can_parse(self, text: str) -> bool:
        lower = text.lower()
        return "state bank of india" in lower and "credit card" in lower

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement:  # type: ignore[name-defined]
        raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        account_ref = self._extract_account_ref(raw_text)
        period_start, period_end = self._extract_period(raw_text)
        opening_balance_paise = self._extract_opening_balance(raw_text)
        closing_balance_paise = self._extract_closing_balance(raw_text)

        transactions: list[ParsedTransaction] = []
        for page in pdf.pages:
            rows = self._extract_rows(page)
            for row in rows:
                txn = self._build_transaction(row, account_ref, transactions)
                if txn is not None:
                    transactions.append(txn)

        return ParsedStatement(
            bank="sbi_cc",
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

    def _extract_account_ref(self, text: str) -> str:
        match = re.search(r"Account:\s*(\S+)", text)
        return match.group(1) if match else ""

    def _extract_period(self, text: str) -> tuple[date_type, date_type]:
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
        match = re.search(
            r"Previous Balance:\s*([\d,]+\.\d{2}\s+(?:Cr|Dr))",
            text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("Could not locate opening balance in SBI CC statement header")
        return self._parse_amount(match.group(1))

    def _extract_closing_balance(self, text: str) -> int:
        match = re.search(
            r"New Balance:\s*([\d,]+\.\d{2}\s+(?:Cr|Dr))",
            text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("Could not locate closing balance in SBI CC statement header")
        return self._parse_amount(match.group(1))

    def _extract_rows(self, page: pdfplumber.page.PageBase) -> list[list[str]]:  # type: ignore[name-defined]
        table = page.extract_table()
        if not table:
            return []
        rows: list[list[str]] = []
        for row in table:
            if row is None:
                continue
            cells = [str(c or "").strip() for c in row]
            if cells and cells[0].upper() in ("DATE", "DATE & TIME"):
                continue
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
        # Columns: Date | Transaction Details | Amount
        if len(row) < 3:
            return None
        date_str = row[0].strip()
        raw_narration = row[1].strip()
        amount_str = row[2].strip()
        if not date_str or not amount_str:
            return None
        try:
            value_date = self._parse_date(date_str)
            amount_paise = self._parse_amount(amount_str)
        except (ValueError, IndexError, ArithmeticError):
            return None

        narration = re.sub(r"\s+", " ", raw_narration).strip()
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
            running_balance_paise=None,
        )

    @staticmethod
    def _parse_amount(amount_str: str) -> int:
        s = amount_str.strip()
        parts = s.rsplit(" ", 1)
        numeric = parts[0].replace(",", "")
        suffix = parts[1].upper() if len(parts) > 1 else "CR"
        paise = int(Decimal(numeric) * 100)
        return paise if suffix == "CR" else -paise

    @staticmethod
    def _parse_date(date_str: str) -> date_type:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y").date()

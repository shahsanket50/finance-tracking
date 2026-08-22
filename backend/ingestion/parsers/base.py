"""Parser contracts: ParsedTransaction, ParsedStatement, AbstractParser.
Implements TRD §9.1 and PRD §14.2 parser interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

import pdfplumber


@dataclass
class ParsedTransaction:
    account_ref: str
    value_date: date
    amount_paise: int  # signed; debits negative, credits positive
    narration: str  # raw text from statement
    canonical_narration: str  # result of canonicalize_narration(narration)
    occurrence_index: int  # 0-based ordinal within group
    idempotency_hash: str  # 64-char hex SHA-256
    running_balance_paise: int | None  # validation-only; NOT in hash


@dataclass
class ParsedStatement:
    bank: str
    account_ref: str
    account_type: str  # "savings" | "credit_card" | "fd" — used by resolver pipeline
    period_start: date
    period_end: date
    opening_balance_paise: int
    closing_balance_paise: int
    transactions: list[ParsedTransaction]
    confidence: int  # 0–10000 basis points
    raw_text: str  # full extracted text, for golden diffs


class AbstractParser(ABC):
    """Base class for all bank statement parsers."""

    @abstractmethod
    def can_parse(self, text: str) -> bool:
        """Return True if this parser can handle the given extracted text."""
        ...

    @abstractmethod
    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement:  # type: ignore[name-defined]
        """Parse the given PDF and return a ParsedStatement."""
        ...

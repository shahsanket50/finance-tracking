"""Real-shape transaction rows for tests. Implements ADR-024.

Every row this module produces went through the production path. A synthetic statement
is rendered to PDF, the real parser selected by the dry-run harness parses it, and the
real confirm() payload builder (or the real confirm() itself) turns it into events. Signs,
payload keys and the transaction_type vocabulary are therefore exactly what production
writes, including known defects (B-4: transaction_type is "debit"/"credit").

This is the ONLY place in backend/tests allowed to construct transaction payloads,
ParsedTransaction objects or append_event calls; scripts/check-test-row-shapes.py
enforces it in CI.

Levels:
    parse_statement(...)         → ParsedStatement (real parser, no DB)
    ingested_events(...)         → list[Event] as confirm() would write them (no DB, no
                                   resolver events: pass excluded hashes explicitly or use
                                   the integration level)
    ingest_via_confirm(...)      → runs the real dry_run() + confirm() against Postgres and
                                   Redis, which also runs the real resolver (integration only)
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

from sqlalchemy.orm import Session

from core.events.store import Event
from core.events.types import TRANSACTION_INGESTED
from ingestion.dryrun.confirm import confirm, transaction_event_payload
from ingestion.dryrun.harness import dry_run
from ingestion.fetchers.pdf_reader import open_pdf
from ingestion.parsers.base import ParsedStatement
from ingestion.parsers.hdfc_cc import HdfcCcParser
from ingestion.parsers.hdfc_savings import HdfcSavingsParser
from ingestion.parsers.sbi_cc import SbiCcParser
from ingestion.parsers.sbi_savings import SbiSavingsParser
from ingestion.parsers.slice_savings import SliceSavingsParser
from tests.fixtures.pdf_generator import dict_to_pdf

BANKS: tuple[str, ...] = ("hdfc_cc", "sbi_cc", "hdfc_savings", "sbi_savings", "slice_savings")

_PARSERS = (
    HdfcCcParser(),
    SbiCcParser(),
    HdfcSavingsParser(),
    SbiSavingsParser(),
    SliceSavingsParser(),
)


@dataclass(frozen=True)
class Txn:
    """One line on a synthetic statement. amount_paise is signed: debit <0, credit >0."""

    narration: str
    amount_paise: int
    value_date: date


def render_statement_pdf(
    bank: str,
    account_ref: str,
    period_start: date,
    period_end: date,
    txns: Sequence[Txn],
    opening_balance_paise: int = 0,
) -> bytes:
    """Synthetic statement → PDF bytes in the bank's real layout.

    Narrations must be in the bank's printed format (e.g. Slice: "UPI-Debit-<ref>-<merchant>").

    closing = opening + Σ signed amounts, so the real balance check (Invariant 2) passes.
    Built as the golden-JSON statement shape that dict_to_pdf renders for all five banks
    (generate_statement() lacks the CC templates and does not round-trip every bank).
    """
    rows: list[dict[str, object]] = []
    running = opening_balance_paise
    for t in txns:
        running += t.amount_paise
        rows.append(
            {
                "narration": t.narration,
                "amount_paise": t.amount_paise,
                "value_date": t.value_date,
                "running_balance_paise": running,  # printed by savings layouts
            }
        )
    statement: dict[str, object] = {
        "bank": bank,
        "account_ref": account_ref,
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance_paise": opening_balance_paise,
        "closing_balance_paise": opening_balance_paise + sum(t.amount_paise for t in txns),
        "transactions": rows,
    }
    return dict_to_pdf(statement, bank)


def parse_pdf(pdf_bytes: bytes) -> ParsedStatement:
    """Parse PDF bytes with the production parser the dry-run harness would select."""
    with open_pdf(pdf_bytes) as pdf:
        raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        parser = next((p for p in _PARSERS if p.can_parse(raw_text)), None)
        if parser is None:
            raise ValueError("No production parser accepts this PDF")
        return parser.parse(pdf)


def parse_statement(
    bank: str,
    account_ref: str,
    period_start: date,
    period_end: date,
    txns: Sequence[Txn],
    opening_balance_paise: int = 0,
) -> ParsedStatement:
    """Synthetic statement → real parser output."""
    pdf_bytes = render_statement_pdf(
        bank, account_ref, period_start, period_end, txns, opening_balance_paise
    )
    return parse_pdf(pdf_bytes)


def ingested_events(
    statement: ParsedStatement,
    user_id: uuid.UUID | None = None,
    start_seq: int = 1,
) -> list[Event]:
    """In-memory TransactionIngested events carrying exactly the payload confirm() writes."""
    owner = user_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    created = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Event(
            id=uuid.uuid4(),
            seq=start_seq + i,
            event_version=1,
            event_type=TRANSACTION_INGESTED,
            user_id=owner,
            aggregate_id=txn.account_ref,
            payload=transaction_event_payload(statement, txn),
            created_at=created,
        )
        for i, txn in enumerate(statement.transactions)
    ]


@contextmanager
def _redis_patched(redis_client: Any) -> Iterator[None]:
    with (
        patch("ingestion.dryrun.harness.get_redis_client", return_value=redis_client),
        patch("ingestion.dryrun.confirm.get_redis_client", return_value=redis_client),
    ):
        yield


def ingest_via_confirm(
    session: Session,
    redis_client: Any,
    user_id: uuid.UUID,
    pdf_bytes: bytes,
    account_ref: str,
) -> None:
    """Run the production dry_run() + confirm() on pdf_bytes (writes events, runs resolver).

    confirm() commits. Integration tests using this must isolate by user_id, not by rollback.
    """
    with _redis_patched(redis_client):
        dry_session = dry_run(pdf_bytes, user_id, account_ref)
        confirm(dry_session.session_id, session)

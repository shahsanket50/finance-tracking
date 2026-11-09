"""Real-shape transaction rows for tests. Implements ADR-024.

Every row this module produces went through the production path. A synthetic statement
is rendered to PDF, the real parser selected by the dry-run harness parses it, and the
real confirm() payload builder (or the real confirm() itself) turns it into events. Signs,
payload keys and the transaction_type vocabulary are therefore exactly what production
writes, including known defects (B-4: transaction_type is "debit"/"credit").

This is the ONLY place in backend/tests allowed to construct transaction payloads,
ParsedTransaction objects or append_event calls; ci/guards/test_row_shapes.py
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
from datetime import UTC, date, datetime, timedelta
from functools import cache
from typing import Any
from unittest.mock import patch

from sqlalchemy.orm import Session

from core.events.store import Event
from core.events.types import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_FD,
    ACCOUNT_TYPE_SAVINGS,
    TRANSACTION_INGESTED,
)
from core.hashing.hash import canonicalize_narration, compute_idempotency_hash
from ingestion.dryrun.confirm import confirm, transaction_event_payload
from ingestion.dryrun.harness import dry_run
from ingestion.fetchers.pdf_reader import open_pdf
from ingestion.parsers.base import ParsedStatement
from ingestion.parsers.hdfc_cc import HdfcCcParser
from ingestion.parsers.hdfc_savings import HdfcSavingsParser
from ingestion.parsers.sbi_cc import SbiCcParser
from ingestion.parsers.sbi_savings import SbiSavingsParser
from ingestion.parsers.slice_savings import SliceSavingsParser
from ingestion.validators.balance_check import validate_balance
from processing.accounts.contract import StatementRecord
from processing.resolver.candidate import CandidateTxn
from processing.resolver.pipeline import _cascade_matchers, candidate_from_ingested
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


def statement_id(statement: ParsedStatement) -> uuid.UUID:
    """Deterministic stand-in for the IngestionEvent id confirm() would create."""
    key = f"{statement.account_ref}:{statement.period_start}:{statement.period_end}"
    return uuid.uuid5(uuid.NAMESPACE_URL, key)


def statement_record(statement: ParsedStatement, seq: int) -> StatementRecord:
    """The StatementRecord load_account_statements() would return for this statement.

    seq stands in for the IngestionEvent's global sequence (higher = uploaded later).
    """
    return StatementRecord(
        ingestion_event_id=statement_id(statement),
        seq=seq,
        account_ref=statement.account_ref,
        account_type=statement.account_type,
        period_end=statement.period_end,
        closing_balance_paise=statement.closing_balance_paise,
        balance_check=validate_balance(
            statement.opening_balance_paise,
            statement.transactions,
            statement.closing_balance_paise,
        ).value,
    )


def ingested_events(
    statement: ParsedStatement,
    user_id: uuid.UUID | None = None,
    start_seq: int = 1,
) -> list[Event]:
    """In-memory TransactionIngested events carrying exactly the payload confirm() writes.

    Each event's ingestion_event_id is statement_id(statement), matching statement_record().
    """
    owner = user_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    created = datetime(2026, 1, 1, tzinfo=UTC)
    source = statement_id(statement)
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
            ingestion_event_id=source,
        )
        for i, txn in enumerate(statement.transactions)
    ]


# Resolver candidates --------------------------------------------------------------------------

_CANDIDATE_BANK = {
    ACCOUNT_TYPE_SAVINGS: ("sbi_savings", "SBI_SAV_9000"),
    ACCOUNT_TYPE_CREDIT_CARD: ("sbi_cc", "SBI_CC_9000"),
}


@cache
def real_candidate(
    amount_paise: int, value_date: date, account_type: str, narration: str = "UPI TRANSFER"
) -> CandidateTxn:
    """One matcher candidate built from real parser output via the pipeline's own conversion.

    savings / credit_card rows go through a rendered statement and the production parser.
    fd has no statement parser yet, so fd candidates come from fd_candidate().
    """
    if account_type == ACCOUNT_TYPE_FD:
        return fd_candidate(amount_paise, value_date, narration)
    bank, ref = _CANDIDATE_BANK[account_type]
    statement = parse_statement(
        bank, ref, value_date - timedelta(days=1), value_date + timedelta(days=1),
        [Txn(narration, amount_paise, value_date)], 1_000_000,
    )  # fmt: skip
    (txn,) = statement.transactions
    payload = transaction_event_payload(statement, txn)
    return candidate_from_ingested(txn.idempotency_hash, txn.amount_paise, txn.value_date, payload)


def candidates_from_events(events: Sequence[Event]) -> list[CandidateTxn]:
    """Matcher candidates from TransactionIngested events, via the pipeline's conversion."""
    return [
        candidate_from_ingested(
            str(e.payload["idempotency_hash"]),
            int(str(e.payload["amount_paise"])),
            date.fromisoformat(str(e.payload["value_date"])),
            e.payload,
        )
        for e in events
        if e.event_type == TRANSACTION_INGESTED
    ]


def resolver_events(events: Sequence[Event], user_id: uuid.UUID | None = None) -> list[Event]:
    """Real resolver decisions (no DB): the production matcher cascade over ingested events,
    each match wrapped as run_resolver persists it (payload = the matcher's model_dump())."""
    owner = user_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    next_seq = max((e.seq for e in events), default=0) + 1
    created = datetime(2026, 1, 2, tzinfo=UTC)
    matches = _cascade_matchers(candidates_from_events(events), set())
    return [
        Event(
            id=uuid.uuid4(),
            seq=next_seq + i,
            event_version=1,
            event_type=event_type,
            user_id=owner,
            aggregate_id="RESOLVER",
            payload=match.model_dump(),
            created_at=created,
        )
        for i, (event_type, _h1, _h2, match) in enumerate(matches)
    ]


def fd_candidate(
    amount_paise: int, value_date: date, narration: str = "FD BOOKING"
) -> CandidateTxn:
    """FD leg for resolver tests. No production parser emits FD rows yet (no FD statement
    format), so this is the single sanctioned synthesis point: the hash is computed with the
    production hash function and account_type is the production constant."""
    canonical = canonicalize_narration(narration)
    return CandidateTxn(
        idempotency_hash=compute_idempotency_hash(
            "FD_SYNTH", value_date, amount_paise, canonical, 0
        ),
        amount_paise=amount_paise,
        value_date=value_date,
        account_type=ACCOUNT_TYPE_FD,
    )


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


def insert_corrupt_transaction_row(
    session: Session, user_id: uuid.UUID, account_ref: str, ingestion_event_id: uuid.UUID
) -> None:
    """Fault injection: one TransactionIngested row whose payload can't be decrypted.

    The only sanctioned hand-built transaction_events row (ADR-024): it exists to prove that
    a corrupt payload fails loudly and stays scoped to its own account (review N3). INSERT
    only; the append-only table is never updated.
    """
    from sqlalchemy import select

    from core.events.models import TransactionEvent, UserEncryptionKey

    key = session.scalars(
        select(UserEncryptionKey).where(UserEncryptionKey.user_id == user_id)
    ).first()
    if key is None:
        raise ValueError(f"user {user_id} has no encryption key")
    session.add(
        TransactionEvent(
            user_id=user_id,
            event_type=TRANSACTION_INGESTED,
            account_ref=account_ref,
            value_date=date(2026, 3, 15),
            amount_paise=-1,
            idempotency_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            transaction_type="debit",
            narration="CORRUPT PAYLOAD FAULT INJECTION",
            actor="system",
            payload=b"\x00" * 12 + b"not-a-valid-aes-gcm-ciphertext",
            encryption_key_id=key.id,
            ingestion_event_id=ingestion_event_id,
        )
    )
    session.commit()

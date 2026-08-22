"""Integration: audit endpoints return correct data from the real event log (PRD §15).

Tests call the logic functions directly (get_sync_history, get_overlap_map, etc.)
rather than through HTTP so the pg_session fixture provides full transactional isolation.

Seeding strategy:
- sync-history / overlap-map: seed IngestionEvent rows directly (no parsers needed).
- dedup-ledger / resolver-pairings: use confirm() to exercise the full write path
  including run_resolver(), mirroring how data actually enters the system.
"""

from __future__ import annotations

import pickle
import uuid
from datetime import UTC, datetime
from datetime import date as date_type
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.encryption import encrypt_payload
from core.events.models import IngestionEvent, TransactionEvent, User
from core.events.types import ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_SAVINGS
from core.hashing.hash import canonicalize_narration, compute_idempotency_hash
from ingestion.dryrun.session import DryRunSession
from ingestion.parsers.base import ParsedStatement, ParsedTransaction
from ingestion.validators.balance_check import BalanceCheckResult
from processing.audit.router import (
    get_dedup_ledger,
    get_overlap_map,
    get_resolver_pairings,
    get_sync_history,
)

# ── Seeding helpers ────────────────────────────────────────────────────────────


def _seed_ingestion_event(
    session: Session,
    user_id: uuid.UUID,
    account_ref: str,
    bank: str,
    period_start: date_type,
    period_end: date_type,
    status: str = "ingested",
    records_added: int = 2,
    created_at: datetime | None = None,
) -> IngestionEvent:
    """Insert a minimal IngestionEvent directly (no parsers or Redis needed).

    Pass created_at explicitly when testing sort order — within a single DB
    transaction NOW() returns the same timestamp for all inserts, making
    insertion-order-based ordering non-deterministic.
    """
    payload_dict: dict[str, object] = {
        "account_ref": account_ref,
        "bank": bank,
        "raw_artifact_content_hash": "a" * 64,
        "transaction_count": records_added,
    }
    encrypted, key_id = encrypt_payload(session, user_id, payload_dict)

    kwargs: dict[str, object] = {
        "user_id": user_id,
        "source": "pdf_upload",
        "period_start": period_start,
        "period_end": period_end,
        "records_added": records_added,
        "records_skipped": 0,
        "records_flagged": 0,
        "balance_check": "pass",
        "confidence": 9000,
        "status": status,
        "payload": encrypted,
        "encryption_key_id": key_id,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at

    event = IngestionEvent(**kwargs)
    session.add(event)
    session.flush()
    return event


def _make_transfer_dry_session(user_id: uuid.UUID) -> DryRunSession:
    """Build a DryRunSession with a savings↔savings transfer pair (–50000 / +50000 paise)."""
    account_ref = "HDFC_SAVINGS_AUDIT"
    value_date = date_type(2026, 2, 10)

    debit_narration = "NEFT TO SBI"
    debit_canon = canonicalize_narration(debit_narration)
    debit_hash = compute_idempotency_hash(account_ref, value_date, -50000, debit_canon, 0)
    debit = ParsedTransaction(
        account_ref=account_ref,
        value_date=value_date,
        amount_paise=-50000,
        narration=debit_narration,
        canonical_narration=debit_canon,
        occurrence_index=0,
        idempotency_hash=debit_hash,
        running_balance_paise=None,
    )

    credit_narration = "NEFT FROM HDFC"
    credit_canon = canonicalize_narration(credit_narration)
    credit_hash = compute_idempotency_hash(account_ref, value_date, 50000, credit_canon, 0)
    credit = ParsedTransaction(
        account_ref=account_ref,
        value_date=value_date,
        amount_paise=50000,
        narration=credit_narration,
        canonical_narration=credit_canon,
        occurrence_index=0,
        idempotency_hash=credit_hash,
        running_balance_paise=None,
    )

    statement = ParsedStatement(
        bank="hdfc_savings",
        account_ref=account_ref,
        account_type=ACCOUNT_TYPE_SAVINGS,
        period_start=date_type(2026, 2, 1),
        period_end=date_type(2026, 2, 28),
        opening_balance_paise=0,
        closing_balance_paise=0,
        transactions=[debit, credit],
        confidence=9000,
        raw_text="synthetic transfer pair",
    )
    return DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        account_ref=account_ref,
        statement=statement,
        balance_check=BalanceCheckResult.PASS,
        raw_artifact_content_hash="c" * 64,
        created_at=datetime.now(UTC),
    )


def _confirm_dry_session(dry_session: DryRunSession, db_session: Session) -> None:
    from ingestion.dryrun.confirm import confirm

    mock_redis = MagicMock()
    mock_redis.get.return_value = pickle.dumps(dry_session)
    with patch("ingestion.dryrun.confirm.get_redis_client", return_value=mock_redis):
        confirm(dry_session.session_id, db_session)


# ── sync-history ──────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_sync_history_empty_for_new_user(pg_session: Session, test_user: User) -> None:
    result = get_sync_history(pg_session, test_user.id)
    assert result == []


@pytest.mark.integration
def test_sync_history_returns_ingestion_event(pg_session: Session, test_user: User) -> None:
    _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="SBI_SAVINGS",
        bank="sbi_savings",
        period_start=date_type(2026, 1, 1),
        period_end=date_type(2026, 1, 31),
    )

    result = get_sync_history(pg_session, test_user.id)

    assert len(result) == 1
    entry = result[0]
    assert entry.account_ref == "SBI_SAVINGS"
    assert entry.bank == "sbi_savings"
    assert entry.period_start == date_type(2026, 1, 1)
    assert entry.period_end == date_type(2026, 1, 31)
    assert entry.status == "ingested"
    assert entry.records_added == 2
    assert entry.balance_check == "pass"


@pytest.mark.integration
def test_sync_history_newest_first(pg_session: Session, test_user: User) -> None:
    # Use explicit timestamps — within a single DB transaction NOW() returns the
    # same value for all inserts, so insertion order alone can't test DESC sorting.
    _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="ACC_JAN",
        bank="hdfc_savings",
        period_start=date_type(2026, 1, 1),
        period_end=date_type(2026, 1, 31),
        created_at=datetime(2026, 1, 31, 12, 0, 0, tzinfo=UTC),
    )
    _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="ACC_FEB",
        bank="hdfc_savings",
        period_start=date_type(2026, 2, 1),
        period_end=date_type(2026, 2, 28),
        created_at=datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC),
    )

    result = get_sync_history(pg_session, test_user.id)

    assert len(result) == 2
    assert result[0].account_ref == "ACC_FEB", "Newest (Feb) must be first"
    assert result[1].account_ref == "ACC_JAN"


# ── overlap-map ───────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_overlap_map_no_overlap_for_distinct_periods(pg_session: Session, test_user: User) -> None:
    _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="HDFC_SAVINGS",
        bank="hdfc_savings",
        period_start=date_type(2026, 1, 1),
        period_end=date_type(2026, 1, 31),
    )
    _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="HDFC_SAVINGS",
        bank="hdfc_savings",
        period_start=date_type(2026, 2, 1),
        period_end=date_type(2026, 2, 28),
    )

    result = get_overlap_map(pg_session, test_user.id)

    assert len(result.accounts) == 1
    account = result.accounts[0]
    assert account.account_ref == "HDFC_SAVINGS"
    for bar in account.statements:
        assert bar.overlaps_with == [], f"Expected no overlaps, got {bar.overlaps_with}"


@pytest.mark.integration
def test_overlap_map_flags_overlapping_periods(pg_session: Session, test_user: User) -> None:
    e1 = _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="HDFC_SAVINGS",
        bank="hdfc_savings",
        period_start=date_type(2026, 1, 1),
        period_end=date_type(2026, 1, 31),
    )
    e2 = _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="HDFC_SAVINGS",
        bank="hdfc_savings",
        period_start=date_type(2026, 1, 15),  # overlaps e1
        period_end=date_type(2026, 2, 14),
    )

    result = get_overlap_map(pg_session, test_user.id)

    assert len(result.accounts) == 1
    bars = {b.event_id: b for b in result.accounts[0].statements}
    assert str(e2.id) in bars[str(e1.id)].overlaps_with
    assert str(e1.id) in bars[str(e2.id)].overlaps_with


@pytest.mark.integration
def test_overlap_map_separates_different_accounts(pg_session: Session, test_user: User) -> None:
    _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="HDFC_SAVINGS",
        bank="hdfc_savings",
        period_start=date_type(2026, 1, 1),
        period_end=date_type(2026, 1, 31),
    )
    _seed_ingestion_event(
        pg_session,
        test_user.id,
        account_ref="SBI_SAVINGS",  # different account
        bank="sbi_savings",
        period_start=date_type(2026, 1, 15),  # overlapping period, but different account
        period_end=date_type(2026, 2, 14),
    )

    result = get_overlap_map(pg_session, test_user.id)

    assert len(result.accounts) == 2
    for account in result.accounts:
        for bar in account.statements:
            assert bar.overlaps_with == [], "Different accounts must not overlap each other"


# ── dedup-ledger ──────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_dedup_ledger_empty_for_new_user(pg_session: Session, test_user: User) -> None:
    result = get_dedup_ledger(pg_session, test_user.id, None, None)
    assert result.total_seen == 0
    assert result.total_counted == 0
    assert result.total_excluded == 0
    assert result.entries == []


@pytest.mark.integration
def test_dedup_ledger_shows_transfer_pair_as_excluded(pg_session: Session, test_user: User) -> None:
    dry_session = _make_transfer_dry_session(test_user.id)
    _confirm_dry_session(dry_session, pg_session)

    result = get_dedup_ledger(pg_session, test_user.id, None, None)

    assert result.total_seen == 2
    assert result.total_counted == 0, "Both legs of a transfer must be excluded"
    assert result.total_excluded == 2

    for entry in result.entries:
        assert entry.is_counted is False
        assert entry.exclusion_reason == "internal_transfer"


@pytest.mark.integration
def test_dedup_ledger_date_filter_restricts_entries(pg_session: Session, test_user: User) -> None:
    dry_session = _make_transfer_dry_session(test_user.id)
    _confirm_dry_session(dry_session, pg_session)

    # Transactions are on 2026-02-10 — filter to a window that excludes them
    result = get_dedup_ledger(
        pg_session,
        test_user.id,
        from_date=date_type(2026, 3, 1),
        to_date=date_type(2026, 3, 31),
    )
    assert result.total_seen == 0
    assert result.entries == []


@pytest.mark.integration
def test_dedup_ledger_date_filter_includes_matching_entries(
    pg_session: Session, test_user: User
) -> None:
    dry_session = _make_transfer_dry_session(test_user.id)
    _confirm_dry_session(dry_session, pg_session)

    # Transactions are on 2026-02-10 — filter window includes them
    result = get_dedup_ledger(
        pg_session,
        test_user.id,
        from_date=date_type(2026, 2, 1),
        to_date=date_type(2026, 2, 28),
    )
    assert result.total_seen == 2


# ── resolver-pairings ─────────────────────────────────────────────────────────


@pytest.mark.integration
def test_resolver_pairings_empty_for_new_user(pg_session: Session, test_user: User) -> None:
    result = get_resolver_pairings(pg_session, test_user.id)
    assert result == []


@pytest.mark.integration
def test_resolver_pairings_returns_transfer_pair(pg_session: Session, test_user: User) -> None:
    dry_session = _make_transfer_dry_session(test_user.id)
    _confirm_dry_session(dry_session, pg_session)

    result = get_resolver_pairings(pg_session, test_user.id)

    assert len(result) == 1
    pairing = result[0]
    assert pairing.event_type == "MarkedInternalTransfer"
    assert pairing.matched_by == "transfer_v1"
    assert pairing.confidence > 0
    assert pairing.value_date == date_type(2026, 2, 10)

    roles = {leg.role for leg in pairing.legs}
    assert roles == {"debit", "credit"}

    for leg in pairing.legs:
        assert len(leg.idempotency_hash) == 64, "Idempotency hash must be a 64-char hex string"


@pytest.mark.integration
def test_resolver_pairings_legs_match_transaction_hashes(
    pg_session: Session, test_user: User
) -> None:
    """The hash in each leg must exactly match the idempotency_hash of the transaction."""
    dry_session = _make_transfer_dry_session(test_user.id)
    _confirm_dry_session(dry_session, pg_session)

    pairings = get_resolver_pairings(pg_session, test_user.id)
    assert len(pairings) == 1

    all_leg_hashes = {leg.idempotency_hash for leg in pairings[0].legs}
    expected_hashes = {txn.idempotency_hash for txn in dry_session.statement.transactions}
    assert all_leg_hashes == expected_hashes, (
        "Pairing legs must reference the same hashes as the ingested transactions"
    )


# ── resolver-pairings leg enrichment ─────────────────────────────────────────


def _make_cc_payment_dry_sessions(
    user_id: uuid.UUID,
) -> tuple[DryRunSession, DryRunSession]:
    """Two DryRunSessions: savings debit + CC credit that the resolver matches as CCPayment."""
    savings_account = "HDFC_SAVINGS_CC_TEST"
    cc_account = "HDFC_CC_9876_TEST"
    payment_date = date_type(2026, 3, 15)
    amount = 75_000  # paise

    debit_narration = "CC BILL PAYMENT HDFC"
    debit_canon = canonicalize_narration(debit_narration)
    debit_hash = compute_idempotency_hash(savings_account, payment_date, -amount, debit_canon, 0)
    debit_txn = ParsedTransaction(
        account_ref=savings_account,
        value_date=payment_date,
        amount_paise=-amount,
        narration=debit_narration,
        canonical_narration=debit_canon,
        occurrence_index=0,
        idempotency_hash=debit_hash,
        running_balance_paise=None,
    )
    savings_statement = ParsedStatement(
        bank="hdfc_savings",
        account_ref=savings_account,
        account_type=ACCOUNT_TYPE_SAVINGS,
        period_start=date_type(2026, 3, 1),
        period_end=date_type(2026, 3, 31),
        opening_balance_paise=amount,
        closing_balance_paise=0,
        transactions=[debit_txn],
        confidence=9000,
        raw_text="synthetic savings statement for CC payment test",
    )
    savings_session = DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        account_ref=savings_account,
        statement=savings_statement,
        balance_check=BalanceCheckResult.PASS,
        raw_artifact_content_hash="d" * 64,
        created_at=datetime.now(UTC),
    )

    credit_narration = "PAYMENT RECEIVED THANK YOU"
    credit_canon = canonicalize_narration(credit_narration)
    credit_hash = compute_idempotency_hash(cc_account, payment_date, amount, credit_canon, 0)
    credit_txn = ParsedTransaction(
        account_ref=cc_account,
        value_date=payment_date,
        amount_paise=amount,
        narration=credit_narration,
        canonical_narration=credit_canon,
        occurrence_index=0,
        idempotency_hash=credit_hash,
        running_balance_paise=None,
    )
    # CC statement period: billing cycle the payment covers (distinct from savings period).
    cc_period_start = date_type(2026, 2, 15)
    cc_period_end = date_type(2026, 3, 14)
    cc_statement = ParsedStatement(
        bank="hdfc_cc",
        account_ref=cc_account,
        account_type=ACCOUNT_TYPE_CREDIT_CARD,
        period_start=cc_period_start,
        period_end=cc_period_end,
        opening_balance_paise=-amount,
        closing_balance_paise=0,
        transactions=[credit_txn],
        confidence=9000,
        raw_text="synthetic CC statement for CC payment test",
    )
    cc_session = DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        account_ref=cc_account,
        statement=cc_statement,
        balance_check=BalanceCheckResult.PASS,
        raw_artifact_content_hash="e" * 64,
        created_at=datetime.now(UTC),
    )

    return savings_session, cc_session


@pytest.mark.integration
def test_cc_payment_leg_carries_account_ref_and_statement_period(
    pg_session: Session, test_user: User
) -> None:
    """The cc_credit leg of a MarkedCCPayment pairing must carry the CC account's account_ref
    and the statement period from the IngestionEvent that brought in the CC credit transaction.

    This is the data the client needs to query 'all purchases covered by this bill'
    without a separate hash-lookup round-trip (Journey 7 / E12 drill-down).
    """
    savings_session, cc_session = _make_cc_payment_dry_sessions(test_user.id)

    # Confirming the savings session first: resolver finds no match (only 1 candidate).
    _confirm_dry_session(savings_session, pg_session)
    # Confirming the CC session: resolver now sees both legs and writes MarkedCCPayment.
    _confirm_dry_session(cc_session, pg_session)
    pg_session.flush()

    pairings = get_resolver_pairings(pg_session, test_user.id)
    cc_pairings = [p for p in pairings if p.event_type == "MarkedCCPayment"]
    assert len(cc_pairings) == 1, f"Expected 1 CC payment pairing, got {len(cc_pairings)}"

    legs = {leg.role: leg for leg in cc_pairings[0].legs}
    assert "cc_credit" in legs, f"Expected 'cc_credit' leg, got roles: {set(legs)}"

    cc_leg = legs["cc_credit"]
    assert cc_leg.account_ref == "HDFC_CC_9876_TEST", (
        f"cc_credit leg account_ref {cc_leg.account_ref!r} != expected 'HDFC_CC_9876_TEST'"
    )
    assert cc_leg.period_start == date_type(2026, 2, 15), (
        f"cc_credit leg period_start {cc_leg.period_start} != expected 2026-02-15"
    )
    assert cc_leg.period_end == date_type(2026, 3, 14), (
        f"cc_credit leg period_end {cc_leg.period_end} != expected 2026-03-14"
    )


# ── resolver event DB constraint ──────────────────────────────────────────────


@pytest.mark.integration
def test_duplicate_resolver_event_raises_integrity_error(
    pg_session: Session, test_user: User
) -> None:
    """DB UNIQUE constraint on (user_id, idempotency_hash) rejects duplicate resolver events.

    Simulates two concurrent run_resolver() calls racing past the in-memory pre-write
    check: the second attempt to write a row with the same (user_id, idempotency_hash)
    raises IntegrityError, not a silent duplicate.

    The constraint is uq_transaction_events_user_idempotency_hash on transaction_events.
    Resolver events are stored there — this test confirms it covers them.
    """
    from sqlalchemy.exc import IntegrityError

    from core.events.store import append_event
    from core.events.types import RESOLVER_EVENT_TYPES

    dry_session = _make_transfer_dry_session(test_user.id)
    _confirm_dry_session(dry_session, pg_session)
    pg_session.flush()

    # Find the resolver event that run_resolver() wrote during confirm().
    resolver_row = pg_session.scalars(
        select(TransactionEvent).where(
            TransactionEvent.user_id == test_user.id,
            TransactionEvent.event_type.in_(list(RESOLVER_EVENT_TYPES)),
        )
    ).first()
    assert resolver_row is not None, "Expected a resolver event after confirm()"

    # A second append_event() with the same (user_id, idempotency_hash) must be rejected.
    with pytest.raises(IntegrityError):
        append_event(
            pg_session,
            test_user.id,
            resolver_row.event_type,
            "RESOLVER",
            {},
            value_date=resolver_row.value_date,
            amount_paise=0,
            idempotency_hash=resolver_row.idempotency_hash,
            transaction_type="transfer",
            narration="",
            ingestion_event_id=resolver_row.ingestion_event_id,
        )
        pg_session.flush()

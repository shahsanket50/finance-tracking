"""End-to-end: registered /api/v1/accounts routes + real confirm() rows → anchored balance.

Covers what the unit tests can't: main.py registration (B-7), the IngestionEvent anchor written
by confirm() (ADR-022), anchor_period_end in the API response, and the B-5 sign on a real
card statement. Routes use the stub user (Phase 5 replaces it), so account refs are unique per
run and the stub user is created once if absent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.encryption import create_user_key
from core.events.models import IngestionEvent, User, UserEncryptionKey
from core.models.mutable import Account
from db import get_db
from main import app
from processing.accounts.adapter import LEDGER_DECRYPTION_ALERT, STATEMENT_DECRYPTION_ALERT
from tests.factories.real_rows import (
    Txn,
    ingest_via_confirm,
    insert_corrupt_transaction_row,
    render_statement_pdf,
)

STUB_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def client(pg_session: Session) -> Iterator[TestClient]:
    if pg_session.get(User, STUB_USER_ID) is None:
        pg_session.add(User(id=STUB_USER_ID, email="stub-user@example.invalid"))
        pg_session.flush()
        create_user_key(pg_session, STUB_USER_ID)
        pg_session.commit()

    def _db() -> Iterator[Session]:
        yield pg_session

    app.dependency_overrides[get_db] = _db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _unique_digits() -> str:
    return str(uuid.uuid4().int)[:6]


def _create_account(client: TestClient, account_ref: str, account_type: str) -> str:
    """POST /api/v1/accounts. The row belongs to whichever user the router's stub id names."""
    response = client.post(
        "/api/v1/accounts",
        json={"nickname": account_ref, "account_type": account_type, "account_ref": account_ref},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _balance(client: TestClient, account_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/accounts/{account_id}/balance")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_savings_balance_equals_statement_closing_with_anchor_period_end(
    client: TestClient, pg_session: Session, redis_client: Any
) -> None:
    ref = f"HDFC_SAV_{_unique_digits()}"
    pdf = render_statement_pdf(
        "hdfc_savings",
        ref,
        date(2026, 1, 1),
        date(2026, 1, 31),
        [
            Txn("NEFTCR SALARY ACME", 5_000_000, date(2026, 1, 1)),
            Txn("UPI DMART GROCERY", -320_000, date(2026, 1, 12)),
        ],
        opening_balance_paise=1_000_000,
    )
    ingest_via_confirm(pg_session, redis_client, STUB_USER_ID, pdf, ref)
    account_id = _create_account(client, ref, "savings")

    body = _balance(client, account_id)

    assert body["derived_balance_paise"] == str(1_000_000 + 5_000_000 - 320_000)
    assert body["outstanding_liability_paise"] is None
    assert body["anchor_period_end"] == "2026-01-31"


def test_card_liability_is_positive_for_purchases_on_real_statement(
    client: TestClient, pg_session: Session, redis_client: Any
) -> None:
    ref = f"SBI_CC_{_unique_digits()}"
    pdf = render_statement_pdf(
        "sbi_cc",
        ref,
        date(2026, 2, 1),
        date(2026, 2, 28),
        [
            Txn("AMAZON PURCHASE", -55_000, date(2026, 2, 6)),
            Txn("UBER RIDE", -40_000, date(2026, 2, 9)),
        ],
    )
    ingest_via_confirm(pg_session, redis_client, STUB_USER_ID, pdf, ref)
    account_id = _create_account(client, ref, "credit_card")

    body = _balance(client, account_id)

    assert body["outstanding_liability_paise"] == "95000"  # B-5: owed is positive
    assert body["derived_balance_paise"] is None
    assert body["anchor_period_end"] == "2026-02-28"


def test_account_without_statement_reports_unknown_not_zero(client: TestClient) -> None:
    account_id = _create_account(client, f"HDFC_SAV_{_unique_digits()}", "savings")

    body = _balance(client, account_id)

    assert body["derived_balance_paise"] is None
    assert body["anchor_period_end"] is None


def _ingest(
    pg_session: Session, redis_client: Any, bank: str, ref: str, txns: list[Txn], **kw: Any
) -> None:
    period = kw.pop("period", (date(2026, 3, 1), date(2026, 3, 31)))
    pdf = render_statement_pdf(bank, ref, period[0], period[1], txns, kw.pop("opening", 0))
    ingest_via_confirm(pg_session, redis_client, STUB_USER_ID, pdf, ref)


def _error(client: TestClient, account_id: str) -> tuple[int, str]:
    response = client.get(f"/api/v1/accounts/{account_id}/balance")
    return response.status_code, str(response.json()["detail"]["code"])


def test_c1_row_value_dated_after_period_end_is_not_double_counted_end_to_end(
    client: TestClient, pg_session: Session, redis_client: Any
) -> None:
    ref = f"SBI_SAV_{_unique_digits()}"
    _ingest(
        pg_session, redis_client, "sbi_savings", ref,
        [Txn("UPI CREDIT SALARY", 100_000, date(2026, 4, 1))], opening=460_000,
    )  # fmt: skip
    body = _balance(client, _create_account(client, ref, "savings"))
    assert body["derived_balance_paise"] == "560000"  # the printed closing, not 660000
    assert body["stale"] is False


def test_c2_empty_statement_is_accepted_not_applicable_and_never_anchors(
    client: TestClient, pg_session: Session, redis_client: Any
) -> None:
    ref = f"HDFC_SAV_{_unique_digits()}"
    _ingest(pg_session, redis_client, "hdfc_savings", ref, [])
    row = pg_session.scalars(
        select(IngestionEvent).where(IngestionEvent.source_detail["account_ref"].as_string() == ref)
    ).one()
    assert (row.status, row.balance_check) == ("ingested", "not_applicable")

    body = _balance(client, _create_account(client, ref, "savings"))
    assert body["derived_balance_paise"] is None  # unknown, never "0"
    assert body["anchor_period_end"] is None


def test_account_without_type_is_structured_422(client: TestClient, pg_session: Session) -> None:
    account = Account(
        user_id=STUB_USER_ID,
        account_ref=f"HDFC_SAV_{_unique_digits()}",
        account_type=None,
        created_at=datetime.now(UTC),
    )
    pg_session.add(account)
    pg_session.commit()
    assert _error(client, str(account.id)) == (422, "account_type_missing")


def test_card_account_on_savings_statements_is_type_mismatch_422(
    client: TestClient, pg_session: Session, redis_client: Any
) -> None:
    ref = f"HDFC_SAV_{_unique_digits()}"
    _ingest(
        pg_session, redis_client, "hdfc_savings", ref,
        [Txn("UPI DMART GROCERY", -40_000, date(2026, 3, 9))], opening=500_000,
    )  # fmt: skip
    assert _error(client, _create_account(client, ref, "credit_card")) == (
        422,
        "account_type_mismatch",
    )


def test_investment_account_is_structured_422(client: TestClient) -> None:
    account_id = _create_account(client, f"ZERODHA_{_unique_digits()}", "investment")
    assert _error(client, account_id) == (422, "balance_not_supported_for_account_type")


def test_undecryptable_statement_fails_only_its_account_and_alerts(
    client: TestClient,
    pg_session: Session,
    redis_client: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken_ref, healthy_ref = f"HDFC_SAV_{_unique_digits()}", f"SBI_SAV_{_unique_digits()}"
    _ingest(
        pg_session, redis_client, "sbi_savings", healthy_ref,
        [Txn("UPI DMART GROCERY", -40_000, date(2026, 3, 9))], opening=500_000,
    )  # fmt: skip
    key = pg_session.scalars(
        select(UserEncryptionKey).where(UserEncryptionKey.user_id == STUB_USER_ID)
    ).first()
    assert key is not None
    pg_session.add(
        IngestionEvent(
            user_id=STUB_USER_ID,
            source="pdf_upload",
            source_detail={"account_ref": broken_ref, "account_type": "savings"},
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            records_added=0,
            records_skipped=0,
            records_flagged=0,
            balance_check="pass",
            status="ingested",
            payload=b"\x00" * 12 + b"not-a-valid-aes-gcm-ciphertext",
            encryption_key_id=key.id,
        )
    )
    pg_session.commit()

    with caplog.at_level("ERROR"):
        status_code, code = _error(client, _create_account(client, broken_ref, "savings"))

    assert (status_code, code) == (500, "statement_decryption_failed")
    assert any(getattr(r, "alert", None) == STATEMENT_DECRYPTION_ALERT for r in caplog.records)
    healthy = _balance(client, _create_account(client, healthy_ref, "savings"))
    assert healthy["derived_balance_paise"] == "460000"  # other accounts unaffected


def _statement_id(pg_session: Session, ref: str) -> uuid.UUID:
    row = pg_session.scalars(
        select(IngestionEvent).where(IngestionEvent.source_detail["account_ref"].as_string() == ref)
    ).one()
    return row.id


def test_corrupt_transaction_row_fails_only_its_own_account_and_alerts(
    client: TestClient,
    pg_session: Session,
    redis_client: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review N3: a corrupt transaction payload on account B must not break account A.

    Runs as a dedicated user: the injected row is committed, and the resolver (correctly)
    fails loudly on any undecryptable row of a user, so it must not leak into other tests.
    """
    isolated = User(email=f"n3-{uuid.uuid4().hex[:8]}@example.invalid")
    pg_session.add(isolated)
    pg_session.flush()
    create_user_key(pg_session, isolated.id)
    pg_session.commit()
    monkeypatch.setattr("processing.accounts.crud_router._STUB_USER_ID", isolated.id)

    broken_ref, healthy_ref = f"SBI_SAV_{_unique_digits()}", f"SBI_SAV_{_unique_digits()}"
    for ref in (broken_ref, healthy_ref):
        pdf = render_statement_pdf(
            "sbi_savings", ref, date(2026, 3, 1), date(2026, 3, 31),
            [Txn("UPI DMART GROCERY", -40_000, date(2026, 3, 9))], 500_000,
        )  # fmt: skip
        ingest_via_confirm(pg_session, redis_client, isolated.id, pdf, ref)
    insert_corrupt_transaction_row(
        pg_session, isolated.id, broken_ref, _statement_id(pg_session, broken_ref)
    )

    healthy = _balance(client, _create_account(client, healthy_ref, "savings"))
    assert healthy["derived_balance_paise"] == "460000"

    with caplog.at_level("ERROR"):
        status_code, code = _error(client, _create_account(client, broken_ref, "savings"))
    assert (status_code, code) == (500, "transaction_decryption_failed")
    assert any(getattr(r, "alert", None) == LEDGER_DECRYPTION_ALERT for r in caplog.records)

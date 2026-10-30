"""End-to-end: registered /api/v1/accounts routes + real confirm() rows → anchored balance.

Covers what the unit tests can't: main.py registration (B-7), the IngestionEvent anchor written
by confirm() (ADR-022), anchor_period_end in the API response, and the B-5 sign on a real
card statement. Routes use the stub user (Phase 5 replaces it), so account refs are unique per
run and the stub user is created once if absent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.events.encryption import create_user_key
from core.events.models import User
from db import get_db
from main import app
from tests.factories.real_rows import Txn, ingest_via_confirm, render_statement_pdf

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
    yield TestClient(app)
    app.dependency_overrides.clear()


def _unique_digits() -> str:
    return str(uuid.uuid4().int)[:6]


def _create_account(client: TestClient, account_ref: str, account_type: str) -> str:
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

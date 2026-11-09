"""Budget routes on real Postgres through main.app (B1, B4, B5; review GAP 5/6).

Proves on the migrated schema what mock sessions could not: the unique key returns 409, any
other integrity failure (a real FK violation) is a structured 500 and never "duplicate",
PATCH changes only the limit and leaves derived utilization untouched, and DELETE removes
the budget row without touching the immutable event log.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.events.encryption import create_user_key
from core.events.models import TransactionEvent, User
from core.events.store import Event, read_since_seq
from core.models.mutable import Budget
from db import get_db
from main import app
from processing.budgets.contract import budget_transactions_from_events, derive_budget_utilization
from processing.classifier.categories import Category
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
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _unique_month() -> str:
    """Budgets are unique per (user, category, month); tests share the stub user."""
    n = uuid.uuid4().int
    return date(2100 + n % 800, 1 + (n // 800) % 12, 1).isoformat()


def _create(client: TestClient, category: str, month: str, target: str = "500000") -> Any:
    return client.post(
        "/api/v1/budgets", json={"category": category, "month": month, "target_paise": target}
    )


def test_create_persists_row_and_returns_201(client: TestClient, pg_session: Session) -> None:
    month = _unique_month()
    response = _create(client, "groceries", month)
    assert response.status_code == 201, response.text
    row = pg_session.get(Budget, uuid.UUID(response.json()["id"]))
    assert row is not None
    assert (row.category, row.month.isoformat(), row.target_paise) == ("groceries", month, 500_000)


def test_duplicate_on_unique_key_is_409_budget_duplicate(client: TestClient) -> None:
    month = _unique_month()
    assert _create(client, "travel", month).status_code == 201
    response = _create(client, "travel", month)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "budget_duplicate"


def test_fk_violation_is_structured_500_not_duplicate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user that doesn't exist violates budgets.user_id → users.id on real Postgres."""
    monkeypatch.setattr("processing.budgets.router._STUB_USER_ID", uuid.uuid4())
    response = _create(client, "shopping", _unique_month())
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "database_integrity_error"
    assert "foreign key" in response.json()["detail"]["message"].lower()


def test_session_still_usable_after_rejected_insert(client: TestClient) -> None:
    month = _unique_month()
    assert _create(client, "utilities", month).status_code == 201
    assert _create(client, "utilities", month).status_code == 409
    assert _create(client, "education", month).status_code == 201  # savepoint rolled back


def test_patch_changes_only_the_limit_and_not_derived_utilization(
    client: TestClient, pg_session: Session, redis_client: Any
) -> None:
    """B4: the limit is mutable; utilization is a derivation over the event log."""
    ref = f"HDFC_SAV_{str(uuid.uuid4().int)[:6]}"
    pdf = render_statement_pdf(
        "hdfc_savings", ref, date(2026, 5, 1), date(2026, 5, 31),
        [Txn("UPI DMART GROCERY", -320_000, date(2026, 5, 12))], 1_000_000,
    )  # fmt: skip
    ingest_via_confirm(pg_session, redis_client, STUB_USER_ID, pdf, ref)

    def ledger() -> list[Event]:  # re-read every time, so "before == after" can fail
        return [e for e in read_since_seq(pg_session, STUB_USER_ID) if e.aggregate_id == ref]

    categories: dict[str, Category] = {
        str(e.payload["idempotency_hash"]): "groceries" for e in ledger()
    }

    def spent() -> int:
        records = budget_transactions_from_events(ledger(), categories)
        return derive_budget_utilization(records, frozenset(), "groceries", date(2026, 5, 1))

    created = _create(client, "groceries", _unique_month()).json()
    before = spent()

    patched = client.patch(f"/api/v1/budgets/{created['id']}", json={"target_paise": 900_000})

    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["target_paise"] == "900000"
    assert (body["category"], body["month"]) == (created["category"], created["month"])
    assert spent() == before == 320_000
    rejected = client.patch(
        f"/api/v1/budgets/{created['id']}", json={"target_paise": 1, "category": "travel"}
    )
    assert rejected.status_code == 422  # category/month are immutable


def test_delete_removes_budget_and_leaves_event_log_untouched(
    client: TestClient, pg_session: Session, redis_client: Any
) -> None:
    """B5: hard delete on the mutable budgets table; transaction_events is unchanged."""
    ref = f"HDFC_SAV_{str(uuid.uuid4().int)[:6]}"
    pdf = render_statement_pdf(
        "hdfc_savings", ref, date(2026, 6, 1), date(2026, 6, 30),
        [Txn("UPI DMART GROCERY", -50_000, date(2026, 6, 3))], 200_000,
    )  # fmt: skip
    ingest_via_confirm(pg_session, redis_client, STUB_USER_ID, pdf, ref)
    count = select(func.count()).select_from(TransactionEvent)
    events_before = pg_session.scalar(count)
    created = _create(client, "groceries", _unique_month()).json()

    deleted = client.delete(f"/api/v1/budgets/{created['id']}")

    assert deleted.status_code == 204
    assert client.get(f"/api/v1/budgets/{created['id']}").status_code == 404
    assert pg_session.get(Budget, uuid.UUID(created["id"])) is None
    assert pg_session.scalar(count) == events_before

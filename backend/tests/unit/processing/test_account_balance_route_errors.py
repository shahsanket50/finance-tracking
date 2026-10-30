"""GET /accounts/{id}/balance maps derivation errors to structured API errors.

A derivation that rejects recorded data (ValueError/TypeError) must surface as a
machine-readable 500 `ledger_integrity_error`, never a bare traceback or a partial number.
An account type with no balance formula is a structured 422, not an integrity error.
The success path on real rows is covered end-to-end in
tests/integration/test_account_balance_route.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_errors import BALANCE_NOT_SUPPORTED, LEDGER_INTEGRITY_ERROR
from db import get_db
from processing.accounts.contract import StatementAnchor
from processing.accounts.crud_router import router


def _client(account_type: str) -> TestClient:
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(
        id=uuid.uuid4(), account_ref="HDFC_SAV_5501", account_type=account_type
    )
    app = FastAPI()
    app.include_router(router)

    def _db() -> Iterator[MagicMock]:
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app, raise_server_exceptions=False)


def _get(client: TestClient) -> tuple[int, dict[str, object]]:
    response = client.get(f"/accounts/{uuid.uuid4()}/balance")
    return response.status_code, response.json()


def test_anchor_for_another_account_is_structured_integrity_error() -> None:
    wrong = StatementAnchor(
        account_ref="SOMEONE_ELSE", period_end=date(2026, 1, 31), closing_balance_paise=1
    )
    with (
        patch("processing.accounts.crud_router.load_statement_anchor", return_value=wrong),
        patch("processing.accounts.crud_router.read_since_seq", return_value=[]),
    ):
        status_code, body = _get(_client("savings"))
    assert status_code == 500
    assert body["detail"]["code"] == LEDGER_INTEGRITY_ERROR  # type: ignore[index]
    assert "SOMEONE_ELSE" in body["detail"]["message"]  # type: ignore[index]


def test_non_int_amount_in_ledger_is_structured_integrity_error() -> None:
    with (
        patch(
            "processing.accounts.crud_router.load_statement_anchor",
            side_effect=TypeError("closing_balance_paise must be int paise, got float"),
        ),
        patch("processing.accounts.crud_router.read_since_seq", return_value=[]),
    ):
        status_code, body = _get(_client("credit_card"))
    assert status_code == 500
    assert body["detail"]["code"] == LEDGER_INTEGRITY_ERROR  # type: ignore[index]


@pytest.mark.parametrize("account_type", ["investment", "fd"])
def test_type_without_balance_formula_is_structured_422(account_type: str) -> None:
    status_code, body = _get(_client(account_type))
    assert status_code == 422
    assert body["detail"]["code"] == BALANCE_NOT_SUPPORTED  # type: ignore[index]


def test_no_anchor_is_null_balance_and_null_anchor_not_zero() -> None:
    with (
        patch("processing.accounts.crud_router.load_statement_anchor", return_value=None),
        patch("processing.accounts.crud_router.read_since_seq", return_value=[]),
    ):
        status_code, body = _get(_client("savings"))
    assert status_code == 200
    assert body["derived_balance_paise"] is None
    assert body["outstanding_liability_paise"] is None
    assert body["anchor_period_end"] is None

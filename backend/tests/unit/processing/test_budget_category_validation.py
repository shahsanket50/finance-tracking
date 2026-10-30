"""Budgets accept expense categories only (owner decision 2026-10-30, PRD §4.3).

income / transfers / investments are flows, not spend; unknown strings are not categories.
Both go through the single EXPENSE_CATEGORIES constant and return 422 at the API.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db import get_db
from processing.budgets.router import router
from processing.classifier.categories import (
    ALL_CATEGORIES,
    EXPENSE_CATEGORIES,
    NON_EXPENSE_CATEGORIES,
)


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)

    def _db() -> Iterator[MagicMock]:
        yield MagicMock()

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_constant_partitions_all_categories() -> None:
    assert set(EXPENSE_CATEGORIES) | NON_EXPENSE_CATEGORIES == set(ALL_CATEGORIES)
    assert not set(EXPENSE_CATEGORIES) & NON_EXPENSE_CATEGORIES
    assert NON_EXPENSE_CATEGORIES == {"income", "transfers", "investments"}


@pytest.mark.parametrize("category", sorted(NON_EXPENSE_CATEGORIES) + ["not_a_category", ""])
def test_non_expense_or_unknown_category_is_422(client: TestClient, category: str) -> None:
    response = client.post(
        "/budgets",
        json={"category": category, "month": "2026-03-01", "target_paise": "100000"},
    )
    assert response.status_code == 422
    assert "expense category" in response.text


@pytest.mark.parametrize("category", EXPENSE_CATEGORIES)
def test_every_expense_category_passes_validation(client: TestClient, category: str) -> None:
    response = client.post(
        "/budgets",
        json={"category": category, "month": "2026-03-01", "target_paise": "100000"},
    )
    assert response.status_code != 422, response.text

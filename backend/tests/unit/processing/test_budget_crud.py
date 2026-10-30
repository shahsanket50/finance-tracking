"""Independent tests for Budget CRUD — B1 acceptance criteria.

Authored from spec (PROJECT_STATE.md B1, PRD §12, CLAUDE.md §3.5) without
reading any implementation file. Implements TRD §11 independent-authoring rule.

Test split:
- Validation tests (422 responses): use TestClient against in-memory FastAPI
  app; Pydantic rejects the request before any DB call, so no DB fixture needed.
- DB-touching tests (201 / 409 / 404): use mock SQLAlchemy sessions and call
  router functions directly, avoiding SQLite UUID incompatibilities.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from processing.budgets.router import create_budget, get_budget, list_budgets
from processing.budgets.schemas import BudgetCreate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STUB_USER = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _mock_budget(
    category: str = "food_dining",
    month: date = date(2026, 3, 1),
    target_paise: int = 500_000,
    budget_id: uuid.UUID | None = None,
) -> MagicMock:
    """Return a mock Budget ORM object with realistic attribute values."""
    b = MagicMock()
    b.id = budget_id or uuid.uuid4()
    b.user_id = _STUB_USER
    b.category = category
    b.month = month
    b.target_paise = target_paise
    b.created_at = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    b.updated_at = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    return b


def _commit_db(captured: list[object]) -> MagicMock:
    """Return a mock DB session that captures the added object on commit."""
    db = MagicMock()

    def _add(obj: object) -> None:
        captured.append(obj)

    db.add.side_effect = _add
    db.commit.return_value = None
    db.refresh.return_value = None
    return db


def _validation_client() -> TestClient:
    """Minimal FastAPI app with the budget router — used for 422 validation tests."""
    from db import get_db
    from processing.budgets.router import router

    app = FastAPI()
    app.include_router(router)

    # Override get_db with a no-op; validation tests never reach the DB layer
    def _noop_db() -> Iterator[MagicMock]:
        db = MagicMock()
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _noop_db
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def validation_client() -> TestClient:
    return _validation_client()


# ---------------------------------------------------------------------------
# B1-1  POST: 201 + correct fields
# ---------------------------------------------------------------------------


class TestBudgetCreate:
    def test_create_returns_budget_response(self) -> None:
        captured: list[object] = []
        db = _commit_db(captured)
        body = BudgetCreate(category="food_dining", month=date(2026, 3, 1), target_paise=500_000)
        result = create_budget(body, db)
        assert result.category == "food_dining"
        assert result.month == date(2026, 3, 1)
        assert result.target_paise == "500000"

    def test_target_paise_serialized_as_string(self) -> None:
        """CLAUDE.md §3.5: money must be str in JSON responses, never a number."""
        captured: list[object] = []
        db = _commit_db(captured)
        body = BudgetCreate(category="groceries", month=date(2026, 4, 1), target_paise=200_000)
        result = create_budget(body, db)
        assert isinstance(result.target_paise, str), (
            f"target_paise must be str, got {type(result.target_paise)}"
        )

    def test_target_paise_accepted_as_json_number_in_request(
        self, validation_client: TestClient
    ) -> None:
        """Pydantic coerces JSON int → int; response must still be str."""
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "transport",
                "month": "2026-05-01",
                "target_paise": 150_000,  # JSON number, not string
            },
        )
        # Validation passes; the mock DB returns without error
        assert resp.status_code == 201

    def test_month_stored_as_first_of_month(self) -> None:
        captured: list[object] = []
        db = _commit_db(captured)
        body = BudgetCreate(category="utilities", month=date(2026, 6, 1), target_paise=300_000)
        result = create_budget(body, db)
        assert result.month == date(2026, 6, 1)

    def test_created_at_and_updated_at_set(self) -> None:
        captured: list[object] = []
        db = _commit_db(captured)
        body = BudgetCreate(category="entertainment", month=date(2026, 7, 1), target_paise=100_000)
        result = create_budget(body, db)
        assert result.created_at is not None
        assert result.updated_at is not None

    def test_id_present_in_response(self) -> None:
        captured: list[object] = []
        db = _commit_db(captured)
        body = BudgetCreate(category="rent_housing", month=date(2026, 3, 1), target_paise=1_500_000)
        result = create_budget(body, db)
        assert result.id is not None
        assert isinstance(result.id, uuid.UUID)

    def test_user_id_present_in_response(self) -> None:
        captured: list[object] = []
        db = _commit_db(captured)
        body = BudgetCreate(category="health_medical", month=date(2026, 3, 1), target_paise=100_000)
        result = create_budget(body, db)
        assert result.user_id == _STUB_USER


# ---------------------------------------------------------------------------
# B1-2  Duplicate (user_id, category, month) → 409
# ---------------------------------------------------------------------------


class TestBudgetDuplicate:
    def test_duplicate_raises_409(self) -> None:
        db = MagicMock()
        db.commit.side_effect = IntegrityError("UNIQUE constraint", {}, Exception("duplicate key"))
        body = BudgetCreate(category="shopping", month=date(2026, 3, 1), target_paise=100_000)
        with pytest.raises(HTTPException) as exc_info:
            create_budget(body, db)
        assert exc_info.value.status_code == 409

    def test_duplicate_error_message_is_descriptive(self) -> None:
        db = MagicMock()
        db.commit.side_effect = IntegrityError("UNIQUE constraint", {}, Exception("duplicate key"))
        body = BudgetCreate(category="shopping", month=date(2026, 3, 1), target_paise=100_000)
        with pytest.raises(HTTPException) as exc_info:
            create_budget(body, db)
        assert "already exists" in exc_info.value.detail.lower()

    def test_db_is_rolled_back_on_duplicate(self) -> None:
        db = MagicMock()
        db.commit.side_effect = IntegrityError("UNIQUE constraint", {}, Exception("duplicate key"))
        body = BudgetCreate(category="shopping", month=date(2026, 3, 1), target_paise=100_000)
        with pytest.raises(HTTPException):
            create_budget(body, db)
        db.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# B1-3  Invalid category → 422
# ---------------------------------------------------------------------------


class TestBudgetCategoryValidation:
    def test_invalid_category_returns_422(self, validation_client: TestClient) -> None:
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "not_a_real_category",
                "month": "2026-03-01",
                "target_paise": "100000",
            },
        )
        assert resp.status_code == 422

    def test_empty_category_returns_422(self, validation_client: TestClient) -> None:
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "",
                "month": "2026-03-01",
                "target_paise": "100000",
            },
        )
        assert resp.status_code == 422

    def test_all_expense_categories_accepted(self) -> None:
        """Owner decision 2026-10-30: only expense categories are budgetable (PRD §4.3)."""
        from processing.classifier.categories import EXPENSE_CATEGORIES

        for cat in EXPENSE_CATEGORIES:
            body = BudgetCreate(category=cat, month=date(2026, 3, 1), target_paise=100_000)
            assert body.category == cat

    def test_non_expense_categories_rejected(self) -> None:
        from processing.classifier.categories import NON_EXPENSE_CATEGORIES

        for cat in NON_EXPENSE_CATEGORIES:
            with pytest.raises(ValidationError):
                BudgetCreate(category=cat, month=date(2026, 3, 1), target_paise=100_000)


# ---------------------------------------------------------------------------
# B1-4  month not first-of-month → 422
# ---------------------------------------------------------------------------


class TestBudgetMonthValidation:
    def test_non_first_of_month_returns_422(self, validation_client: TestClient) -> None:
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "food_dining",
                "month": "2026-03-15",
                "target_paise": "100000",
            },
        )
        assert resp.status_code == 422

    def test_last_day_of_month_returns_422(self, validation_client: TestClient) -> None:
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "food_dining",
                "month": "2026-03-31",
                "target_paise": "100000",
            },
        )
        assert resp.status_code == 422

    def test_invalid_date_string_returns_422(self, validation_client: TestClient) -> None:
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "food_dining",
                "month": "not-a-date",
                "target_paise": "100000",
            },
        )
        assert resp.status_code == 422

    def test_pydantic_rejects_non_first_directly(self) -> None:
        with pytest.raises(ValidationError):
            BudgetCreate(category="food_dining", month=date(2026, 3, 15), target_paise=100_000)


# ---------------------------------------------------------------------------
# B1-5  target_paise zero or negative → 422
# ---------------------------------------------------------------------------


class TestBudgetTargetPaiseValidation:
    def test_zero_target_paise_returns_422(self, validation_client: TestClient) -> None:
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "food_dining",
                "month": "2026-03-01",
                "target_paise": 0,
            },
        )
        assert resp.status_code == 422

    def test_negative_target_paise_returns_422(self, validation_client: TestClient) -> None:
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "food_dining",
                "month": "2026-03-01",
                "target_paise": -100_000,
            },
        )
        assert resp.status_code == 422

    def test_missing_target_paise_returns_422(self, validation_client: TestClient) -> None:
        resp = validation_client.post(
            "/budgets",
            json={
                "category": "food_dining",
                "month": "2026-03-01",
            },
        )
        assert resp.status_code == 422

    def test_pydantic_rejects_zero_directly(self) -> None:
        with pytest.raises(ValidationError):
            BudgetCreate(category="food_dining", month=date(2026, 3, 1), target_paise=0)

    def test_pydantic_rejects_negative_directly(self) -> None:
        with pytest.raises(ValidationError):
            BudgetCreate(category="food_dining", month=date(2026, 3, 1), target_paise=-1)


# ---------------------------------------------------------------------------
# B1-6  GET /budgets and GET /budgets/{id}
# ---------------------------------------------------------------------------


class TestBudgetRead:
    def test_list_budgets_empty(self) -> None:
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        result = list_budgets(db)
        assert result == []

    def test_list_budgets_returns_created(self) -> None:
        b1 = _mock_budget(category="food_dining")
        b2 = _mock_budget(category="groceries")
        db = MagicMock()
        db.scalars.return_value.all.return_value = [b1, b2]
        result = list_budgets(db)
        assert len(result) == 2
        categories = {r.category for r in result}
        assert categories == {"food_dining", "groceries"}

    def test_get_budget_by_id_returns_correct_budget(self) -> None:
        bid = uuid.uuid4()
        b = _mock_budget(category="rent_housing", target_paise=1_500_000, budget_id=bid)
        db = MagicMock()
        db.scalar.return_value = b
        result = get_budget(bid, db)
        assert result.id == bid
        assert result.target_paise == "1500000"

    def test_get_nonexistent_budget_returns_404(self) -> None:
        db = MagicMock()
        db.scalar.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_budget(uuid.uuid4(), db)
        assert exc_info.value.status_code == 404

    def test_list_response_target_paise_is_string(self) -> None:
        b = _mock_budget(target_paise=75_000)
        db = MagicMock()
        db.scalars.return_value.all.return_value = [b]
        result = list_budgets(db)
        assert isinstance(result[0].target_paise, str)
        assert result[0].target_paise == "75000"

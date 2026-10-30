"""Every router's routes are registered in the live app and the committed OpenAPI spec.

Guards against B-7: the Wave 4 account CRUD router and the Wave 5 budgets router were built
and unit-tested but never included in main.py, so they were unreachable in production and
the OpenAPI drift check could not notice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from main import app

COMMITTED_SPEC = Path(__file__).parents[3] / "docs" / "api" / "openapi.json"

EXPECTED: dict[str, set[str]] = {
    "/health": {"get"},
    "/api/v1/accounts": {"get", "post"},
    "/api/v1/accounts/{account_id}": {"get", "patch", "delete"},
    "/api/v1/accounts/{account_id}/balance": {"get"},
    "/api/v1/accounts/{account_ref}/transactions": {"get"},
    "/api/v1/budgets": {"get", "post"},
    "/api/v1/budgets/{budget_id}": {"get", "patch", "delete"},
}


def _methods(spec: dict[str, dict[str, object]], path: str) -> set[str]:
    return {m for m in spec.get(path, {}) if m in {"get", "post", "put", "patch", "delete"}}


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_route_is_live(path: str) -> None:
    live = app.openapi()["paths"]
    assert EXPECTED[path] <= _methods(live, path), f"{path} not registered in main.py"


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_route_is_in_committed_spec(path: str) -> None:
    committed = json.loads(COMMITTED_SPEC.read_text())["paths"]
    assert EXPECTED[path] <= _methods(committed, path), f"{path} missing from openapi.json"


def test_no_router_module_left_unregistered() -> None:
    """Each APIRouter defined under processing/ or ingestion/ contributes a live route."""
    import importlib
    import pkgutil

    from fastapi import APIRouter

    import ingestion
    import processing

    # FastAPI keeps each included router as a wrapper exposing original_router.
    included = {id(r.original_router) for r in app.routes if hasattr(r, "original_router")}
    unregistered: list[str] = []
    for package in (ingestion, processing):
        for module_info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
            if not module_info.name.endswith("router"):
                continue
            module = importlib.import_module(module_info.name)
            router = getattr(module, "router", None)
            if isinstance(router, APIRouter) and router.routes and id(router) not in included:
                unregistered.append(module_info.name)
    assert unregistered == [], f"routers never included in main.py: {unregistered}"

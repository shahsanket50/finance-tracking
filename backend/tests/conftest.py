"""Pytest configuration and fixtures for finance-backend tests."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring a live database (deselect with -m 'not integration')",
    )

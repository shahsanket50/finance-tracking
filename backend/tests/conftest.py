"""Pytest configuration and fixtures for finance-backend tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add repo root to sys.path so ci.guards.* is importable from unit tests.
# The ci/ directory lives at the repo root. In Docker, the repo root is at /repo.
# On local dev, it's one level above the backend directory.
repo_root = Path("/repo") if Path("/repo").exists() else Path(__file__).parents[2]
sys.path.insert(0, str(repo_root))


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring a live database (deselect with -m 'not integration')",
    )

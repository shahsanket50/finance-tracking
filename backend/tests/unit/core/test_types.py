"""Unit tests for C5 newtypes."""
from __future__ import annotations

from core.hashing.types import BasisPoints, FxRate, Paise, Units4dp


def test_paise_is_int_subclass() -> None:
    p = Paise(100)
    assert isinstance(p, int)
    assert int(p) == 100


def test_paise_negative() -> None:
    p = Paise(-5000)
    assert p < 0


def test_paise_arithmetic_preserves_value() -> None:
    a = Paise(1000)
    b = Paise(500)
    assert int(a) + int(b) == 1500


def test_units4dp_repr() -> None:
    u = Units4dp(12345)
    assert "12345" in repr(u)


def test_basis_points_repr() -> None:
    bp = BasisPoints(200)
    assert "200" in repr(bp)


def test_fxrate_is_int() -> None:
    fx = FxRate(83_500_000)  # ~83.5 USD/INR
    assert isinstance(fx, int)

"""C5: Money and financial quantity newtypes.

All financial quantities are scaled integers. No float anywhere.
These classes exist to make type-level intent clear and to catch
accidental mixing of scales at the type checker level.
"""

from __future__ import annotations


class Paise(int):
    """Signed paise amount. 1 paise = ₹0.01. Debits are negative."""

    def __repr__(self) -> str:
        return f"Paise({int(self)})"


class Units4dp(int):
    """Mutual fund units or NAV, scaled to 10⁻⁴. 10000 = 1.0000 units."""

    def __repr__(self) -> str:
        return f"Units4dp({int(self)})"


class BasisPoints(int):
    """Rate or percentage scaled to 10⁻⁴. 10000 bp = 100%. 100 bp = 1%."""

    def __repr__(self) -> str:
        return f"BasisPoints({int(self)})"


class FxRate(int):
    """FX rate scaled to 10⁻⁶. 1_000_000 = 1.000000."""

    def __repr__(self) -> str:
        return f"FxRate({int(self)})"

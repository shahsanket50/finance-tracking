"""Rounding utilities for financial amounts.

largest_remainder: splits an integer total into N parts so they sum exactly.
round_to_nearest_10: Sections 288A/288B tax rounding.

No float arithmetic anywhere.
"""
from __future__ import annotations

from core.hashing.types import Paise


def largest_remainder(total_paise: int, weights: list[int]) -> list[int]:
    """Split total_paise into len(weights) parts proportional to weights.

    Uses the largest-remainder method so parts always sum exactly to total_paise.
    weights need not sum to any specific value — they are relative.

    Args:
        total_paise: The amount to split (signed integer).
        weights: Non-negative integers. Must have at least one positive weight.

    Returns:
        List of paise amounts that sum exactly to total_paise.
    """
    if not weights:
        return []
    total_weight = sum(weights)
    if total_weight == 0:
        raise ValueError("weights must have at least one positive value")

    # Integer quotients
    quotients = [(total_paise * w) // total_weight for w in weights]
    # Remainders (scaled to avoid float)
    # remainder_i = (total_paise * w_i) - quotient_i * total_weight
    remainders = [(total_paise * w) % total_weight for w in weights]

    allocated = sum(quotients)
    shortfall = total_paise - allocated

    # Distribute shortfall to the parts with the largest remainders
    # Sort by remainder descending, break ties by index for determinism
    order = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for i in range(abs(shortfall)):
        idx = order[i]
        if shortfall > 0:
            quotients[idx] += 1
        else:
            quotients[idx] -= 1

    assert sum(quotients) == total_paise, "largest_remainder invariant violated"
    return quotients


def round_to_nearest_10(amount_paise: int) -> int:
    """Round to nearest 10 paise per Sections 288A/288B.

    288A (income): round half-up.
    288B (tax): round half-up.
    Both sections use the same rule: nearest 10, half rounds up.

    Input and output are in paise. The rounding is to the nearest 10 paise
    (i.e., nearest ₹0.10).
    """
    remainder = amount_paise % 10
    if remainder >= 5:
        return amount_paise + (10 - remainder)
    return amount_paise - remainder

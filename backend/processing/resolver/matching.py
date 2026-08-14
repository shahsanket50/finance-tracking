"""Shared candidate-pair scoring primitive for all resolver matchers (ADR-014).

All four matchers use this function to compute match confidence. Calibration
changes (window, scoring formula) are made here once, not in four places.
"""

from datetime import date

from processing.resolver.config import (
    CONFIDENCE_BASE_BP,
    CONFIDENCE_PER_DAY_PENALTY_BP,
    CONFIDENCE_SAME_DAY_BONUS_BP,
)


def score_candidate_pair(
    amount_a_paise: int,
    date_a: date,
    amount_b_paise: int,
    date_b: date,
    window_days: int,
) -> int:
    """Return match confidence in basis points (0–10000), or 0 if no match.

    Matching conditions (both must hold):
    1. |amount_a| == |amount_b|  (amounts equal in magnitude)
    2. |date_a - date_b| <= window_days

    Confidence formula (when matched):
    - Base: 9000 bp
    - Bonus: +500 bp if same-day (date_a == date_b)
    - Penalty: -200 bp per day of separation (after day 0)
    Final clamped to [0, 10000].

    amount_a and amount_b are signed — the caller is responsible for asserting
    correct sign polarity before calling this function. This primitive only
    compares magnitudes.
    """
    if abs(amount_a_paise) != abs(amount_b_paise):
        return 0
    day_diff = abs((date_b - date_a).days)
    if day_diff > window_days:
        return 0
    confidence = CONFIDENCE_BASE_BP + (
        CONFIDENCE_SAME_DAY_BONUS_BP if day_diff == 0 else -CONFIDENCE_PER_DAY_PENALTY_BP * day_diff
    )
    return max(0, min(10000, confidence))

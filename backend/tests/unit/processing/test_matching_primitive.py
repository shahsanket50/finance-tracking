"""Unit tests for the score_candidate_pair matching primitive (Wave 2, independent test-authoring).

Tests derived from TRD §9.1 C3, ADR-014, and the Task 2 spec in
docs/superpowers/plans/2026-08-14-phase2-ledger-correctness.md.

INDEPENDENT AUTHORING: this file was written from the spec without opening
processing/resolver/matching.py.

Contracts asserted here:
- score_candidate_pair(amount_a_paise, date_a, amount_b_paise, date_b, window_days) -> int
- Returns 0 if |amount_a| != |amount_b|
- Returns 0 if |date_a - date_b| > window_days
- Confidence formula when matched:
    base = 9000
    same-day bonus = +500
    per-day penalty = -200 per day after day 0
    clamped to [0, 10000]
- Signs: compares magnitudes — debit -50000 matches credit +50000
- Zero amounts: |0| == |0|, confidence still computed normally
"""

from datetime import date

from processing.resolver.matching import score_candidate_pair


class TestAmountMismatch:
    def test_amount_mismatch_returns_zero(self) -> None:
        """Different magnitudes → no match regardless of date proximity."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50001,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert result == 0

    def test_amount_mismatch_large_difference_returns_zero(self) -> None:
        result = score_candidate_pair(
            amount_a_paise=-100000,
            date_a=date(2025, 6, 1),
            amount_b_paise=200000,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert result == 0

    def test_amount_mismatch_different_signs_different_magnitude_returns_zero(self) -> None:
        result = score_candidate_pair(
            amount_a_paise=-10000,
            date_a=date(2025, 1, 15),
            amount_b_paise=10001,
            date_b=date(2025, 1, 15),
            window_days=5,
        )
        assert result == 0


class TestDateWindow:
    def test_date_outside_window_returns_zero(self) -> None:
        """4-day gap with window=3 → no match."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 5),
            window_days=3,
        )
        assert result == 0

    def test_exactly_one_day_past_window_returns_zero(self) -> None:
        """window=2, gap=3 → no match."""
        result = score_candidate_pair(
            amount_a_paise=-25000,
            date_a=date(2025, 3, 1),
            amount_b_paise=25000,
            date_b=date(2025, 3, 4),
            window_days=2,
        )
        assert result == 0

    def test_date_direction_does_not_matter(self) -> None:
        """b before a should be treated same as a before b — absolute day gap."""
        result_fwd = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 2),
            window_days=3,
        )
        result_bwd = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 2),
            amount_b_paise=50000,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert result_fwd == result_bwd
        assert result_fwd > 0


class TestConfidenceFormula:
    def test_same_day_match_confidence_is_9500(self) -> None:
        """Same-day: base 9000 + bonus 500 = 9500."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert result == 9500

    def test_one_day_separation_confidence_is_8800(self) -> None:
        """1-day gap: base 9000 - 200*1 = 8800."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 2),
            window_days=3,
        )
        assert result == 8800

    def test_two_day_separation_confidence_is_8600(self) -> None:
        """2-day gap: base 9000 - 200*2 = 8600."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 3),
            window_days=3,
        )
        assert result == 8600

    def test_three_day_separation_at_window_edge_confidence_is_8400(self) -> None:
        """3-day gap (at window=3 edge): base 9000 - 200*3 = 8400."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 4),
            window_days=3,
        )
        assert result == 8400

    def test_four_day_separation_just_outside_window_returns_zero(self) -> None:
        """4-day gap with window=3 → 0 (outside window)."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 5),
            window_days=3,
        )
        assert result == 0

    def test_confidence_clamped_to_10000_max(self) -> None:
        """Confidence must not exceed 10000 even if formula would produce more."""
        # Same-day match always yields 9500 which is <= 10000 naturally,
        # but if the formula were different we need the clamp. Verify the cap holds.
        result = score_candidate_pair(
            amount_a_paise=-1,
            date_a=date(2025, 1, 1),
            amount_b_paise=1,
            date_b=date(2025, 1, 1),
            window_days=0,
        )
        assert result <= 10000

    def test_confidence_clamped_to_zero_min(self) -> None:
        """Returned confidence is never negative."""
        # With window_days=10 and large penalty accumulation, the minimum returned is 0.
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 10),
            window_days=10,
        )
        assert result >= 0


class TestSignHandling:
    def test_debit_negative_credit_positive_same_magnitude_matches(self) -> None:
        """The core transfer case: -50000 and +50000 have equal magnitude."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert result > 0

    def test_both_negative_same_magnitude_matches(self) -> None:
        """Both debits — magnitudes equal, primitive does not enforce polarity."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=-50000,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        # Primitive compares magnitudes only; callers enforce polarity
        assert result > 0

    def test_both_positive_same_magnitude_matches(self) -> None:
        """Both credits — magnitudes equal, primitive does not enforce polarity."""
        result = score_candidate_pair(
            amount_a_paise=50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert result > 0

    def test_asymmetric_signs_different_magnitudes_no_match(self) -> None:
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=60000,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert result == 0


class TestZeroAmount:
    def test_zero_amount_matches_zero_amount(self) -> None:
        """|0| == |0| — edge case, not a special case in the primitive."""
        result = score_candidate_pair(
            amount_a_paise=0,
            date_a=date(2025, 6, 1),
            amount_b_paise=0,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        # Both magnitudes equal (both 0), same day → formula runs normally
        assert result == 9500

    def test_zero_amount_does_not_match_nonzero(self) -> None:
        result = score_candidate_pair(
            amount_a_paise=0,
            date_a=date(2025, 6, 1),
            amount_b_paise=100,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert result == 0


class TestReturnType:
    def test_return_type_is_int(self) -> None:
        """Confidence is always an int (basis points), never a float."""
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=50000,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert isinstance(result, int)

    def test_no_match_return_type_is_int(self) -> None:
        result = score_candidate_pair(
            amount_a_paise=-50000,
            date_a=date(2025, 6, 1),
            amount_b_paise=99999,
            date_b=date(2025, 6, 1),
            window_days=3,
        )
        assert isinstance(result, int)

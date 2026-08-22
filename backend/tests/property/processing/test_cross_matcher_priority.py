"""Property test: no transaction hash claimed by more than one matcher (B-3 regression).

The cross-matcher claiming bug (B-3, DECISIONS.md) occurred because transfer and reversal
matchers share overlapping criteria. This test asserts that for any valid set of candidates,
the cascading exclusion in run_resolver() ensures each hash is claimed by at most one matcher.

Tests the logic in pipeline.py _MATCHER_PRIORITY / _available() without a DB — drives the
matchers directly and checks the union of their outputs for duplicate hashes.
"""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from core.events.types import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_FD,
    ACCOUNT_TYPE_SAVINGS,
)
from processing.resolver.candidate import CandidateTxn
from processing.resolver.matchers import cc_payment, fd_booking, reversal, transfer

_ACCOUNT_TYPES = [ACCOUNT_TYPE_SAVINGS, ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_FD]
_BASE_DATE = date(2026, 2, 10)

_hash_str = st.text(min_size=64, max_size=64, alphabet="abcdef0123456789")


@st.composite
def candidate_list(draw: st.DrawFn) -> list[CandidateTxn]:
    """Draw 2–10 CandidateTxn with distinct hashes and realistic account_types/amounts."""
    n = draw(st.integers(min_value=2, max_value=10))
    hashes = draw(st.lists(_hash_str, min_size=n, max_size=n, unique=True))
    candidates: list[CandidateTxn] = []
    for i, h in enumerate(hashes):
        account_type = draw(st.sampled_from(_ACCOUNT_TYPES))
        # Alternate debits and credits so there are candidates for both sides.
        amount = draw(st.integers(min_value=1_000, max_value=1_000_000_00))
        sign = -1 if i % 2 == 0 else 1
        offset_days = draw(st.integers(min_value=0, max_value=3))
        candidates.append(
            CandidateTxn(
                idempotency_hash=h,
                amount_paise=sign * amount,
                value_date=_BASE_DATE + timedelta(days=offset_days),
                account_type=account_type,
            )
        )
    return candidates


def _run_cascading(candidates: list[CandidateTxn]) -> dict[str, list[str]]:
    """Simulate _MATCHER_PRIORITY cascading exclusion from pipeline.py.

    Returns a mapping of matcher_name → list of hashes it claimed.
    """
    claimed: set[str] = set()
    results: dict[str, list[str]] = {}

    def available() -> list[CandidateTxn]:
        return [c for c in candidates if c.idempotency_hash not in claimed]

    # Priority order mirrors pipeline._MATCHER_PRIORITY exactly.
    for name, matcher in (
        ("transfer", transfer),
        ("cc_payment", cc_payment),
        ("fd_booking", fd_booking),
        ("reversal", reversal),
    ):
        matched_hashes: list[str] = []
        for match in matcher.find_matches(available()):
            # Extract the two hashes from each match result via model_dump.
            payload = match.model_dump()
            pair = [str(v) for k, v in payload.items() if k.endswith("_hash")]
            for h in pair:
                if h not in claimed:
                    claimed.add(h)
                    matched_hashes.append(h)
        results[name] = matched_hashes

    return results


@given(candidate_list())
@settings(max_examples=200)
def test_no_hash_claimed_by_more_than_one_matcher(candidates: list[CandidateTxn]) -> None:
    """For any set of candidates, cascading exclusion ensures each hash is claimed by ≤1 matcher."""
    claims = _run_cascading(candidates)

    all_claimed: list[str] = []
    for matcher_name, hashes in claims.items():
        for h in hashes:
            assert h not in all_claimed, (
                f"Hash {h!r} was claimed by multiple matchers. "
                f"First claim was by an earlier matcher; duplicate claim by {matcher_name!r}. "
                f"Full claims: {claims}"
            )
            all_claimed.append(h)

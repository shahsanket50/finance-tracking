"""Property test: no transaction hash claimed by more than one matcher (B-3 regression).

Calls _cascade_matchers() from pipeline.py directly — the production cascade function,
not a reimplementation. If pipeline._cascade_matchers() has a bug, this test catches it.
A reimplementation would only prove that the reimplementation is internally consistent.
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
from processing.resolver.pipeline import _cascade_matchers

_ACCOUNT_TYPES = [ACCOUNT_TYPE_SAVINGS, ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_FD]
_BASE_DATE = date(2026, 2, 10)

_hash_str = st.text(min_size=64, max_size=64, alphabet="abcdef0123456789")


@st.composite
def candidate_list(draw: st.DrawFn) -> list[CandidateTxn]:
    """Draw 2–10 CandidateTxn with distinct hashes, varied account_types and amounts."""
    n = draw(st.integers(min_value=2, max_value=10))
    hashes = draw(st.lists(_hash_str, min_size=n, max_size=n, unique=True))
    candidates: list[CandidateTxn] = []
    for i, h in enumerate(hashes):
        account_type = draw(st.sampled_from(_ACCOUNT_TYPES))
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


@given(candidate_list())
@settings(max_examples=200)
def test_no_hash_claimed_by_more_than_one_matcher(candidates: list[CandidateTxn]) -> None:
    """_cascade_matchers() must never yield a hash already claimed by an earlier matcher."""
    claimed: set[str] = set()
    results = _cascade_matchers(candidates, claimed)

    seen: set[str] = set()
    for _et, h1, h2, _m in results:
        assert h1 not in seen, f"Hash {h1!r} appears in multiple results from _cascade_matchers"
        assert h2 not in seen, f"Hash {h2!r} appears in multiple results from _cascade_matchers"
        seen.add(h1)
        seen.add(h2)

    # `claimed` must equal the exact union of all output hash pairs (no phantom claims).
    result_hashes = {h for _et, h1, h2, _m in results for h in (h1, h2)}
    assert claimed == result_hashes, f"claimed {claimed!r} != result hashes {result_hashes!r}"

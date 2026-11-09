"""Property-based determinism test for the merchant normalizer.

Derived from TRD §9.2 (decisions vs derivations) and CLAUDE.md invariant 3
(event log replay is deterministic). Any correct implementation must satisfy this.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from processing.normalizer.base import normalize_merchant


@given(
    transaction_hash=st.text(min_size=1, max_size=64),
    narration=st.text(min_size=1, max_size=200),
)
@settings(max_examples=100)
def test_normalize_merchant_is_deterministic(transaction_hash: str, narration: str) -> None:
    """For any narration, calling normalize_merchant twice returns the same canonical_name.

    This is the property-based form of N1. It would catch:
    - An implementation that calls the LLM without recording and re-calls on replay.
    - Any implementation where the output depends on mutable module state that changes
      between calls (e.g. a counter, a cache that flushes, random tie-breaking).
    """
    result1 = normalize_merchant(transaction_hash, narration)
    result2 = normalize_merchant(transaction_hash, narration)
    assert result1.canonical_name == result2.canonical_name
    assert result1.method == result2.method

# Phase 2 — Ledger & Correctness: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan wave-by-wave. Tests for critical modules (Wave 2 matchers, Wave 3 projection reducer) are authored in a SEPARATE session from the implementation — see PHASE_PROTOCOL.md §3.

**Goal:** Overlapping statements ingested twice → zero double-counting, provable in an audit view.

**Architecture:** The resolver is a new processing layer (step 3 in the pipeline). It reads TransactionIngested events, detects transfer/payment/FD/reversal patterns, and emits MarkedInternalTransfer / MarkedCCPayment / MarkedFDBooking / MarkedReversal decisions. These are DECISIONS recorded as events — never re-derived at projection time (TRD §9.1 C3, §9.2). The audit view (PRD §15) tracks seen-vs-counted per hash, proving zero double-counting.

**Tech Stack:** Python + FastAPI, Pydantic v2, SQLAlchemy ORM, Alembic migrations, Hypothesis (property tests).

## Global Constraints

- Branch: `feature/phase2`, base commit from latest merged main after PR #4 merge
- All numeric quantities are scaled integers — paise for money (`BIGINT`), basis points for confidence (`INTEGER`, 0–10000). No floats anywhere.
- Resolver decisions MUST be recorded as events (TRD §9.1 C3). Never re-run at projection time — replay reads recorded pairings.
- Match windows are **named constants** in `processing/resolver/config.py`, never bare literals. Each constant has a comment citing the calibration risk in PROJECT_STATE.md.
- `MarkedReversal` is explicitly in scope for Phase 2 (owner confirmed 2026-08-14).
- Pipeline ordering is a hard constraint: resolver (step 3) before categorization (step 5). CLAUDE.md §3.3.
- Money in JSON always as strings. CLAUDE.md §3.5.
- Migrations are forward-only. Never UPDATE/DELETE on `transaction_events`.
- All invariants (CLAUDE.md §2) must remain passing at every wave gate.
- Wave 2 matchers and Wave 3 projection reducer are critical modules — independent test authoring required per PHASE_PROTOCOL.md §3.
- Adjustment (owner, 2026-08-14): Before Wave 2A implementation begins, decide explicitly whether the four matchers share a common matching primitive or are fully independent — document the decision before writing any matcher code.

---

### Task 1: Resolver scaffolding — package structure, config constants, event payload schemas

Wave 1. Builds the foundation Wave 2 depends on. No matching logic yet.

Resolver events (MarkedInternalTransfer etc.) go into the existing `transaction_events` table — TRD §3.1 already lists them there. The payload for each event type is a Pydantic model stored encrypted in the `payload` column. No new DB table is needed.

`reverses_transaction_id` column (TRD §9.5 M4) is deferred to Wave 2 when the reversal matcher is implemented. Add a one-line ADR note to `docs/DECISIONS.md` explaining the deferral.

**Files:**
- Create: `backend/processing/__init__.py` (empty, package marker)
- Create: `backend/processing/resolver/__init__.py` (empty, package marker)
- Create: `backend/processing/resolver/config.py`
- Create: `backend/processing/resolver/events.py`
- Create: `backend/tests/unit/processing/__init__.py` (empty)
- Create: `backend/tests/unit/processing/test_resolver_events.py`
- Modify: `docs/DECISIONS.md` (append ADR for reverses_transaction_id deferral)

**Interfaces:**
- Produces: `TRANSFER_MATCH_WINDOW_DAYS`, `CC_PAYMENT_MATCH_WINDOW_DAYS`, `FD_BOOKING_MATCH_WINDOW_DAYS`, `RESOLVER_CONFIDENCE_THRESHOLD` (int constants from config); `MarkedInternalTransferPayload`, `MarkedCCPaymentPayload`, `MarkedFDBookingPayload`, `MarkedReversalPayload` (frozen Pydantic BaseModel); `RESOLVER_EVENT_TYPES` (frozenset[str])
- Consumes: pydantic (already in pyproject.toml)

**`backend/processing/resolver/config.py` — exact content:**

```python
"""Resolver configuration constants.

All match windows are named constants — never bare literals in matching logic.
Calibration risk: these values are working assumptions; calibrate against real
statement data before Phase 2 closes. See PROJECT_STATE.md §Standing risks.
"""

# Calendar days (IST) a savings-account debit may precede or follow a paired credit.
# Calibration is a standing risk — see PROJECT_STATE.md.
TRANSFER_MATCH_WINDOW_DAYS: int = 3
CC_PAYMENT_MATCH_WINDOW_DAYS: int = 3  # CC bill typically clears 1–3 days after savings debit
FD_BOOKING_MATCH_WINDOW_DAYS: int = 3

# Confidence floor below which a resolver match is not auto-committed (basis points, 0–10000).
RESOLVER_CONFIDENCE_THRESHOLD: int = 8500
```

**`backend/processing/resolver/events.py` — exact content:**

```python
"""Resolver event payload schemas (TRD §9.1 C3, §9.2).

Each class defines the payload for a resolver DECISION event stored in
transaction_events with a resolver event_type. These payloads are encrypted
and stored in the payload column.

These are DECISIONS — recorded once at resolve time, never re-derived during
replay. Recomputing them on replay would break Invariant 3 (replay determinism).

All four resolver event types are in scope for Phase 2 (owner confirmed 2026-08-14):
  MarkedInternalTransfer — savings↔savings pair (both legs excluded from totals)
  MarkedCCPayment        — savings debit + CC bill credit (both legs excluded)
  MarkedFDBooking        — savings debit + FD creation credit (both legs excluded)
  MarkedReversal         — original debit + reversal credit (both legs excluded)

reverses_transaction_id column (TRD §9.5 M4) is deferred to Wave 2.
"""

from pydantic import BaseModel, Field


class MarkedInternalTransferPayload(BaseModel):
    """Payload for MarkedInternalTransfer event_type."""

    model_config = {"frozen": True}

    debit_hash: str = Field(..., description="Idempotency hash of the debit leg")
    credit_hash: str = Field(..., description="Idempotency hash of the credit leg")
    matched_by: str = Field(..., description="Resolver algorithm version, e.g. 'transfer_v1'")
    confidence: int = Field(..., ge=0, le=10000, description="Match confidence in basis points")


class MarkedCCPaymentPayload(BaseModel):
    """Payload for MarkedCCPayment event_type."""

    model_config = {"frozen": True}

    savings_debit_hash: str = Field(..., description="Idempotency hash of the savings debit")
    cc_credit_hash: str = Field(..., description="Idempotency hash of the CC bill credit")
    matched_by: str
    confidence: int = Field(..., ge=0, le=10000)
    match_window_days: int = Field(..., description="Actual window used (from config constant)")


class MarkedFDBookingPayload(BaseModel):
    """Payload for MarkedFDBooking event_type."""

    model_config = {"frozen": True}

    savings_debit_hash: str = Field(..., description="Idempotency hash of the savings debit")
    fd_credit_hash: str = Field(..., description="Idempotency hash of the FD credit")
    matched_by: str
    confidence: int = Field(..., ge=0, le=10000)
    match_window_days: int = Field(..., description="Actual window used (from config constant)")


class MarkedReversalPayload(BaseModel):
    """Payload for MarkedReversal event_type (TRD §9.5 M4).

    reverses_transaction_id column on transaction_events is deferred to Wave 2.
    """

    model_config = {"frozen": True}

    original_hash: str = Field(..., description="Idempotency hash of the original transaction")
    reversal_hash: str = Field(..., description="Idempotency hash of the reversal transaction")
    matched_by: str
    confidence: int = Field(..., ge=0, le=10000)


# Canonical event_type strings for resolver events — exactly what goes in
# transaction_events.event_type when the resolver records a decision.
RESOLVER_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "MarkedInternalTransfer",
        "MarkedCCPayment",
        "MarkedFDBooking",
        "MarkedReversal",
    }
)
```

**`backend/tests/unit/processing/test_resolver_events.py` — exact content:**

```python
"""Unit tests for resolver event payload schemas and config constants (Wave 1).

Tests derived from TRD §9.1 C3, §9.2, and §9.5 M4.
"""

import pytest
from pydantic import ValidationError

from processing.resolver.config import (
    CC_PAYMENT_MATCH_WINDOW_DAYS,
    FD_BOOKING_MATCH_WINDOW_DAYS,
    RESOLVER_CONFIDENCE_THRESHOLD,
    TRANSFER_MATCH_WINDOW_DAYS,
)
from processing.resolver.events import (
    RESOLVER_EVENT_TYPES,
    MarkedCCPaymentPayload,
    MarkedFDBookingPayload,
    MarkedInternalTransferPayload,
    MarkedReversalPayload,
)


def test_four_resolver_event_types_defined() -> None:
    """All four resolver event types confirmed in scope (owner, 2026-08-14)."""
    assert RESOLVER_EVENT_TYPES == {
        "MarkedInternalTransfer",
        "MarkedCCPayment",
        "MarkedFDBooking",
        "MarkedReversal",
    }


def test_marked_internal_transfer_valid() -> None:
    p = MarkedInternalTransferPayload(
        debit_hash="a" * 64,
        credit_hash="b" * 64,
        matched_by="transfer_v1",
        confidence=9500,
    )
    assert p.confidence == 9500
    assert p.debit_hash != p.credit_hash


def test_marked_cc_payment_valid() -> None:
    p = MarkedCCPaymentPayload(
        savings_debit_hash="a" * 64,
        cc_credit_hash="b" * 64,
        matched_by="cc_payment_v1",
        confidence=9000,
        match_window_days=CC_PAYMENT_MATCH_WINDOW_DAYS,
    )
    assert p.match_window_days == CC_PAYMENT_MATCH_WINDOW_DAYS


def test_marked_fd_booking_valid() -> None:
    p = MarkedFDBookingPayload(
        savings_debit_hash="a" * 64,
        fd_credit_hash="b" * 64,
        matched_by="fd_booking_v1",
        confidence=9000,
        match_window_days=FD_BOOKING_MATCH_WINDOW_DAYS,
    )
    assert p.match_window_days == FD_BOOKING_MATCH_WINDOW_DAYS


def test_marked_reversal_valid() -> None:
    p = MarkedReversalPayload(
        original_hash="a" * 64,
        reversal_hash="b" * 64,
        matched_by="reversal_v1",
        confidence=9500,
    )
    assert p.original_hash != p.reversal_hash


def test_confidence_above_max_rejected() -> None:
    with pytest.raises(ValidationError):
        MarkedInternalTransferPayload(
            debit_hash="a" * 64,
            credit_hash="b" * 64,
            matched_by="v1",
            confidence=10001,
        )


def test_confidence_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        MarkedInternalTransferPayload(
            debit_hash="a" * 64,
            credit_hash="b" * 64,
            matched_by="v1",
            confidence=-1,
        )


def test_payloads_are_frozen() -> None:
    """Frozen Pydantic models — prevent accidental mutation after construction."""
    p = MarkedInternalTransferPayload(
        debit_hash="a" * 64,
        credit_hash="b" * 64,
        matched_by="v1",
        confidence=9000,
    )
    with pytest.raises(Exception):
        p.confidence = 5000  # type: ignore[misc]


def test_match_window_constants_are_positive_ints() -> None:
    for val in (
        TRANSFER_MATCH_WINDOW_DAYS,
        CC_PAYMENT_MATCH_WINDOW_DAYS,
        FD_BOOKING_MATCH_WINDOW_DAYS,
    ):
        assert isinstance(val, int)
        assert val > 0


def test_resolver_confidence_threshold_in_range() -> None:
    assert isinstance(RESOLVER_CONFIDENCE_THRESHOLD, int)
    assert 0 < RESOLVER_CONFIDENCE_THRESHOLD <= 10000


def test_transfer_payload_round_trips_through_dict() -> None:
    """Payload survives dict() → model reconstruct (Pydantic serialization)."""
    original = MarkedInternalTransferPayload(
        debit_hash="a" * 64,
        credit_hash="b" * 64,
        matched_by="transfer_v1",
        confidence=9500,
    )
    reconstructed = MarkedInternalTransferPayload(**original.model_dump())
    assert reconstructed == original


def test_all_payload_classes_are_importable() -> None:
    """All four payload classes must be importable from events module."""
    from processing.resolver.events import (  # noqa: F401
        MarkedCCPaymentPayload,
        MarkedFDBookingPayload,
        MarkedInternalTransferPayload,
        MarkedReversalPayload,
    )
```

- [ ] **Step 1:** Create the five new files (3 package `__init__.py`s, `config.py`, `events.py`) with exact content above.
- [ ] **Step 2:** Create `backend/tests/unit/processing/__init__.py` (empty) and `test_resolver_events.py` with exact content above.
- [ ] **Step 3:** Run tests:
  ```bash
  cd backend && PYTHONPATH=. python3 -m pytest tests/unit/processing/test_resolver_events.py -v
  ```
  Expected: 12 tests, all PASS.
- [ ] **Step 4:** Run mypy:
  ```bash
  cd backend && python3 -m mypy --config-file pyproject.toml --explicit-package-bases processing/resolver/ -v
  ```
  Expected: no errors.
- [ ] **Step 5:** Append ADR to `docs/DECISIONS.md`:
  ```markdown
  ## ADR-012: reverses_transaction_id column deferred to Wave 2

  **Date:** 2026-08-14
  **Status:** Decided

  TRD §9.5 M4 specifies a `reverses_transaction_id` FK column on `transaction_events`
  for reversals. Wave 1 defers this column to Wave 2 (reversal matcher implementation),
  when the exact FK semantics (UUID vs idempotency hash, nullable vs required) can be
  decided with the matcher code in hand. The `MarkedReversalPayload` stores
  `original_hash` and `reversal_hash` in the encrypted payload column in the interim.
  ```
- [ ] **Step 6:** Commit:
  ```bash
  git add backend/processing/ backend/tests/unit/processing/ docs/DECISIONS.md
  git commit -m "Wave 1: resolver scaffolding — config constants + event payload schemas

  Creates backend/processing/resolver/ with:
  - config.py: TRANSFER/CC_PAYMENT/FD_BOOKING_MATCH_WINDOW_DAYS, RESOLVER_CONFIDENCE_THRESHOLD
    (named constants, never bare literals; calibration risk noted per PROJECT_STATE.md)
  - events.py: MarkedInternalTransferPayload, MarkedCCPaymentPayload,
    MarkedFDBookingPayload, MarkedReversalPayload (frozen Pydantic models),
    RESOLVER_EVENT_TYPES frozenset

  MarkedReversal is explicitly in scope for Phase 2 (owner confirmed 2026-08-14).
  reverses_transaction_id column (TRD §9.5 M4) deferred to Wave 2 — ADR-012.

  12/12 unit tests pass. mypy clean."
  ```

---

### Task 2: Wave 2 — Matcher implementations (CRITICAL — independent test authoring)

Decision recorded: ADR-014 — four matchers share a common primitive (`score_candidate_pair` in `processing/resolver/matching.py`).

**Architecture:**
- `processing/resolver/matching.py` — shared primitive `score_candidate_pair`
- `processing/resolver/matchers/transfer.py` — calls primitive, emits `MarkedInternalTransferPayload`
- `processing/resolver/matchers/cc_payment.py` — calls primitive, emits `MarkedCCPaymentPayload`
- `processing/resolver/matchers/fd_booking.py` — calls primitive, emits `MarkedFDBookingPayload`
- `processing/resolver/matchers/reversal.py` — calls primitive, emits `MarkedReversalPayload`

**`processing/resolver/matching.py` — shared primitive:**

```python
"""Shared candidate-pair scoring primitive for all resolver matchers (ADR-014).

All four matchers use this function to compute match confidence. Calibration
changes (window, scoring formula) are made here once, not in four places.
"""

from datetime import date


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
    confidence = 9000 + (500 if day_diff == 0 else -200 * day_diff)
    return max(0, min(10000, confidence))
```

**Matcher contract (all four matchers follow this pattern):**

Each matcher exposes one function:
```python
def find_matches(
    candidates: list[CandidateTxn],
) -> list[<PayloadType>]:
```

Where `CandidateTxn` is:
```python
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class CandidateTxn:
    idempotency_hash: str
    amount_paise: int   # signed; debits negative, credits positive
    value_date: date
    account_type: str   # e.g. "savings", "credit_card", "fd"
```

Each matcher filters candidates by sign polarity and account type, then calls `score_candidate_pair`, and returns a list of payload objects for pairs that exceed `RESOLVER_CONFIDENCE_THRESHOLD`.

**Files:**
- Create: `backend/processing/resolver/matching.py`
- Create: `backend/processing/resolver/matchers/__init__.py` (empty)
- Create: `backend/processing/resolver/matchers/transfer.py`
- Create: `backend/processing/resolver/matchers/cc_payment.py`
- Create: `backend/processing/resolver/matchers/fd_booking.py`
- Create: `backend/processing/resolver/matchers/reversal.py`
- Create: `backend/processing/resolver/candidate.py` (CandidateTxn dataclass)
- Create: `backend/tests/unit/processing/test_matching_primitive.py`
- Create: `backend/tests/unit/processing/test_matchers.py`

**Interfaces:**
- Produces: `score_candidate_pair(amount_a, date_a, amount_b, date_b, window_days) → int`; `CandidateTxn` dataclass; `find_matches(candidates) → list[PayloadType]` for each matcher
- Consumes: `TRANSFER_MATCH_WINDOW_DAYS`, `CC_PAYMENT_MATCH_WINDOW_DAYS`, `FD_BOOKING_MATCH_WINDOW_DAYS`, `RESOLVER_CONFIDENCE_THRESHOLD` from `processing.resolver.config`; payload classes from `processing.resolver.events`

**`processing/resolver/candidate.py` — exact content:**

```python
"""CandidateTxn: the input unit for all resolver matchers."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CandidateTxn:
    idempotency_hash: str
    amount_paise: int
    value_date: date
    account_type: str
```

**`processing/resolver/matchers/transfer.py` — exact content:**

```python
"""Transfer matcher: detects savings↔savings internal transfer pairs (ADR-014)."""

from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import (
    RESOLVER_CONFIDENCE_THRESHOLD,
    TRANSFER_MATCH_WINDOW_DAYS,
)
from processing.resolver.events import MarkedInternalTransferPayload
from processing.resolver.matching import score_candidate_pair


def find_matches(candidates: list[CandidateTxn]) -> list[MarkedInternalTransferPayload]:
    """Find savings↔savings transfer pairs among candidates.

    Criteria:
    - Both legs must have account_type == "savings"
    - One leg is a debit (amount_paise < 0), the other a credit (amount_paise > 0)
    - Magnitudes equal, within TRANSFER_MATCH_WINDOW_DAYS
    - Confidence >= RESOLVER_CONFIDENCE_THRESHOLD
    """
    debits = [c for c in candidates if c.account_type == "savings" and c.amount_paise < 0]
    credits = [c for c in candidates if c.account_type == "savings" and c.amount_paise > 0]
    results: list[MarkedInternalTransferPayload] = []
    matched_hashes: set[str] = set()
    for debit in debits:
        if debit.idempotency_hash in matched_hashes:
            continue
        for credit in credits:
            if credit.idempotency_hash in matched_hashes:
                continue
            confidence = score_candidate_pair(
                debit.amount_paise, debit.value_date,
                credit.amount_paise, credit.value_date,
                TRANSFER_MATCH_WINDOW_DAYS,
            )
            if confidence >= RESOLVER_CONFIDENCE_THRESHOLD:
                results.append(MarkedInternalTransferPayload(
                    debit_hash=debit.idempotency_hash,
                    credit_hash=credit.idempotency_hash,
                    matched_by="transfer_v1",
                    confidence=confidence,
                ))
                matched_hashes.add(debit.idempotency_hash)
                matched_hashes.add(credit.idempotency_hash)
                break
    return results
```

**`processing/resolver/matchers/cc_payment.py` — exact content:**

```python
"""CC payment matcher: savings debit + credit_card credit pair (ADR-014)."""

from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import (
    CC_PAYMENT_MATCH_WINDOW_DAYS,
    RESOLVER_CONFIDENCE_THRESHOLD,
)
from processing.resolver.events import MarkedCCPaymentPayload
from processing.resolver.matching import score_candidate_pair


def find_matches(candidates: list[CandidateTxn]) -> list[MarkedCCPaymentPayload]:
    """Find savings-debit + credit-card-credit pairs.

    Criteria:
    - Debit leg: account_type == "savings", amount_paise < 0
    - Credit leg: account_type == "credit_card", amount_paise > 0
    - Magnitudes equal, within CC_PAYMENT_MATCH_WINDOW_DAYS
    - Confidence >= RESOLVER_CONFIDENCE_THRESHOLD
    """
    debits = [c for c in candidates if c.account_type == "savings" and c.amount_paise < 0]
    credits = [c for c in candidates if c.account_type == "credit_card" and c.amount_paise > 0]
    results: list[MarkedCCPaymentPayload] = []
    matched_hashes: set[str] = set()
    for debit in debits:
        if debit.idempotency_hash in matched_hashes:
            continue
        for credit in credits:
            if credit.idempotency_hash in matched_hashes:
                continue
            confidence = score_candidate_pair(
                debit.amount_paise, debit.value_date,
                credit.amount_paise, credit.value_date,
                CC_PAYMENT_MATCH_WINDOW_DAYS,
            )
            if confidence >= RESOLVER_CONFIDENCE_THRESHOLD:
                results.append(MarkedCCPaymentPayload(
                    savings_debit_hash=debit.idempotency_hash,
                    cc_credit_hash=credit.idempotency_hash,
                    matched_by="cc_payment_v1",
                    confidence=confidence,
                    match_window_days=CC_PAYMENT_MATCH_WINDOW_DAYS,
                ))
                matched_hashes.add(debit.idempotency_hash)
                matched_hashes.add(credit.idempotency_hash)
                break
    return results
```

**`processing/resolver/matchers/fd_booking.py` — exact content:**

```python
"""FD booking matcher: savings debit + FD credit pair (ADR-014)."""

from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import (
    FD_BOOKING_MATCH_WINDOW_DAYS,
    RESOLVER_CONFIDENCE_THRESHOLD,
)
from processing.resolver.events import MarkedFDBookingPayload
from processing.resolver.matching import score_candidate_pair


def find_matches(candidates: list[CandidateTxn]) -> list[MarkedFDBookingPayload]:
    """Find savings-debit + FD-credit pairs.

    Criteria:
    - Debit leg: account_type == "savings", amount_paise < 0
    - Credit leg: account_type == "fd", amount_paise > 0
    - Magnitudes equal, within FD_BOOKING_MATCH_WINDOW_DAYS
    - Confidence >= RESOLVER_CONFIDENCE_THRESHOLD
    """
    debits = [c for c in candidates if c.account_type == "savings" and c.amount_paise < 0]
    credits = [c for c in candidates if c.account_type == "fd" and c.amount_paise > 0]
    results: list[MarkedFDBookingPayload] = []
    matched_hashes: set[str] = set()
    for debit in debits:
        if debit.idempotency_hash in matched_hashes:
            continue
        for credit in credits:
            if credit.idempotency_hash in matched_hashes:
                continue
            confidence = score_candidate_pair(
                debit.amount_paise, debit.value_date,
                credit.amount_paise, credit.value_date,
                FD_BOOKING_MATCH_WINDOW_DAYS,
            )
            if confidence >= RESOLVER_CONFIDENCE_THRESHOLD:
                results.append(MarkedFDBookingPayload(
                    savings_debit_hash=debit.idempotency_hash,
                    fd_credit_hash=credit.idempotency_hash,
                    matched_by="fd_booking_v1",
                    confidence=confidence,
                    match_window_days=FD_BOOKING_MATCH_WINDOW_DAYS,
                ))
                matched_hashes.add(debit.idempotency_hash)
                matched_hashes.add(credit.idempotency_hash)
                break
    return results
```

**`processing/resolver/matchers/reversal.py` — exact content:**

```python
"""Reversal matcher: original transaction + reversal credit pair (ADR-014)."""

from processing.resolver.candidate import CandidateTxn
from processing.resolver.config import (
    RESOLVER_CONFIDENCE_THRESHOLD,
    TRANSFER_MATCH_WINDOW_DAYS,
)
from processing.resolver.events import MarkedReversalPayload
from processing.resolver.matching import score_candidate_pair

# Reversals use the same window as transfers — a reversal typically posts within days.
_REVERSAL_WINDOW_DAYS = TRANSFER_MATCH_WINDOW_DAYS


def find_matches(candidates: list[CandidateTxn]) -> list[MarkedReversalPayload]:
    """Find original-debit + reversal-credit pairs.

    Criteria:
    - Original leg: amount_paise < 0 (debit)
    - Reversal leg: amount_paise > 0 (credit), same account_type as original
    - Magnitudes equal, within _REVERSAL_WINDOW_DAYS
    - Confidence >= RESOLVER_CONFIDENCE_THRESHOLD
    """
    debits = [c for c in candidates if c.amount_paise < 0]
    credits = [c for c in candidates if c.amount_paise > 0]
    results: list[MarkedReversalPayload] = []
    matched_hashes: set[str] = set()
    for debit in debits:
        if debit.idempotency_hash in matched_hashes:
            continue
        for credit in credits:
            if credit.idempotency_hash in matched_hashes:
                continue
            if credit.account_type != debit.account_type:
                continue
            confidence = score_candidate_pair(
                debit.amount_paise, debit.value_date,
                credit.amount_paise, credit.value_date,
                _REVERSAL_WINDOW_DAYS,
            )
            if confidence >= RESOLVER_CONFIDENCE_THRESHOLD:
                results.append(MarkedReversalPayload(
                    original_hash=debit.idempotency_hash,
                    reversal_hash=credit.idempotency_hash,
                    matched_by="reversal_v1",
                    confidence=confidence,
                ))
                matched_hashes.add(debit.idempotency_hash)
                matched_hashes.add(credit.idempotency_hash)
                break
    return results
```

**Test cases for independent test authoring (test author reads ONLY this spec + contract, not the implementation):**

`test_matching_primitive.py` must cover:
- Amount mismatch → 0
- Date outside window → 0
- Same-day match → confidence = 9500 (9000 + 500)
- 1-day separation → confidence = 8800 (9000 - 200)
- 3-day separation (at window edge) → confidence = 8400 (9000 - 600)
- 4-day separation (just outside window=3) → 0
- Confidence clamped to [0, 10000] — a formula that would overflow still caps
- Signs: |amount_a| == |amount_b| regardless of sign (debit –50000 matches credit +50000)
- Zero amount: |0| == |0| but confidence still computed (not a special case)

`test_matchers.py` must cover (per matcher):

*transfer matcher:*
- savings debit + savings credit, same amount, same day → match returned
- savings debit + savings credit, both credits → no match (no debit)
- savings debit + CC credit → no match (wrong account_type for transfer)
- Two debits, one credit → at most one match (no double-use of a leg)
- Confidence below RESOLVER_CONFIDENCE_THRESHOLD (e.g. forced by window=0 but date 4 days apart) → no result

*cc_payment matcher:*
- savings debit + credit_card credit, same amount, same day → match
- savings debit + savings credit → no match (credit must be credit_card)
- confidence threshold respected

*fd_booking matcher:*
- savings debit + fd credit, same amount → match
- savings debit + savings credit → no match
- confidence threshold respected

*reversal matcher:*
- savings debit + savings credit, same amount, same account_type → match
- savings debit + credit_card credit → no match (account_type mismatch)
- confidence threshold respected

- [ ] **Step 1 (TEST-AUTHORING SESSION):** Dispatch independent test-authoring subagent. It reads this spec (Task 2 section) and the Wave 1 contracts (`events.py`, `config.py`, `candidate.py` spec above). It does NOT open or read any implementation file. It writes `test_matching_primitive.py` and `test_matchers.py`. Commits with message `"Wave 2 (independent test-authoring): matching primitive + matcher tests"`.

- [ ] **Step 2 (IMPLEMENTATION SESSION):** Dispatch implementation subagent. It reads this spec and the test files (to understand contracts), writes `matching.py`, `candidate.py`, `matchers/*.py`. Commits with message `"Wave 2: matching primitive + four matchers"`.

- [ ] **Step 3:** Run all Wave 2 tests:
  ```bash
  cd backend && PYTHONPATH=. python3 -m pytest tests/unit/processing/test_matching_primitive.py tests/unit/processing/test_matchers.py -v
  ```
  Expected: all PASS.

- [ ] **Step 4:** Run mypy:
  ```bash
  cd backend && python3 -m mypy --config-file pyproject.toml --explicit-package-bases processing/resolver/ -v
  ```
  Expected: no errors.

- [ ] **Step 5:** Confirm independence: test commit hash must predate implementation commit hash in `git log`.

---

### Task 3: Wave 3 — Projection reducer for resolver events (CRITICAL — independent test authoring)

**What this does:** Registers a `"transactions_view"` projection reducer with the existing builder registry. The reducer builds a state containing all ingested transactions, the set of hashes excluded by resolver decisions, and derived totals. Resolver events are READ from the event log (per TRD §9.1 C3) — the reducer never calls matcher logic.

**Architecture:**
- `processing/resolver/reducer.py` — defines initial state + reducer, calls `register_reducer`
- Modify: `backend/core/projections/builder.py` — import reducer to trigger registration
- `backend/tests/unit/processing/test_transactions_view_reducer.py` — independently authored tests

**Event contracts (what the reducer reads from `Event.payload`):**

`TransactionIngested` payload fields used by reducer:
```python
{
    "idempotency_hash": str,   # 64-char hex
    "amount_paise": int,       # signed (debits negative)
    "value_date": str,         # ISO date "YYYY-MM-DD"
    "account_ref": str,
    "canonical_narration": str | None,
    "transaction_type": str,   # "income" | "expense" | "transfer" | "investment"
}
```

Resolver event payload fields used by reducer (read from `Event.payload`):

| event_type | hash fields to exclude |
|---|---|
| `MarkedInternalTransfer` | `debit_hash`, `credit_hash` |
| `MarkedCCPayment` | `savings_debit_hash`, `cc_credit_hash` |
| `MarkedFDBooking` | `savings_debit_hash`, `fd_credit_hash` |
| `MarkedReversal` | `original_hash`, `reversal_hash` |

Unknown `event_type` values are silently ignored (pass-through — forward compatibility).

**State structure:**
```python
{
    "transactions": [
        {
            "idempotency_hash": str,
            "amount_paise": int,
            "value_date": str,
            "account_ref": str,
            "canonical_narration": str | None,
            "transaction_type": str,
        },
        ...
    ],
    "excluded_hashes": list[str],   # JSON-serializable; use set() for O(1) lookups internally
    "totals": {
        "income_paise": int,        # sum of amount_paise for non-excluded income transactions
        "expense_paise": int,       # abs() sum of amount_paise for non-excluded expense transactions (positive)
        "excluded_count": int,      # number of transactions excluded from totals
    }
}
```

**`processing/resolver/reducer.py` — exact content:**

```python
"""Transactions-view projection reducer (TRD §9.1 C3, §9.2).

Builds a view of all ingested transactions, tracking which are excluded by
resolver decisions (internal transfers, CC payments, FD bookings, reversals).

This reducer reads resolver DECISIONS from recorded events — it never calls
matcher logic. Calling matchers here would break Invariant 3 (replay
determinism) and violate TRD §9.2 (decisions vs derivations).

Registers the 'transactions_view' projection type with the builder registry.
"""

from __future__ import annotations

from core.events.store import Event
from core.projections.builder import register_reducer


def _initial_state() -> dict[str, object]:
    return {
        "transactions": [],
        "excluded_hashes": [],
        "totals": {
            "income_paise": 0,
            "expense_paise": 0,
            "excluded_count": 0,
        },
    }


def _reducer(state: dict[str, object], event: Event) -> dict[str, object]:
    transactions: list[dict[str, object]] = list(
        state["transactions"]  # type: ignore[arg-type]
    )
    excluded: list[str] = list(state["excluded_hashes"])  # type: ignore[arg-type]

    if event.event_type == "TransactionIngested":
        p = event.payload
        transactions.append(
            {
                "idempotency_hash": p["idempotency_hash"],
                "amount_paise": p["amount_paise"],
                "value_date": p["value_date"],
                "account_ref": p.get("account_ref", event.aggregate_id),
                "canonical_narration": p.get("canonical_narration"),
                "transaction_type": p.get("transaction_type", "expense"),
            }
        )
    elif event.event_type == "MarkedInternalTransfer":
        p = event.payload
        excluded.append(str(p["debit_hash"]))
        excluded.append(str(p["credit_hash"]))
    elif event.event_type == "MarkedCCPayment":
        p = event.payload
        excluded.append(str(p["savings_debit_hash"]))
        excluded.append(str(p["cc_credit_hash"]))
    elif event.event_type == "MarkedFDBooking":
        p = event.payload
        excluded.append(str(p["savings_debit_hash"]))
        excluded.append(str(p["fd_credit_hash"]))
    elif event.event_type == "MarkedReversal":
        p = event.payload
        excluded.append(str(p["original_hash"]))
        excluded.append(str(p["reversal_hash"]))
    # Unknown event types are silently ignored (forward compatibility).

    excluded_set = set(excluded)
    active = [t for t in transactions if t["idempotency_hash"] not in excluded_set]

    income_paise = sum(
        int(t["amount_paise"])  # type: ignore[arg-type]
        for t in active
        if t.get("transaction_type") == "income"
    )
    expense_paise = sum(
        abs(int(t["amount_paise"]))  # type: ignore[arg-type]
        for t in active
        if t.get("transaction_type") == "expense"
    )
    excluded_count = len(transactions) - len(active)

    return {
        "transactions": transactions,
        "excluded_hashes": excluded,
        "totals": {
            "income_paise": income_paise,
            "expense_paise": expense_paise,
            "excluded_count": excluded_count,
        },
    }


register_reducer("transactions_view", _initial_state, _reducer)
```

**Modification to `backend/core/projections/builder.py`:**

Add this import at the end of the existing imports block (after the `register_reducer` call for `events_list`):

```python
# Register transactions_view reducer (side-effect import — must stay at module level)
import processing.resolver.reducer  # noqa: F401, E402
```

**Test cases for independent test authoring:**

`test_transactions_view_reducer.py` must cover:

*Basic ingestion:*
- Empty event list → `{"transactions": [], "excluded_hashes": [], "totals": {"income_paise": 0, "expense_paise": 0, "excluded_count": 0}}`
- One `TransactionIngested` (expense –50000) → transactions has 1 entry, totals.expense_paise == 50000, excluded_count == 0
- One `TransactionIngested` (income +100000) → totals.income_paise == 100000
- Two `TransactionIngested` events → transactions has 2 entries, totals accumulate correctly

*Exclusion:*
- `TransactionIngested` then `MarkedInternalTransfer` covering its hash → excluded_count == 1, totals.expense_paise == 0 (INVARIANT 4)
- `MarkedCCPayment` excludes both `savings_debit_hash` and `cc_credit_hash`
- `MarkedFDBooking` excludes both `savings_debit_hash` and `fd_credit_hash`
- `MarkedReversal` excludes both `original_hash` and `reversal_hash`
- Resolver event before `TransactionIngested` for its hash (out-of-order) → excluded_hashes contains the hash; when the TransactionIngested arrives, it is still excluded

*Invariant 4 — no double-count in totals:*
- Two savings accounts, each with debit/credit pair, `MarkedInternalTransfer` covering both → totals.expense_paise == 0, totals.income_paise == 0
- An excluded transaction's amount does NOT appear in expense_paise or income_paise

*Determinism:*
- Build projection twice from same events → identical result dict

*Unknown events:*
- Unknown `event_type` passes through without error, state unchanged

*Projection type registration:*
- `build_projection_from_events(events, "transactions_view")` does not raise (projection type is registered)

- [ ] **Step 1 (TEST-AUTHORING SESSION):** Dispatch independent test-authoring subagent. It reads this spec (Task 3 section), `core/events/store.py` (the `Event` dataclass), and `core/projections/builder.py` (the `build_projection_from_events` interface). It does NOT open `reducer.py` (which doesn't exist yet). Commits with message `"Wave 3 (independent test-authoring): transactions_view reducer tests"`.

- [ ] **Step 2 (IMPLEMENTATION SESSION):** Dispatch implementation subagent. Creates `reducer.py`, modifies `builder.py`. Commits with message `"Wave 3: transactions_view reducer + builder registration"`.

- [ ] **Step 3:** Run tests:
  ```bash
  cd backend && PYTHONPATH=. python3 -m pytest tests/unit/processing/test_transactions_view_reducer.py -v
  ```
  Expected: all PASS.

- [ ] **Step 4:** Run mypy:
  ```bash
  cd backend && python3 -m mypy --config-file pyproject.toml --explicit-package-bases processing/resolver/ core/projections/ -v
  ```
  Expected: no errors.

- [ ] **Step 5:** Confirm independence: test commit must predate implementation commit in `git log`.

---

### Task 4: Wave 4 — Integration tests + audit view

*To be detailed before Wave 4 begins.*

---

### Task 5: Wave 5 — Full test suite + gate + Phase 2 close

*To be detailed before Wave 5 begins.*

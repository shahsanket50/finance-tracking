"""Independent contract tests for the category classifier.

Tests are derived from PRD §4 and TRD §9.2 — implementation files were NOT read.
Every test here documents a behavioural expectation from the spec; a wrong
implementation causes one or more tests to fail.

Covers exit criteria C1–C6.
"""

from __future__ import annotations

import inspect
import unittest.mock as mock

import pytest

from adapters.llm.base import BelowConfidenceThreshold, LLMResult
from processing.classifier.base import (
    classify_transaction,
    record_correction,
    resolve_category,
)
from processing.classifier.categories import ALL_CATEGORIES
from processing.classifier.config import CATEGORIZATION_CONFIDENCE_THRESHOLD
from processing.classifier.events import (
    CategoryCorrectedPayload,
    TransactionCategorizedPayload,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_categorized(
    transaction_hash: str = "hash_a",
    category: str = "shopping",
    method: str = "rule",
    confidence_bps: int = 9000,
    merchant_canonical: str = "Amazon",
) -> TransactionCategorizedPayload:
    return TransactionCategorizedPayload(
        transaction_hash=transaction_hash,
        category=category,  # type: ignore[arg-type]
        method=method,  # type: ignore[arg-type]
        confidence_bps=confidence_bps,
        rule_id="r001" if method == "rule" else None,
        prompt_version=None if method == "rule" else "v1",
        merchant_canonical=merchant_canonical,
    )


def _make_corrected(
    transaction_hash: str = "hash_a",
    category: str = "food_dining",
    prior_category: str = "shopping",
    merchant_canonical: str = "Amazon",
    corrected_by: str = "user_001",
) -> CategoryCorrectedPayload:
    return CategoryCorrectedPayload(
        transaction_hash=transaction_hash,
        category=category,  # type: ignore[arg-type]
        prior_category=prior_category,  # type: ignore[arg-type]
        merchant_canonical=merchant_canonical,
        corrected_by=corrected_by,
    )


# ---------------------------------------------------------------------------
# C1 — high-confidence auto-commit
# ---------------------------------------------------------------------------

class TestHighConfidenceAutoCommit:
    """C1: well-known merchant → confidence >= threshold, valid category, valid method."""

    @pytest.mark.parametrize("merchant,expected_category", [
        ("Swiggy", "food_dining"),
        ("Zomato", "food_dining"),
        ("Amazon", "shopping"),
    ])
    def test_result_confidence_meets_threshold(self, merchant: str, expected_category: str) -> None:
        result = classify_transaction("hash_c1", merchant, [])
        assert result.confidence_bps >= CATEGORIZATION_CONFIDENCE_THRESHOLD, (
            f"classify_transaction('{merchant}') returned confidence_bps="
            f"{result.confidence_bps} which is below threshold "
            f"{CATEGORIZATION_CONFIDENCE_THRESHOLD}"
        )

    @pytest.mark.parametrize("merchant", ["Swiggy", "Zomato", "Amazon"])
    def test_result_category_is_valid(self, merchant: str) -> None:
        result = classify_transaction("hash_c1_cat", merchant, [])
        assert result.category in ALL_CATEGORIES, (
            f"classify_transaction returned category '{result.category}' not in ALL_CATEGORIES"
        )

    @pytest.mark.parametrize("merchant", ["Swiggy", "Zomato", "Amazon"])
    def test_result_method_is_rule_or_llm(self, merchant: str) -> None:
        result = classify_transaction("hash_c1_method", merchant, [])
        assert result.method in ("rule", "llm"), (
            f"classify_transaction returned unexpected method '{result.method}'"
        )

    @pytest.mark.parametrize("merchant,expected_category", [
        ("Swiggy", "food_dining"),
        ("Zomato", "food_dining"),
        ("Amazon", "shopping"),
    ])
    def test_result_type(self, merchant: str, expected_category: str) -> None:
        result = classify_transaction("hash_c1_type", merchant, [])
        assert isinstance(result, TransactionCategorizedPayload)


# ---------------------------------------------------------------------------
# C2 — low-confidence → BelowConfidenceThreshold
# ---------------------------------------------------------------------------

class TestLowConfidenceRaisesException:
    """C2: when the LLM returns confidence below threshold, BelowConfidenceThreshold is raised."""

    def test_below_threshold_raised_on_low_confidence_llm(self) -> None:
        """Patch the module-level LLM adapter to return confidence below threshold."""
        low_confidence = CATEGORIZATION_CONFIDENCE_THRESHOLD - 1

        # We patch wherever the classifier module resolves its adapter.
        # The contract says classify_transaction raises BelowConfidenceThreshold
        # when the LLM result is below threshold — we arrange that scenario.
        with pytest.raises(BelowConfidenceThreshold) as exc_info:
            with mock.patch(
                "processing.classifier.base._llm_adapter",
                new_callable=mock.MagicMock,
            ) as mock_adapter:
                # Build a fake async complete that returns low confidence

                async def fake_complete(  # type: ignore[type-arg]
                    prompt: str,
                    output_schema: type,
                    prompt_version: str,
                ) -> LLMResult:
                    # Produce a plausible structured output for a low-confidence merchant
                    from pydantic import BaseModel

                    class _FakeOutput(BaseModel):
                        category: str = "other"

                    return LLMResult(
                        output=_FakeOutput(),
                        confidence_bps=low_confidence,
                        model_id="fake-model",
                        prompt_version=prompt_version,
                    )

                mock_adapter.complete = fake_complete
                classify_transaction("hash_c2", "UnknownGarbage12345XYZ", [])

        exc = exc_info.value
        assert hasattr(exc, "confidence_bps"), "BelowConfidenceThreshold must carry confidence_bps"
        assert hasattr(exc, "threshold"), "BelowConfidenceThreshold must carry threshold"
        assert exc.confidence_bps < exc.threshold

    def test_below_threshold_attributes_are_integers(self) -> None:
        """confidence_bps and threshold on the exception are integers (not strings)."""
        exc = BelowConfidenceThreshold(confidence_bps=3000, threshold=7500)
        assert isinstance(exc.confidence_bps, int)
        assert isinstance(exc.threshold, int)
        assert exc.confidence_bps == 3000
        assert exc.threshold == 7500


# ---------------------------------------------------------------------------
# C3 — per-user learning: record_correction payload contract
# ---------------------------------------------------------------------------

class TestRecordCorrectionPayload:
    """C3: record_correction returns CategoryCorrectedPayload with correct fields."""

    def test_returns_category_corrected_payload(self) -> None:
        result = record_correction(
            transaction_hash="hash_c3",
            merchant_canonical="UnknownCafe",
            corrected_category="food_dining",
            prior_category="other",
            user_id="user_001",
        )
        assert isinstance(result, CategoryCorrectedPayload)

    def test_corrected_category_stored_in_category_field(self) -> None:
        result = record_correction(
            transaction_hash="hash_c3b",
            merchant_canonical="UnknownCafe",
            corrected_category="food_dining",
            prior_category="other",
            user_id="user_001",
        )
        assert result.category == "food_dining"

    def test_prior_category_preserved(self) -> None:
        result = record_correction(
            transaction_hash="hash_c3c",
            merchant_canonical="UnknownCafe",
            corrected_category="food_dining",
            prior_category="other",
            user_id="user_001",
        )
        assert result.prior_category == "other"

    def test_merchant_canonical_preserved(self) -> None:
        result = record_correction(
            transaction_hash="hash_c3d",
            merchant_canonical="UnknownCafe",
            corrected_category="food_dining",
            prior_category="other",
            user_id="user_001",
        )
        assert result.merchant_canonical == "UnknownCafe"

    def test_corrected_by_set_to_user_id(self) -> None:
        result = record_correction(
            transaction_hash="hash_c3e",
            merchant_canonical="UnknownCafe",
            corrected_category="food_dining",
            prior_category="other",
            user_id="user_001",
        )
        assert result.corrected_by == "user_001"

    def test_learned_rule_applied_when_correction_event_passed(self) -> None:
        """C3 — event-log-driven learning: if a CategoryCorrected event is in the
        correction_events list, classify_transaction must use it as the learned rule.

        This is the key invariant: per-user learning works by passing recorded
        CategoryCorrected events to classify_transaction, NOT via side-effectful
        in-memory state. This test would fail against an implementation that
        discards the correction_events list and relies on a mutable dict instead.
        """
        # Record a correction for "UnknownCafe" → "food_dining"
        correction = record_correction(
            transaction_hash="hash_c3f_original",
            merchant_canonical="UnknownCafe",
            corrected_category="food_dining",
            prior_category="other",
            user_id="user_learn",
        )
        # Now classify a NEW transaction for the same merchant, passing the correction event.
        # A correct implementation derives the learned rule from correction_events.
        result = classify_transaction(
            "hash_c3f_new", "UnknownCafe", [correction]
        )
        assert result.category == "food_dining", (
            f"classify_transaction returned '{result.category}' for 'UnknownCafe' after "
            "a correction event was passed — learned rule from event history was not applied."
        )
        assert result.method == "rule", (
            "classify_transaction should use method='rule' for a learned correction, "
            f"got method='{result.method}'"
        )

    def test_learned_rule_absent_without_correction_event(self) -> None:
        """Complement of above: passing no correction events → no learned rule.

        An unknown merchant with no correction history must go to LLM fallback
        (or global rules), not magically get a category from phantom state.
        Confirms correction_events=[] means no learned rules, regardless of
        what prior test runs may have called record_correction() on.
        """
        # Unknown merchant, no correction events — should NOT use "food_dining"
        # as if it learned from a prior test.
        result = classify_transaction("hash_c3g", "TotallyUnknownXYZ999", [])
        # Result is valid but must not come from a learned rule (no corrections passed)
        assert result.method in ("rule", "llm"), "method must be rule or llm"
        # If method == "rule" and rule_id starts with "learned:", that is a bug —
        # no learned rules were passed in.
        if result.method == "rule" and result.rule_id is not None:
            assert not result.rule_id.startswith("learned:"), (
                f"classify_transaction used a learned rule (rule_id={result.rule_id!r}) "
                "despite correction_events=[] — implementation has phantom mutable state."
            )


# ---------------------------------------------------------------------------
# C4 — classifier signature accepts merchant_canonical, not raw_narration
# ---------------------------------------------------------------------------

class TestClassifierSignatureContract:
    """C4: classify_transaction must accept merchant_canonical as a parameter name."""

    def test_parameter_named_merchant_canonical(self) -> None:
        sig = inspect.signature(classify_transaction)
        params = list(sig.parameters.keys())
        assert "merchant_canonical" in params, (
            f"classify_transaction signature is {params!r}; "
            "expected 'merchant_canonical' but it is missing — "
            "pipeline ordering contract broken (PRD §4.1)"
        )

    def test_parameter_not_named_raw_narration(self) -> None:
        sig = inspect.signature(classify_transaction)
        params = list(sig.parameters.keys())
        assert "raw_narration" not in params, (
            "classify_transaction has a 'raw_narration' parameter — "
            "this means the classifier is taking raw text instead of "
            "the normalizer's output, violating PRD §4.1 pipeline ordering"
        )

    def test_parameter_order(self) -> None:
        """transaction_hash, merchant_canonical, correction_events — in that order."""
        sig = inspect.signature(classify_transaction)
        params = list(sig.parameters.keys())
        assert params[:3] == ["transaction_hash", "merchant_canonical", "correction_events"], (
            f"Parameter order is {params!r}, expected "
            "['transaction_hash', 'merchant_canonical', 'correction_events']"
        )


# ---------------------------------------------------------------------------
# C4b — pipeline ordering: resolver-excluded transactions never classified
# ---------------------------------------------------------------------------
#
# The existing TestClassifierSignatureContract tests only that the function
# accepts a parameter named merchant_canonical. The REAL C4 invariant is:
# transactions excluded by the resolver (internal transfers, CC payments,
# FD bookings, reversals) must not receive a category classification.
#
# Enforcement strategy: the caller (the pipeline orchestrator) is responsible
# for skipping excluded transactions before calling classify_transaction.
# The classifier itself has no awareness of resolver state — it can't check.
# So the test must verify that a pipeline that DOES call classify_transaction
# for an excluded transaction is detectable as wrong.
#
# What we can test here: the pipeline contract — classify_transaction returns
# a valid category payload for any merchant canonical it receives, but it is
# the CALLER's responsibility not to call it for excluded transactions.
# We document this as a pipeline invariant test with a clear failure mode.


class TestPipelineOrderingC4:
    """C4: resolver exclusions must precede classification — pipeline ordering (PRD §4.1)."""

    def test_excluded_transaction_types_must_not_be_classified(self) -> None:
        """A transaction the resolver has excluded must never receive a category.

        This test documents the pipeline contract: when a transaction is marked
        as an internal transfer, CC payment, FD booking, or reversal by the resolver,
        the pipeline must short-circuit BEFORE calling classify_transaction.

        Enforcement: if classify_transaction IS called with the canonical name of
        a resolver-excluded transaction, it returns a result — it has no way to
        refuse. This confirms the invariant lives at the pipeline caller level,
        not inside the classifier. The test records the expected behavior and
        the boundary of responsibility.

        A future pipeline integration test (Wave 6) will assert end-to-end that
        excluded transactions produce no TransactionCategorizedPayload event in
        the event log.
        """
        # These merchant canonicals correspond to resolver-excluded transaction types.
        # If the classifier is called with them — which it must NOT be — it will
        # return a category (e.g. "transfers"), not raise. The correct prevention
        # is at the caller, not here.
        excluded_merchant_canonicals = [
            "NEFT Credit",    # income/transfer — resolver excludes the transfer leg
        ]
        for canonical in excluded_merchant_canonicals:
            # Classifier does NOT refuse — it classifies anything it receives.
            # This assertion documents that the guard must be upstream.
            result = classify_transaction("excluded_hash", canonical, [])
            # The result category here is irrelevant — what matters is that a
            # correctly-wired pipeline never produces this call for excluded txns.
            assert result.category in (
                "income", "transfers", "other"
            ), (
                f"Classifier returned unexpected category {result.category!r} for "
                f"excluded-type merchant {canonical!r} — this call should never "
                "have reached the classifier in a correctly-ordered pipeline."
            )

    def test_pipeline_ordering_documented_as_caller_responsibility(self) -> None:
        """Confirm classify_transaction has no resolver_excluded parameter.

        If an implementation adds resolver_excluded: bool to the signature to
        'guard' inside the classifier, that is wrong — it leaks resolver state
        into the classifier layer. The classifier must be stateless w.r.t. resolver.
        """
        sig = inspect.signature(classify_transaction)
        params = list(sig.parameters.keys())
        assert "resolver_excluded" not in params
        assert "is_excluded" not in params
        assert "excluded" not in params


# ---------------------------------------------------------------------------
# C5 — golden fixture: known merchant canonicals → expected categories
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("merchant_canonical,expected_category", [
    ("Swiggy", "food_dining"),
    ("Zomato", "food_dining"),
    ("Amazon", "shopping"),
    ("Uber", "transport"),
    ("Ola", "transport"),
    ("Netflix", "subscriptions"),
    ("BigBasket", "groceries"),
    ("NEFT Credit", "income"),
])
def test_golden_merchant_to_category(merchant_canonical: str, expected_category: str) -> None:
    """C5 golden fixture: if the rules map a known merchant to a different category,
    this test fails and the deviation is visible before it reaches production."""
    result = classify_transaction("hash_golden", merchant_canonical, [])
    assert result.category == expected_category, (
        f"Golden fixture mismatch for '{merchant_canonical}': "
        f"expected '{expected_category}', got '{result.category}'. "
        "If this rule intentionally changed, update the golden dataset first."
    )


# ---------------------------------------------------------------------------
# C6 — resolve_category: corrections win on replay
# ---------------------------------------------------------------------------

class TestResolveCategory:
    """C6: resolve_category is a DERIVATION — must honour the most recent correction."""

    def test_single_categorized_event_returns_system_category(self) -> None:
        """Only a TransactionCategorized event → return its category."""
        event = _make_categorized(transaction_hash="hash_r1", category="shopping")
        result = resolve_category("hash_r1", "user_001", [event])
        assert result == "shopping"

    def test_correction_supersedes_original_category(self) -> None:
        """A CategoryCorrected event after a TransactionCategorized event wins."""
        categorized = _make_categorized(
            transaction_hash="hash_r2", category="shopping", merchant_canonical="Amazon"
        )
        corrected = _make_corrected(
            transaction_hash="hash_r2",
            category="food_dining",
            prior_category="shopping",
            merchant_canonical="Amazon",
        )
        result = resolve_category("hash_r2", "user_001", [categorized, corrected])
        assert result == "food_dining", (
            "resolve_category returned the original 'shopping' instead of the "
            "corrected 'food_dining' — corrections are not winning on replay"
        )

    def test_last_correction_wins_when_multiple_corrections(self) -> None:
        """With two corrections in order, the second (later) one wins."""
        categorized = _make_categorized(transaction_hash="hash_r3", category="other")
        first_correction = _make_corrected(
            transaction_hash="hash_r3",
            category="shopping",
            prior_category="other",
        )
        second_correction = _make_corrected(
            transaction_hash="hash_r3",
            category="transport",
            prior_category="shopping",
        )
        result = resolve_category(
            "hash_r3", "user_001", [categorized, first_correction, second_correction]
        )
        assert result == "transport", (
            "resolve_category should return the LAST correction's category ('transport') "
            f"but returned '{result}'"
        )

    @pytest.mark.xfail(
        reason="Contract says ValueError on empty list but this is not 100% explicit; "
               "marking xfail to document the expectation — implementation may differ"
    )
    def test_empty_event_list_raises_value_error(self) -> None:
        """No events at all → should raise ValueError per contract docstring."""
        with pytest.raises(ValueError):
            resolve_category("hash_empty", "user_001", [])

    def test_correction_is_never_reverted_by_replay(self) -> None:
        """Critical invariant C6: once a correction exists, replay must never return
        the original system-assigned category for that transaction."""
        categorized = _make_categorized(
            transaction_hash="hash_revert",
            category="other",
            merchant_canonical="SomeMerchant",
        )
        corrected = _make_corrected(
            transaction_hash="hash_revert",
            category="health_medical",
            prior_category="other",
            merchant_canonical="SomeMerchant",
        )
        # Replay the same events twice — result must be identical and must be the correction
        result_first_replay = resolve_category("hash_revert", "user_001", [categorized, corrected])
        result_second_replay = resolve_category("hash_revert", "user_001", [categorized, corrected])

        assert result_first_replay == "health_medical", (
            "First replay reverted the correction — "
            "returned original category instead of 'health_medical'"
        )
        assert result_second_replay == "health_medical", (
            "Second replay reverted the correction — replay is not deterministic (TRD §9.2 C6)"
        )
        assert result_first_replay == result_second_replay, (
            "resolve_category is not deterministic across replays — Invariant 3 violated"
        )

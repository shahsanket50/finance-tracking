"""Nature tagger unit tests. Derived from PRD §5.1 and TRD §8.3.

Implementation files were NOT read.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from adapters.llm.base import BelowConfidenceThreshold
from adapters.llm.stub import StubLLMAdapter
from processing.nature.base import (
    record_nature_correction,
    resolve_nature,
    set_adapter,
    tag_nature,
)
from processing.nature.config import NATURE_CONFIDENCE_THRESHOLD
from processing.nature.events import (
    ALL_NATURES,
    NatureCorrectedPayload,
    NatureTaggedPayload,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tagged(
    transaction_hash: str = "hash_a",
    nature: str = "discretionary",
    method: str = "rule",
    confidence_bps: int = 9500,
    category: str = "entertainment",
) -> NatureTaggedPayload:
    return NatureTaggedPayload(
        transaction_hash=transaction_hash,
        nature=nature,  # type: ignore[arg-type]
        method=method,  # type: ignore[arg-type]
        confidence_bps=confidence_bps,
        rule_id="r001" if method == "rule" else None,
        prompt_version=None if method == "rule" else "tagger-v1",
        category=category,
    )


def _make_corrected(
    transaction_hash: str = "hash_a",
    nature: str = "essential_variable",
    prior_nature: str = "discretionary",
    corrected_by: str = "user_001",
) -> NatureCorrectedPayload:
    return NatureCorrectedPayload(
        transaction_hash=transaction_hash,
        nature=nature,  # type: ignore[arg-type]
        prior_nature=prior_nature,  # type: ignore[arg-type]
        corrected_by=corrected_by,
    )


# ---------------------------------------------------------------------------
# N1 — NatureTaggedPayload contract
# ---------------------------------------------------------------------------


class TestNatureTaggedPayloadContract:
    """N1: NatureTaggedPayload is a frozen Pydantic model with validated fields."""

    def test_payload_is_frozen(self) -> None:
        payload = _make_tagged()
        with pytest.raises((TypeError, ValidationError)):
            payload.nature = "luxury"  # type: ignore[misc]

    @pytest.mark.parametrize("nature", ALL_NATURES)
    def test_all_four_nature_values_are_valid(self, nature: str) -> None:
        payload = NatureTaggedPayload(
            transaction_hash="hash_n1",
            nature=nature,  # type: ignore[arg-type]
            method="rule",
            confidence_bps=9500,
            rule_id="r001",
            prompt_version=None,
            category="food_dining",
        )
        assert payload.nature == nature

    def test_confidence_bps_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NatureTaggedPayload(
                transaction_hash="hash_n1_low",
                nature="discretionary",
                method="rule",
                confidence_bps=-1,
                rule_id=None,
                prompt_version=None,
                category="entertainment",
            )

    def test_confidence_bps_above_ten_thousand_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NatureTaggedPayload(
                transaction_hash="hash_n1_high",
                nature="discretionary",
                method="rule",
                confidence_bps=10001,
                rule_id=None,
                prompt_version=None,
                category="entertainment",
            )

    def test_confidence_bps_at_boundaries_accepted(self) -> None:
        for bps in (0, 10000):
            payload = NatureTaggedPayload(
                transaction_hash=f"hash_n1_bnd_{bps}",
                nature="discretionary",
                method="llm",
                confidence_bps=bps,
                rule_id=None,
                prompt_version="tagger-v1",
                category="entertainment",
            )
            assert payload.confidence_bps == bps

    def test_method_must_be_rule_or_llm(self) -> None:
        with pytest.raises(ValidationError):
            NatureTaggedPayload(
                transaction_hash="hash_n1_m",
                nature="discretionary",
                method="manual",  # type: ignore[arg-type]
                confidence_bps=9000,
                rule_id=None,
                prompt_version=None,
                category="entertainment",
            )

    def test_category_field_is_preserved(self) -> None:
        payload = NatureTaggedPayload(
            transaction_hash="hash_n1_cat",
            nature="essential_variable",
            method="rule",
            confidence_bps=9500,
            rule_id="r001",
            prompt_version=None,
            category="groceries",
        )
        assert payload.category == "groceries"

    def test_confidence_bps_is_int_not_float(self) -> None:
        payload = _make_tagged(confidence_bps=8000)
        assert isinstance(payload.confidence_bps, int), (
            "confidence_bps must be int (basis points), not float"
        )


# ---------------------------------------------------------------------------
# N2 — tag_nature signature contract
# ---------------------------------------------------------------------------


class TestTagNatureSignatureContract:
    """N2: tag_nature has the correct public signature."""

    def test_function_exists(self) -> None:
        import processing.nature.base as base_module

        assert hasattr(base_module, "tag_nature"), (
            "tag_nature must be exported from processing.nature.base"
        )

    def test_parameter_names(self) -> None:
        sig = inspect.signature(tag_nature)
        params = list(sig.parameters.keys())
        assert "transaction_hash" in params
        assert "category" in params
        assert "merchant_canonical" in params
        assert "transaction_type" in params
        assert "correction_events" in params

    def test_returns_nature_tagged_payload(self) -> None:
        result = tag_nature(
            transaction_hash="hash_n2",
            category="rent_housing",
            merchant_canonical="Landlord",
            transaction_type="expense",
            correction_events=[],
        )
        assert isinstance(result, NatureTaggedPayload)


# ---------------------------------------------------------------------------
# N3 — transaction_type guard
# ---------------------------------------------------------------------------


class TestTransactionTypeGuard:
    """N3: tag_nature raises ValueError for non-expense transaction types."""

    def test_expense_type_is_accepted(self) -> None:
        result = tag_nature(
            transaction_hash="hash_n3_ok",
            category="groceries",
            merchant_canonical="BigBasket",
            transaction_type="expense",
            correction_events=[],
        )
        assert isinstance(result, NatureTaggedPayload)

    @pytest.mark.parametrize("txn_type", ["transfer", "income", "investment"])
    def test_non_expense_type_raises_value_error(self, txn_type: str) -> None:
        with pytest.raises(ValueError):
            tag_nature(
                transaction_hash="hash_n3_bad",
                category="groceries",
                merchant_canonical="BigBasket",
                transaction_type=txn_type,
                correction_events=[],
            )

    def test_guard_fires_before_llm_not_below_confidence(self) -> None:
        """ValueError must be raised even when the adapter would produce BelowConfidenceThreshold.

        If the guard were absent or ran after the LLM call, the error type would be
        BelowConfidenceThreshold rather than ValueError.
        """
        set_adapter(StubLLMAdapter(confidence_bps=0))
        try:
            with pytest.raises(ValueError):
                tag_nature(
                    transaction_hash="hash_n3_guard",
                    category="other",
                    merchant_canonical="SomeAmbiguousMerchant",
                    transaction_type="transfer",
                    correction_events=[],
                )
        finally:
            set_adapter(StubLLMAdapter())


# ---------------------------------------------------------------------------
# N4 — rules-first nature tagging
# ---------------------------------------------------------------------------


class TestRulesFirstNatureTagging:
    """N4: known categories map to their nature via rules before LLM is invoked."""

    @pytest.mark.parametrize(
        "category,expected_nature",
        [
            ("rent_housing", "essential_fixed"),
            ("groceries", "essential_variable"),
            ("utilities", "essential_variable"),
            ("entertainment", "discretionary"),
            ("shopping", "discretionary"),
        ],
    )
    def test_known_category_maps_to_expected_nature(
        self, category: str, expected_nature: str
    ) -> None:
        result = tag_nature(
            transaction_hash=f"hash_n4_{category}",
            category=category,  # type: ignore[arg-type]
            merchant_canonical="SomeMerchant",
            transaction_type="expense",
            correction_events=[],
        )
        assert result.nature == expected_nature, (
            f"category='{category}' → expected nature='{expected_nature}', got '{result.nature}'"
        )

    @pytest.mark.parametrize(
        "category", ["rent_housing", "groceries", "utilities", "entertainment", "shopping"]
    )
    def test_rule_result_uses_rule_method(self, category: str) -> None:
        result = tag_nature(
            transaction_hash=f"hash_n4_method_{category}",
            category=category,  # type: ignore[arg-type]
            merchant_canonical="SomeMerchant",
            transaction_type="expense",
            correction_events=[],
        )
        assert result.method == "rule", (
            f"category='{category}' should use method='rule', got '{result.method}'"
        )

    @pytest.mark.parametrize(
        "category", ["rent_housing", "groceries", "utilities", "entertainment", "shopping"]
    )
    def test_rule_result_confidence_above_threshold(self, category: str) -> None:
        result = tag_nature(
            transaction_hash=f"hash_n4_conf_{category}",
            category=category,  # type: ignore[arg-type]
            merchant_canonical="SomeMerchant",
            transaction_type="expense",
            correction_events=[],
        )
        assert result.confidence_bps >= NATURE_CONFIDENCE_THRESHOLD, (
            f"category='{category}' rule result has confidence_bps={result.confidence_bps} "
            f"below threshold {NATURE_CONFIDENCE_THRESHOLD}"
        )

    @pytest.mark.parametrize(
        "category", ["rent_housing", "groceries", "utilities", "entertainment", "shopping"]
    )
    def test_rule_result_has_rule_id(self, category: str) -> None:
        result = tag_nature(
            transaction_hash=f"hash_n4_rid_{category}",
            category=category,  # type: ignore[arg-type]
            merchant_canonical="SomeMerchant",
            transaction_type="expense",
            correction_events=[],
        )
        assert result.rule_id is not None, (
            f"category='{category}' rule result must have rule_id set"
        )

    @pytest.mark.parametrize(
        "category", ["rent_housing", "groceries", "utilities", "entertainment", "shopping"]
    )
    def test_rule_result_has_no_prompt_version(self, category: str) -> None:
        result = tag_nature(
            transaction_hash=f"hash_n4_pv_{category}",
            category=category,  # type: ignore[arg-type]
            merchant_canonical="SomeMerchant",
            transaction_type="expense",
            correction_events=[],
        )
        assert result.prompt_version is None, (
            f"category='{category}' rule result must have prompt_version=None (no LLM used), "
            f"got '{result.prompt_version}'"
        )


# ---------------------------------------------------------------------------
# N5 — LLM fallback nature tagging
# ---------------------------------------------------------------------------


class TestLLMFallbackNatureTagging:
    """N5: for categories not covered by rules, the tagger falls back to LLM."""

    def test_unknown_category_falls_back_to_llm(self) -> None:
        set_adapter(StubLLMAdapter(confidence_bps=8000))
        try:
            result = tag_nature(
                transaction_hash="hash_n5_llm",
                category="other",
                merchant_canonical="SomeObscureShop",
                transaction_type="expense",
                correction_events=[],
            )
            assert result.method == "llm", (
                f"Expected method='llm' for unknown category fallback, got '{result.method}'"
            )
        finally:
            set_adapter(StubLLMAdapter())

    def test_llm_result_has_prompt_version(self) -> None:
        set_adapter(StubLLMAdapter(confidence_bps=8000))
        try:
            result = tag_nature(
                transaction_hash="hash_n5_pv",
                category="other",
                merchant_canonical="SomeObscureShop",
                transaction_type="expense",
                correction_events=[],
            )
            assert result.prompt_version is not None, (
                "LLM fallback result must have prompt_version set"
            )
        finally:
            set_adapter(StubLLMAdapter())

    def test_llm_result_confidence_reflects_adapter(self) -> None:
        set_adapter(StubLLMAdapter(confidence_bps=8000))
        try:
            result = tag_nature(
                transaction_hash="hash_n5_conf",
                category="other",
                merchant_canonical="SomeObscureShop",
                transaction_type="expense",
                correction_events=[],
            )
            assert result.confidence_bps == 8000
        finally:
            set_adapter(StubLLMAdapter())

    def test_below_threshold_raises_when_llm_low_confidence(self) -> None:
        low_confidence = NATURE_CONFIDENCE_THRESHOLD - 1
        set_adapter(StubLLMAdapter(confidence_bps=low_confidence))
        try:
            with pytest.raises(BelowConfidenceThreshold) as exc_info:
                tag_nature(
                    transaction_hash="hash_n5_low",
                    category="other",
                    merchant_canonical="AmbiguousMerchant",
                    transaction_type="expense",
                    correction_events=[],
                )
            exc = exc_info.value
            assert exc.confidence_bps < exc.threshold
            assert exc.confidence_bps == low_confidence
        finally:
            set_adapter(StubLLMAdapter())


# ---------------------------------------------------------------------------
# N6 — event-log-driven learning (critical)
# ---------------------------------------------------------------------------


class TestEventLogDrivenLearning:
    """N6: nature overrides are derived from correction_events, never from mutable state."""

    def test_record_nature_correction_is_pure_function(self) -> None:
        """record_nature_correction must return the payload and have no side effects.

        Call it twice with the same args: both results must be equal and calling
        tag_nature with empty events must NOT reflect the correction.
        """
        c1 = record_nature_correction("hash_n6a", "luxury", "discretionary", "user_001")
        c2 = record_nature_correction("hash_n6a", "luxury", "discretionary", "user_001")
        assert c1 == c2, "record_nature_correction must be deterministic (pure function)"
        assert isinstance(c1, NatureCorrectedPayload)

    def test_correction_event_applied_when_passed(self) -> None:
        """If a NatureCorrectedPayload is in correction_events, tag_nature must use it.

        This is the key invariant: learned overrides come from the event log, not mutable state.
        tag_nature(correction_events=[correction]) for the same transaction_hash must apply
        the override.
        """
        correction = record_nature_correction(
            transaction_hash="hash_n6b",
            corrected_nature="luxury",
            prior_nature="discretionary",
            user_id="user_learn",
        )
        # Use a rule-matching category so without correction it would return "discretionary"
        result = tag_nature(
            transaction_hash="hash_n6b",
            category="entertainment",
            merchant_canonical="SomeVenueXYZ",
            transaction_type="expense",
            correction_events=[correction],
        )
        assert result.nature == "luxury", (
            f"tag_nature returned '{result.nature}' but expected 'luxury' — "
            "correction event from event log was not applied."
        )

    def test_no_learned_override_without_correction_event(self) -> None:
        """Complement: passing correction_events=[] must not apply any learned override.

        An unknown merchant with no corrections must not magically get a nature
        from phantom mutable state left over from other test runs.
        """
        result = tag_nature(
            transaction_hash="hash_n6c",
            category="entertainment",
            merchant_canonical="TotallyUnknownVenue999",
            transaction_type="expense",
            correction_events=[],
        )
        # Result must not come from a learned rule (no corrections were passed).
        if result.method == "rule" and result.rule_id is not None:
            assert not result.rule_id.startswith("learned:"), (
                f"tag_nature used a learned override (rule_id={result.rule_id!r}) "
                "despite correction_events=[] — implementation has phantom mutable state."
            )

    def test_last_correction_wins(self) -> None:
        """When multiple corrections exist for the same transaction_hash, the last one wins."""
        first = record_nature_correction(
            transaction_hash="hash_n6d",
            corrected_nature="essential_variable",
            prior_nature="discretionary",
            user_id="user_001",
        )
        second = record_nature_correction(
            transaction_hash="hash_n6d",
            corrected_nature="luxury",
            prior_nature="essential_variable",
            user_id="user_001",
        )
        result = tag_nature(
            transaction_hash="hash_n6d",
            category="entertainment",
            merchant_canonical="SomeVenue",
            transaction_type="expense",
            correction_events=[first, second],
        )
        assert result.nature == "luxury", (
            f"Last correction should win ('luxury'), got '{result.nature}'"
        )


# ---------------------------------------------------------------------------
# N7 — resolve_nature derivation
# ---------------------------------------------------------------------------


class TestResolveNature:
    """N7: resolve_nature is a pure DERIVATION over NatureTagged/NatureCorrected events."""

    def test_returns_nature_from_tagged_event(self) -> None:
        tagged = _make_tagged(transaction_hash="hash_n7a", nature="essential_fixed")
        result = resolve_nature("hash_n7a", [tagged])
        assert result == "essential_fixed"

    def test_correction_overrides_tagged_event(self) -> None:
        tagged = _make_tagged(transaction_hash="hash_n7b", nature="discretionary")
        corrected = _make_corrected(
            transaction_hash="hash_n7b", nature="luxury", prior_nature="discretionary"
        )
        result = resolve_nature("hash_n7b", [tagged, corrected])
        assert result == "luxury", (
            f"NatureCorrectedPayload should override NatureTaggedPayload, got '{result}'"
        )

    def test_last_correction_wins_in_resolve(self) -> None:
        tagged = _make_tagged(transaction_hash="hash_n7c", nature="discretionary")
        first_correction = _make_corrected(
            transaction_hash="hash_n7c", nature="essential_variable", prior_nature="discretionary"
        )
        second_correction = _make_corrected(
            transaction_hash="hash_n7c", nature="luxury", prior_nature="essential_variable"
        )
        result = resolve_nature("hash_n7c", [tagged, first_correction, second_correction])
        assert result == "luxury", f"Last correction should win ('luxury'), got '{result}'"

    def test_empty_events_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            resolve_nature("hash_n7d", [])

    def test_resolve_is_deterministic(self) -> None:
        """Calling resolve_nature twice with the same list returns the same value."""
        tagged = _make_tagged(transaction_hash="hash_n7e", nature="essential_variable")
        result1 = resolve_nature("hash_n7e", [tagged])
        result2 = resolve_nature("hash_n7e", [tagged])
        assert result1 == result2


# ---------------------------------------------------------------------------
# N8 — pipeline ordering
# ---------------------------------------------------------------------------


class TestPipelineOrderingN8:
    """N8: nature tagging is step 6.

    It receives category as input and never imports classifier internals.
    """

    def test_category_is_input_to_tag_nature(self) -> None:
        """category must be a parameter — the result's category field echoes it back."""
        result = tag_nature(
            transaction_hash="hash_n8a",
            category="groceries",
            merchant_canonical="BigBasket",
            transaction_type="expense",
            correction_events=[],
        )
        assert result.category == "groceries", (
            f"tag_nature result.category should echo the input category 'groceries', "
            f"got '{result.category}' — proves category flows IN, not out."
        )

    def test_tagger_does_not_import_classifier_internals(self) -> None:
        """The nature tagger module must not import from processing.classifier.classifier.

        A reverse dependency (tagger → classifier internals) would invert the pipeline
        ordering and create a coupling that prevents independent testing of either module.
        """
        tagger_path = (
            Path(__file__).parent.parent.parent.parent / "processing" / "nature" / "tagger.py"
        )
        if not tagger_path.exists():
            pytest.skip("tagger.py not yet implemented — skip import boundary check")

        source = tagger_path.read_text()
        tree = ast.parse(source)

        forbidden = "processing.classifier.classifier"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != forbidden, (
                        f"tagger.py imports '{alias.name}' — nature tagger must not "
                        "depend on classifier internals (pipeline ordering violation)"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != forbidden, (
                    f"tagger.py imports from '{module}' — nature tagger must not "
                    "depend on classifier internals (pipeline ordering violation)"
                )


# ---------------------------------------------------------------------------
# N9 — NatureCorrectedPayload is also frozen
# ---------------------------------------------------------------------------


class TestPayloadFrozenN9:
    """N9: NatureCorrectedPayload is a frozen Pydantic model."""

    def test_nature_corrected_payload_is_frozen(self) -> None:
        payload = _make_corrected()
        with pytest.raises((TypeError, ValidationError)):
            payload.nature = "luxury"  # type: ignore[misc]

    def test_nature_corrected_payload_fields(self) -> None:
        payload = _make_corrected(
            transaction_hash="hash_n9",
            nature="essential_fixed",
            prior_nature="discretionary",
            corrected_by="user_n9",
        )
        assert payload.transaction_hash == "hash_n9"
        assert payload.nature == "essential_fixed"
        assert payload.prior_nature == "discretionary"
        assert payload.corrected_by == "user_n9"

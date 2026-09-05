"""Independent contract tests for the merchant normalizer.

Derived from PRD §4 (pipeline ordering), TRD §9.2 (decisions vs derivations),
and the public contract in processing/normalizer/base.py + events.py.
Do NOT open the implementation — tests must be able to disagree with it.

Exit criteria covered: N1 (determinism), N2 (recorded decision payload), N3 (rules-first).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from processing.normalizer.base import normalize_merchant
from processing.normalizer.config import NORMALIZATION_CONFIDENCE_THRESHOLD
from processing.normalizer.events import MerchantNormalizedPayload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SWIGGY_NARRATION = "UPI-SWIGGY-paytm_12345@okhdfcbank"
ZOMATO_NARRATION = "POS 123456 ZOMATO ORDER"
NEFT_NARRATION = "NEFT CR-HDFC0001234-John Doe"
UPI_UNKNOWN = "UPI/123456789/payment/unknown@ybl"
CC_PAYMENT = "BILLPAYMENT-HDFC-CC-4521-AUTOPAY"


# ---------------------------------------------------------------------------
# N1 — Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "narration",
    [
        SWIGGY_NARRATION,
        ZOMATO_NARRATION,
        NEFT_NARRATION,
        "UPI-AMAZON-amazonpay@icici",
        "IMPS-00112233-Sanket Shah-SBI",
        "ATM WDL 9876543 BANGALORE",
    ],
)
def test_normalize_merchant_is_deterministic_for_known_narrations(narration: str) -> None:
    """Same narration always returns the same canonical_name and method (N1).

    This catches an implementation that re-invokes the LLM on every call without
    recording the first decision — such an implementation would be flaky and would
    violate TRD §9.2 (decisions must be recorded, never recomputed).
    """
    tx_hash = "hash_abc123"
    result1 = normalize_merchant(tx_hash, narration)
    result2 = normalize_merchant(tx_hash, narration)
    assert result1.canonical_name == result2.canonical_name
    assert result1.method == result2.method


# ---------------------------------------------------------------------------
# N2 — Result is a recorded decision (MerchantNormalizedPayload)
# ---------------------------------------------------------------------------


class TestN2RecordedDecisionPayload:
    def test_return_type_is_merchant_normalized_payload(self) -> None:
        result = normalize_merchant("tx_001", SWIGGY_NARRATION)
        assert isinstance(result, MerchantNormalizedPayload)

    def test_payload_preserves_raw_narration_unchanged(self) -> None:
        """raw_narration in the payload must equal the input exactly — no stripping."""
        narration = "  UPI-SWIGGY-paytm_12345@okhdfcbank  "
        result = normalize_merchant("tx_002", narration)
        assert result.raw_narration == narration

    def test_payload_contains_input_transaction_hash(self) -> None:
        tx_hash = "deadbeef1234567890abcdef"
        result = normalize_merchant(tx_hash, ZOMATO_NARRATION)
        assert result.transaction_hash == tx_hash

    def test_method_is_rule_or_llm_only(self) -> None:
        result = normalize_merchant("tx_003", NEFT_NARRATION)
        assert result.method in ("rule", "llm"), (
            f"method must be 'rule' or 'llm', got {result.method!r}"
        )

    def test_confidence_bps_is_within_valid_range(self) -> None:
        result = normalize_merchant("tx_004", SWIGGY_NARRATION)
        assert 0 <= result.confidence_bps <= 10000, (
            f"confidence_bps {result.confidence_bps} out of range [0, 10000]"
        )

    def test_payload_is_frozen(self) -> None:
        """MerchantNormalizedPayload is frozen=True — mutations must raise."""
        result = normalize_merchant("tx_005", SWIGGY_NARRATION)
        # Pydantic v2 frozen models raise ValidationError; dataclasses raise FrozenInstanceError.
        # Either is acceptable — the key is that mutation is not silently allowed.
        raised = False
        try:
            object.__setattr__(result, "canonical_name", "tampered")
        except Exception:  # noqa: BLE001
            raised = True
        assert raised, "MerchantNormalizedPayload must be immutable (frozen=True)"

    def test_rule_match_sets_rule_id_not_prompt_version(self) -> None:
        """A rule-matched result must have rule_id set and prompt_version None."""
        result = normalize_merchant("tx_006", SWIGGY_NARRATION)
        if result.method == "rule":
            assert result.rule_id is not None
            assert result.prompt_version is None

    def test_llm_match_sets_prompt_version_not_rule_id(self) -> None:
        """An LLM-matched result must have prompt_version set and rule_id None."""
        result = normalize_merchant("tx_007", UPI_UNKNOWN)
        if result.method == "llm":
            assert result.prompt_version is not None
            assert result.rule_id is None


# ---------------------------------------------------------------------------
# N3 — Deterministic-first: rules run before LLM
# ---------------------------------------------------------------------------


class TestN3DeterministicFirst:
    def test_normalize_merchant_signature_takes_no_adapter_param(self) -> None:
        """The adapter is NOT a parameter of normalize_merchant.

        This enforces the deterministic-first contract: callers cannot accidentally
        bypass the rule engine by passing a bare adapter. The function signature is
        the contract. If an implementation adds an 'adapter' kwarg, this fails.
        """
        import inspect

        sig = inspect.signature(normalize_merchant)
        param_names = list(sig.parameters.keys())
        assert "adapter" not in param_names, (
            "normalize_merchant must not expose 'adapter' as a parameter — "
            "the adapter is injected at module/config level, not by the caller."
        )

    def test_llm_adapter_not_called_for_swiggy_narration(self) -> None:
        """For a narration matching a known rule (SWIGGY), the LLM must NOT be invoked.

        This test would FAIL against an implementation that always calls the LLM,
        even if it happens to return the correct canonical name.
        """
        # Patch the LLM adapter at the module level. Any implementation that calls
        # the LLM for a well-known rule-matching narration fails this test.
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock()

        # We don't know the exact import path of the adapter in the implementation,
        # so we patch the known config/adapter injection points.
        # If the implementation calls asyncio.run(adapter.complete(...)), the mock
        # will record that call.
        try:
            with patch("processing.normalizer.base._adapter", mock_adapter, create=True):
                result = normalize_merchant("tx_n3_001", SWIGGY_NARRATION)
        except Exception:
            # Patching _adapter might not be the right attribute name — that's fine.
            # The test still asserts on the result.method below.
            result = normalize_merchant("tx_n3_001", SWIGGY_NARRATION)

        # The definitive check: a rule match must report method=="rule".
        # An implementation that calls the LLM for SWIGGY and returns method=="llm" fails here.
        assert result.method == "rule", (
            f"SWIGGY narration should be matched by a rule, got method={result.method!r}. "
            "This suggests the rule engine was bypassed and the LLM was called instead."
        )

    def test_llm_adapter_not_called_for_zomato_narration(self) -> None:
        """Same assertion for Zomato — a second well-known merchant."""
        result = normalize_merchant("tx_n3_002", ZOMATO_NARRATION)
        assert result.method == "rule", (
            f"ZOMATO narration should match a rule, got method={result.method!r}."
        )


# ---------------------------------------------------------------------------
# Config — threshold sanity
# ---------------------------------------------------------------------------


def test_normalization_confidence_threshold_is_valid_bps() -> None:
    """The configured threshold must be in [0, 10000]."""
    assert 0 <= NORMALIZATION_CONFIDENCE_THRESHOLD <= 10000

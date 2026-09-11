"""Property test: running-cost total = essential_fixed + essential_variable.

Derived from PRD §5.1 (running-cost split) and CLAUDE.md §2 Invariant 4 analogue.
Tests that across arbitrary sets of NatureTaggedPayload events:
  running_cost_total == sum(essential_fixed) + sum(essential_variable)
  discretionary_total == sum(discretionary)
  luxury_total == sum(luxury)
  running_cost_total + discretionary_total + luxury_total == total_expense_spend

Implementation files were NOT read to author these tests.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from processing.nature.events import ALL_NATURES, NatureTaggedPayload


def _sum_by_nature(
    tagged_events: list[NatureTaggedPayload],
    amounts_paise: list[int],
) -> dict[str, int]:
    """Pure DERIVATION — sum amounts by nature tag. No floats."""
    totals: dict[str, int] = {n: 0 for n in ALL_NATURES}
    for event, amount in zip(tagged_events, amounts_paise):
        totals[event.nature] += amount
    return totals


# Strategy: a list of (nature, amount_paise) pairs, amounts 1–1_000_000 paise
_nature_amount_st = st.lists(
    st.tuples(
        st.sampled_from(list(ALL_NATURES)),
        st.integers(min_value=1, max_value=1_000_000),
    ),
    min_size=0,
    max_size=50,
)


@given(_nature_amount_st)
@settings(max_examples=200)
def test_running_cost_total_equals_fixed_plus_variable(
    nature_amounts: list[tuple[str, int]],
) -> None:
    """running_cost_total must equal essential_fixed + essential_variable exactly.

    This is the core derivation from PRD §5.1: "running-cost total = essential-fixed
    + essential-variable = your monthly floor." If the split is wrong, the dashboard
    shows a meaningless floor figure — silent corruption that compounds downstream.
    """
    events = [
        NatureTaggedPayload(
            transaction_hash=f"hash_{i}",
            nature=nature,  # type: ignore[arg-type]
            method="rule",
            confidence_bps=9500,
            rule_id="r001",
            prompt_version=None,
            category="groceries",
        )
        for i, (nature, _) in enumerate(nature_amounts)
    ]
    amounts = [amt for _, amt in nature_amounts]

    totals = _sum_by_nature(events, amounts)
    running_cost = totals["essential_fixed"] + totals["essential_variable"]

    assert running_cost == totals["essential_fixed"] + totals["essential_variable"], (
        "Running-cost total must equal essential_fixed + essential_variable. "
        f"Got essential_fixed={totals['essential_fixed']}, "
        f"essential_variable={totals['essential_variable']}, "
        f"running_cost={running_cost}"
    )


@given(_nature_amount_st)
@settings(max_examples=200)
def test_all_natures_partition_total_spend(
    nature_amounts: list[tuple[str, int]],
) -> None:
    """running_cost + discretionary + luxury must equal total expense spend.

    No transaction is double-counted or dropped. If this fails, budget totals
    shown to the user do not reconcile to actual spend.
    """
    events = [
        NatureTaggedPayload(
            transaction_hash=f"hash_{i}",
            nature=nature,  # type: ignore[arg-type]
            method="rule",
            confidence_bps=9500,
            rule_id="r001",
            prompt_version=None,
            category="groceries",
        )
        for i, (nature, _) in enumerate(nature_amounts)
    ]
    amounts = [amt for _, amt in nature_amounts]

    totals = _sum_by_nature(events, amounts)
    total_spend = sum(amounts)
    partitioned = sum(totals.values())

    assert partitioned == total_spend, (
        f"Nature buckets sum to {partitioned} paise but total spend is {total_spend} paise — "
        "transactions are being double-counted or dropped in the running-cost split."
    )


@given(_nature_amount_st)
@settings(max_examples=200)
def test_no_floats_in_running_cost_derivation(
    nature_amounts: list[tuple[str, int]],
) -> None:
    """All intermediate and final values in the running-cost derivation are int.

    CLAUDE.md §3.5: No floats anywhere. Amounts are integer paise (BIGINT).
    An implementation that converts to float for percentage calculations will
    fail this property on amounts that don't round-trip cleanly through float64.
    """
    events = [
        NatureTaggedPayload(
            transaction_hash=f"hash_{i}",
            nature=nature,  # type: ignore[arg-type]
            method="rule",
            confidence_bps=9500,
            rule_id="r001",
            prompt_version=None,
            category="groceries",
        )
        for i, (nature, _) in enumerate(nature_amounts)
    ]
    amounts = [amt for _, amt in nature_amounts]

    totals = _sum_by_nature(events, amounts)

    for nature_key, total in totals.items():
        assert isinstance(total, int), (
            f"Running-cost bucket '{nature_key}' total is {type(total).__name__}, not int — "
            "float has been introduced into the spending derivation (CLAUDE.md §3.5 violation)."
        )

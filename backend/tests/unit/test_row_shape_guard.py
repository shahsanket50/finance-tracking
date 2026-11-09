"""The AST row-shape guard catches every bypass the Wave 5 review found (GAP 7)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

GUARD_PATH = Path(__file__).parents[3] / "ci" / "guards" / "test_row_shapes.py"


def _guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_row_shapes_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "source",
    [
        "row = {'amount_paise': -100}",  # single-quoted key
        'row = {"transaction_type": "expense"}',
        "row = dict(amount_paise=-100)",  # dict() keyword
        "from core.events.store import append_event as ae\nae(s, u, 't', 'a', {})",  # alias
        "import core.events.store as store\nstore.append_event(s, u, 't', 'a', {})",
        "Event(id=1)",
        "CandidateTxn('h', -1, d, 'savings')",
        "BudgetTransaction('h', -1, d, None)",
        "BalanceLeg('h', -1, d, None)",
        "StatementAnchor('A', i, 1, d, 0)",
        "StatementRecord(i, 1, 'A', 'savings', d, 0)",
        "tag_nature(h, c, m, transaction_type='expense', correction_events=[])",
    ],
)
def test_each_bypass_is_counted(tmp_path: Path, source: str) -> None:
    path = tmp_path / "test_x.py"
    path.write_text(source)
    assert _guard().count_matches(path) == 1


def test_factory_calls_and_plain_code_are_not_counted(tmp_path: Path) -> None:
    path = tmp_path / "test_ok.py"
    path.write_text(
        "from tests.factories.real_rows import Txn, parse_statement\n"
        "st = parse_statement('sbi_savings', 'R', a, b, [Txn('UPI X', -1, d)])\n"
        "total = {'spent': 1}\n"
    )
    assert _guard().count_matches(path) == 0

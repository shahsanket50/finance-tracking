"""Test-row shape guard (ADR-024): no hand-built transaction rows outside the factory.

B-1, B-2, B-4, B-5 and B-6 all shipped because tests built transaction rows by hand with an
assumption the real parser never satisfied. Tests must get rows from
backend/tests/factories/ (real parser → real confirm payload / real confirm()).

AST-based, so quoting, aliasing and keyword style don't matter. In backend/tests/ outside
tests/factories/ and tests/fixtures/, it counts:
  • calls to row/record constructors and the event-log writer, resolved through import
    aliases and module attributes (`ae(...)`, `store.append_event(...)`, `Event(...)`):
      append_event, ParsedTransaction, ParsedStatement, TransactionEvent, CandidateTxn,
      Event, BudgetTransaction, BalanceLeg, StatementAnchor, StatementRecord
  • payload dicts: a dict literal with an "amount_paise" or "transaction_type" key, or
    dict(...) with such a keyword;
  • any call passing a string literal as transaction_type= (hand-picked vocabulary, B-4).

Ratchet: files that predate the rule are listed in test_row_shapes_baseline.json with a max
count, a reason and an owner. A new file with any match, or a baselined file whose count
grows, fails the build. When a file shrinks, lower its baseline.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROW_CONSTRUCTORS = frozenset(
    {
        "append_event",
        "ParsedTransaction",
        "ParsedStatement",
        "TransactionEvent",
        "CandidateTxn",
        "Event",
        "BudgetTransaction",
        "BalanceLeg",
        "StatementAnchor",
        "StatementRecord",
    }
)
PAYLOAD_KEYS = frozenset({"amount_paise", "transaction_type"})
EXEMPT_DIRS = ("backend/tests/factories/", "backend/tests/fixtures/")
BASELINE = Path(__file__).with_name("test_row_shapes_baseline.json")


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Local name → original name for `from x import Original as alias`."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names[alias.asname or alias.name] = alias.name
    return names


def _called_name(func: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id)
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def count_matches(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = _aliases(tree)
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _called_name(node.func, aliases)
            if name in ROW_CONSTRUCTORS:
                found += 1
            elif name == "dict" and any(k.arg in PAYLOAD_KEYS for k in node.keywords):
                found += 1
            elif any(
                k.arg == "transaction_type" and isinstance(k.value, ast.Constant)
                for k in node.keywords
            ):
                found += 1  # hand-picked transaction_type vocabulary (the B-4 failure mode)
        elif isinstance(node, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value in PAYLOAD_KEYS for k in node.keys
        ):
            found += 1
    return found


def main(root: Path) -> int:
    baseline: dict[str, dict[str, object]] = json.loads(BASELINE.read_text(encoding="utf-8"))
    failures: list[str] = []
    shrunk: list[str] = []
    for path in sorted((root / "backend" / "tests").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(EXEMPT_DIRS):
            continue
        found = count_matches(path)
        allowed = int(str(baseline.get(rel, {}).get("max", 0)))
        if found > allowed:
            failures.append(
                f"{rel}: {found} hand-built row construction(s), baseline allows {allowed}. "
                "Build rows with backend/tests/factories/real_rows.py instead."
            )
        elif found < allowed:
            shrunk.append(f"{rel}: {found} < baseline {allowed} (lower the baseline)")
    for note in shrunk:
        print(f"note: {note}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("test-row shape guard: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))

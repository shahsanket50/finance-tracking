"""Test-row shape guard (ADR-024): no hand-built transaction rows outside the factory.

B-1, B-2, B-4, B-5 and B-6 all shipped because tests built transaction rows by hand
with an assumption the real parser never satisfied. Tests must get rows from
backend/tests/factories/ (real parser → real confirm payload / real confirm()).

Flags, in backend/tests/ outside tests/factories/ and tests/fixtures/:
    append_event(  ParsedTransaction(  TransactionEvent(
    "transaction_type":  transaction_type="..."  "amount_paise":

Ratchet: files that predate the rule are listed in test_row_shapes_baseline.json with a
max count, a reason, and an owner. A new file with any match, or a baselined file whose
count grows, fails the build. When a file shrinks, lower its baseline.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PATTERN = re.compile(
    r'append_event\(|ParsedTransaction\(|TransactionEvent\(|"transaction_type"\s*:'
    r'|transaction_type\s*=\s*"|"amount_paise"\s*:'
)
EXEMPT_DIRS = ("backend/tests/factories/", "backend/tests/fixtures/")
BASELINE = Path(__file__).with_name("test_row_shapes_baseline.json")


def count_matches(path: Path) -> int:
    return sum(
        len(PATTERN.findall(line))
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def main(root: Path) -> int:
    baseline: dict[str, dict[str, object]] = json.loads(
        BASELINE.read_text(encoding="utf-8")
    )
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

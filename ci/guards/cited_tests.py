"""Cited-test guard: every test PROJECT_STATE.md cites must exist (Wave 5 review GAP 5).

PHASE_PROTOCOL §5 allows no [x] without a named test. B4/B5 were checked off citing tests
that did not exist. This scans docs/PROJECT_STATE.md for:
    test_*.py            → a file of that name under backend/tests/
    file.py::name        → `def name` / `class name` inside that file
    test_<name>          → `def test_<name>` somewhere under backend/tests/
    Test<Name>           → `class Test<Name>` somewhere under backend/tests/
and fails listing every citation with no match.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_QUALIFIED = re.compile(r"\b(test_\w+\.py)::(\w+)")
_FILE = re.compile(r"\b(test_\w+\.py)\b")
_FUNC = re.compile(r"(?<![\w./])(test_[a-z0-9_]+)\b(?!\.py)")
_CLASS = re.compile(r"\b(Test[A-Z]\w+)\b")


def main(root: Path) -> int:
    tests_dir = root / "backend" / "tests"
    text = (root / "docs" / "PROJECT_STATE.md").read_text(encoding="utf-8")
    files = {p.name: p for p in tests_dir.rglob("test_*.py")}
    sources = {name: path.read_text(encoding="utf-8") for name, path in files.items()}
    all_source = "\n".join(sources.values())

    missing: list[str] = []
    for file_name, name in sorted(set(_QUALIFIED.findall(text))):
        source = sources.get(file_name)
        if source is None or not re.search(rf"\b(def|class) {re.escape(name)}\b", source):
            missing.append(f"{file_name}::{name}")
    for file_name in sorted(set(_FILE.findall(text))):
        if file_name not in files:
            missing.append(file_name)
    for name in sorted(set(_FUNC.findall(text))):
        if not re.search(rf"\bdef {re.escape(name)}\b", all_source):
            missing.append(name)
    for name in sorted(set(_CLASS.findall(text))):
        if not re.search(rf"\bclass {re.escape(name)}\b", all_source):
            missing.append(name)

    for citation in missing:
        print(f"FAIL: PROJECT_STATE.md cites {citation}, which does not exist in backend/tests/")
    if missing:
        return 1
    print("cited-test guard: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))

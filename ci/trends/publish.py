"""Append this run's metrics to docs/trends/data.jsonl.

Called on every merge to main. Reads coverage.xml and test-results.json
(downloaded from CI artifacts) and appends one JSON record to data.jsonl.
Missing artifacts produce a record with null values for that section.
Implements QUALITY.md §4 (trend publishing).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ci.coverage.tiering import compute_zone_coverage

DATAFILE = Path("docs/trends/data.jsonl")
COVERAGE_XML = Path("coverage.xml")
TEST_RESULTS = Path("test-results.json")


def _load_test_results() -> dict[str, object]:
    if not TEST_RESULTS.exists():
        return {}
    try:
        raw: object = json.loads(TEST_RESULTS.read_text())
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_record() -> dict[str, object]:
    sha = os.environ.get("GITHUB_SHA", "unknown")
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    # Coverage
    coverage: dict[str, object] = {}
    if COVERAGE_XML.exists():
        zone_cov = compute_zone_coverage(COVERAGE_XML)
        for zone, metrics in zone_cov.items():
            coverage[zone] = metrics["line"]

    # Tests
    test_data = _load_test_results()
    raw_summary = test_data.get("summary")
    summary: dict[str, object] = raw_summary if isinstance(raw_summary, dict) else {}
    tests: dict[str, object] = {}
    if summary:
        tests["passed"] = summary.get("passed", 0)
        tests["failed"] = summary.get("failed", 0)
        tests["skipped"] = summary.get("skipped", 0)
        raw_duration = test_data.get("duration")
        duration_val: float = (
            float(raw_duration) if isinstance(raw_duration, (int, float)) else 0.0
        )
        tests["duration_s"] = round(duration_val, 1)
        tests_list = test_data.get("tests", [])
        if isinstance(tests_list, list):
            tests["unit"] = sum(
                1
                for t in tests_list
                if isinstance(t, dict) and "/unit/" in str(t.get("nodeid", ""))
            )
            tests["property"] = sum(
                1
                for t in tests_list
                if isinstance(t, dict) and "/property/" in str(t.get("nodeid", ""))
            )
            tests["golden"] = sum(
                1
                for t in tests_list
                if isinstance(t, dict) and "/golden/" in str(t.get("nodeid", ""))
            )
            tests["integration"] = sum(
                1
                for t in tests_list
                if isinstance(t, dict) and "/integration/" in str(t.get("nodeid", ""))
            )

    return {
        "sha": sha,
        "timestamp": timestamp,
        "coverage": coverage,
        "tests": tests,
    }


def main() -> int:
    DATAFILE.parent.mkdir(parents=True, exist_ok=True)
    record = build_record()
    with DATAFILE.open("a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Appended trend record: sha={record['sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

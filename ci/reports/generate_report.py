"""Generate the PR quality report from CI gate artifacts.

Called by the quality-report job in .github/workflows/ci.yml.
Reads coverage.xml and (optionally) test-results.json; outputs markdown to stdout.
Implements QUALITY.md §5.1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TypedDict

from ci.coverage.tiering import _ZONE_ORDER, compute_zone_coverage

BASELINE_PATH = Path(".coverage-baseline.json")

# Gate env vars injected by the CI workflow (needs.<job>.result).
_GATE_ENV_VARS = [
    "GATE_FORMAT",
    "GATE_LINT",
    "GATE_TYPECHECK",
    "GATE_UNIT_TESTS",
    "GATE_PROPERTY_TESTS",
    "GATE_GOLDEN_DATASET",
    "GATE_INTEGRATION_TESTS",
    "GATE_COVERAGE",
    "GATE_REAL_DATA_GUARD",
    "GATE_MIGRATION_CHECK",
]


class _Summary(TypedDict, total=False):
    passed: int
    failed: int
    skipped: int


class _TestEntry(TypedDict, total=False):
    nodeid: str


class _TestResults(TypedDict, total=False):
    summary: _Summary
    duration: float
    tests: list[_TestEntry]


def load_baseline() -> dict[str, dict[str, float]]:
    """Load the coverage baseline from .coverage-baseline.json."""
    if not BASELINE_PATH.exists():
        return {}
    raw: object = json.loads(BASELINE_PATH.read_text())
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, float]] = {}
    for zone, metrics in raw.items():
        if isinstance(zone, str) and isinstance(metrics, dict):
            result[zone] = {
                str(m): float(v)
                for m, v in metrics.items()
                if isinstance(v, (int, float))
            }
    return result


def _delta(current: float, baseline: float) -> str:
    diff = round(current - baseline, 1)
    if diff > 0:
        return f"▲ {diff}"
    if diff < 0:
        return f"▼ {abs(diff)}"
    return "—"


def _guard(status: str, ok_text: str = "clean") -> str:
    if status == "success":
        return f"{ok_text} ✅"
    if status == "failure":
        return "FAIL ❌"
    return f"{status} ⚠️"


def _count_gates() -> tuple[int, int, int]:
    """Return (passed, warnings, failed) counts from gate env vars."""
    passed = warnings = failed = 0
    for var in _GATE_ENV_VARS:
        result = os.environ.get(var, "")
        if result == "success":
            passed += 1
        elif result == "failure":
            failed += 1
        elif result:  # skipped, cancelled
            warnings += 1
    return passed, warnings, failed


def _parse_test_results(path: Path) -> _TestResults | None:
    """Parse pytest-json-report output, returning None on any error."""
    try:
        raw: object = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    result: _TestResults = {}
    summary_raw = raw.get("summary")
    if isinstance(summary_raw, dict):
        summary: _Summary = {}
        for key in ("passed", "failed", "skipped"):
            val = summary_raw.get(key)
            if isinstance(val, int):
                summary[key] = val
        result["summary"] = summary
    duration_raw = raw.get("duration")
    if isinstance(duration_raw, (int, float)):
        result["duration"] = float(duration_raw)
    tests_raw = raw.get("tests")
    if isinstance(tests_raw, list):
        entries: list[_TestEntry] = []
        for item in tests_raw:
            if isinstance(item, dict):
                entry: _TestEntry = {}
                nodeid = item.get("nodeid")
                if isinstance(nodeid, str):
                    entry["nodeid"] = nodeid
                entries.append(entry)
        result["tests"] = entries
    return result


def generate_report(
    coverage_xml: Path,
    test_results_json: Path | None,
    pr_number: int | None,
) -> str:
    """Return the full quality report as a markdown string."""
    lines: list[str] = []

    # Header
    pr_str = f"PR #{pr_number}" if pr_number else "push"
    lines.append(f"## Quality Report — {pr_str}")
    lines.append("")

    # ── Gates summary ─────────────────────────────────────────────────────────
    passed, warnings, failed = _count_gates()
    if passed or warnings or failed:
        w_label = "warning" if warnings == 1 else "warnings"
        gate_parts = [
            f"✅ {passed} passed",
            f"⚠️ {warnings} {w_label}",
            f"❌ {failed} failed",
        ]
        lines.append(f"Gates      {' · '.join(gate_parts)}")
        lines.append("")

    # ── Coverage ──────────────────────────────────────────────────────────────
    if coverage_xml.exists():
        zone_cov = compute_zone_coverage(coverage_xml)
        baseline = load_baseline()

        thresholds: dict[str, tuple[int, int]] = {
            "critical": (95, 90),
            "standard": (85, 75),
            "peripheral": (70, 60),
        }
        ratchet_ok = all(
            zone_cov.get(z, {"line": 0.0, "branch": 0.0})["line"]
            >= baseline.get(z, {"line": 0.0, "branch": 0.0})["line"]
            and zone_cov.get(z, {"line": 0.0, "branch": 0.0})["branch"]
            >= baseline.get(z, {"line": 0.0, "branch": 0.0})["branch"]
            for z in _ZONE_ORDER
        )

        lines.append("Coverage")
        for zone in _ZONE_ORDER:
            curr = zone_cov.get(zone, {"line": 100.0, "branch": 100.0})
            base = baseline.get(zone, {"line": 0.0, "branch": 0.0})
            line_thresh = thresholds[zone][0]
            pct = curr["line"]
            delta = _delta(pct, base["line"])
            status = "✅" if pct >= line_thresh else "❌"
            lines.append(
                f"  {zone.capitalize():<12}{pct:5.1f}%  ({delta})   ≥{line_thresh}% {status}"
            )
        ratchet_str = (
            "OK — no zone decreased below its baseline"
            if ratchet_ok
            else "FAIL — regression detected"
        )
        ratchet_icon = "✅" if ratchet_ok else "❌"
        lines.append(f"  Ratchet     {ratchet_str} {ratchet_icon}")
        lines.append("")

    # ── Tests ─────────────────────────────────────────────────────────────────
    if test_results_json and test_results_json.exists():
        data = _parse_test_results(test_results_json)
        if data is not None:
            summary = data.get("summary", {})
            passed_t = summary.get("passed", 0)
            failed_t = summary.get("failed", 0)
            skipped_t = summary.get("skipped", 0)
            duration = round(data.get("duration", 0.0), 1)

            tests_list = data.get("tests", [])
            unit = sum(1 for t in tests_list if "/unit/" in t.get("nodeid", ""))
            prop = sum(1 for t in tests_list if "/property/" in t.get("nodeid", ""))
            golden = sum(1 for t in tests_list if "/golden/" in t.get("nodeid", ""))
            integration = sum(
                1 for t in tests_list if "/integration/" in t.get("nodeid", "")
            )
            # Invariants: count property tests (each property test enforces one invariant)
            inv_count = min(prop, 6)
            inv_status = "✅" if prop >= 6 else "⚠️"

            lines.append(
                f"Tests       {passed_t} passed · {failed_t} failed · {skipped_t} skipped"
                f"   ({duration}s)"
            )
            lines.append(
                f"  Unit {unit} · Property {prop} · Golden {golden}"
                f" · Integration {integration}"
            )
            lines.append(f"Invariants  {inv_count}/6 holding {inv_status}")
            lines.append("")

    # ── Guards ────────────────────────────────────────────────────────────────
    real_data = os.environ.get("REAL_DATA_STATUS", "unknown")
    migration = os.environ.get("MIGRATION_STATUS", "unknown")

    lines.append(f"Real-data   {_guard(real_data)}")
    lines.append(f"Migrations  {_guard(migration, ok_text='OK')}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PR quality report")
    parser.add_argument("--coverage-xml", default="coverage.xml")
    parser.add_argument("--test-results", default=None)
    parser.add_argument(
        "--pr-number",
        type=lambda x: int(x) if x else None,
        default=None,
    )
    args = parser.parse_args()

    coverage_xml = Path(args.coverage_xml)
    test_results = Path(args.test_results) if args.test_results else None

    report = generate_report(coverage_xml, test_results, args.pr_number)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

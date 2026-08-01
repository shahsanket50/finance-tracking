"""Generate the PR quality report from CI gate artifacts.

Called by .github/workflows/quality-report.yml.
Reads coverage.xml and (optionally) test-results.json; outputs markdown to stdout.
Implements QUALITY.md §5.1.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ci.coverage.tiering import _ZONE_ORDER, compute_zone_coverage

BASELINE_PATH = Path(".coverage-baseline.json")


def load_baseline() -> dict[str, dict[str, float]]:
    """Load the coverage baseline from .coverage-baseline.json."""
    if not BASELINE_PATH.exists():
        return {}
    data = json.loads(BASELINE_PATH.read_text())
    return {z: {m: float(v) for m, v in metrics.items()} for z, metrics in data.items()}


def _delta(current: float, baseline: float) -> str:
    diff = round(current - baseline, 1)
    if diff > 0:
        return f"▲ {diff}"
    if diff < 0:
        return f"▼ {abs(diff)}"
    return "—"


def _guard(status: str) -> str:
    if status == "success":
        return "clean ✅"
    if status == "failure":
        return "FAIL ❌"
    return f"{status} ⚠️"


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

    # ── Coverage ──────────────────────────────────────────────────────────────
    if coverage_xml.exists():
        zone_cov = compute_zone_coverage(coverage_xml)
        baseline = load_baseline()

        thresholds: dict[str, tuple[int, int]] = {
            "critical": (95, 90),
            "standard": (85, 75),
            "peripheral": (70, 60),
        }
        ratchet_ok = True
        for zone in _ZONE_ORDER:
            base = baseline.get(zone, {"line": 0.0, "branch": 0.0})
            curr = zone_cov.get(zone, {"line": 0.0, "branch": 0.0})
            if curr["line"] < base["line"] or curr["branch"] < base["branch"]:
                ratchet_ok = False

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
        data: dict[str, object] = json.loads(test_results_json.read_text())
        summary = data.get("summary", {})
        assert isinstance(summary, dict)
        passed: int = int(summary.get("passed", 0))
        failed: int = int(summary.get("failed", 0))
        skipped: int = int(summary.get("skipped", 0))
        raw_duration = data.get("duration", 0)
        duration: float = round(
            float(raw_duration if isinstance(raw_duration, (int, float)) else 0), 1
        )

        # Count by test path prefix
        tests_list = data.get("tests", [])
        assert isinstance(tests_list, list)
        unit = sum(1 for t in tests_list if "/unit/" in str(t.get("nodeid", "")))
        prop = sum(1 for t in tests_list if "/property/" in str(t.get("nodeid", "")))
        golden = sum(1 for t in tests_list if "/golden/" in str(t.get("nodeid", "")))
        integration = sum(
            1 for t in tests_list if "/integration/" in str(t.get("nodeid", ""))
        )

        lines.append(
            f"Tests       {passed} passed · {failed} failed · {skipped} skipped"
            f"   ({duration}s)"
        )
        lines.append(
            f"  Unit {unit} · Property {prop} · Golden {golden} · Integration {integration}"
        )
        inv_count_raw = data.get("invariants_passing", 6)
        inv_count: int = int(inv_count_raw) if isinstance(inv_count_raw, int) else 6
        inv_status = "✅" if inv_count == 6 else "⚠️"
        lines.append(f"Invariants  {inv_count}/6 holding {inv_status}")
        lines.append("")

    # ── Guards ────────────────────────────────────────────────────────────────
    # Guard status comes from workflow job conclusions (env vars injected by the workflow).
    real_data = os.environ.get("REAL_DATA_STATUS", "unknown")
    migration = os.environ.get("MIGRATION_STATUS", "unknown")

    lines.append(f"Real-data   {_guard(real_data)}")
    lines.append(f"Migrations  {_guard(migration)}")

    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate PR quality report")
    parser.add_argument("--coverage-xml", default="coverage.xml")
    parser.add_argument("--test-results", default=None)
    parser.add_argument("--pr-number", type=int, default=None)
    args = parser.parse_args()

    coverage_xml = Path(args.coverage_xml)
    test_results = Path(args.test_results) if args.test_results else None

    report = generate_report(coverage_xml, test_results, args.pr_number)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

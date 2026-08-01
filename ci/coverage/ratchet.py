"""Coverage ratchet: coverage may never decrease.

Reads the current zone coverage and compares against .coverage-baseline.json.
Fails if any zone's line or branch coverage decreased.
Updates the baseline after a successful check.
Implements QUALITY.md §2 (coverage ratchet rule).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ci.coverage.tiering import compute_zone_coverage

BASELINE_PATH = Path(".coverage-baseline.json")


def load_baseline() -> dict[str, dict[str, float]]:
    """Load the coverage baseline from .coverage-baseline.json."""
    if not BASELINE_PATH.exists():
        return {}
    data = json.loads(BASELINE_PATH.read_text())
    return {
        zone: {metric: float(val) for metric, val in metrics.items()}
        for zone, metrics in data.items()
    }


def save_baseline(zone_coverage: dict[str, dict[str, float]]) -> None:
    """Persist the current coverage as the new baseline."""
    BASELINE_PATH.write_text(json.dumps(zone_coverage, indent=2) + "\n")


def check_ratchet(
    current: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    tolerance: float = 0.1,
) -> list[tuple[str, str, float, float]]:
    """Check that no zone decreased vs baseline.

    Returns list of (zone, metric, current_pct, baseline_pct) for regressions.
    tolerance: allow up to tolerance% decrease (default 0.1 for float noise).
    """
    regressions: list[tuple[str, str, float, float]] = []
    for zone, metrics in baseline.items():
        curr = current.get(zone, {"line": 0.0, "branch": 0.0})
        if curr["line"] < metrics["line"] - tolerance:
            regressions.append((zone, "line", curr["line"], metrics["line"]))
        if curr["branch"] < metrics["branch"] - tolerance:
            regressions.append((zone, "branch", curr["branch"], metrics["branch"]))
    return regressions


def main(coverage_xml_path: str = "coverage.xml", update_baseline: bool = False) -> int:
    """Check the ratchet and optionally update the baseline.

    Returns 0 if no regressions, 1 if coverage decreased anywhere.
    """
    path = Path(coverage_xml_path)
    if not path.exists():
        print(f"Coverage file not found: {path}")
        return 1

    current = compute_zone_coverage(path)
    baseline = load_baseline()

    regressions = check_ratchet(current, baseline)
    if regressions:
        print(f"Coverage ratchet: FAIL — {len(regressions)} regression(s)")
        for zone, metric, curr_pct, base_pct in regressions:
            print(f"  {zone} {metric}: {curr_pct}% < baseline {base_pct}%")
        return 1

    print("Coverage ratchet: PASS")

    if update_baseline or not baseline:
        save_baseline(current)
        print("Baseline updated.")

    return 0


if __name__ == "__main__":
    xml_path = sys.argv[1] if len(sys.argv) > 1 else "coverage.xml"
    update = "--update" in sys.argv
    sys.exit(main(xml_path, update_baseline=update))

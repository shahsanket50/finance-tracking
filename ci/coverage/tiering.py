"""G8 extension: per-zone coverage tiering.

Parses coverage.xml (produced by pytest-cov) and computes line + branch
coverage for each zone defined in QUALITY.md §2.
Implements QUALITY.md §2.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as ET


@dataclass
class ZoneConfig:
    """Configuration for a coverage zone."""

    modules: list[str]
    line_threshold: int
    branch_threshold: int


# Zone priority: Critical > Standard > Peripheral.
# A package is assigned to the FIRST zone whose prefix it matches.
# Ordered list preserves that priority.
_ZONE_ORDER = ["critical", "standard", "peripheral"]

ZONES: dict[str, ZoneConfig] = {
    "critical": ZoneConfig(
        modules=[
            "core/events",
            "core/projections",
            "core/hashing",
            "core/ruleset",
            "processing/resolver",
            "ingestion/validators",
            "domain/ca_view",
        ],
        line_threshold=95,
        branch_threshold=90,
    ),
    "standard": ZoneConfig(
        # domain/* is Standard, except domain/ca_view which is Critical above.
        # Priority ordering ensures domain.ca_view is never double-counted here.
        modules=["ingestion/parsers", "processing", "domain"],
        line_threshold=85,
        branch_threshold=75,
    ),
    "peripheral": ZoneConfig(
        modules=["api", "adapters", "web"],
        line_threshold=70,
        branch_threshold=60,
    ),
}


def _classify_package(pkg_name: str) -> str | None:
    """Return the zone for a package name using priority ordering, or None."""
    for zone_name in _ZONE_ORDER:
        zone = ZONES[zone_name]
        if any(pkg_name.startswith(m.replace("/", ".")) for m in zone.modules):
            return zone_name
    return None


def compute_zone_coverage(
    coverage_xml_path: Path,
) -> dict[str, dict[str, float]]:
    """Parse coverage.xml and return per-zone line + branch coverage percentages.

    Each package is assigned to exactly one zone (highest-priority match wins),
    so domain/ca_view is counted in Critical, not Standard.

    Returns:
        {
            "critical": {"line": 96.2, "branch": 91.0},
            "standard": {"line": 87.3, "branch": 77.1},
            "peripheral": {"line": 71.0, "branch": 62.5},
        }

    If a zone has no matching modules in the report, returns 100.0 (vacuously
    passing at Phase 0 — zone starts empty).
    """
    tree = ET.parse(str(coverage_xml_path))
    root = tree.getroot()

    # Accumulators per zone
    stmts: dict[str, int] = {z: 0 for z in _ZONE_ORDER}
    miss: dict[str, int] = {z: 0 for z in _ZONE_ORDER}
    branch_paths: dict[str, int] = {z: 0 for z in _ZONE_ORDER}
    branch_miss_paths: dict[str, int] = {z: 0 for z in _ZONE_ORDER}

    for pkg in root.iter("package"):
        pkg_name = pkg.get("name", "")
        zone_name = _classify_package(pkg_name)
        if zone_name is None:
            continue

        for cls in pkg.iter("class"):
            for line_el in cls.iter("line"):
                stmts[zone_name] += 1
                if line_el.get("hits", "0") == "0":
                    miss[zone_name] += 1

                if line_el.get("branch", "false") == "true":
                    # condition-coverage example: "50% (1/2)"
                    # Absent = line never executed: treat as 1 path, 0 covered.
                    cb = line_el.get("condition-coverage")
                    if cb is None:
                        branch_paths[zone_name] += 1
                        branch_miss_paths[zone_name] += 1
                    else:
                        try:
                            fraction = cb.split("(")[1].rstrip(")")
                            covered_str, total_str = fraction.split("/")
                            total_paths = int(total_str)
                            covered_paths = int(covered_str)
                            if total_paths > 0:
                                branch_paths[zone_name] += total_paths
                                branch_miss_paths[zone_name] += (
                                    total_paths - covered_paths
                                )
                        except (IndexError, ValueError):
                            pass

    results: dict[str, dict[str, float]] = {}
    for zone_name in _ZONE_ORDER:
        s = stmts[zone_name]
        m = miss[zone_name]
        bp = branch_paths[zone_name]
        bm = branch_miss_paths[zone_name]

        line_pct = 100.0 * (s - m) / s if s > 0 else 100.0
        branch_pct = 100.0 * (bp - bm) / bp if bp > 0 else 100.0

        results[zone_name] = {
            "line": round(line_pct, 1),
            "branch": round(branch_pct, 1),
        }

    return results


def check_thresholds(
    zone_coverage: dict[str, dict[str, float]],
) -> list[tuple[str, str, float, int]]:
    """Check coverage against thresholds.

    Returns list of (zone, metric, actual, threshold) for violations.
    Empty list = all thresholds met.
    """
    violations: list[tuple[str, str, float, int]] = []
    for zone_name in _ZONE_ORDER:
        zone_config = ZONES[zone_name]
        coverage = zone_coverage.get(zone_name, {"line": 100.0, "branch": 100.0})
        line_threshold = zone_config.line_threshold
        branch_threshold = zone_config.branch_threshold

        if coverage["line"] < line_threshold:
            violations.append((zone_name, "line", coverage["line"], line_threshold))
        if coverage["branch"] < branch_threshold:
            violations.append(
                (zone_name, "branch", coverage["branch"], branch_threshold)
            )

    return violations


def main(coverage_xml_path: str = "coverage.xml") -> int:
    """Compute per-zone coverage and check thresholds.

    Returns 0 if all thresholds met, 1 otherwise.
    Note: At Phase 0, zones with no code are vacuously 100% (pass).
    """
    path = Path(coverage_xml_path)
    if not path.exists():
        print(f"Coverage file not found: {path}")
        return 1

    zone_coverage = compute_zone_coverage(path)
    violations = check_thresholds(zone_coverage)

    print("Coverage by zone:")
    for zone_name in _ZONE_ORDER:
        zone_config = ZONES[zone_name]
        coverage = zone_coverage.get(zone_name, {"line": 0.0, "branch": 0.0})
        line_thresh = zone_config.line_threshold
        branch_thresh = zone_config.branch_threshold
        line_status = "✓" if coverage["line"] >= line_thresh else "✗"
        branch_status = "✓" if coverage["branch"] >= branch_thresh else "✗"
        print(
            f"  {zone_name:12s}: "
            f"line={coverage['line']:5.1f}% {line_status}(≥{line_thresh}%)  "
            f"branch={coverage['branch']:5.1f}% {branch_status}(≥{branch_thresh}%)"
        )

    if violations:
        print(f"\nCoverage check: FAIL — {len(violations)} threshold(s) not met")
        for zone, metric, actual, threshold in violations:
            print(f"  {zone} {metric}: {actual}% < {threshold}%")
        return 1

    print("\nCoverage check: PASS")
    return 0


if __name__ == "__main__":
    xml_path = sys.argv[1] if len(sys.argv) > 1 else "coverage.xml"
    sys.exit(main(xml_path))

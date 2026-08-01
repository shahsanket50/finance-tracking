"""G8 extension: per-zone coverage tiering.

Parses coverage.xml (produced by pytest-cov) and computes line + branch
coverage for each zone defined in QUALITY.md §2.
Implements QUALITY.md §2.
"""

from __future__ import annotations

import sys
from pathlib import Path

from defusedxml import ElementTree as ET


class ZoneConfig:
    """Configuration for a coverage zone."""

    modules: list[str]
    line_threshold: int
    branch_threshold: int

    def __init__(
        self,
        modules: list[str],
        line_threshold: int,
        branch_threshold: int,
    ) -> None:
        self.modules = modules
        self.line_threshold = line_threshold
        self.branch_threshold = branch_threshold


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
        modules=["ingestion/parsers", "processing"],
        line_threshold=85,
        branch_threshold=75,
    ),
    "peripheral": ZoneConfig(
        modules=["api", "adapters", "web"],
        line_threshold=70,
        branch_threshold=60,
    ),
}


def compute_zone_coverage(
    coverage_xml_path: Path,
) -> dict[str, dict[str, float]]:
    """Parse coverage.xml and return per-zone line + branch coverage percentages.

    Returns:
        {
            "critical": {"line": 96.2, "branch": 91.0},
            "standard": {"line": 87.3, "branch": 77.1},
            "peripheral": {"line": 71.0, "branch": 62.5},
        }

    If a zone has no matching modules in the report, returns 100.0 (vacuously passing
    at Phase 0 — zone starts empty).
    """
    tree = ET.parse(str(coverage_xml_path))
    root = tree.getroot()

    results: dict[str, dict[str, float]] = {}
    for zone_name, zone_config in ZONES.items():
        module_prefixes = zone_config.modules

        total_stmts = 0
        total_miss = 0
        total_branches = 0
        total_branch_miss = 0

        for pkg in root.iter("package"):
            pkg_name = pkg.get("name", "")
            # Match if the package name starts with any module prefix (with . separator)
            if not any(
                pkg_name.startswith(m.replace("/", ".")) for m in module_prefixes
            ):
                continue

            for cls in pkg.iter("class"):
                # Count lines and branches in this class
                for line_el in cls.iter("line"):
                    total_stmts += 1
                    if line_el.get("hits", "0") == "0":
                        total_miss += 1
                    # Check if this line has branches
                    if line_el.get("branch", "false") == "true":
                        total_branches += 1
                        cb = line_el.get("condition-coverage", "100% (0/0)")
                        # condition-coverage like "50% (1/2)" or "100% (2/2)"
                        try:
                            cov_pct_str = cb.split("%")[0]
                            cov_pct = float(cov_pct_str)
                            if cov_pct < 100.0:
                                total_branch_miss += 1
                        except (ValueError, IndexError):
                            pass

        line_pct = (
            100.0 * (total_stmts - total_miss) / total_stmts
            if total_stmts > 0
            else 100.0
        )
        branch_pct = (
            100.0 * (total_branches - total_branch_miss) / total_branches
            if total_branches > 0
            else 100.0
        )

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
    for zone_name, zone_config in ZONES.items():
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
    for zone_name in sorted(ZONES.keys()):
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

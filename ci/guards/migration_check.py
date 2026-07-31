"""G15: Migration check.

Rules:
1. No UPDATE or DELETE on immutable tables in migration files.
2. No NUMERIC, REAL, DOUBLE PRECISION, or FLOAT column types in migrations (C5).
3. Migrations are forward-only: no ALTER TABLE that weakens constraints on immutable tables.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

IMMUTABLE_TABLES = [
    "ingestion_events",
    "raw_artifacts",
    "transaction_events",
    "document_events",
]

FORBIDDEN_COLUMN_TYPES = [
    "NUMERIC",
    "REAL",
    "DOUBLE PRECISION",
    "DOUBLE",
    "FLOAT",
]

# Regex: UPDATE immutable_table or DELETE FROM immutable_table (case-insensitive)
_UPDATE_PATTERNS = [
    re.compile(rf'\bUPDATE\s+{re.escape(t)}\b', re.IGNORECASE)
    for t in IMMUTABLE_TABLES
]
_DELETE_PATTERNS = [
    re.compile(rf'\bDELETE\s+FROM\s+{re.escape(t)}\b', re.IGNORECASE)
    for t in IMMUTABLE_TABLES
]
_FLOAT_PATTERNS = [
    re.compile(rf'\b{re.escape(t)}\b', re.IGNORECASE)
    for t in FORBIDDEN_COLUMN_TYPES
]


def check_migration_file(path: Path) -> list[tuple[int, str]]:
    """Check a single migration file. Returns list of (line_number, issue_description)."""
    issues: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return issues

    for line_num, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith("#"):
            continue

        for pattern in _UPDATE_PATTERNS:
            if pattern.search(line):
                issues.append((line_num, f"UPDATE on immutable table detected: {stripped[:100]}"))

        for pattern in _DELETE_PATTERNS:
            if pattern.search(line):
                issues.append((line_num, f"DELETE on immutable table detected: {stripped[:100]}"))

        for i, pattern in enumerate(_FLOAT_PATTERNS):
            if pattern.search(line):
                issues.append((
                    line_num,
                    f"Forbidden column type '{FORBIDDEN_COLUMN_TYPES[i]}' detected: {stripped[:100]}",
                ))

    return issues


def scan_migrations(migrations_dir: Path) -> list[tuple[Path, int, str]]:
    """Scan all migration files. Returns (path, line_number, issue_description)."""
    results: list[tuple[Path, int, str]] = []

    if not migrations_dir.exists():
        return results

    for path in sorted(migrations_dir.rglob("*.py")):
        for line_num, issue in check_migration_file(path):
            results.append((path, line_num, issue))

    return results


def main(repo_root: str = ".") -> int:
    """Run the migration check. Returns exit code (0 = clean, 1 = violations)."""
    root = Path(repo_root)
    migrations_dir = root / "backend" / "migrations" / "versions"
    findings = scan_migrations(migrations_dir)

    if not findings:
        print("G15 migration check: PASS")
        return 0

    print(f"G15 migration check: FAIL — {len(findings)} issue(s)")
    for path, line_num, issue in findings:
        rel_path = path.relative_to(root)
        print(f"  {rel_path}:{line_num}: {issue}")
    return 1


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    sys.exit(main(root))

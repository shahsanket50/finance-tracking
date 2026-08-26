"""G14: Real-data guard.

Scans tests/, docs/, and data files for PAN, Aadhaar, IFSC, 12-18 digit account
numbers, and bank domains. Fails if any match is found.

Real bank data must never enter the repository — use synthetic fixtures only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REAL_DATA_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("Aadhaar", re.compile(r"\b[2-9][0-9]{11}\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("AccountNumber", re.compile(r"\b[0-9]{12,18}\b")),
    ("BankDomain", re.compile(r"(hdfc|icici|sbi|axis|kotak)bank\.com", re.IGNORECASE)),
]

SCAN_EXTENSIONS = {".json", ".yaml", ".yml", ".csv", ".txt", ".md"}
SCAN_DIRS = ["tests", "docs"]

# Patterns that are false positives in test code (e.g. regex patterns themselves)
# These are exact strings that the scanner should skip
ALLOWLIST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\\b\[A-Z\]\{5\}"),  # regex pattern definitions
    re.compile(r"REAL_DATA_PATTERNS"),  # this file itself
    re.compile(r"00000000-0000-0000-0000-[0-9a-f]+"),  # synthetic sentinel UUIDs
]


def scan_file(path: Path) -> list[tuple[str, int, str]]:
    """Scan a single file. Returns list of (pattern_name, line_number, line_content)."""
    findings: list[tuple[str, int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings

    for line_num, line in enumerate(text.splitlines(), start=1):
        # Skip lines that contain allowlist patterns
        if any(allow.search(line) for allow in ALLOWLIST_PATTERNS):
            continue
        for pattern_name, pattern in REAL_DATA_PATTERNS:
            if pattern.search(line):
                findings.append((pattern_name, line_num, line.strip()[:120]))
    return findings


def scan_repo(repo_root: Path) -> list[tuple[Path, str, int, str]]:
    """Scan the repository. Returns findings as (path, pattern_name, line, content)."""
    results: list[tuple[Path, str, int, str]] = []

    for scan_dir in SCAN_DIRS:
        target = repo_root / scan_dir
        if not target.exists():
            continue
        for path in target.rglob("*"):
            if path.is_file() and path.suffix in SCAN_EXTENSIONS:
                for pattern_name, line_num, content in scan_file(path):
                    results.append((path, pattern_name, line_num, content))

    return results


def main(repo_root: str = ".") -> int:
    """Run the real-data guard. Returns exit code (0 = clean, 1 = violations found)."""
    root = Path(repo_root)
    findings = scan_repo(root)

    if not findings:
        print("G14 real-data guard: PASS — no real data patterns found")
        return 0

    print(f"G14 real-data guard: FAIL — {len(findings)} finding(s)")
    for path, pattern, line_num, content in findings:
        rel_path = path.relative_to(root)
        print(f"  {rel_path}:{line_num} [{pattern}] {content}")
    return 1


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    sys.exit(main(root))

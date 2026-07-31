"""G15 extension: Python float-ban for financial modules (C5).

Scans core/, processing/, domain/ for float literals and float() calls.
These modules must use Paise/BasisPoints/Units4dp newtypes only.
"""
from __future__ import annotations
import ast
import sys
from pathlib import Path

FINANCIAL_MODULES = ["core", "processing", "domain"]

# AST-based check: catch float() calls and float literal constants
# This is more reliable than regex for Python source.


def check_python_file(path: Path) -> list[tuple[int, str]]:
    """Check a Python file for float usage. Returns (line_number, issue)."""
    issues: list[tuple[int, str]] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return issues

    for node in ast.walk(tree):
        # float() calls: ast.Call with ast.Name func named 'float'
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "float"
        ):
            issues.append((node.lineno, f"float() call at line {node.lineno}"))

        # float literals: ast.Constant with float value
        # Exclude: 0.0 from imports like `__version__ = "0.1.0"` — those are strings.
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            issues.append((node.lineno, f"float literal {node.value!r} at line {node.lineno}"))

    return issues


def scan_financial_modules(backend_dir: Path) -> list[tuple[Path, int, str]]:
    """Scan financial modules for float usage."""
    results: list[tuple[Path, int, str]] = []

    for module_name in FINANCIAL_MODULES:
        module_dir = backend_dir / module_name
        if not module_dir.exists():
            continue
        for path in sorted(module_dir.rglob("*.py")):
            for line_num, issue in check_python_file(path):
                results.append((path, line_num, issue))

    return results


def main(repo_root: str = ".") -> int:
    """Run the float lint check. Returns exit code (0 = clean, 1 = violations)."""
    root = Path(repo_root)
    backend_dir = root / "backend"
    findings = scan_financial_modules(backend_dir)

    if not findings:
        print("G15 float lint: PASS — no float usage in financial modules")
        return 0

    print(f"G15 float lint: FAIL — {len(findings)} float usage(s) in financial modules")
    for path, line_num, issue in findings:
        rel_path = path.relative_to(root)
        print(f"  {rel_path}: {issue}")
    return 1


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    sys.exit(main(root))

"""CI drift check: fail if the committed openapi.json is out of date.

Regenerates the spec from the live app and diffs against docs/api/openapi.json.
Exits 0 if identical, 1 if different (with diff summary printed).

Usage:
    PYTHONPATH=backend python scripts/check-openapi-drift.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from main import app  # noqa: E402

committed_path = Path(__file__).parent.parent / "docs" / "api" / "openapi.json"

if not committed_path.exists():
    print("FAIL: docs/api/openapi.json does not exist. Run scripts/export-openapi.py first.")
    sys.exit(1)

committed = json.loads(committed_path.read_text())
live = app.openapi()

committed_str = json.dumps(committed, indent=2, sort_keys=True)
live_str = json.dumps(live, indent=2, sort_keys=True)

if committed_str == live_str:
    print("PASS: docs/api/openapi.json matches the live app spec.")
    sys.exit(0)

# Print which top-level keys differ
committed_paths = set(committed.get("paths", {}).keys())
live_paths = set(live.get("paths", {}).keys())
added = live_paths - committed_paths
removed = committed_paths - live_paths

committed_schemas = set(committed.get("components", {}).get("schemas", {}).keys())
live_schemas = set(live.get("components", {}).get("schemas", {}).keys())
schemas_added = live_schemas - committed_schemas
schemas_removed = committed_schemas - live_schemas

print("FAIL: docs/api/openapi.json is out of date. Run scripts/export-openapi.py and commit.")
if added:
    print(f"  Paths added in live app (not in committed): {sorted(added)}")
if removed:
    print(f"  Paths in committed but missing from live app: {sorted(removed)}")
if schemas_added:
    print(f"  Schemas added: {sorted(schemas_added)}")
if schemas_removed:
    print(f"  Schemas removed: {sorted(schemas_removed)}")
if not (added or removed or schemas_added or schemas_removed):
    print("  (route paths and schemas match, but body content differs — a field or annotation changed)")

sys.exit(1)

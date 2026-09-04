"""Export the FastAPI OpenAPI spec to docs/api/openapi.json.

Usage:
    PYTHONPATH=backend python scripts/export-openapi.py

The output file is committed to the repo and is the single source of truth
for the API contract. Frontend types and Bruno collections are generated from it.
Run this script whenever a backend route changes, before committing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from main import app  # noqa: E402

spec = app.openapi()

out = Path(__file__).parent.parent / "docs" / "api" / "openapi.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(spec, indent=2) + "\n")

print(f"OpenAPI spec written to {out.relative_to(Path(__file__).parent.parent)}")
print(f"  {len(spec.get('paths', {}))} paths, {len(spec.get('components', {}).get('schemas', {}))} schemas")

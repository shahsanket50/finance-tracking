"""Generate a Bruno collection from docs/api/openapi.json.

Writes plain-text .bru files to docs/api/bruno-collection/, organized by tag.
Bruno .bru format: https://docs.usebruno.com/bru-lang/overview

Usage:
    python scripts/generate-bruno-collection.py

Run this after export-openapi.py whenever routes change.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SPEC_PATH = REPO_ROOT / "docs" / "api" / "openapi.json"
OUT_ROOT = REPO_ROOT / "docs" / "api" / "bruno-collection"
BASE_URL = "{{base_url}}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def path_to_bruno_url(path: str) -> str:
    # Convert {param} → :param for Bruno
    return re.sub(r"\{(\w+)\}", r":\1", path)


def build_query_params(op: dict) -> list[tuple[str, str, bool]]:
    """Returns list of (name, default, disabled) tuples."""
    params = []
    for p in op.get("parameters", []):
        if p.get("in") == "query":
            params.append((p["name"], "", not p.get("required", False)))
    return params


def build_bru(method: str, path: str, op: dict, base_url: str) -> str:
    name = op.get("summary") or op.get("operationId") or f"{method} {path}"
    url = base_url + path_to_bruno_url(path)
    query_params = build_query_params(op)

    lines = [
        f"meta {{",
        f"  name: {name}",
        f"  type: http",
        f"  seq: 1",
        f"}}",
        f"",
        f"{method.lower()} {{",
        f"  url: {url}",
        f"  body: none",
        f"  auth: none",
        f"}}",
    ]

    if query_params:
        lines += ["", "params:query {"]
        for name_p, default, disabled in query_params:
            prefix = "~" if disabled else " "
            lines.append(f"  {prefix}{name_p}: {default}")
        lines.append("}")

    if op.get("description"):
        lines += ["", "docs {", f"  {op['description']}", "}"]

    return "\n".join(lines) + "\n"


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text())
    servers = spec.get("servers", [])
    base_url = servers[0]["url"] if servers else "http://localhost:8000"

    # Group operations by tag
    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if not isinstance(op, dict):
                continue
            tags = op.get("tags", ["untagged"])
            for tag in tags:
                by_tag.setdefault(tag, []).append((method, path, op))

    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Write bruno.json collection manifest
    (OUT_ROOT / "bruno.json").write_text(
        json.dumps({"version": "1", "name": "Finance Tracker API", "type": "collection"}, indent=2) + "\n"
    )

    # Write environments
    env_dir = OUT_ROOT / "environments"
    env_dir.mkdir(exist_ok=True)
    (env_dir / "local.bru").write_text(
        "vars {\n  base_url: http://localhost:8000\n}\n"
    )

    total = 0
    for tag, ops in sorted(by_tag.items()):
        tag_dir = OUT_ROOT / slug(tag)
        tag_dir.mkdir(exist_ok=True)
        for method, path, op in ops:
            name = op.get("summary") or f"{method} {path}"
            filename = slug(name) + ".bru"
            bru = build_bru(method, path, op, BASE_URL)
            (tag_dir / filename).write_text(bru)
            total += 1

    print(f"Bruno collection written to {OUT_ROOT.relative_to(REPO_ROOT)}")
    print(f"  {len(by_tag)} folders, {total} requests")
    print(f"  Base URL variable: {BASE_URL} (set in environments/local.bru)")


if __name__ == "__main__":
    main()

"""Root conftest — ensures /app is on sys.path so tests can import core.*."""

from __future__ import annotations

import sys
from pathlib import Path

# /app is the package root; add it if not already present
app_root = str(Path(__file__).parent)
if app_root not in sys.path:
    sys.path.insert(0, app_root)

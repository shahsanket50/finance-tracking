"""JSON serialization for money values (TRD §10.5).

JSON.parse produces IEEE-754 doubles — this corrupts paise values that exceed
2^53. Serialize money as strings, not numbers.
"""

from __future__ import annotations

from core.hashing.types import Paise


def money_to_json_str(paise: Paise) -> str:
    """Serialize a Paise value to a JSON-safe string."""
    return str(int(paise))


def json_str_to_paise(s: str) -> Paise:
    """Deserialize a JSON string back to Paise."""
    return Paise(int(s))

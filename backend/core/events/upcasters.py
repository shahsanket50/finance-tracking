"""C4: Event upcaster registry.

When event_version > 1 exists, register upcasters that transform older payloads
to the current version. At read time, the chain is applied automatically.

Usage:
    @register_upcaster("TransactionIngested", from_version=1)
    def upcast_v1_to_v2(payload: dict) -> dict:
        payload["new_field"] = payload.pop("old_field", None)
        return payload
"""

from __future__ import annotations

from collections.abc import Callable

# Maps (event_type, from_version) -> upcaster function.
# The upcaster receives a payload at `from_version` and returns it at from_version+1.
_UPCASTERS: dict[tuple[str, int], Callable[[dict[str, object]], dict[str, object]]] = {}

CURRENT_VERSION = 1  # bump this when a schema change requires an upcaster


def register_upcaster(
    event_type: str,
    from_version: int,
) -> Callable[
    [Callable[[dict[str, object]], dict[str, object]]],
    Callable[[dict[str, object]], dict[str, object]],
]:
    """Decorator to register an upcaster for (event_type, from_version)."""

    def decorator(
        fn: Callable[[dict[str, object]], dict[str, object]],
    ) -> Callable[[dict[str, object]], dict[str, object]]:
        _UPCASTERS[(event_type, from_version)] = fn
        return fn

    return decorator


def upcast(event_type: str, event_version: int, payload: dict[str, object]) -> dict[str, object]:
    """Apply the upcaster chain from event_version to CURRENT_VERSION.

    If no upcasters are registered (common at this stage), returns payload unchanged.
    Always returns a copy — never the original object.
    """
    current: dict[str, object] = payload.copy()
    version = event_version
    while version < CURRENT_VERSION:
        upcaster = _UPCASTERS.get((event_type, version))
        if upcaster is None:
            break
        current = upcaster(current)
        version += 1
    return current

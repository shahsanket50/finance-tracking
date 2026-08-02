"""Unit tests for the upcaster registry."""

from __future__ import annotations

from core.events.upcasters import _UPCASTERS, CURRENT_VERSION, register_upcaster, upcast


def test_register_upcaster_adds_to_registry() -> None:
    @register_upcaster("FakeEvent", from_version=99)
    def my_upcaster(payload: dict[str, object]) -> dict[str, object]:
        return {**payload, "upcasted": True}

    assert ("FakeEvent", 99) in _UPCASTERS
    _UPCASTERS.pop(("FakeEvent", 99))  # cleanup


def test_upcast_unknown_event_type_returns_copy() -> None:
    """Unknown event types with no upcasters return a copy of the payload."""
    payload: dict[str, object] = {"data": 42}
    result = upcast("UnknownEvent", CURRENT_VERSION, payload)
    assert result == payload
    assert result is not payload


def test_upcast_chain_stops_when_no_upcaster() -> None:
    """upcast chain stops at the first missing upcaster in a gap."""
    import core.events.upcasters as upcasters_mod

    original_version = upcasters_mod.CURRENT_VERSION
    try:
        # Set CURRENT_VERSION = 3 but only register v1->v2 (not v2->v3)
        upcasters_mod.CURRENT_VERSION = 3
        _UPCASTERS[("ChainTest", 1)] = lambda p: {**p, "step2": True}
        # No upcaster for version 2

        result = upcast("ChainTest", 1, {"original": True})
        # Should apply v1->v2 then stop (no v2->v3 upcaster)
        assert result == {"original": True, "step2": True}
    finally:
        upcasters_mod.CURRENT_VERSION = original_version
        _UPCASTERS.pop(("ChainTest", 1), None)


def test_upcast_current_version_returns_copy_not_original() -> None:
    """upcast at current version returns a copy, not the original dict."""
    payload: dict[str, object] = {"immutable_check": True}
    result = upcast("AnyEvent", CURRENT_VERSION, payload)
    assert result is not payload
    assert result == payload


def test_register_upcaster_is_decorator() -> None:
    """register_upcaster returns the original function unchanged."""

    def raw_fn(payload: dict[str, object]) -> dict[str, object]:
        return payload

    decorated = register_upcaster("DecoratorTest", from_version=999)(raw_fn)
    assert decorated is raw_fn
    _UPCASTERS.pop(("DecoratorTest", 999), None)  # cleanup

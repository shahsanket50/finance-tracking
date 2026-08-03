"""Unit tests for event store primitives."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.events.store import append_event, read_stream


def _make_key(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    """Build a mock UserEncryptionKey with real 256-bit key material."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        key_material=os.urandom(32),
        deactivated_at=None,
    )


# ── encryption round-trip ──────────────────────────────────────────────────────


def test_encrypt_decrypt_round_trip() -> None:
    """Payload dict survives encrypt -> decrypt unchanged."""
    from core.events.encryption import decrypt_payload, encrypt_payload

    session = MagicMock()
    user_id = uuid.uuid4()
    key = _make_key(user_id)

    with patch("core.events.encryption._get_active_key", return_value=key):
        session.get.return_value = key
        payload: dict[str, object] = {"amount": "100", "narration": "test"}
        ciphertext, key_id = encrypt_payload(session, user_id, payload)
        result = decrypt_payload(session, key_id, ciphertext)
        assert result == payload


def test_encrypt_decrypt_unknown_key_raises() -> None:
    """decrypt_payload raises ValueError when key_id is not found."""
    from core.events.encryption import decrypt_payload

    session = MagicMock()
    session.get.return_value = None
    with pytest.raises(ValueError, match="not found"):
        decrypt_payload(session, uuid.uuid4(), b"\x00" * 32)


def test_encrypt_no_active_key_raises() -> None:
    """encrypt_payload raises ValueError when user has no active key."""
    from core.events.encryption import encrypt_payload

    session = MagicMock()
    with patch("core.events.encryption._get_active_key", side_effect=ValueError("No active")):
        with pytest.raises(ValueError, match="No active"):
            encrypt_payload(session, uuid.uuid4(), {"k": "v"})


# ── upcaster chain ─────────────────────────────────────────────────────────────


def test_upcast_no_op_when_at_current_version() -> None:
    """upcast returns payload unchanged when event_version == CURRENT_VERSION."""
    from core.events.upcasters import CURRENT_VERSION, upcast

    payload: dict[str, object] = {"field": "value"}
    result = upcast("TransactionIngested", CURRENT_VERSION, payload)
    assert result == payload
    assert result is not payload  # must return a copy


def test_upcast_applies_registered_upcaster() -> None:
    """upcast applies the registered upcaster function."""
    import core.events.upcasters as upcasters_mod
    from core.events.upcasters import _UPCASTERS, upcast

    original_version = upcasters_mod.CURRENT_VERSION
    try:
        upcasters_mod.CURRENT_VERSION = 2
        _UPCASTERS[("TestEvent", 1)] = lambda p: {**p, "v2_field": True}
        result = upcast("TestEvent", 1, {"original": True})
        assert result == {"original": True, "v2_field": True}
    finally:
        upcasters_mod.CURRENT_VERSION = original_version
        _UPCASTERS.pop(("TestEvent", 1), None)


# ── append_event ──────────────────────────────────────────────────────────────


def test_append_event_returns_int() -> None:
    """append_event returns a plain int seq number."""
    session = MagicMock()
    user_id = uuid.uuid4()
    ingestion_id = uuid.uuid4()
    key = _make_key(user_id)

    # After flush+refresh, row.seq is set by the DB.
    # Simulate session.refresh setting seq on the ORM row object.
    def fake_refresh(obj: object) -> None:
        obj.__dict__["seq"] = 42

    session.refresh.side_effect = fake_refresh

    with patch("core.events.encryption._get_active_key", return_value=key):
        seq = append_event(
            session,
            user_id=user_id,
            event_type="TransactionIngested",
            aggregate_id="HDFC_SAVINGS_001",
            payload={"narration": "test"},
            idempotency_hash="abc123def456",
            value_date=date(2026, 3, 15),
            ingestion_event_id=ingestion_id,
        )

    assert isinstance(seq, int)
    assert seq == 42
    session.add.assert_called_once()
    session.flush.assert_called_once()
    session.refresh.assert_called_once()


# ── read_stream ordering ──────────────────────────────────────────────────────


def test_read_stream_returns_events_in_seq_order() -> None:
    """read_stream returns events ordered by seq ascending."""
    from core.events.encryption import encrypt_payload

    user_id = uuid.uuid4()
    key = _make_key(user_id)

    # Encrypt two payloads using a real session mock with key lookup
    enc_session = MagicMock()
    with patch("core.events.encryption._get_active_key", return_value=key):
        p1, _ = encrypt_payload(enc_session, user_id, {"seq_label": "10"})
        p2, _ = encrypt_payload(enc_session, user_id, {"seq_label": "20"})

    # Build mock TransactionEvent rows as SimpleNamespace to avoid ORM setup
    def make_row(seq_num: int, payload_bytes: bytes) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            seq=seq_num,
            event_version=1,
            event_type="TransactionIngested",
            account_ref="HDFC_SAVINGS_001",
            user_id=user_id,
            encryption_key_id=key.id,
            payload=payload_bytes,
            created_at=datetime.now(tz=UTC),
        )

    row1 = make_row(10, p1)
    row2 = make_row(20, p2)

    session = MagicMock()
    session.scalars.return_value.all.return_value = [row1, row2]
    session.get.return_value = key

    events = read_stream(session, user_id, "HDFC_SAVINGS_001")

    assert len(events) == 2
    assert events[0].seq == 10
    assert events[1].seq == 20
    assert events[0].seq < events[1].seq


def test_append_event_raises_without_value_date() -> None:
    """value_date is required — silent date.today() default was removed (F-7)."""
    with pytest.raises(TypeError, match="value_date"):
        append_event(  # type: ignore[call-arg]
            MagicMock(),
            user_id=uuid.uuid4(),
            event_type="TransactionIngested",
            aggregate_id="ACC",
            payload={},
            idempotency_hash="abc",
            ingestion_event_id=uuid.uuid4(),
            # value_date intentionally omitted
        )

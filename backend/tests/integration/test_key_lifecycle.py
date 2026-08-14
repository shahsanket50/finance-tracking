"""Integration test: encryption key lifecycle and crypto-shredding (TRD §H2).

Deactivating a key:
  - blocks new encryption (no active key)
  - preserves decryption of existing ciphertext (cold storage for audit)
  - allows a replacement key to be issued
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.encryption import create_user_key, decrypt_payload, encrypt_payload
from core.events.models import User, UserEncryptionKey


@pytest.mark.integration
def test_deactivated_key_blocks_new_encrypt(
    pg_session: Session,
    test_user: User,
) -> None:
    """After key deactivation, encrypt_payload raises ValueError — no active key."""
    key = pg_session.scalars(
        select(UserEncryptionKey).where(UserEncryptionKey.user_id == test_user.id)
    ).first()
    assert key is not None

    key.deactivated_at = datetime.now(UTC)
    pg_session.flush()

    with pytest.raises(ValueError, match="No active encryption key"):
        encrypt_payload(pg_session, test_user.id, {"test": "payload"})


@pytest.mark.integration
def test_deactivated_key_still_decrypts_existing_ciphertext(
    pg_session: Session,
    test_user: User,
) -> None:
    """Deactivated keys remain usable for decryption (cold storage — audit requirement)."""
    original_payload = {"narration": "Swiggy", "amount": "-50000"}

    ciphertext, key_id = encrypt_payload(pg_session, test_user.id, original_payload)

    key = pg_session.get(UserEncryptionKey, key_id)
    assert key is not None
    key.deactivated_at = datetime.now(UTC)
    pg_session.flush()

    recovered = decrypt_payload(pg_session, key_id, ciphertext)
    assert recovered == original_payload


@pytest.mark.integration
def test_new_key_issued_after_deactivation(
    pg_session: Session,
    test_user: User,
) -> None:
    """create_user_key issues a new active key after all existing keys are deactivated."""
    existing_key = pg_session.scalars(
        select(UserEncryptionKey).where(UserEncryptionKey.user_id == test_user.id)
    ).first()
    assert existing_key is not None
    existing_key.deactivated_at = datetime.now(UTC)
    pg_session.flush()

    new_key = create_user_key(pg_session, test_user.id)
    assert new_key.deactivated_at is None

    ciphertext, used_key_id = encrypt_payload(pg_session, test_user.id, {"test": "new key works"})
    assert used_key_id == new_key.id

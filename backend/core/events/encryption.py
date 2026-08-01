"""H2: Per-user payload encryption for crypto-shredding.

Each user has a key envelope in user_encryption_keys.
Deactivating all keys for a user cryptographically shreds their data.
Implements TRD §H2.
"""

from __future__ import annotations

import json
import os
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.events.models import UserEncryptionKey


def encrypt_payload(
    session: Session,
    user_id: uuid.UUID,
    data: dict[str, object],
) -> tuple[bytes, uuid.UUID]:
    """Encrypt a payload dict using the user's active key.

    Returns (ciphertext, key_id). The ciphertext includes the 12-byte nonce
    prepended to the AES-GCM output.
    """
    key_row = _get_active_key(session, user_id)
    aesgcm = AESGCM(key_row.key_material)
    nonce = os.urandom(12)
    plaintext = json.dumps(data, sort_keys=True).encode()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext, key_row.id


def decrypt_payload(
    session: Session,
    key_id: uuid.UUID,
    ciphertext: bytes,
) -> dict[str, object]:
    """Decrypt a payload using the key identified by key_id."""
    key_row = session.get(UserEncryptionKey, key_id)
    if key_row is None:
        raise ValueError(f"Encryption key {key_id} not found")
    aesgcm = AESGCM(key_row.key_material)
    nonce, data = ciphertext[:12], ciphertext[12:]
    plaintext = aesgcm.decrypt(nonce, data, None)
    loaded: dict[str, object] = json.loads(plaintext)
    return dict(loaded)


def create_user_key(session: Session, user_id: uuid.UUID) -> UserEncryptionKey:
    """Generate and store a new 256-bit key for user_id.

    Call this when creating a new user. Returns the persisted key row.
    """
    key_row = UserEncryptionKey(
        user_id=user_id,
        key_material=os.urandom(32),  # 256-bit AES key
    )
    session.add(key_row)
    session.flush()
    return key_row


def _get_active_key(session: Session, user_id: uuid.UUID) -> UserEncryptionKey:
    stmt = (
        select(UserEncryptionKey)
        .where(
            UserEncryptionKey.user_id == user_id,
            UserEncryptionKey.deactivated_at.is_(None),
        )
        .limit(1)
    )
    key_row = session.scalars(stmt).first()
    if key_row is None:
        raise ValueError(f"No active encryption key for user {user_id}")
    assert isinstance(key_row, UserEncryptionKey)
    return key_row

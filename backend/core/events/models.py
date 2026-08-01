"""SQLAlchemy ORM models for immutable event tables and identity tables.

Implements TRD §3.1 (immutable event log) and the identity subset of TRD §3.2.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    TIMESTAMP,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )


class InviteAllowlist(Base):
    __tablename__ = "invite_allowlist"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )


class UserEncryptionKey(Base):
    __tablename__ = "user_encryption_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    key_material: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, nullable=False)
    event_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date())
    period_end: Mapped[date | None] = mapped_column(Date())
    records_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_flagged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance_check: Mapped[str | None] = mapped_column(String(8))
    confidence: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    encryption_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_encryption_keys.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )


class RawArtifact(Base):
    __tablename__ = "raw_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, nullable=False)
    event_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    ingestion_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_events.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    retained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )


class TransactionEvent(Base):
    __tablename__ = "transaction_events"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "idempotency_hash", name="uq_transaction_events_user_idempotency_hash"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, nullable=False)
    event_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    ingestion_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_events.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    value_date: Mapped[date] = mapped_column(Date(), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurrence_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    narration: Mapped[str] = mapped_column(Text(), nullable=False)
    normalized_narration: Mapped[str | None] = mapped_column(Text())
    running_balance_paise: Mapped[int | None] = mapped_column(BigInteger)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    encryption_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_encryption_keys.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )


class DocumentEvent(Base):
    __tablename__ = "document_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, nullable=False)
    event_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    encryption_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_encryption_keys.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )

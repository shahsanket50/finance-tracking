"""Dry-run harness: parse PDF → validate balance → store DryRunSession. Implements TRD §9.1."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ingestion.dryrun.session import DryRunSession, save_session
from ingestion.fetchers.pdf_reader import open_pdf
from ingestion.parsers.base import AbstractParser
from ingestion.parsers.hdfc_cc import HdfcCcParser
from ingestion.parsers.sbi_cc import SbiCcParser
from ingestion.validators.balance_check import validate_balance

_DEFAULT_PARSERS: list[AbstractParser] = [HdfcCcParser(), SbiCcParser()]


def get_redis_client() -> Any:
    """Return a Redis client. Reads REDIS_URL env var. Patched in unit tests."""
    import redis  # imported here so redis absence doesn't break import at module load

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(url)


def dry_run(
    pdf_bytes: bytes,
    user_id: UUID,
    account_ref: str,
    password: str | None = None,
    parsers: list[AbstractParser] | None = None,
) -> DryRunSession:
    """Parse a PDF, validate balance, and store a DryRunSession in Redis.

    Returns the DryRunSession. Writes nothing to the database.
    Raises ValueError if no parser can handle the PDF.
    Raises PasswordRequiredError / PasswordIncorrectError from open_pdf on encryption issues.
    """
    _parsers = parsers if parsers is not None else _DEFAULT_PARSERS

    # 1. Open PDF from bytes
    with open_pdf(pdf_bytes, password) as pdf:
        # 2. Extract text for parser selection
        raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        # 3. Select parser
        parser = next((p for p in _parsers if p.can_parse(raw_text)), None)
        if parser is None:
            raise ValueError("No parser found for this PDF")

        # 4. Parse
        statement = parser.parse(pdf)

    # 5. Validate balance (Invariant 2)
    balance_check = validate_balance(
        statement.opening_balance_paise,
        statement.transactions,
        statement.closing_balance_paise,
    )

    # 6. Content hash (SHA-256 of raw bytes — used for raw_artifact in confirm)
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # 7. Build and store session
    session = DryRunSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        account_ref=account_ref,
        statement=statement,
        balance_check=balance_check,
        raw_artifact_content_hash=content_hash,
        created_at=datetime.now(UTC),
    )

    redis_client = get_redis_client()
    save_session(redis_client, session)

    return session

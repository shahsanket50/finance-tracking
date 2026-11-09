"""Seed the local docker-compose stack with real-path test data (Wave 5 verify step).

Everything goes through the production path: synthetic statements rendered in the bank's
real PDF layout (tests/factories/real_rows.py) → POST /api/v1/statements/upload (real parser,
dry run) → POST /{session}/confirm (event log + resolver) → POST /api/v1/accounts.
No event payload is hand-built.

The one thing done directly in the database is dev-only: creating the stub user (and its
encryption key) that every route acts as until Phase 5 auth. Without it every confirm
fails with a foreign-key error on a fresh database.

Rerun-safe: an account that already exists is skipped with its statements (re-confirming
an ingested statement is rejected by the idempotency constraint, Invariant 1).

Usage (stack up and migrated):  make seed
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.events.encryption import create_user_key  # noqa: E402
from core.events.models import User  # noqa: E402
from tests.factories.real_rows import Txn, render_statement_pdf  # noqa: E402

API = os.environ.get("SEED_API", "http://localhost:8000")
DATABASE_URL = os.environ.get(
    "SEED_DATABASE_URL", "postgresql+psycopg://finance:finance@localhost:5433/finance"
)
STUB_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@dataclass(frozen=True)
class Statement:
    bank: str
    period: tuple[date, date]
    opening_paise: int
    txns: tuple[Txn, ...]


@dataclass(frozen=True)
class SeedAccount:
    account_ref: str
    account_type: str
    nickname: str
    statements: tuple[Statement, ...]


ACCOUNTS = (
    SeedAccount(
        "HDFC_SAV_2001",
        "savings",
        "HDFC Savings (seed)",
        (
            Statement(
                "hdfc_savings",
                (date(2026, 1, 1), date(2026, 1, 31)),
                2_000_000,
                (
                    Txn("NEFTCR SALARY ACME", 5_000_000, date(2026, 1, 1)),
                    Txn("UPI DMART GROCERY", -320_000, date(2026, 1, 12)),
                    Txn("CC PAYMENT SBI CARD", -1_500_000, date(2026, 1, 28)),
                ),
            ),
            Statement(
                "hdfc_savings",
                (date(2026, 2, 1), date(2026, 2, 28)),
                5_180_000,
                (Txn("UPI ZOMATO ORDER", -85_000, date(2026, 2, 3)),),
            ),
        ),
    ),
    SeedAccount(
        "SBI_CC_3001",
        "credit_card",
        "SBI Card (seed)",
        (
            Statement(
                "sbi_cc",
                (date(2026, 1, 1), date(2026, 1, 31)),
                -1_500_000,
                (
                    Txn("AMAZON PURCHASE", -249_900, date(2026, 1, 6)),
                    Txn("UBER RIDE", -55_000, date(2026, 1, 9)),
                    Txn("PAYMENT RECEIVED THANK YOU", 1_500_000, date(2026, 1, 29)),
                ),
            ),
        ),
    ),
)


def ensure_stub_user() -> None:
    with Session(create_engine(DATABASE_URL)) as session:
        if session.get(User, STUB_USER_ID) is not None:
            print("stub user: exists")
            return
        session.add(User(id=STUB_USER_ID, email="stub-user@localhost.invalid"))
        session.flush()
        create_user_key(session, STUB_USER_ID)
        session.commit()
        print("stub user: created (with encryption key)")


def ingest(client: httpx.Client, account: SeedAccount, statement: Statement) -> None:
    pdf = render_statement_pdf(
        statement.bank,
        account.account_ref,
        statement.period[0],
        statement.period[1],
        list(statement.txns),
        statement.opening_paise,
    )
    preview = client.post(
        "/api/v1/statements/upload",
        params={"account_ref": account.account_ref},
        files={"file": (f"{account.account_ref}.pdf", pdf, "application/pdf")},
    )
    preview.raise_for_status()
    body = preview.json()
    print(
        f"  upload {account.account_ref} {statement.period[0]}..{statement.period[1]}: "
        f"balance_check={body['balance_check']} closing={body['closing_balance_paise']}"
    )
    confirmed = client.post(f"/api/v1/statements/{body['session_id']}/confirm")
    confirmed.raise_for_status()
    print(f"  confirm: {confirmed.json()['status']}")


def main() -> int:
    ensure_stub_user()
    with httpx.Client(base_url=API, timeout=60) as client:
        existing = {a["account_ref"] for a in client.get("/api/v1/accounts").json()}
        for account in ACCOUNTS:
            if account.account_ref in existing:
                print(f"{account.account_ref}: already seeded, skipped")
                continue
            print(f"{account.account_ref} ({account.account_type}):")
            for statement in account.statements:
                ingest(client, account, statement)
            created = client.post(
                "/api/v1/accounts",
                json={
                    "nickname": account.nickname,
                    "account_type": account.account_type,
                    "account_ref": account.account_ref,
                },
            )
            created.raise_for_status()
            print(f"  account created: {created.json()['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

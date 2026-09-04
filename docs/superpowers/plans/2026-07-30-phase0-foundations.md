# Phase 0 — Foundations: Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get from empty repo → append an event → build a projection from it → replay produces identical output → CI runs all quality gates G1–G15 and publishes a report on every push.

**Architecture:** Event-sourcing with a strict immutable/mutable split. All ledger writes are append-only events; projections are derived and disposable. Decisions (anything involving an LLM or time-dependent lookup) are recorded as events; derivations (arithmetic over recorded facts) are recomputed freely.

**Tech Stack:** Python 3.12 + FastAPI, Next.js/TypeScript strict, **Postgres 18** (native `uuidv7()`), Alembic migrations, Celery + Redis, pytest + Hypothesis, GitHub Actions CI, `uuid6` Python package for application-layer UUIDv7 generation.

---

## Context

Phase 0 exists to establish the skeleton that every future feature depends on. It is not about shipping user-visible functionality — it is about making correctness mechanically enforceable before any business logic is added.

The core TRD principle is: **correctness > architecture > cost > speed**. This has two concrete consequences for Phase 0 ordering:
1. The data model (schema, hash, event primitives) must be right before any code that depends on it is written. Retrofitting the idempotency hash or `event_version` after parsers exist is a full rewrite.
2. Quality gates must be live before feature code lands. Retrofitting a CI harness onto an AI-generated codebase is materially harder than building it first.

---

## Key invariants (assert in every code review)

| # | Invariant | Where enforced |
|---|---|---|
| I1 | No transaction hash counted more than once | `core/hashing/` + property test |
| I2 | Balance check passes or parse is rejected — never partial ingest | `ingestion/validators/` + property test |
| I3 | Replaying the same event stream twice produces byte-identical projections | `core/projections/` + property test |
| I4 | A matched transfer pair never appears in expense totals | `processing/resolver/` + property test |
| I5 | A closed FY's projection never changes silently | `core/ruleset/` + property test |
| I6 | Nothing below confidence threshold enters ledger without confirm event | `ingestion/dryrun/` + property test |

---

## Immutable vs mutable — what lives where

**Immutable (append-only — never UPDATE, never DELETE):**
`ingestion_events`, `raw_artifacts`, `transaction_events`, `document_events`

**Mutable (normal CRUD):**
`users`, `accounts`, `budgets`, `category_overrides`, `settings`, `statement_credentials`, `merchant_section_map`, `notification_preferences`, `invite_allowlist`

**Projections (derived, rebuildable from event log):**
`transactions_current`, `budget_status`, `ca_view_fy`, `net_worth_snapshots`, `audit_view`, `dedup_ledger`

---

## Decisions vs derivations — the enforcement rule

> **Decision:** involves an LLM, or a lookup whose result depends on what data existed at the time → **record as an event**.
> **Derivation:** purely arithmetic over already-recorded facts → **recompute freely**.

Decisions: resolver pairings, LLM category, deduction-section detection, confidence scores, merchant normalization.
Derivations: budget totals, net worth, FY aggregates, allocation %.

Violating this makes replay non-deterministic (breaks I3).

---

## TRD §9 critical fixes — absorbed into Phase 0 tasks

These are binding (TRD §9.1–§9.2) and must land in Phase 0:

| Fix | Where it lands |
|---|---|
| C1: Hash = `hash(account_ref + value_date + amount + normalized_narration + occurrence_index)` | Task 0.3 (schema field) + Task 0.7 (implementation) |
| C2: `occurrence_index` — ordinal within (account, date, amount, narration) group | Task 0.3 (schema field) + Task 0.7 (implementation) |
| C3: Resolver outcomes are recorded events, never recomputed on replay | Task 0.3 (event shape in schema) |
| C4: `event_version` on every event + upcaster layer | Task 0.3 (schema field) + Task 0.5 (upcaster scaffold) |
| C5: Money as `BIGINT` paise end-to-end + lint rule banning float | Task 0.3 (schema types) + Task 0.7 (newtypes + lint) |
| H2: Per-user encryption envelope for crypto-shredding | Task 0.3 (schema) + Task 0.5 (key management) |
| H4: UTC storage, IST FY/period logic, boundary property test | Task 0.6 (projections) |
| H5: Celery + Redis in Docker (cannot retrofit async into sync codebase) | Task 0.2 (Docker) |
| H7: Global monotonic `BIGSERIAL` on event log | Task 0.3 (schema) |
| M9: PITR config + tested restore | Task 0.2 (Docker config) + Task 0.5 (restore test) |
| M10: Index strategy defined at schema time | Task 0.3 (schema) |

---

## Execution order

Dependencies dictate eight waves. Tasks within a wave have no dependency on each other and can run in parallel.

```
Wave 1 ─── 0.2 (Docker + Celery/Redis + PITR)
       └── 0.8 (CI skeleton: G1 format, G2 lint, G3 type-check)

Wave 2 ─── 0.3 (Immutable schema — absorbs H7, M10, C2, C3, C4, H2, C5 column types)
       └── 0.4 (Mutable schema — all settings + 3 new tables from TRD §8.3)

Wave 3 ─── 0.5 (Event-log primitives — absorbs C4 upcasters, H2 key management, M9 restore test)
       └── 0.7 (Idempotency hash — absorbs C1, C2 computation, C5 newtypes + lint + rounding, JSON strings)

Wave 4 ─── 0.6 (Projection builder + replay — absorbs H4, H1 snapshots, M2 shadow table)
       ├── 0.9 (Synthetic fixture generator)
       └── 0.11 (Custom gates G14 + G15)

Wave 5 ─── 0.14 (Integration test harness — ephemeral Postgres, full event→projection→replay path)

Wave 6 ─── 0.10 (CI gates G1–G8 fully wired)

Wave 7 ─── 0.12 (Coverage tiering + ratchet)

Wave 8 ─── 0.13 (PR quality-report comment bot)
       └── 0.15 (Trend dashboard)
```

---

## Task details

### Wave 1A — Task 0.2: Docker local dev environment
**Files to create:**
- `docker-compose.yml` — **Postgres 18** (native `uuidv7()`), FastAPI (hot-reload), Next.js (dev), Redis, Celery worker
- `docker-compose.override.yml` — local dev mounts
- `backend/pyproject.toml` — deps: fastapi, sqlalchemy 2, alembic, celery, redis, cryptography, hypothesis, pytest, pytest-cov, mypy, ruff, **uuid6** (UUIDv7 generation in Python; `uuid6.uuid7()` used wherever application code needs to generate a UUID)
- `web/package.json` — deps: next, react, typescript, eslint, prettier, vitest
- `Makefile` — targets: `up`, `down`, `migrate`, `test`, `lint`

**TRD requirements absorbed:**
- H5: Celery worker + Redis in compose
- M9: Postgres started with `wal_level=replica` for PITR readiness; document the restore test procedure in `docs/DECISIONS.md` as ADR-011

**Key decisions:**
- All four services communicate over a Docker bridge network named `finance`
- Postgres data volume is named (`finance_pgdata`) so `docker compose down` does not destroy data
- Celery beat is a separate container so it can be disabled in test environments

---

### Wave 1B — Task 0.8: CI skeleton
**Files to create:**
- `.github/workflows/ci.yml` — runs on every push; jobs: format, lint, typecheck
- `.github/workflows/quality-report.yml` — placeholder for the full report (filled in 0.13)
- `backend/.ruff.toml` — ruff config (C901 complexity, plus the float-ban rule added in 0.7)
- `web/.eslintrc.json` — eslint + prettier config
- `web/tsconfig.json` — strict mode

**Gate wiring:**
- G1 (format): `ruff format --check` + `prettier --check`
- G2 (lint): `ruff check` + `eslint`
- G3 (type check): `mypy --strict backend/` + `tsc --noEmit`

At this wave, G4–G15 are present as commented-out stubs (no code to run them against yet). They expand in later tasks.

---

### Wave 2A — Task 0.3: Postgres immutable schema

**Migration ordering (decision 1B):** Task 0.3 owns **two** migration files, run in order:
- `000_identity.py` — creates `users`, `invite_allowlist`, `user_encryption_keys` first (prerequisites for immutable FK)
- `001_immutable.py` — creates all four append-only event tables

Task 0.4 then adds `002_mutable.py` for remaining operational tables.

**Files to create:**
- `backend/migrations/versions/000_identity.py` — Alembic migration (users + identity tables)
- `backend/migrations/versions/001_immutable.py` — Alembic migration (event tables)
- `backend/core/events/models.py` — SQLAlchemy models for all immutable tables
- `backend/core/events/types.py` — `transaction_type` enum (`income | expense | transfer | investment`)

**UUID convention (decision 2A + UUIDv7):** All `id` columns are `UUID PRIMARY KEY DEFAULT uuidv7()`. Postgres 18 provides `uuidv7()` natively. In Python (SQLAlchemy), set `server_default=text("uuidv7()")` — do **not** use `gen_random_uuid()` anywhere. `uuid6` package provides `uuid6.uuid7()` for application-layer generation when needed.

**Migration 000 — identity tables (mutable, created first):**

```sql
-- 000_identity: prerequisite for immutable FK references

CREATE TABLE users (
    id         UUID PRIMARY KEY DEFAULT uuidv7(),
    email      VARCHAR(320) NOT NULL UNIQUE,
    google_sub VARCHAR(255) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE invite_allowlist (
    email      VARCHAR(320) PRIMARY KEY,
    invited_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_encryption_keys (
    id             UUID PRIMARY KEY DEFAULT uuidv7(),
    user_id        UUID NOT NULL REFERENCES users(id),
    key_material   BYTEA NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at TIMESTAMPTZ
);
```

**Migration 001 — immutable event tables:**

`ingestion_events`:
```sql
id            UUID PRIMARY KEY DEFAULT uuidv7(),
seq           BIGSERIAL UNIQUE NOT NULL,            -- H7: global monotonic ordering
event_version SMALLINT NOT NULL DEFAULT 1,          -- C4
user_id       UUID NOT NULL REFERENCES users(id),
source        VARCHAR(32) NOT NULL,                 -- 'gmail' | 'aa' | 'slack' | 'manual'
source_detail JSONB,
period_start  DATE,
period_end    DATE,
records_added   INTEGER NOT NULL DEFAULT 0,
records_skipped INTEGER NOT NULL DEFAULT 0,
records_flagged INTEGER NOT NULL DEFAULT 0,
balance_check VARCHAR(8),                           -- 'pass' | 'fail' | null
confidence    INTEGER,                              -- basis points, 0–10000
status        VARCHAR(16) NOT NULL,                 -- 'success' | 'partial' | 'failed' | 'rejected'
payload       BYTEA NOT NULL,                       -- H2: encrypted JSONB
encryption_key_id UUID NOT NULL REFERENCES user_encryption_keys(id),
created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

`raw_artifacts`:
```sql
id                 UUID PRIMARY KEY DEFAULT uuidv7(),
seq                BIGSERIAL UNIQUE NOT NULL,       -- H7
event_version      SMALLINT NOT NULL DEFAULT 1,
ingestion_event_id UUID NOT NULL REFERENCES ingestion_events(id),
user_id            UUID NOT NULL REFERENCES users(id),
content_hash       VARCHAR(64) NOT NULL UNIQUE,     -- SHA-256 of raw bytes
retained           BOOLEAN NOT NULL DEFAULT FALSE,  -- M1: only retain failed parses
created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

`transaction_events`:
```sql
id                 UUID PRIMARY KEY DEFAULT uuidv7(),
seq                BIGSERIAL UNIQUE NOT NULL,        -- H7: ordering
event_version      SMALLINT NOT NULL DEFAULT 1,      -- C4
ingestion_event_id UUID NOT NULL REFERENCES ingestion_events(id),
user_id            UUID NOT NULL REFERENCES users(id),
event_type         VARCHAR(64) NOT NULL,
-- event_type values: TransactionIngested, CategoryAssigned, CategoryCorrected,
--   MarkedInternalTransfer, MarkedDuplicate, NatureTagged, TransactionAmended,
--   DeductionTagged, DeductionUntagged, MerchantSectionMappingLearned
account_ref        VARCHAR(128) NOT NULL,
value_date         DATE NOT NULL,                    -- H4: calendar date from statement (IST)
amount_paise       BIGINT NOT NULL,                  -- C5: signed, debits negative
idempotency_hash   CHAR(64) NOT NULL,                -- C1: SHA-256
occurrence_index   SMALLINT NOT NULL DEFAULT 0,      -- C2
transaction_type   VARCHAR(16) NOT NULL,              -- T16: income|expense|transfer|investment
narration          TEXT NOT NULL,
normalized_narration TEXT,
running_balance_paise BIGINT,                        -- validation-only, NOT part of hash (C1)
actor              VARCHAR(16) NOT NULL,              -- 'system' | 'user' | 'ai'
confidence         INTEGER,                           -- basis points
payload            BYTEA NOT NULL,                   -- H2: encrypted JSONB with full detail
encryption_key_id  UUID NOT NULL REFERENCES user_encryption_keys(id),
created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

`document_events`:
```sql
id            UUID PRIMARY KEY DEFAULT uuidv7(),
seq           BIGSERIAL UNIQUE NOT NULL,             -- H7
event_version SMALLINT NOT NULL DEFAULT 1,
user_id       UUID NOT NULL REFERENCES users(id),
document_type VARCHAR(32) NOT NULL,  -- 'form16' | 'cas' | 'ais' | 'epf' | 'loan_deed'
event_type    VARCHAR(64) NOT NULL,
payload       BYTEA NOT NULL,        -- H2: encrypted
encryption_key_id UUID NOT NULL REFERENCES user_encryption_keys(id),
created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**Indexes (M10):** on `transaction_events`:
- `(user_id, value_date)` — account + date range queries
- `(idempotency_hash)` — dedup lookups
- `(user_id, value_date, transaction_type)` — FY filters
- `(seq)` — event-sequence scan (already covered by BIGSERIAL but explicit)

**Append-only enforcement:** DB-level trigger on each immutable table that raises on UPDATE or DELETE.

**No float columns anywhere.** Migration check (G15, 0.11) will assert this.

---

### Wave 2B — Task 0.4: Postgres mutable schema
**Files to create:**
- `backend/migrations/versions/002_mutable.py` — Alembic migration (depends on 000)
- `backend/core/models/mutable.py` — SQLAlchemy models

All `id` columns use `UUID PRIMARY KEY DEFAULT uuidv7()`. FK references to `users(id)` already exist from migration 000.

**Tables:**

`accounts`:
```sql
id             UUID PRIMARY KEY DEFAULT uuidv7(),
user_id        UUID NOT NULL REFERENCES users(id),
nickname       VARCHAR(128),
account_type   VARCHAR(32),  -- 'savings' | 'current' | 'credit_card' | 'fd' | 'broker'
last4          VARCHAR(4),
sync_status    VARCHAR(16) NOT NULL DEFAULT 'pending',
last_synced_at TIMESTAMPTZ,
created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

`budgets`:
```sql
id           UUID PRIMARY KEY DEFAULT uuidv7(),
user_id      UUID NOT NULL REFERENCES users(id),
category     VARCHAR(64) NOT NULL,
month        DATE NOT NULL,
target_paise BIGINT NOT NULL,
created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
UNIQUE (user_id, category, month)
```

`category_overrides`:
```sql
id                  UUID PRIMARY KEY DEFAULT uuidv7(),
user_id             UUID NOT NULL REFERENCES users(id),
normalized_merchant VARCHAR(256) NOT NULL,
category            VARCHAR(64) NOT NULL,
created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
UNIQUE (user_id, normalized_merchant)
```

`merchant_section_map`:
```sql
id                  UUID PRIMARY KEY DEFAULT uuidv7(),
user_id             UUID NOT NULL REFERENCES users(id),
normalized_merchant VARCHAR(256) NOT NULL,
tax_section         VARCHAR(16) NOT NULL,
created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
UNIQUE (user_id, normalized_merchant)
```

`settings`:
```sql
user_id     UUID PRIMARY KEY REFERENCES users(id),
preferences JSONB NOT NULL DEFAULT '{}',
updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

`statement_credentials`:
```sql
id              UUID PRIMARY KEY DEFAULT uuidv7(),
user_id         UUID NOT NULL REFERENCES users(id),
account_id      UUID REFERENCES accounts(id),
credential_type VARCHAR(32) NOT NULL,
encrypted_value BYTEA NOT NULL,
created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

`notification_preferences`:
```sql
user_id        UUID PRIMARY KEY REFERENCES users(id),
channels       JSONB NOT NULL DEFAULT '{"slack": false, "email": true}',
tier2_toggles  JSONB NOT NULL DEFAULT '{}',
updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

---

### Wave 3A — Task 0.5: Event-log primitives
**Files to create:**
- `backend/core/events/__init__.py`
- `backend/core/events/store.py` — `append_event()`, `read_stream()`, `read_since_seq()`
- `backend/core/events/upcasters.py` — C4: upcaster registry, `upcast(event_version, payload) -> latest_payload`
- `backend/core/events/encryption.py` — H2: `encrypt_payload(user_id, data) -> (bytes, key_id)`, `decrypt_payload(key_id, bytes) -> data`
- `tests/unit/core/test_event_store.py`
- `tests/unit/core/test_upcasters.py`

**`append_event()` contract:**
```python
def append_event(
    session: Session,
    user_id: UUID,
    event_type: str,
    aggregate_id: str,
    payload: dict,
    event_version: int = 1,
) -> int:  # returns global seq number
```
- Encrypts payload before writing (H2)
- Never raises on duplicate seq (uses `INSERT ... RETURNING seq`)
- DB trigger enforces no UPDATE/DELETE (verified by a test that asserts `sqlalchemy.exc.ProgrammingError` on attempted update)

**`read_stream()` contract:**
```python
def read_stream(
    session: Session,
    user_id: UUID,
    aggregate_id: str,
    since_seq: int = 0,
) -> list[Event]:
```
- Returns events in strict `seq` order (H7)
- Decrypts payload before returning (H2)
- Upcasts to latest version (C4)

**Upcaster scaffold (C4):**
```python
UPCASTERS: dict[tuple[str, int], Callable] = {}
# Register: @upcast("TransactionIngested", from_version=1)
# At read time: apply all upcasters for (event_type, version) chain
```

**PITR restore test (M9):**
- `tests/integration/test_pitr.py` — documents the restore procedure as a test that fails loudly if `wal_level` is not `replica` on the running Postgres. This is the "tested restore" — a real point-in-time restore test is documented in `docs/DECISIONS.md` ADR-011 and must be run manually before beta.

---

### Wave 3B — Task 0.7: Idempotency hash + type system
**Files to create:**
- `backend/core/hashing/__init__.py`
- `backend/core/hashing/hash.py` — `compute_idempotency_hash()`, `compute_occurrence_index()`
- `backend/core/hashing/types.py` — C5 newtypes: `Paise`, `Units4dp`, `BasisPoints`, `FxRate`
- `backend/core/hashing/rounding.py` — largest-remainder splitter, `round_to_nearest_10()` for 288A/288B
- `backend/core/hashing/serialization.py` — `money_to_json_str()`, `json_str_to_paise()`
- `backend/.ruff.toml` — updated with `bandit`-style rule banning `float` in `backend/core/`, `backend/processing/`, `backend/domain/`
- `tests/unit/core/test_hash.py`
- `tests/unit/core/test_types.py`
- `tests/unit/core/test_rounding.py`
- `tests/property/core/test_hash_invariants.py`

**Hash definition (C1 + C2):**
```python
def compute_idempotency_hash(
    account_ref: str,
    value_date: date,
    amount_paise: int,  # Paise, signed
    normalized_narration: str,
    occurrence_index: int,  # C2
) -> str:  # hex SHA-256
    raw = f"{account_ref}|{value_date.isoformat()}|{amount_paise}|{normalized_narration}|{occurrence_index}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

**Occurrence index (C2):**
```python
def compute_occurrence_index(
    transactions: list[dict],  # sorted as they appear in the source statement
    account_ref: str,
    value_date: date,
    amount_paise: int,
    normalized_narration: str,
) -> int:
    # Returns the 0-based ordinal of this transaction within its group
```

**Newtypes (C5):**
```python
class Paise(int):
    """Signed integer — debits negative, credits positive. 1 paise = ₹0.01."""

class Units4dp(int):
    """MF units or NAV scaled to 10⁻⁴."""

class BasisPoints(int):
    """Rate or percentage scaled to 10⁻⁴ (100bp = 1%)."""
```

**JSON serialization (TRD §10.5):**
```python
def money_to_json_str(paise: Paise) -> str:
    return str(int(paise))

def json_str_to_paise(s: str) -> Paise:
    return Paise(int(s))
```

**Property tests:**
- Round-trip through JSON preserves exact value
- Largest-remainder splits always sum to the original
- No aggregate substitutes 0 for NULL (Hypothesis)
- Same (account_ref, date, amount, narration, occurrence_index) always produces the same hash
- Two transactions differing only in occurrence_index produce different hashes

---

### Wave 4A — Task 0.6: Projection builder + replay mechanism
**Files to create:**
- `backend/core/projections/__init__.py`
- `backend/core/projections/builder.py` — `build_projection()`, `replay_from_seq()`
- `backend/core/projections/snapshot.py` — H1: snapshot every 1000 events, `load_snapshot()`, `save_snapshot()`
- `backend/core/projections/rebuild.py` — M2: shadow table + atomic swap
- `backend/core/projections/timezone.py` — H4: `utc_to_ist()`, `ist_fy_year()`, `ist_statement_period()`
- `tests/unit/core/test_projections.py`
- `tests/property/core/test_replay_determinism.py`

**`build_projection()` contract:**
```python
def build_projection(
    session: Session,
    user_id: UUID,
    projection_type: str,
    since_seq: int = 0,
) -> dict:
    # Reads events via read_stream(), applies reducers, returns projected state
```

**Replay determinism (I3):**
```python
def test_replay_is_deterministic(events: list[Event]):
    # Hypothesis-generated event stream
    result_a = build_projection_from_events(events)
    result_b = build_projection_from_events(events)
    assert result_a == result_b  # byte-identical after JSON normalization
```

**UTC storage + IST FY logic (H4):**
```python
IST = ZoneInfo("Asia/Kolkata")

def ist_fy_year(utc_dt: datetime) -> int:
    """Returns the financial year start year for a UTC datetime."""
    ist_dt = utc_dt.astimezone(IST)
    return ist_dt.year if ist_dt.month >= 4 else ist_dt.year - 1
```

**Boundary property test (H4):**
```python
def test_fy_boundary_around_31_march():
    # 2026-03-31T23:30:00Z = 2026-04-01T05:00:00 IST = FY 2026-27
    dt = datetime(2026, 3, 31, 23, 30, tzinfo=timezone.utc)
    assert ist_fy_year(dt) == 2026  # it's still FY 2025-26 in IST? No.
    # 2026-04-01T05:00 IST is FY 2026-27. Assert correct.
    assert ist_fy_year(dt) == 2026  # FY 2026-27 starts April 1 2026, so year label = 2026
```

**Snapshot (H1):**
- Every 1000th event triggers `save_snapshot()`
- `load_snapshot()` returns the latest snapshot + `last_seq` so replay only processes newer events
- Snapshots stored in `projection_snapshots` table (mutable — disposable derived data)

**Shadow table rebuild (M2):**
```python
def rebuild_projection(session: Session, user_id: UUID, projection_type: str):
    shadow_table = f"{projection_type}_shadow_{uuid4().hex[:8]}"
    # 1. Create shadow table with same schema
    # 2. Replay all events into shadow table
    # 3. Atomic RENAME: shadow → live table
    # No downtime, no inconsistent reads
```

---

### Wave 4B — Task 0.9: Synthetic fixture generator
**Files to create:**
- `tests/fixtures/generator.py` — `generate_statement(bank, num_transactions, seed)`
- `tests/fixtures/templates/hdfc_savings.py` — HDFC Savings template
- `tests/fixtures/templates/sbi_savings.py` — SBI Savings template
- `tests/fixtures/golden/` — directory for golden statement fixtures (committed)

**Generator contract:**
```python
def generate_statement(
    bank: str,
    account_ref: str,
    period_start: date,
    period_end: date,
    transactions: list[dict],  # [{narration, amount_paise, value_date, type}]
    seed: int = 42,
) -> dict:
    """
    Returns a synthetic statement dict matching the bank's PDF structure.
    Computes occurrence_index and idempotency_hash per transaction.
    Computes opening/closing balance so the balance check passes.
    """
```

**Key rule:** generator must produce statements where `opening + credits - debits == closing` exactly — these are the fixtures that will exercise invariant I2.

---

### Wave 4C — Task 0.11: Custom gates G14 + G15
**Files to create:**
- `ci/guards/real_data_guard.py` — G14: scan for PAN, Aadhaar, IFSC, 12+ digit account numbers, bank domains
- `ci/guards/migration_check.py` — G15: scan Alembic migration files for UPDATE/DELETE on immutable tables; scan schema for NUMERIC/REAL/FLOAT columns
- `ci/guards/float_lint.py` — extension of C5: verify ruff config catches float literals in financial modules
- `.github/workflows/ci.yml` — updated to run G14 + G15 on every push (blocking)

**G14 patterns:**
```python
REAL_DATA_PATTERNS = [
    r'\b[A-Z]{5}[0-9]{4}[A-Z]\b',              # PAN
    r'\b[2-9][0-9]{11}\b',                       # Aadhaar
    r'\b[A-Z]{4}0[A-Z0-9]{6}\b',                # IFSC
    r'\b[0-9]{12,18}\b',                          # account numbers
    r'(hdfc|icici|sbi|axis|kotak)bank\.com',     # bank domains in fixture headers
]
# Scans: tests/, docs/, *.json, *.yaml, *.csv
```

**G15 rules:**
```python
IMMUTABLE_TABLES = ['ingestion_events', 'raw_artifacts', 'transaction_events', 'document_events']
FORBIDDEN_COLUMN_TYPES = ['NUMERIC', 'REAL', 'DOUBLE PRECISION', 'FLOAT']
# Fail if any migration file contains: UPDATE {immutable_table} or DELETE FROM {immutable_table}
# Fail if any migration file contains: NUMERIC, REAL, DOUBLE PRECISION, FLOAT as column type
```

---

### Wave 5 — Task 0.14: Integration test harness
**Files to create:**
- `tests/integration/conftest.py` — `pg_session` fixture using `testcontainers-python` or `pytest-postgresql`
- `tests/integration/test_event_append_and_replay.py`
- `tests/integration/test_replay_determinism.py`
- `tests/integration/test_projection_rebuild.py`

**Key integration tests:**

```python
def test_event_append_and_projection_round_trip(pg_session):
    # Append a TransactionIngested event
    seq = append_event(pg_session, user_id=TEST_USER, event_type="TransactionIngested", ...)
    # Build projection
    projection = build_projection(pg_session, user_id=TEST_USER, projection_type="transactions_current")
    # Assert the transaction appears in the projection
    assert len(projection["transactions"]) == 1

def test_replay_produces_identical_output(pg_session):
    # Append 10 events
    for i in range(10):
        append_event(pg_session, ...)
    projection_a = build_projection(pg_session, ...)
    # Wipe projection table, replay
    wipe_projection(pg_session, ...)
    projection_b = build_projection(pg_session, ...)
    assert projection_a == projection_b  # I3

def test_append_only_enforcement(pg_session):
    seq = append_event(pg_session, ...)
    with pytest.raises(Exception):
        pg_session.execute(text("UPDATE transaction_events SET narration = 'tampered' WHERE seq = :seq"), {"seq": seq})
```

**`testcontainers` setup:**
```python
@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:18") as pg:
        run_migrations(pg.get_connection_url())
        yield pg

@pytest.fixture
def pg_session(pg_container):
    engine = create_engine(pg_container.get_connection_url())
    with Session(engine) as session:
        yield session
        session.rollback()
```

---

### Wave 6 — Task 0.10: CI gates G1–G8 fully wired
**Files to modify:**
- `.github/workflows/ci.yml` — add G4–G8 jobs

**Gate wiring:**
- G4 (unit tests): `pytest tests/unit/ -v`
- G5 (property tests): `pytest tests/property/ -v --hypothesis-seed=0`
- G6 (golden dataset): `pytest tests/golden/ -m golden -v` — empty at Phase 0, must pass
- G7 (integration tests): `pytest tests/integration/ -m integration -v` (spins up Postgres container)
- G8 (coverage): `pytest --cov=backend --cov-report=xml` then coverage threshold check

At Phase 0 exit, the golden dataset directory exists but is empty (0 fixtures, 0 tests). G6 passes vacuously. First fixture lands in Phase 1 when the first parser is built.

---

### Wave 7 — Task 0.12: Coverage tiering + ratchet
**Files to create:**
- `ci/coverage/tiering.py` — parse `coverage.xml`, compute per-zone coverage
- `ci/coverage/ratchet.py` — compare against baseline stored in `.coverage-baseline.json`, fail if any zone decreased
- `.coverage-baseline.json` — initialized with 0% (everything starts passing vacuously; ratchet activates on first real code)
- `.github/workflows/ci.yml` — updated to run tiering + ratchet after G8

**Zone definitions (from QUALITY.md §2):**
```python
ZONES = {
    "critical": {
        "modules": ["core/events", "core/projections", "core/hashing", "core/ruleset",
                    "processing/resolver", "ingestion/validators", "domain/ca_view"],
        "line_threshold": 95, "branch_threshold": 90,
    },
    "standard": {
        "modules": ["ingestion/parsers", "processing"],
        "line_threshold": 85, "branch_threshold": 75,
    },
    "peripheral": {
        "modules": ["api", "adapters", "web"],
        "line_threshold": 70, "branch_threshold": 60,
    },
}
```

---

### Wave 8A — Task 0.13: PR quality-report comment bot
**Files to create:**
- `ci/reports/generate_report.py` — assembles the quality report markdown from all gate outputs
- `.github/workflows/quality-report.yml` — runs after all gate jobs; posts/updates PR comment via `gh` CLI
- `.github/workflows/ci.yml` — updated to upload gate artifacts (coverage XML, test results JSON)

**Report format (from QUALITY.md §5.1):**
```markdown
## Quality Report — PR #{{ pr_number }}

Gates      ✅ {{ passed }} passed · ⚠️ {{ warnings }} warnings · ❌ {{ failed }} failed

Coverage
  Critical    {{ pct }}%  ({{ delta }})   ≥95% {{ status }}
  Standard    {{ pct }}%  ({{ delta }})   ≥85% {{ status }}
  Peripheral  {{ pct }}%  ({{ delta }})   ≥70% {{ status }}
  Ratchet     {{ ratchet_status }}

Tests       {{ total }} passed · {{ failed }} failed · {{ skipped }} skipped   ({{ duration }}s)
  Unit {{ unit_count }} · Property {{ property_count }} · Golden {{ golden_count }} · Integration {{ integration_count }}
Invariants  {{ invariant_count }}/6 holding {{ status }}

Real-data   {{ guard_status }}
Migrations  {{ migration_status }}
```

---

### Wave 8B — Task 0.15: Trend dashboard
**Files to create:**
- `ci/trends/publish.py` — appends this run's metrics to `docs/trends/data.jsonl`
- `.github/workflows/trends.yml` — runs only on merge to `main`; commits `data.jsonl` update
- `docs/trends/index.html` — static chart rendering `data.jsonl` (Chart.js, no build step)

**Metrics captured per run:**
```json
{
  "sha": "abc123", "timestamp": "2026-07-30T10:00:00Z",
  "coverage": {"critical": 96.2, "standard": 87.1, "peripheral": 71.3},
  "test_counts": {"unit": 310, "property": 24, "golden": 0, "integration": 17},
  "invariants_passing": 6,
  "golden_fixture_count": 0,
  "complexity_avg": 3.2, "complexity_max": 11,
  "open_warnings": 1
}
```

Published to GitHub Pages (or served from the repo itself).

---

## Phase 0 exit verification

Run these in order. All must pass to advance to Phase 1.

```bash
# 1. Environment
docker compose up -d
docker compose exec backend alembic upgrade head

# 2. Core invariants: append → projection → replay
docker compose exec backend python -c "
from core.events.store import append_event
from core.projections.builder import build_projection, wipe_and_replay
# (run the round-trip test manually)
"

# 3. Determinism test
pytest tests/property/core/test_replay_determinism.py -v

# 4. Integration suite (ephemeral Postgres)
pytest tests/integration/ -m integration -v

# 5. All CI gates
act push  # or push to a branch and watch GitHub Actions

# 6. Quality report visible on a PR
# Open a test PR, confirm the comment is posted and all gates show ✅

# 7. Confirm exit criterion
# ✅ Event can be appended
# ✅ Projection built from it
# ✅ Replay produces identical output
# ✅ CI runs green on an empty golden dataset
# ✅ All gates G1–G15 run and publish a report on every push
```

---

## Files created by Phase 0 (full list)

```
docker-compose.yml
docker-compose.override.yml
Makefile
backend/
  pyproject.toml
  .ruff.toml
  core/
    events/__init__.py, store.py, models.py, types.py, upcasters.py, encryption.py
    projections/__init__.py, builder.py, snapshot.py, rebuild.py, timezone.py
    hashing/__init__.py, hash.py, types.py, rounding.py, serialization.py
    ruleset/  (empty __init__.py — scaffold for Phase 4)
  migrations/
    env.py
    versions/000_identity.py       (users, invite_allowlist, user_encryption_keys)
    versions/001_immutable.py      (event tables — FKs users, user_encryption_keys)
    versions/002_mutable.py        (accounts, budgets, overrides, settings, etc.)
  api/  (empty __init__.py)
web/
  package.json, tsconfig.json, .eslintrc.json
  app/  (empty layout.tsx)
tests/
  unit/core/test_event_store.py, test_upcasters.py, test_hash.py, test_types.py, test_rounding.py
  property/core/test_hash_invariants.py, test_replay_determinism.py
  integration/conftest.py, test_event_append_and_replay.py, test_replay_determinism.py, test_projection_rebuild.py, test_pitr.py, test_append_only_enforcement.py
  golden/  (empty — populated from Phase 1)
  fixtures/generator.py, templates/hdfc_savings.py, templates/sbi_savings.py
ci/
  guards/real_data_guard.py, migration_check.py, float_lint.py
  coverage/tiering.py, ratchet.py
  reports/generate_report.py
  trends/publish.py
.github/workflows/ci.yml, quality-report.yml, trends.yml
.coverage-baseline.json
docs/trends/data.jsonl, index.html
```

---

## Notes for the implementing agent

1. **Always run `mypy --strict` before committing any Python file** — strict mode catches the Paise newtype misuse that the lint rule targets.
2. **Never use `float` or `NUMERIC`** in financial modules. If you see one, that is a bug, not a style choice.
3. **Never pass `running_balance` into the idempotency hash** — it is a validation signal only (C1).
4. **Resolver pairings (MarkedInternalTransfer etc.) are events, not projections.** If you find yourself recomputing a pairing on replay, stop — that breaks I3.
5. **`NULL` and `0` are different.** A missing cost basis is `NULL`. An account with zero balance is `0`. Never coerce.
6. **UTC in, IST out.** All timestamps stored in UTC. All FY/period logic runs in `Asia/Kolkata`. Use `ZoneInfo("Asia/Kolkata")` from the stdlib, no third-party TZ library needed.

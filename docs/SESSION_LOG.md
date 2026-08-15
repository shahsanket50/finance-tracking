# Session Log

> **Append-only.** Newest entries at the top. Never edit or delete past entries — if something was wrong, add a correcting entry.
>
> Every session appends one block using the template at the bottom.

---

## 2026-08-14 — Session 011: Wave 5 — Phase 2 closure gate

**Phase:** 2 — Ledger & Correctness → CLOSED
**Participants:** Sanket + Claude

### Done

- **Fixed `test_payloads_are_frozen`** in `backend/tests/unit/processing/test_resolver_events.py`: narrowed `pytest.raises(Exception)` to `pytest.raises(ValidationError)` — minor finding from Wave 1 task review; `ValidationError` was already imported.
- **Ran full unit test suite**: 317 tests, all pass (0 failures).
- **Ran full integration test suite**: 27/28 pass. 1 pre-existing failure (`test_pitr.py::test_wal_level_is_replica`) requires Docker `db` host — not a regression; this test has never passed without `docker compose up`. All 27 testcontainer-based integration tests pass.
- **mypy**: clean — 0 issues in 18 source files (`processing/` + `core/projections/`).
- **Updated `docs/PROJECT_STATE.md`**: Phase 2 marked CLOSED; all 7 exit criteria checked off (with note that Level A overlap-map UI is partial — deferred to Phase 3); Phase 2 blockers A-3 + C-2 marked FIXED; standing risk for F-9 marked CLOSED; phase roadmap table updated.

### Decisions made

- Level A audit view (overlap-map UI) deferred to Phase 3. The UniqueConstraint on `idempotency_hash` provides the correctness guarantee; a queryable overlap view is UX, not correctness.
- PITR integration test (`test_pitr.py`) is gated on a live Docker `db` host. It is an infra-readiness check, not a unit/functional gate. Excluded from the Wave 5 pass/fail threshold.

### Phase 2 exit gate summary

| Gate | Result |
|---|---|
| Unit tests | 317/317 pass |
| Integration tests | 27/28 pass (1 PITR Docker-only, pre-existing) |
| mypy | Clean — 0 issues, 18 source files |
| Exit criterion checklist | 7/7 checked (Level A partial — noted and deferred) |

### Next

- Phase 3: Day-to-Day Layer — budget tracking, monthly totals, surplus reconciliation.

---

## 2026-08-13 — Session 010: Phase 1 hard close — integration tests run for real + gate hardening

**Phase:** 1 — Ingestion & Trust → CLOSED
**Participants:** Sanket + Claude

### Done

- **Ran 8 integration tests against real Docker testcontainers** (psycopg[binary] installed to fix missing libpq; testcontainers Postgres + Redis). All 8 pass: `test_idempotent_ingest`, `test_malformed_input` (user-scoped count fix), `test_session_expiry`, `test_password_protected`.
- **Fixed `test_malformed_input.py`**: `count() == 0` was checking the whole table; changed to `.filter(TransactionEvent.user_id == test_user.id).count() == 0`. Real bug — prior committed tests had left rows in the shared DB.
- **Added 5 negative tests** (NULL≠0 guard):
  - `test_sbi_savings_parser.py`: `test_missing_opening_balance_header_raises_value_error`
  - `test_hdfc_cc_parser.py`: `test_no_previous_balance_row_raises_value_error`, `test_no_new_balance_row_raises_value_error`
  - `test_sbi_cc_parser.py`: `test_no_previous_balance_row_raises_value_error`, `test_no_new_balance_row_raises_value_error`
- **Added 2 ₹-prefix regex tests** in `test_slice_savings_parser.py`: `test_real_rupee_prefix_opening_balance_parsed_correctly`, `test_real_rupee_prefix_closing_balance_parsed_correctly` — feed literal ₹ directly into parser methods, bypassing fpdf2 rendering limitation.
- **Added G18 gate** (`docs/QUALITY.md`): permanent gate requiring every `AbstractParser` subclass in `_DEFAULT_PARSERS`. Enforcement test in `test_dryrun_harness.py::test_all_concrete_parsers_registered_in_default_parsers`.
- **Added Slice ref-number open item** to `docs/PROJECT_STATE.md` standing risks: `\S+` regex not confirmed against a real Slice statement.
- **Marked Phase 1 CLOSED** in `docs/PROJECT_STATE.md`.
- Total: 212 unit + property tests passing.

### Decisions

- User-scoped filter on malformed-input assertions is correct: `dry_run()` never writes to DB, so rows for a fresh `test_user` are always 0 regardless of what other tests committed.
- `setex` deprecation warning left in place — Redis still supports it; fixing is cosmetic and not blocking.

### Next

- Phase 2: Dynamic Parser Builder (LLM fallback). Plan at `docs/superpowers/plans/2026-08-08-dynamic-parser-builder.md`.
- Fix `compute_occurrence_index()` arg-order bug in Phase 2 plan before implementation begins.
- Validate Slice ref-number regex against a real Slice statement before Phase 2 Slice work.

---

## 2026-08-08 — Session 009: Phase 1 closure — savings parsers + integration tests

**Phase:** 1 — Ingestion & Trust
**Participants:** Sanket + Claude

### Done

**Three new savings parsers (T1–T6):**
- `backend/ingestion/parsers/hdfc_savings.py` — HdfcSavingsParser using `extract_words()` + x-position bounding box column detection; `running_balance_paise` non-None for all transactions; opening balance derived as `first.running_balance_paise - first.amount_paise`; 15 tests pass.
- `backend/ingestion/parsers/sbi_savings.py` — SbiSavingsParser using `extract_tables()`; opening balance from "Balance as on" header regex; raises `ValueError` on missing opening balance or empty transactions; 15 tests pass.
- `backend/ingestion/parsers/slice_savings.py` — SliceSavingsParser using line regex with `\S+` ref number (handles alphanumeric synthetic refs); handles `₹` and `Rs.` prefixes; apostrophe date format `"DD Mon 'YY"` via `str.replace("'", "20")`; 15 tests pass.

**Golden fixtures for all three parsers:**
- `backend/tests/fixtures/golden/hdfc_savings/statement_001.{json,pdf}` — 4 transactions, opening 10 000 000 paise
- `backend/tests/fixtures/golden/sbi_savings/statement_001.{json,pdf}` — 3 transactions, opening 500 000 paise
- `backend/tests/fixtures/golden/slice_savings/statement_001.{json,pdf}` — 3 transactions, opening 100 000 paise

**`backend/tests/fixtures/pdf_generator.py`** — added `dict_to_pdf_hdfc_savings()`, `dict_to_pdf_sbi_savings()`, `dict_to_pdf_slice_savings()`; all use `Decimal` arithmetic (no raw float division).

**Four integration tests (T7–T10):**
- `test_idempotent_ingest.py` — two scenarios: confirming same statement twice → IntegrityError; genuine same-day duplicate → both rows with occurrence_index 0 and 1.
- `test_malformed_input.py` — garbage bytes + empty bytes → exception from harness → zero DB rows.
- `test_session_expiry.py` — real Redis testcontainer TTL=1 second + `time.sleep(2)` → real key eviction confirmed before calling confirm() → `SessionExpiredError` raised → zero DB rows.
- `test_password_protected.py` — pikepdf AES-128 in-memory fixture; correct password → full parse + PASS balance check; missing password → `PasswordRequiredError`; wrong password → `PasswordIncorrectError`.

**`backend/tests/integration/conftest.py`** — added `redis_container` (session-scoped `RedisContainer("redis:7-alpine")`) and `redis_client` (per-test, flushdb on teardown) fixtures.

**`backend/ingestion/fetchers/pdf_reader.py`** — fixed password-exception detection: modern pdfminer wraps `PDFPasswordIncorrect` in `PdfminerException` with empty string; now inspects `exc.__context__.__class__.__name__` as primary path, string-match kept as fallback.

**`backend/pyproject.toml`** — added `pikepdf>=9.0` and `testcontainers[postgres,redis]` (upgraded from postgres-only) to dev extras.

### Decisions made

- `extract_words()` + x-position bounding boxes is the correct approach for HDFC Savings (pdfplumber collapses all inter-column whitespace to single spaces in `extract_text()`; regex on text cannot distinguish columns).
- Slice Savings ref number regex uses `\S+` not `\d{10,25}` — real bank statements have long numeric refs but synthetic fixtures use alphanumeric `REFxxxxxxxxx`.
- fpdf2 Helvetica cannot render ₹ Unicode — synthetic PDFs use `Rs.`; all Slice parser regex patterns handle both `(?:₹|Rs\.)`.
- Password detection in pdf_reader.py should use `exc.__context__` inspection (not `str(exc)`) for compatibility with modern pdfminer.
- All savings parsers raise `ValueError` (not return `0`) on missing opening/closing balance — `0` would violate NULL≠0 invariant and silently corrupt balance-check math.

### Commits (T1–T10)
- `49e1ae3` test: T1 HDFC Savings independent test-authoring
- `6da579f` feat: T2 HdfcSavingsParser + golden fixtures
- `144ab0d` fix: T2 None checks, Decimal generator, assert not type:ignore
- `c95d4ef` test: T3 SBI Savings independent test-authoring
- `286caf5` feat: T4 SbiSavingsParser + golden fixtures
- `3802ddd` fix: T4 raise on missing balances, tighter period regex, Decimal divisors
- `7e5a037` test: T5 Slice Savings independent test-authoring
- `6d6189d` feat: T6 SliceSavingsParser + golden fixtures
- `9528e55` test: T7 idempotent ingest integration tests
- `1ee23e2` test: T8 malformed input integration tests
- `0f7a6bb` test: T9 session expiry integration test (real Redis TTL)
- `a2a2839` test: T10 password-protected integration test (pikepdf + pdf_reader fix)

### Blocked / open
- T19: Dynamic Parser Builder design (spec only, no implementation) — deferred to end of Phase 1
- Integration tests require Docker (testcontainers) to run — syntax verified only; full runtime requires `docker compose up`
- Phase 0 known gap (F-9): `core/hashing/`, `core/events/`, `core/projections/` tests need re-authoring before Phase 2 closes

### Next session should
- T19: Spec Dynamic Parser Builder into TRD §9.2 + PRD §14; write implementation plan to `docs/superpowers/plans/`; flag as Phase 2 scope
- Run full Phase 1 acceptance checklist (run unit tests, verify quality gates)
- Final whole-branch review → `superpowers:finishing-a-development-branch`

---

## 2026-08-02 — Session 008: Phase 0 adversarial review + blocker resolution

**Phase:** 0 — Foundations
**Participants:** Sanket + Claude

### Done
- Phase 0 adversarial review completed. 9 findings: F-1, F-2, F-3, F-4, F-6, F-7, F-8 (blockers/important), F-5, F-9 (docs gaps).
- Resolved all four wave-gate blockers across three commit groups.
- Added TRD §11 (anti-drift process), ADR-012, CLAUDE.md §6 updates, QUALITY.md §8/§9.

### Known gap recorded
- **F-9 (retroactive gap):** Phase 0 critical-module tests (`core/events`, `core/projections`, `core/hashing`) were co-authored with the implementation in the same session — not independently authored as required by QUALITY.md §9 and TRD §11.2. Root cause: the independent-test-authoring process was not in place when Phase 0 was built; it was added during this adversarial review session.
- **Consequence:** the invariant property tests and unit tests for critical modules may share the same blind spots as the implementation.
- **Mitigation:** a re-authoring session (fresh context, spec-only, no implementation file access) must run for `core/hashing/`, `core/events/`, and `core/projections/` before Phase 2 closes. The Phase 2 adversarial review must confirm independent authorship for these modules.

### Decisions made
- `canonical_narration` replaces `normalized_narration` everywhere (TRD §9.1 C1, CLAUDE.md §2, hash.py, ORM model, migration). Canonicalization is frozen forever; distinct from step-4 merchant normalization.
- `occurrence_index` tiebreaker: position in balance-validated statement sequence, provenance recorded on ingestion event (TRD §9.1 C2).
- `raw_artifacts.content_hash` uniqueness scoped per-user: `UNIQUE(user_id, content_hash)`.
- `append_event` `value_date` is now required (no silent `date.today()` default).

### Commits
- Group 1 `f3c3156` — F-8, F-1: canonical_narration spec + hash.py
- Group 2 `0a1524f` — F-6, F-7, F-2: schema/code fixes
- Group 3 (this commit) — F-3, F-4, F-9: docs

### Next session should
- Re-run adversarial review to confirm all four blockers cleared, then close Phase 0.
- Begin Phase 1: ingestion layer.

---

## 2026-08-01 — Session 007: Trend dashboard (Task 0.15)

**Phase:** 0 — Foundations
**Participants:** Sanket + Claude

### Done
- `ci/trends/__init__.py` — package init.
- `ci/trends/publish.py` — appends one JSON record per main-branch run to `docs/trends/data.jsonl`. Reads `coverage.xml` via `compute_zone_coverage()` and `test-results.json` (pytest-json-report schema). Missing artifacts produce a record with empty sections (no fail). Passes `ruff check`, `ruff format --check`, `mypy --strict --explicit-package-bases`.
- `docs/trends/data.jsonl` — empty seed file (trailing newline). Appended by CI on every merge to main.
- `docs/trends/chart.umd.min.js` — Chart.js v4.4.4 UMD bundle vendored locally (~201KB). No CDN dependency.
- `docs/trends/index.html` — static dashboard with 4 Chart.js line charts: coverage by zone (critical/standard/peripheral with 95/85/70 thresholds implied), test counts (unit/property/golden/integration), test duration, golden dataset size. Degrades gracefully when loaded as local file.
- `.github/workflows/ci.yml` — added `trend-publish` job at bottom. Runs only on `push` to `main` (`if: github.ref == 'refs/heads/main' && github.event_name == 'push'`). Needs all 10 gate jobs. Commits updated `data.jsonl` back to main via `github-actions[bot]` with `[skip ci]`.

### Decisions
- Chart.js vendored locally to avoid CDN trust requirement (per brief security requirement).
- `trend-publish` added to existing `ci.yml` (not a new workflow file) to avoid cross-workflow artifact issues.

### Commit
- `e855bcb` feat: trend dashboard — publish.py + Chart.js viewer (Phase 0 task 0.15)

---

## 2026-07-31 — Session 004: Custom CI gates G14 + G15 (Task 0.11)

**Phase:** 0 — Foundations
**Participants:** Sanket + Claude

### Done
- `ci/__init__.py`, `ci/guards/__init__.py` — package init files for guard module.
- `ci/guards/real_data_guard.py` — G14: scans `tests/` and `docs/` for PAN, Aadhaar, IFSC, 12-18 digit account numbers, and bank domains. Returns exit code 0 (clean) or 1 (violations).
- `ci/guards/migration_check.py` — G15: scans migration versions for UPDATE/DELETE on immutable tables and forbidden column types (NUMERIC/REAL/DOUBLE/FLOAT). Returns exit code 0 or 1.
- `ci/guards/float_lint.py` — G15 extension: AST-based scan of `core/`, `processing/`, `domain/` for float literals and float() calls.
- `backend/tests/unit/test_guards.py` — 13 unit tests covering all three guards (positive + negative cases).
- `backend/tests/conftest.py` — added `sys.path.insert(0, repo_root)` so `ci.guards.*` is importable from tests without Docker.
- `.github/workflows/ci.yml` — activated G14 (`real-data-guard`) and G15 (`migration-check`) jobs; G4–G13 remain commented stubs.
- `docs/PROJECT_STATE.md` — task 0.11 marked Done.

### Verification results
- All three guards pass against current repo (exit code 0).
- 13/13 unit tests pass.
- `python3 -m mypy --strict ci/` — success, no issues in 5 source files.

### Decisions
- Guards placed at repo root `ci/guards/` (not inside `backend/`) for CI clarity — scripts run directly without Docker.
- `sys.path` patched in `backend/tests/conftest.py` (two levels up from conftest to repo root) to keep test file co-located with other unit tests.

---

## 2026-07-30 — Session 003: Postgres schema — immutable event tables (Task 0.3)

**Phase:** 0 — Foundations
**Participants:** Sanket + Claude

### Done
- `backend/migrations/alembic.ini` — Alembic config, `script_location = migrations`, URL overridden in env.py.
- `backend/migrations/env.py` — reads DATABASE_URL from environment; imports `Base` from core.events.models.
- `backend/migrations/versions/000_identity.py` — creates `users`, `invite_allowlist`, `user_encryption_keys`.
- `backend/migrations/versions/001_immutable.py` — creates 4 event tables with append-only triggers + M10 indexes on `transaction_events`.
- `backend/core/__init__.py`, `backend/core/events/__init__.py` — package init files.
- `backend/core/events/models.py` — SQLAlchemy 2.x ORM models for all 7 domain tables (identity + event).
- `backend/core/events/types.py` — `TransactionType`, `Actor`, `BalanceCheck`, `IngestionStatus` enums.
- Ran `alembic upgrade head` inside backend container — both migrations applied cleanly.
- Verified: 8 tables (incl. alembic_version), 4 append-only triggers (8 rows in information_schema due to UPDATE+DELETE each), 3 M10 indexes on transaction_events, 0 NUMERIC/REAL/FLOAT columns.
- Verified: `users` table is mutable (UPDATE works); `ingestion_events` trigger fires and blocks UPDATE.
- Verified: `mypy --strict core/events/` — 0 issues in 3 source files.

### Decisions made
- `source_detail: Mapped[dict | None]` requires explicit `JSON` column type — SQLAlchemy 2.x cannot auto-resolve `dict` in `Mapped[]` annotations without it.
- `uuidv7()` confirmed as Postgres 18 native built-in; no extension needed.
- `psycopg` (psycopg3) driver URL (`postgresql+psycopg://`) works with synchronous Alembic env.py; no async driver needed for migrations.

### Blocked / open
- Nothing blocking next tasks.

### Next session should
- Task 0.4: Postgres schema — mutable settings tables (TRD §3.2) via `002_mutable.py`.

---

## 2026-07-30 — Session 002: Docker local dev environment (Task 0.2)

**Phase:** 0 — Foundations
**Participants:** Sanket + Claude

### Done
- `docker-compose.yml` — 6 services: db (Postgres 18), redis (7-alpine), backend (FastAPI), worker (Celery), beat (Celery beat), web (Next.js 14).
- `backend/Dockerfile`, `backend/pyproject.toml`, `backend/__init__.py`, `backend/main.py` (FastAPI scaffold + /health), `backend/celery_app.py`.
- `web/Dockerfile`, `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/app/layout.tsx`, `web/app/page.tsx`.
- `Makefile` with up/down/migrate/test/lint targets.
- `.gitignore` covering Python, Node, Docker, secrets.
- `docker-compose.override.yml` (git-ignored) for local port remaps.
- ADR-011 added to `docs/DECISIONS.md`.
- Verified: all 6 containers Up, `SHOW wal_level` = replica, `/health` 200 OK, Next.js 200 OK.

### Decisions made
- Postgres 18 changed its data dir convention — volume must mount at `/var/lib/postgresql` not `/var/lib/postgresql/data`. Updated compose accordingly.
- `eslint-config-next@14` requires eslint ^8, not ^9. Pinned eslint to ^8 in web/package.json.
- Local port conflicts (OrbStack holds 5432; local redis-server holds 6379): base compose does not publish db or redis ports; override maps db to 5433 and redis to 6380.
- Celery + Redis wired from day one (TRD H5 — cannot be retrofitted).
- ADR-011 recorded PITR readiness rationale and manual restore checklist.

### Blocked / open
- Nothing blocking next tasks.

### Next session should
- Task 0.3: Postgres schema — immutable event tables (TRD §3.1).
- Task 0.4: Postgres schema — mutable settings tables (TRD §3.2).

---

## 2026-07-22 — Session 001: Project scaffolding

**Phase:** 0 — Foundations
**Participants:** Sanket + Claude

### Done
- Created repo scaffolding and docs-as-code structure.
- Wrote `CLAUDE.md` — agent context, invariants, pipeline ordering constraint, stop-and-ask rules.
- Created `docs/PROJECT_STATE.md` (phase tracking), `docs/SESSION_LOG.md` (this file), `docs/CODE_GRAPH.md` (planned module map), `docs/DECISIONS.md` (ADRs).
- PRD and TRD to be synced into `docs/` from Notion.

### Decisions made
- Docs live in-repo so the AI agent reads the same specs as the human.
- Phase/session state is tracked in files, not memory or chat history.
- Code graph maintained as a living document, updated when structure changes.

### Blocked / open
- Nothing blocking Phase 0 tasks 0.2 onward.
- Standing open item: arrange a CA to review tax rule-set before Phase 4.

### Next session should
- Start Phase 0 task 0.2: Docker local dev environment (Postgres + FastAPI + Next.js).
- Then 0.3/0.4: database schema with the immutable/mutable split.

---

## Entry template

```markdown
## YYYY-MM-DD — Session NNN: <short title>

**Phase:** <n> — <name>
**Participants:**

### Done
- <what actually got built/changed, with file paths where useful>

### Decisions made
- <any decision that future-you or an agent would otherwise have to re-derive>
- <if it's architectural, also add an ADR to DECISIONS.md>

### Blocked / open
- <anything stuck, and what would unblock it>

### Next session should
- <concrete next task, ideally referencing a PROJECT_STATE task number>
```

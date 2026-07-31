# Session Log

> **Append-only.** Newest entries at the top. Never edit or delete past entries — if something was wrong, add a correcting entry.
>
> Every session appends one block using the template at the bottom.

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

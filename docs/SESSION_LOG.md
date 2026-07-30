# Session Log

> **Append-only.** Newest entries at the top. Never edit or delete past entries — if something was wrong, add a correcting entry.
>
> Every session appends one block using the template at the bottom.

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

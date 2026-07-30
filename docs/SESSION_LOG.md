# Session Log

> **Append-only.** Newest entries at the top. Never edit or delete past entries — if something was wrong, add a correcting entry.
>
> Every session appends one block using the template at the bottom.

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

# Architecture Decision Records

> One entry per significant decision. Append-only — supersede rather than edit.
> If an agent has to invent a rule, it gets recorded here, not buried in code.

---

## ADR-001: Product does not file ITR
**Status:** Accepted · **Date:** 2026-07
Planning and tracking only. Filing would require ERI registration and carry compliance liability. We deliver the insight layer and hand off to the user's CA.

## ADR-002: Postgres, not Notion, as the datastore
**Status:** Accepted · **Date:** 2026-07
Notion holds documentation. It cannot serve as a transaction ledger — no ACID guarantees, rate-limited API, and storing real bank data in a Notion workspace is a poor security posture. Single shared Postgres instance with row-level tenant isolation.

## ADR-003: Hybrid immutable/mutable data layer
**Status:** Accepted · **Date:** 2026-07
Append-only event log for the transaction ledger and anything tax-affecting; conventional mutable tables for settings, budgets, nicknames.
**Why:** the audit trail (PRD §15) and FY rule-versioning (PRD §1.4) are impossible to implement honestly on mutable rows — you would end up rebuilding event sourcing badly, later. Full event-sourcing everywhere adds ceremony where history genuinely doesn't matter.

## ADR-004: Provider-agnostic LLM adapter
**Status:** Accepted · **Date:** 2026-07
All model calls route through `adapters/llm/`. No vendor SDK imported elsewhere.
**Why:** model pricing and capability change frequently. Making the model a configuration value means cost/quality optimization becomes a dial to turn once real usage data exists, rather than a decision locked in blind at design time. Route by stakes: cheap models for high-volume categorization, stronger models for low-volume/high-stakes parsing.

## ADR-005: Deterministic-first, LLM as fallback
**Status:** Accepted · **Date:** 2026-07
Rules and template parsers run before any LLM call.
**Why:** cheaper, faster, and testable. An LLM in the default path makes every result probabilistic and every test flaky. The LLM handles the long tail of unmatched layouts.

## ADR-006: Pipeline ordering — resolver before classifier
**Status:** Accepted · **Date:** 2026-07
The relationship resolver (internal transfers, CC bill payments, FD bookings) must run before category classification.
**Why:** if categorization runs first, a credit-card bill payment is counted as spend *in addition to* the individual purchases already counted — silently inflating every budget total. This is enforced in code and asserted in tests.

## ADR-007: Synthetic fixtures only in the repository
**Status:** Accepted · **Date:** 2026-07
Real bank statements never enter the repo or CI. A fixture generator produces realistic-but-fake statements.
**Why:** privacy, and CI portability. Corollary policy: every bug found in real data becomes a synthetic fixture *before* it is fixed, so the golden dataset only grows.

## ADR-008: Phase-gated delivery, not date-gated
**Status:** Accepted · **Date:** 2026-07
Phases advance on demonstrated working software against an explicit exit criterion, not on calendar dates.
**Why:** follows directly from the owner's stated priority ranking — correctness first, shipping speed last.

## ADR-009: Bring-your-own LLM key — rejected
**Status:** Rejected · **Date:** 2026-07
Considered as a trust differentiator for a developer audience. Rejected: adds meaningful product complexity for a narrow benefit. Server-side calls only.

## ADR-010: SMS sync — rejected
**Status:** Rejected · **Date:** 2026-07
Ingestion is Gmail-PDF based (plus AA where available). SMS parsing adds Android permission friction and yields incomplete, alert-shaped data rather than reconcilable statements.

## ADR-011: PITR readiness from day one
**Status:** Accepted · **Date:** 2026-07-30
Postgres runs with `wal_level=replica` from the first container start.
**Why:** The event log is the only source of truth. User confirmations, corrections, and amendment events are irreplaceable. A restore must be tested before beta — an untested backup is not a backup. Manual restore test checklist:
1. Take a base backup: `pg_basebackup -h localhost -U finance -D /tmp/pgbackup -Ft -z -P`
2. Stop the container: `docker compose stop db`
3. Restore to a new container targeting the backup directory.
4. Run `alembic upgrade head` and `pytest tests/integration/` — must pass clean.
KMS upgrade deferred to Phase 5 per H3.

## ADR-012: Anti-Drift Process — independent test authoring + adversarial wave-gate
**Status:** Accepted · **Date:** 2026-08
For correctness-critical modules, tests are authored in a separate session from implementation (spec-only, no implementation file access). At each wave boundary, a fresh-context adversarial review checks deliverables against the spec. Tax constants carry `# UNVERIFIED — CA review pending` until Phase 4.
**Why:** the correctness harness checks code against tests but cannot check tests against spec. When the same agent writes both from the same reading, a misreading produces a passing test that enforces wrong behaviour — green CI, confidently wrong. Running a parallel agent does not fix this: correlated training → correlated blind spots. The fix is structural independence: tests authored without seeing the implementation, and wave-end review by a context that has not absorbed the build session's assumptions. See TRD §11 for the full specification.

---

## Template

```markdown
## ADR-NNN: <title>
**Status:** Proposed | Accepted | Rejected | Superseded by ADR-NNN · **Date:** YYYY-MM
<decision in one or two sentences>
**Why:** <the reasoning that would otherwise have to be re-derived later>
```

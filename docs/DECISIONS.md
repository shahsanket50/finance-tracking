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

---

## Template

```markdown
## ADR-NNN: <title>
**Status:** Proposed | Accepted | Rejected | Superseded by ADR-NNN · **Date:** YYYY-MM
<decision in one or two sentences>
**Why:** <the reasoning that would otherwise have to be re-derived later>
```

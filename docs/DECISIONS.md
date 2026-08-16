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

## ADR-013: reverses_transaction_id column deferred to Wave 2

**Date:** 2026-08-14
**Status:** Decided

TRD §9.5 M4 specifies a `reverses_transaction_id` FK column on `transaction_events`
for reversals. Wave 1 defers this column to Wave 2 (reversal matcher implementation),
when the exact FK semantics (UUID vs idempotency hash, nullable vs required) can be
decided with the matcher code in hand. The `MarkedReversalPayload` stores
`original_hash` and `reversal_hash` in the encrypted payload column in the interim.

**Wave 2 follow-up (2026-08-14):** Reversal matcher is complete. The `reverses_transaction_id`
FK column was not added in Wave 2. The reversal relationship is fully identified by
`original_hash` and `reversal_hash` in the encrypted `MarkedReversalPayload` — no FK column
is required for the matcher or reducer to function. Decision: FK column deferred to Phase 3
review. If the Phase 3 audit view (`domain/audit`) has no structural need for it, the column
will be dropped from scope permanently.

---

## ADR-014: Wave 2 matchers share a common matching primitive

**Date:** 2026-08-14
**Status:** Decided

The four Wave 2 matchers (transfer, CC payment, FD booking, reversal) share a single
`score_candidate_pair` primitive in `processing/resolver/matching.py` rather than each
implementing independent proximity/confidence logic.
**Why:** All four matchers perform the same core operations — amount equality check,
date-proximity check within a configured window, and basis-point confidence scoring.
Duplicating this logic across four callers creates calibration risk: a fix to the
proximity window check must be applied in four places, and drift is silent. A shared
primitive means calibration is a one-line change in one place, and a bug in the
primitive is immediately visible across all four matchers' tests.

---

## ADR-015: Two-context IA (Expense / CA + shared utilities) over flat nav

**Status:** Accepted · **Date:** 2026-08-16
Expense and CA are two distinct usage modes with almost no screen overlap. The IA uses a persistent context switch that swaps the entire sidebar, plus shared utilities (Accounts, Notifications, Settings) reachable from both contexts without switching.
**Why:** A flat nav containing all screens from both modes produces a sidebar too long to be useful in either mode. The shared ledger feeds both contexts, but the user's intent when opening the app is unambiguously one or the other — not both at once. Shared utilities serve both modes equally and should never require a context switch to reach them. See PRD §20.

---

## ADR-016: shadcn/ui as the component library

**Status:** Accepted · **Date:** 2026-08-16
Use shadcn/ui (copy-into-repo model, Radix + Tailwind, CSS-variable theming) rather than an opaque dependency-style component library.
**Why:** Components are copied as fully-typed, readable, modifiable code into `web/components/ui/` — zero abstraction penalty, no opaque dependency boundary. Consistent with TRD T3 ("mainstream, best-documented for AI codegen") and directly supports the token-set design system (ADR-017) since theming is already CSS-variable-based. Alternative libraries (Mantine, Chakra) would add an opaque dependency layer that AI codegen agents cannot inspect or modify without risk.

---

## ADR-017: Theme as a CSS-variable token set (configurable, dark-first)

**Status:** Accepted · **Date:** 2026-08-16
The design system ships as a CSS-variable token file. Dark-first (ink/navy palette). A theme change is a new token file, not a code change. Settings exposes a theme selector (PRD §19).
**Why:** Hardcoded colors in components are the most common cause of an app that looks themed in one place and unstyled in another. A CSS-variable token set is the smallest unit of discipline that prevents drift — every color reference must go through a token. Building dark-first avoids retrofitting (which typically breaks edge cases invisible in light mode). The token-set model also means user-selectable themes add zero per-screen code.

---

## ADR-018: Home is a pure visualization surface

**Status:** Accepted · **Date:** 2026-08-16
Home (Expense context landing screen) contains KPI strip + 7 dashboards driven by a shared time selector, and nothing else. No navigation tiles. No notification preview. No CA/FY data.
**Why:** Navigation is the sidebar's job. Notifications is its own shared screen. CA/FY data belongs in the CA context. A Home that tries to do all three creates a screen with no center of gravity — every element fights for prominence. Making Home a pure visualization surface lets every pixel serve one purpose: telling the user where their money went in the selected window. The original §12 spec included nav tiles and a notification preview; PRD §12A supersedes it after UI review. See PRD §12A.1/§12A.5.

---

## ADR-019: Paired UI phases (N.5) over one appended frontend phase

**Status:** Accepted · **Date:** 2026-08-16
Insert a UI phase after each backend phase that produces something worth seeing (2.5, 3.5, 4.5) rather than building all frontend work in one phase appended at the end.
**Why:** Appending UI at the end means backend APIs are designed without a consumer to validate them, and the UI gets built in one stretch with no feedback loop. Pairing each UI phase with the backend phase that produced its data: (a) never builds against a mock — the exit criterion requires wiring to a real, tested endpoint; (b) amortizes the design system correctly — 2.5 builds tokens once, 3.5/4.5 consume them; (c) makes beta-readiness checkable — Phase 5 ships because 2.5/3.5/4.5 have already built the actual product surface. Phase 2.5 can run in parallel with Phase 3 backend since they touch different layers. See TRD §14.

---

## Template

```markdown
## ADR-NNN: <title>
**Status:** Proposed | Accepted | Rejected | Superseded by ADR-NNN · **Date:** YYYY-MM
<decision in one or two sentences>
**Why:** <the reasoning that would otherwise have to be re-derived later>
```

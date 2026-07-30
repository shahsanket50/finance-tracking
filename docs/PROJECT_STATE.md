# Project State

> **Update this file at the end of every session.** It is the first thing an agent reads after `CLAUDE.md`.

**Last updated:** 2026-07-30
**Current phase:** Phase 0 — Foundations
**Overall status:** Not started (scaffolding created)

---

## Current phase: Phase 0 — Foundations

**Goal:** Establish the skeleton that everything else depends on — repo structure, local environment, database schema with the immutable/mutable split, event-log primitives, replay mechanism, and CI running the correctness harness.

**Exit criterion (must be demonstrably true to advance):**
> An event can be appended, a projection built from it, and a replay produces identical output. CI runs green on an empty golden dataset, **and all quality gates (G1–G15) run and publish a report on every push.**

### Task board

| # | Task | Status | Notes |
|---|---|---|---|
| 0.1 | Repo scaffolding + `CLAUDE.md` + docs structure | Done | This scaffolding |
| 0.2 | Docker local dev environment (Postgres + API + web) | Done | All 6 services up; wal_level=replica; /health 200 |
| 0.3 | Postgres schema: immutable event tables | Not started | See TRD §3.1 |
| 0.4 | Postgres schema: mutable settings tables | Not started | See TRD §3.2 |
| 0.5 | Event-log primitives (append, read stream) | Not started | Append-only enforcement at DB level |
| 0.6 | Projection builder + replay mechanism | Not started | Must be deterministic (invariant 3) |
| 0.7 | Idempotency hash implementation | Not started | See TRD §3.4 |
| 0.8 | CI pipeline + correctness harness skeleton | Not started | Golden dataset runner, empty to start |
| 0.9 | Synthetic fixture generator (basic) | Not started | Realistic-but-fake statements |
| 0.10 | CI pipeline with gates G1–G8 | Not started | See `docs/QUALITY.md` |
| 0.11 | Custom gates: real-data guard + migration check | Not started | G14, G15 — always blocking |
| 0.12 | Coverage tiering config + ratchet | Not started | Critical 95% / Standard 85% / Peripheral 70% |
| 0.13 | PR quality-report comment bot | Not started | Per-run visible reporting |
| 0.14 | Integration test harness (ephemeral Postgres) | Not started | See QUALITY.md §3.4 |
| 0.15 | Trend dashboard publishing | Not started | Slope matters more than single-run numbers |

### Blockers
_None currently blocking Phase 0 tasks._

### Spec gaps — RESOLVED

All 6 blocking gaps were resolved in the journey walkthrough (see "User Stories & Journeys" §16–17 for full decisions).

| # | Gap | Resolution |
|---|---|---|
| G1 | Auth / session / user model | Google OAuth only — one flow covers identity + Gmail access |
| G2 | Onboarding sequence | Skippable checklist, not a forced wizard |
| G3 | Retroactive recategorization vs closed-FY immutability | Amendments allowed with explicit confirmation + original preserved. **Invariant 5 restated.** |
| G4 | Deduction detection mechanism | Hybrid: curated merchant→section table, LLM for unknowns, user confirms both |
| G5 | Silent-staleness failure mode | Exception-based email only (no digest, no push) + silent retry + silent backfill |
| G6 | Beta invite / provisioning | Invite-only email allowlist; strict isolation — owner cannot see beta data |

### Still open (not blocking Phase 0)

| Item | Needs | Blocks |
|---|---|---|
| Match-window tolerance calibration | Real statement data to tune | Phase 2 |
| Confidence/assumption trail UI | Design work (mechanism decided) | Phase 4 |
| Form 16 parser spec | TRACES Part A/B structure spec | Phase 4 |

### Spec changes to write into the PRD/TRD

| Change | Target |
|---|---|
| **Transaction type as first-class field** (`income \| expense \| transfer \| investment`) — replaces exclusion-flag model | PRD §7, TRD §3 |
| **Invariant 5 restated** — closed FY never changes *silently*; amendments allowed with confirmation | TRD, `CLAUDE.md` §2 |
| **"Available to invest"** replaces "surplus"; = income − spent − committed outflows | PRD §12.1 |
| **Auth section** (Google OAuth) — currently absent entirely | PRD, new section |
| **Exception-based email** — currently PRD says "no notifications" | PRD §3 |
| **Deduction detection mechanism** — hybrid table + LLM + confirm | PRD §1.3 |
| **Nature tags apply only to `expense`** type | PRD §5 |

---

## Phase roadmap

| Phase | Name | Status | Exit criterion (short) |
|---|---|---|---|
| 0 | Foundations | **In progress** | Event append → projection → deterministic replay; CI green |
| 1 | Ingestion & Trust | Not started | Real statement parses via dry-run harness, balance check passes, writes nothing until confirmed |
| 2 | Ledger & Correctness | Not started | Overlapping statements ingested twice → zero double-counting, provable in audit view |
| 3 | Day-to-Day Layer | Not started | A full month tracked, budgeted; surplus reconciles against bank statement manually |
| 4 | CA Layer | Not started | Full FY health report from real docs; every number traces to source. **CA review of tax rule-set required.** |
| 5 | Private Beta | Not started | A second user onboards end-to-end unaided; data isolation verified |

---

## Standing risks

| Risk | Mitigation | Status |
|---|---|---|
| Tax logic cannot be owner-verified | Engage a qualified CA to review the rule-set before Phase 4 closes | Open — not yet arranged |
| Gmail restricted-scope verification with Google is a long lead time | Start the application early; it gates Phase 5, not Phase 1 | Open — not started |
| AA TSP partner not selected | Blocks AA ingestion only; Gmail path is unblocked | Open — deferred |
| AI-written code drifting from spec | Golden dataset + invariant tests + spec-traceability rule in `CLAUDE.md` | Mitigated by design |

---

## Deferred decisions

- Specific LLM model routing per task — revisit once real volume/cost data exists.
- Per-user encryption keys (stricter isolation) — architected for, not implemented. Decide before or after beta.
- AA TSP partner selection (Setu / Finvu / OneMoney).

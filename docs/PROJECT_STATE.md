# Project State

> **Update this file at the end of every session.** It is the first thing an agent reads after `CLAUDE.md`.

**Last updated:** 2026-08-08
**Current phase:** Phase 1 — Ingestion & Trust
**Overall status:** Phase 1 IN PROGRESS — core ingestion layer complete; integration tests complete; Phase 1 exit gate pending (acceptance checklist + docs + Dynamic Parser Builder design)

---

## Current phase: Phase 0 — Foundations

**Goal:** Establish the skeleton that everything else depends on — repo structure, local environment, database schema with the immutable/mutable split, event-log primitives, replay mechanism, and CI running the correctness harness.

**Exit criterion (must be demonstrably true to advance):**
> An event can be appended, a projection built from it, and a replay produces identical output. CI runs green on an empty golden dataset, **and all quality gates (G1–G15) run and publish a report on every push. Additionally: (a) adversarial review pass with all findings logged and resolved or explicitly deferred, (b) critical-module tests confirmed independently authored.**

### Task board

| # | Task | Status | Notes |
|---|---|---|---|
| 0.1 | Repo scaffolding + `CLAUDE.md` + docs structure | Done | This scaffolding |
| 0.2 | Docker local dev environment (Postgres + API + web) | Done | All 6 services up; wal_level=replica; /health 200 |
| 0.3 | Postgres schema: immutable event tables | Done | 8 tables, 4 triggers, 3 indexes, 0 float cols, mypy clean |
| 0.4 | Postgres schema: mutable settings tables | Not started | See TRD §3.2 |
| 0.5 | Event-log primitives (append, read stream) | Not started | Append-only enforcement at DB level |
| 0.6 | Projection builder + replay mechanism | Not started | Must be deterministic (invariant 3) |
| 0.7 | Idempotency hash implementation | Not started | See TRD §3.4 |
| 0.8 | CI pipeline + correctness harness skeleton | Not started | Golden dataset runner, empty to start |
| 0.9 | Synthetic fixture generator (basic) | Not started | Realistic-but-fake statements |
| 0.10 | CI pipeline with gates G1–G8 | Not started | See `docs/QUALITY.md` |
| 0.11 | Custom gates: real-data guard + migration check | Done | G14, G15 active; 13/13 unit tests pass; mypy --strict clean |
| 0.12 | Coverage tiering config + ratchet | Done | per-zone thresholds; ratchet prevents regression; baseline auto-updated |
| 0.13 | PR quality-report comment bot | Not started | Per-run visible reporting |
| 0.14 | Integration test harness (ephemeral Postgres) | Not started | See QUALITY.md §3.4 |
| 0.15 | Trend dashboard publishing | Done | publish.py + Chart.js viewer; trend-publish CI job (main-push only) |

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

## Current phase: Phase 1 — Ingestion & Trust

**Goal:** PDF bank statement → dry-run preview → user confirms → ledger events written. Nothing writes before Confirm.

**Exit criterion:** Synthetic PDF parses through dry-run harness, balance check passes, every parsed transaction appears in the preview, and `transaction_events` is empty until Confirm fires. All acceptance checklist items checked.

### Phase 1 task board

| # | Task | Status | Notes |
|---|---|---|---|
| 1.1 | Package scaffolding + base.py contracts | Done | ingestion/ structure, ParsedStatement, AbstractParser, DryRunSession |
| 1.2 | Balance-check validator (Wave 1A) | Done | independent test-authoring confirmed; 14 tests + 2 property tests pass |
| 1.3 | PDF fixture generator + HDFC CC + SBI CC golden fixtures (Wave 1B) | Done | fpdf2; synthetic PDFs committed |
| 1.4 | HDFC CC parser (Wave 2A) | Done | independent test-authoring; 16 tests; extract_tables() |
| 1.5 | SBI CC parser (Wave 2B) | Done | independent test-authoring; 15 tests; extract_tables() |
| 1.6 | pdf_reader.py + password handling (Wave 2C) | Done | PasswordRequiredError / PasswordIncorrectError; 7 unit tests |
| 1.7 | Dry-run harness + session store (Wave 3A) | Done | dry_run() → DryRunSession in Redis; zero DB writes; 12 tests |
| 1.8 | confirm.py + abandon.py (Wave 4A/4B/4C) | Done | independently authored; 14+3 tests; raw-artifact storage wired |
| 1.9 | FastAPI upload endpoint (Wave 5) | Done | POST /api/v1/statements/upload; 152 unit tests passing |
| 1.10 | HDFC Savings parser | Done | extract_words() + x-position bounding boxes; 15 tests; running_balance_paise non-None |
| 1.11 | SBI Savings parser | Done | extract_tables(); explicit opening balance; raises on missing; 15 tests |
| 1.12 | Slice Savings parser | Done | text-based; Rs./₹ both handled; apostrophe date; 15 tests |
| 1.13 | Integration: full pipeline (test_dryrun_full_pipeline.py) | Done | 6 tests; dry_run + confirm + abandon |
| 1.14 | Integration: idempotent ingest (test_idempotent_ingest.py) | Done | overlapping confirms → IntegrityError; genuine duplicate → occ_idx 0+1 |
| 1.15 | Integration: malformed input (test_malformed_input.py) | Done | garbage + empty bytes → zero DB rows |
| 1.16 | Integration: session expiry (test_session_expiry.py) | Done | real Redis TTL=1s; key-gone asserted before confirm; zero DB rows |
| 1.17 | Integration: password-protected (test_password_protected.py) | Done | pikepdf AES-128 in-memory fixture; correct/missing/wrong password |
| 1.18 | Docs update (SESSION_LOG + PROJECT_STATE) | Done | this update |
| 1.19 | Dynamic Parser Builder — design (TRD §9.2 + PRD §14) | Pending | spec-only; no implementation in Phase 1 |

### Phase 1 blockers
_None currently blocking Phase 1 tasks._

### Phase 1 key decisions
- **Five bank parsers** committed: HDFC CC, SBI CC, HDFC Savings, SBI Savings, Slice Savings. All call `compute_occurrence_index()` from shared module (F-1 gate confirmed).
- **Redis session store** for dry-run sessions (1-hour TTL); confirm/abandon are the only write paths to the DB.
- **pdf_reader.py password detection** uses `exc.__context__` inspection (pdfminer wraps `PDFPasswordIncorrect` with empty string in modern versions) with string-match fallback.
- **Savings parser column strategies**: HDFC Savings → `extract_words()` + x-position bounding boxes (text collapses whitespace); SBI Savings → `extract_tables()`; Slice Savings → text regex with `\S+` ref number (handles both numeric and alphanumeric refs in synthetic PDFs).
- **fpdf2 ₹ limitation**: Helvetica built-in font cannot render ₹ — synthetic PDFs use `Rs.`; all savings parsers handle both prefixes.

---

## Phase roadmap

| Phase | Name | Status | Exit criterion (short) |
|---|---|---|---|
| 0 | Foundations | **CLOSED** 2026-08-02 | Event append → projection → deterministic replay; CI green; adversarial review pass; independent test authorship confirmed |
| 1 | Ingestion & Trust | **IN PROGRESS** | Real statement parses via dry-run harness, balance check passes, writes nothing until confirmed |
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
| `read_since_seq` covers `transaction_events` only | Full projection replay requires events from all event tables (`ingestion_events`, `document_events`). Must be fixed before a complete rebuild can be trusted. | Open — Phase 4 blocker |
| Phase 0 critical-module tests not independently authored | Tests for `core/hashing/`, `core/events/`, `core/projections/` were co-authored with implementation (known gap). Re-authoring session needed before Phase 2 closes. | Open — Phase 2 gate requirement |

---

## Deferred decisions

- Specific LLM model routing per task — revisit once real volume/cost data exists.
- Per-user encryption keys (stricter isolation) — architected for, not implemented. Decide before or after beta.
- AA TSP partner selection (Setu / Finvu / OneMoney).

# Project State

> **Update this file at the end of every session.** It is the first thing an agent reads after `CLAUDE.md`.

**Last updated:** 2026-08-23
**Current phase:** Phase 3 — Day-to-Day Layer (backend, not started)
**Overall status:** 381 backend tests + 70 frontend tests (451 total). Phase 2.5 CLOSED 2026-08-23. Phase 3 is next.

---

## Phase 0 — Foundations [CLOSED 2026-08-02]

**Goal:** Establish the skeleton that everything else depends on — repo structure, local environment, database schema with the immutable/mutable split, event-log primitives, replay mechanism, and CI running the correctness harness.

**Exit criterion (must be demonstrably true to advance):**
> An event can be appended, a projection built from it, and a replay produces identical output. CI runs green on an empty golden dataset, **and all quality gates (G1–G15) run and publish a report on every push. Additionally: (a) adversarial review pass with all findings logged and resolved or explicitly deferred, (b) critical-module tests confirmed independently authored.**

### Task board

| # | Task | Status | Notes |
|---|---|---|---|
| 0.1 | Repo scaffolding + `CLAUDE.md` + docs structure | Done | This scaffolding |
| 0.2 | Docker local dev environment (Postgres + API + web) | Done | All 6 services up; wal_level=replica; /health 200 |
| 0.3 | Postgres schema: immutable event tables | Done | 8 tables, 4 triggers, 3 indexes, 0 float cols, mypy clean |
| 0.4 | Postgres schema: mutable settings tables | Done | migration 002_mutable.py |
| 0.5 | Event-log primitives (append, read stream) | Done | core/events/store.py |
| 0.6 | Projection builder + replay mechanism | Done | core/projections/builder.py |
| 0.7 | Idempotency hash implementation | Done | core/hashing/hash.py |
| 0.8 | CI pipeline + correctness harness skeleton | Done | .github/workflows/ci.yml |
| 0.9 | Synthetic fixture generator (basic) | Done | tests/fixtures/generator.py |
| 0.10 | CI pipeline with gates G1–G8 | Done | all gates active in ci.yml |
| 0.11 | Custom gates: real-data guard + migration check | Done | G14, G15 active; 13/13 unit tests pass; mypy --strict clean |
| 0.12 | Coverage tiering config + ratchet | Done | per-zone thresholds; ratchet prevents regression; baseline auto-updated |
| 0.13 | PR quality-report comment bot | Not started | Deferred to Phase 5 |
| 0.14 | Integration test harness (ephemeral Postgres) | Done | tests/integration/conftest.py (testcontainers) |
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
| Match-window tolerance calibration | Real statement data to tune | Phase 3 |
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

## Phase 1 — Ingestion & Trust [CLOSED 2026-08-13]

**Goal:** PDF bank statement → dry-run preview → user confirms → ledger events written. Nothing writes before Confirm.

**Exit criterion:** Synthetic PDF parses through dry-run harness, balance check passes, every parsed transaction appears in the preview, and `transaction_events` is empty until Confirm fires. All acceptance checklist items checked.

**Exit gate result:** 8/8 integration tests passed against real Docker testcontainers (Postgres + Redis). 212 unit + property tests passing. G18 parser-registration gate added. PR #4 open.

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
| 1 | Ingestion & Trust | **CLOSED** 2026-08-13 | Real statement parses via dry-run harness, balance check passes, writes nothing until confirmed |
| 2 | Ledger & Correctness | **CLOSED** 2026-08-14 | Overlapping statements ingested twice → zero double-counting, provable in audit view |
| **2.5** | **Frontend Foundation** | **CLOSED** 2026-08-23 | Audit view renders real Phase 2 data; CSS-variable token system established; 70 frontend + 381 backend tests green |
| 3 | Day-to-Day Layer | Not started | A full month tracked, budgeted; surplus reconciles against bank statement manually |
| **3.5** | **Day-to-Day UI** | **Not started** | All Expense-context screens (Home/7 dashboards, Transactions, Budgets, Categories, Accounts, Notifications, Settings) render real Phase 3 API data; every Journey 1/4 acceptance criterion met on screen |
| 4 | CA Layer | Not started | Full FY health report from real docs; every number traces to source. **CA review of tax rule-set required.** |
| **4.5** | **CA View UI** | **Not started** | All CA-context screens (Tax health, FY checklist, Advance-tax, Deductions, Capital gains, Income & TDS, Documents) render real Phase 4 API data; every CA journey acceptance criterion met on screen |
| 5 | Private Beta | Not started | A second user onboards end-to-end unaided; data isolation verified |

> **Parallelism note:** Phase 2.5 (`web/`) can run alongside Phase 3 (backend) — they touch different layers and have no compile-time dependency on each other. Phase 3.5 cannot start until Phase 3's API surface is real and tested.

---

## Phase 2.5 — Frontend Foundation [CLOSED 2026-08-23]

**Exit criterion met:** Audit view renders real Phase 2 data (overlap map, dedup ledger, resolver pairings, sync history). CSS-variable token system is the single source for all subsequent UI phases.

**Merge commit:** see SESSION_LOG Session 015 for commit SHA.

### Wave progress

| Wave | Name | Status | Notes |
|---|---|---|---|
| 1 | Scaffold — vitest, token CSS, `formatPaise` | Done | `1926e11`; 23 formatPaise tests |
| 2 | App shell — layout, two-context sidebar, shadcn/ui, placeholders, behavioral tests | Done | `a592262` + `154d1c7`; 19 shell tests (E1–E5) |
| 3 | Backend audit endpoints + pipeline fixes (B-1/B-2/B-3) | Done | `5f8399f`–`1eb470d`; 17 integration tests |
| 4 | Audit screen wiring (4 screens, A1–A6) + pre-wave cleanup | Done | `154d1c7`; 10 RTL tests |
| 5 | Phase 2.5 close: adversarial review + critical fixes | Done | this session; 2 CRITICALs fixed, 3 GAPs closed |

### Gate evidence

| Gate | Result |
|---|---|
| E1–E17 acceptance checklist | 17/17 PASS (with E10 gap resolved by Wave 5 critical fixes) |
| Backend tests | 381/381 pass (PITR Docker-only excluded, pre-existing) |
| Frontend tests | 70/70 pass |
| mypy | Clean — 0 issues |
| ruff lint + format | Clean |
| Adversarial review | CONDITIONAL PASS → CRITICALs fixed; 3 GAPs closed in Wave 5 |

### Adversarial review findings (resolved)

| Severity | Finding | Resolution |
|---|---|---|
| CRITICAL | Rejected IngestionEvents appeared in overlap-map + dedup back-references | Added `status != 'rejected'` filter to both queries; 2 integration tests added |
| CRITICAL | `run_resolver()` silent O(n) growth | Added `logger.warning` at 5,000-row threshold; standing risk updated |
| GAP | `rowStatus()`/`pairingLabel()` fallback untested | `web/lib/audit.test.ts` created (17 tests) |
| GAP | A6 CC drill-down malformed URL when cc_credit has no account_ref | Guard added in `pairings/page.tsx`; A6b RTL test added |
| GAP | FD booking + reversal never round-tripped through audit endpoints | `test_resolver_pairings_returns_fd_booking/reversal` added |
| GAP | Invariant 1 not verified at audit-endpoint layer | `test_dedup_ledger_no_double_count_after_confirmed_statement` added |
| GAP | Only 2/4 resolver event types tested end-to-end | Resolved by FD/Reversal tests above |
| GAP | Money large-value precision (> MAX_SAFE_INTEGER) | Deferred — acceptable given TypeScript BigInt types + runtime guard; track in Phase 3.5 |
| NOTATION | `_STUB_USER_ID` not tracked for Phase 5 migration | Added to standing risks below |

### Deviations from approved plan

**D-1** — Wave 2 initial commit `a592262` incomplete (shadcn/ui, CA routes, behavioral tests missing). Detected within-session; remediated in `154d1c7`.

**D-2/D-3** — B-1 (`event_type` casing), B-2 (resolver never wired), B-3 (cross-matcher double-claim): retroactive Phase 1/2 defects found and fixed in Wave 3. All in DECISIONS.md.

**D-4** — Backend endpoints (`processing/audit/`, `processing/accounts/`) were implicit in Phase 2.5 scope but not explicitly planned as Wave 3 deliverables.

**D-5** — `is_stalled` moved from frontend to backend computation (pre-Wave-4 cleanup).

**D-6** — Field renamed `ingestion_event_ids` → `covering_ingestion_event_ids`; Option B accepted; documented in known limitations.

---

## Open UI items (tracked here until each phase's kickoff moves them)

| Item | Deferred to | TRD ref |
|---|---|---|
| Audit API endpoints (overlap-map query, dedup-ledger, resolver-pairings) | Phase 2.5 wiring | TRD §15.5 |
| Empty states for every screen | Phase 3.5 | TRD §15.6 |
| Audit-view empty state (specifically flagged) | Phase 2.5 | TRD §15.6 |
| "Previous comparable period" rule per selector option (this-month→last-month is obvious; custom-range needs a rule before build) | Phase 3.5 kickoff | TRD §15.4 |
| Charting library selection (Recharts vs Chart.js; must theme from CSS-variable tokens) | Phase 3.5 kickoff | TRD §15.1 |

---

## Phase 2 — Ledger & Correctness [CLOSED 2026-08-14]

**Goal:** Overlapping statements ingested twice → zero double-counting, provable in an audit view.

**Exit criterion (testable checklist):**
- [x] `MarkedInternalTransfer`, `MarkedCCPayment`, `MarkedFDBooking`, `MarkedReversal` events exist in schema + migration
- [x] Resolver persists its pairings as events, never re-runs matching at projection time
- [x] Match window is a named config constant `CC_PAYMENT_MATCH_WINDOW_DAYS` (calibration risk tracked below)
- [x] Overlapping statements ingested twice → zero duplicate `TransactionIngested` events
- [x] Audit view: Level B (seen/counted ledger) passes for transfer overlap fixture. Level A (overlap map UI view) is partial — UniqueConstraint on `idempotency_hash` prevents double-ingestion at DB level, but a dedicated overlap-map query/view is not built yet. Deferred to Phase 3.
- [x] No transfer, CC-payment, FD-booking, or reversal appears in expense totals
- [x] F-9 closed: Phase 0 bugs A-3 + C-2 fixed; independently-authored tests pass

### Phase 2.5 retroactive defects [caught 2026-08-17/22]

Three defects in Phase 1/2 code were missed at Phase 2 close and caught during Phase 2.5
Wave 3. All are fixed in Phase 2.5 (`feature/phase2.5`). See DECISIONS.md B-1, B-2, B-3
for full writeup.

| ID | Module | What was broken | Fix |
|---|---|---|---|
| B-1 | `confirm.py` | `event_type="transaction_ingested"` (snake_case) — reducer expects PascalCase | Shared constants in `core/events/types.py` |
| B-2 | `confirm.py` + pipeline | Resolver matchers never wired into production path; payload missing reducer-required fields; no `account_type` for matcher routing | `pipeline.py` built; `confirm.py` payload expanded; `ParsedStatement.account_type` added |
| B-3 | `pipeline.py` | Transfer matcher and reversal matcher share overlapping criteria — savings↔savings pair claimed by both matchers, producing two conflicting resolver events | Cascading `claimed` set + explicit `_MATCHER_PRIORITY` tuple; reversal runs last |

Wave-diff gap that enabled B-1/B-2: Phase 2 integration tests bypassed `confirm.py` and
called `append_event()` directly with hand-crafted payloads. B-3 was latent in the matcher
design (overlapping criteria) and became live when `pipeline.py` was first built in Wave 3.

### Phase 2 follow-ups [2026-08-15]

Three scoped items completed before Phase 3 Wave 1:

| Item | Description | Status |
|---|---|---|
| E2 hardening | `test_reducer_does_not_import_matcher_modules` — AST import boundary test | Done |
| U2 property test | `test_invariant4_property.py` — Hypothesis test, Invariant 4, 200 examples | Done |
| Item 3 proof | Audit view duplicate-event: confirmed no bug; test added | Done |
| CI G1/G2/G3 | 30 pre-existing mypy errors fixed; ruff format + lint green | Done |
| U7 deferred | Audit API endpoints: decision deferred to Phase 3 planning | Deferred |

### Wave 0 — F-9 re-authoring [COMPLETE 2026-08-14]

10 tests written (6 CRITICALs + 4 prioritized GAPs). Results against current code:

| Test | File | Result | Verdict |
|---|---|---|---|
| A-2 field-boundary collision | test_hash.py | PASS | ✓ |
| A-3 float input rejected | test_hash.py | **FAIL** | Phase 0 bug |
| B-1 immutability enforcement | test_append_only_enforcement.py | Already existed — PASS | ✓ |
| B-2 crypto-shredding | test_key_lifecycle.py | PASS | ✓ |
| B-3 replay determinism (unit) | test_event_store.py | PASS | ✓ |
| B-4 global sequence | test_event_append_and_replay.py | PASS | ✓ |
| B-6 upcaster chain on read | test_event_store.py | PASS | ✓ |
| C-1 pure function determinism | test_projections.py | PASS | ✓ |
| C-2 corrupt snapshot handling | test_projections.py | **FAIL** | Phase 0 bug |
| C-3 decisions vs derivations | test_projections.py | PASS | ✓ |

**Phase 0 bugs confirmed:**
- **A-3**: `compute_idempotency_hash` accepts `float` without raising TypeError. `250.0` hashes as `"250.0"` (not `"250"`), silently producing a wrong hash. Fix: add `isinstance(amount_paise, int)` guard.
- **C-2**: `load_snapshot` returns `({}, last_seq)` for corrupt/unexpected data instead of `None`. A caller that receives `({}, 500)` skips events 0–500 and produces a wrong projection. Fix: return `None` in the `else` branch.

### Wave 0 — Tracked GAP debt (7 items)

Low-priority gaps from F-9 re-authoring, deferred to Phase 2 close or later:

| ID | Gap | Deferred to |
|---|---|---|
| A-1 | `canonicalize_narration` not tested on full NFKC compatibility decomposition (e.g. `ﬁ` → `fi`) | Phase 2 close |
| A-4 | `compute_occurrence_index` not tested when `amount_paise` is negative and canonical_narration has leading/trailing spaces (edge case for narrations that differ pre/post canonicalization) | Phase 2 close |
| A-5 | No property test asserting occurrence_index is always ≥ 0 and strictly sequential within group | Phase 2 close |
| A-6 | No test verifying `occurrence_index` uses canonicalized narration, not raw narration, for grouping | Phase 2 close |
| B-5 | No test that `read_since_seq` with `since_seq > 0` correctly excludes earlier events | Phase 2 close |
| C-4 | No test for snapshot round-trip (save → load → verify state matches) in integration | Phase 2 close |
| C-5 | No test that `rebuild_projection` saves a snapshot after full replay | Phase 2 close |

### Phase 2 blockers

| Blocker | Status |
|---|---|
| A-3 Phase 0 bug: float input not rejected | **FIXED** — `isinstance(amount_paise, int)` guard added to `compute_idempotency_hash` |
| C-2 Phase 0 bug: corrupt snapshot not detected | **FIXED** — `load_snapshot` returns `None` in else-branch; callers replay from seq 0 |

---

## Standing risks

| Risk | Mitigation | Status |
|---|---|---|
| Tax logic cannot be owner-verified | Engage a qualified CA to review the rule-set before Phase 4 closes | Open — not yet arranged |
| Gmail restricted-scope verification with Google is a long lead time | Start the application early; it gates Phase 5, not Phase 1 | Open — not started |
| AA TSP partner not selected | Blocks AA ingestion only; Gmail path is unblocked | Open — deferred |
| AI-written code drifting from spec | Golden dataset + invariant tests + spec-traceability rule in `CLAUDE.md` | Mitigated by design |
| `read_since_seq` covers `transaction_events` only | Full projection replay requires events from all event tables (`ingestion_events`, `document_events`). Must be fixed before a complete rebuild can be trusted. | Open — Phase 4 blocker |
| Phase 0 critical-module tests not independently authored | F-9: Re-authoring complete (2026-08-14). 10 new tests written; 2 Phase 0 bugs confirmed (A-3 float hash, C-2 corrupt snapshot). Both bugs fixed in Phase 2. | **CLOSED** — fixed A-3 + C-2; all independently-authored tests pass |
| Confidence formula constants not validated against real data | `CONFIDENCE_BASE_BP` (9000), `CONFIDENCE_SAME_DAY_BONUS_BP` (500), `CONFIDENCE_PER_DAY_PENALTY_BP` (200) are working assumptions in `config.py`. The formula produces scores that gate on `RESOLVER_CONFIDENCE_THRESHOLD` (8500), meaning 3-day matches (8400 bp) are rejected. Calibrate before live data ingestion. | Open — Phase 3 |
| Slice Savings ref-number regex not confirmed against real statements | `slice_savings.py` uses `\S+` for the ref-number column (spec said `\d{10,25}`). Changed to match synthetic alphanumeric fixtures; real Slice statements not sampled. **Do not trust with live Slice data until a real PDF is reviewed.** | Open — validate before Phase 2 Slice ingestion work |
| `SYNC_STALL_THRESHOLD_DAYS = 35` is uncalibrated | Set to 35 (one monthly cycle + grace window) in `backend/processing/audit/config.py`. Works for monthly-statement accounts; accounts with weekly or quarterly cadence need a cadence-aware detection strategy (D7). Calibrate against real usage before Phase 5. | Open — Phase 5 |
| `run_resolver()` re-scans all `TransactionIngested` rows on every call | No watermark — every `confirm()` call decrypts and re-processes every historical transaction for the user. Degrades linearly with statement history. Fix: add a `since_seq` watermark stored per-user (mutable settings table), skip rows already processed. Low-priority until user history is non-trivial. | Open — Phase 3 or 4 |
| `covering_ingestion_event_ids` is a period-covering approximation, not ground truth | **Explicitly accepted limitation (2026-08-23, Option B decision).** `DedupLedgerEntry.covering_ingestion_event_ids` is computed by matching all `IngestionEvent` rows for an account whose `period_start ≤ value_date ≤ period_end`. False-positive case: Statement B covers the period but its parse never emitted hash X — B still appears in the list. This is rare in practice (requires a partial/truncated re-upload, not a standard full-period re-export). Option A (record per-statement hash sets at confirm time via a join table) is the correct fix; deferred to Phase 3 when the full transaction query layer is built and a `statement_transactions` join table serves multiple purposes. Until then, the field is labeled `covering_ingestion_event_ids` (not `seen_by`) in both API and frontend to make the approximation honest. The raw artifacts are deleted on success — backfill is impossible. | Open — Phase 3 |
| `_STUB_USER_ID` hardwired in all API routers | `uuid("00000000-0000-0000-0000-000000000001")` appears in `processing/audit/router.py`, `processing/accounts/router.py`, and `ingestion/api/router.py`. Phase 5 auth (Google OAuth, TRD §T13) replaces these with a request-derived user_id. Grep `_STUB_USER_ID` for all 5 sites. | Open — Phase 5 |

---

## Known limitations

| Limitation | Details | Resolution |
|---|---|---|
| `covering_ingestion_event_ids` false positives | See Standing risks above. Field name is intentionally `covering_` not `seen_by` to signal approximation. | Phase 3 Option A implementation |

---

## Deferred decisions

- Specific LLM model routing per task — revisit once real volume/cost data exists.
- Per-user encryption keys (stricter isolation) — architected for, not implemented. Decide before or after beta.
- AA TSP partner selection (Setu / Finvu / OneMoney).

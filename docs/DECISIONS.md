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

---

## Retroactive defect B-1: event_type casing mismatch in confirm.py

**Caught:** 2026-08-17, Phase 2.5 Wave 3 pre-coding audit
**Phase introduced:** Phase 1 (confirm.py shipped in Wave 4A)
**Phase missed at close:** Phase 2 adversarial review

**What shipped broken:** `confirm.py` wrote `"transaction_ingested"` (snake_case) as the
`event_type` for every ingested transaction. The reducer in `reducer.py` branches on
`"TransactionIngested"` (PascalCase). The two strings never match — in production, replaying
real ingested data produces an empty `transactions` list. The integration tests for the
resolver pipeline bypassed `confirm.py` and called `append_event()` directly with the correct
casing, so the mismatch was invisible to CI.

**Fix:** Created `core/events/types.py` constants (`TRANSACTION_INGESTED`, `MARKED_*` etc.).
`confirm.py` now imports `TRANSACTION_INGESTED`; `reducer.py` imports all five constants.
`processing/resolver/events.py` drops its local `RESOLVER_EVENT_TYPES` and re-exports from
`core.events.types`. Regression test added:
`tests/unit/ingestion/test_confirm.py::test_confirm_pass_event_type_uses_transaction_ingested_constant`.

---

## Retroactive defect B-2: resolver pipeline was never wired into confirm.py

**Caught:** 2026-08-17, Phase 2.5 Wave 3 pre-coding audit
**Phase introduced:** Phase 2 (resolver matchers shipped in Waves 2A–2D)
**Phase missed at close:** Phase 2 adversarial review

**What shipped broken:** `find_matches()` (all four matchers) was never called in production
code. Phase 2 tests exercised each matcher in isolation, bypassing `confirm.py` entirely.
No production path existed that read ingested transactions, ran the matchers, and persisted
resolver events. The audit view endpoints (planned for Phase 2.5 Wave 3) also could not
return meaningful data since no resolver events would ever exist in the ledger.

**Additional payload gap (same cause):** `confirm.py` wrote only `{narration,
canonical_narration, occurrence_index}` to the encrypted `TransactionEvent.payload`. The
reducer reads `idempotency_hash`, `amount_paise`, `value_date`, `account_ref`, and
`transaction_type` from the payload — these were not written, so replay on real data would
raise `KeyError`. The integration tests that passed used `append_event()` directly with
full payloads, masking the gap.

**Fix:** (1) Built `processing/resolver/pipeline.py`: `run_resolver(session, user_id) → int`
— reads `TransactionIngested` rows, builds `CandidateTxn` list (using `account_type` from
payload), checks existing resolver event hashes for idempotency, runs all four matchers,
writes new resolver events with deterministic idempotency_hashes. (2) Added `account_type:
str` to `ParsedStatement`; all five parsers set it (`"credit_card"` for CC parsers,
`"savings"` for savings parsers). (3) `confirm.py` now includes all reducer-required fields
in the payload dict and calls `run_resolver()` after writing transaction events (TRD §2.3).
Integration tests: `tests/integration/test_confirm_resolver_wiring.py` (2 tests).

---

## Retroactive defect B-3: cross-matcher candidate claiming — savings transfer claimed as reversal

**Caught:** 2026-08-22, Phase 2.5 Wave 3 integration tests
**Phase introduced:** Phase 2 (matchers written in Waves 2A–2D) / Phase 2.5 (pipeline.py built)
**Phase missed at close:** Phase 2 adversarial review

**What shipped broken:** The reversal matcher (`reversal.py`) criteria overlap with the transfer matcher (`transfer.py`) criteria. Transfer: both legs `account_type == "savings"`, opposite signs, magnitudes equal. Reversal: both legs `same account_type`, opposite signs, magnitudes equal. A savings↔savings transfer pair satisfies *both* criteria simultaneously. The original `pipeline.py` (built in Phase 2.5 Wave 3) ran all four matchers against the same full candidates list with no cross-matcher coordination. Result: a single savings↔savings pair produced two resolver events — `MarkedInternalTransfer` and `MarkedReversal` — for the same two transaction hashes. The reducer applied both, leaving `exclusion_reason="reversal"` as the final state. The resolver-pairings endpoint returned 2 pairings where 1 was correct. The dedup ledger showed `exclusion_reason="reversal"` instead of `"internal_transfer"`.

**Root cause:** Reversal is intentionally a catch-all (same account_type, opposite sign, any account class). This is correct behavior for reversals — a savings credit reversing a savings debit is valid. But the same criteria are a superset of the transfer criteria. There is no structural fix to the reversal matcher's criteria; the fix must be in the pipeline's execution order.

**Was this in main?** `pipeline.py` did not exist in main before Phase 2.5. The four matchers existed in main with overlapping criteria, but nothing called them together, so the bug was latent (no execution path triggered it). The bug became live the moment `pipeline.py` was first constructed.

**Fix:** Cascading exclusion in `run_resolver()`. A `claimed` set is pre-populated from existing DB resolver event payloads (for idempotent re-run), then updated as each matcher writes events. Lower-priority matchers receive only `_available()` — the candidates not yet in `claimed`. Matcher priority is enforced by `_MATCHER_PRIORITY` tuple in `pipeline.py` (explicit, inspectable):

```python
_MATCHER_PRIORITY = (
    ("transfer", transfer),       # savings↔savings: most specific
    ("cc_payment", cc_payment),   # savings debit + credit_card credit
    ("fd_booking", fd_booking),   # savings debit + fd credit
    ("reversal", reversal),       # catch-all: same account_type, opposite sign
)
```

**Regression tests:** `tests/integration/test_audit_endpoints.py::test_resolver_pairings_returns_transfer_pair` (asserts exactly 1 pairing), `test_dedup_ledger_shows_transfer_pair_as_excluded` (asserts `exclusion_reason=="internal_transfer"`). Property test: `tests/property/processing/test_cross_matcher_priority.py` — Hypothesis, 200 examples, asserts no hash appears in >1 matcher's output.

---

## Retroactive defect B-4: `transaction_type` written as debit/credit, read as expense/income

**Caught:** 2026-10-30, Phase 3 Wave 5 closeout (while checking the refund decision against the code)
**Phase introduced:** Phase 2 / 2.5 (`confirm.py` payload expansion in the B-2 fix)
**Phase missed at close:** Phase 2.5 and Phase 3 Waves 3–4
**Severity:** CRITICAL for the Phase 3 gate. *(Defect series B-n; not the Phase 0 adversarial-review items that reuse B-4/B-5 in PROJECT_STATE.)*

**What shipped broken:** TRD §10.2 defines `transaction_type` as income/expense/transfer/investment, orthogonal to sign. `ingestion/dryrun/confirm.py:92` writes `"debit"`/`"credit"`, derived from the sign. The resolver reducer (`processing/resolver/reducer.py`) counts only `"expense"`/`"income"`, so the `transactions_view` `expense_paise`/`income_paise` totals are **always 0** on real ingested data, a silently wrong number. The nature tagger raises unless `transaction_type == "expense"`, so it rejects every real row.

**Why it was masked:** Phase 2 integration fixtures and the Wave 3 tagger tests were hand-built with `"expense"` and never went through the real parser. This is the same failure family as B-1/B-2.

**Decision (owner, 2026-10-30), ADR-021:** `transaction_type` is derived, not written at ingestion. The implementation plan is approved in Wave 6.
**Containment until fixed:** the Wave 5 reconciliation test is `xfail(strict=True)` citing B-4. No Phase 3.5 UI may wire to `transactions_view` totals until B-4 closes.
**Wave 6 exit criterion:** a fixture file goes through the real parser → ingest → resolver → classifier → nature tagger; totals are non-zero; Σ category net spend + uncategorized = `transactions_view` expense total. Tagger tests also run on real-parser output.

---

## Retroactive defect B-5: credit-card liability sign inverted

**Caught:** 2026-10-30, Phase 3 Wave 5 closeout
**Phase introduced:** Phase 3 Wave 4 (`processing/accounts/balance.py`)
**Phase missed at close:** Wave 4 gate
**Severity:** CRITICAL

**What shipped broken:** The CC parsers (`hdfc_cc.py`, `sbi_cc.py` `_parse_amount`) write Dr (purchase) as negative and Cr (payment) as positive, per TRD §10.2. `derive_cc_outstanding_liability` computed `max(0, Σ amounts)`, assuming spend is positive. On real data a card with ₹15,000 of purchases reports liability 0, and an overpaid card reports its credit surplus as a positive liability.

**Why it was masked:** the Wave 4 tests hand-built CC rows with spend positive, so the parser ↔ derivation sign contract was never exercised.

**Fix (Wave 5 closeout):** outstanding = −(signed anchored balance), unclamped (ADR-022). The sign convention is pinned by a contract test against all five parsers' golden output, and test rows come from the real-parser factory (ADR-024).

---

## Retroactive defect B-6: AC7 expected the wrong balance, and its exclusion wiring was never tested

**Caught:** 2026-10-30, Phase 3 Wave 5 closeout
**Phase introduced:** Phase 3 Wave 4 (`processing/accounts/crud_router.py`, AC7 tests)
**Phase missed at close:** Wave 4 gate
**Severity:** CRITICAL. Wave 4 stays open until it is fixed.

**What shipped broken:**
1. **Wrong expectation.** AC7 (defined only in SESSION_LOG:153, not in PRD/TRD) asserted that the savings balance excludes resolver-paired legs: ₹50k salary − ₹15k CC payment − ₹3.2k grocery gave "₹46,800 (not ₹31,800)". The statement closes at ₹31,800. Excluding legs from a balance breaks cash truth and Invariant 2.
2. **Exclusion wiring never matches.** `crud_router.py:175-186` built `excluded_hashes` from the resolver rows' own `idempotency_hash`. That hash is `sha256(event_type:sorted(h1,h2))` (`resolver/pipeline.py:63-66`); leg hashes live only in the encrypted payload. Nothing was ever excluded.
3. **Untested.** The AC7 tests hand-built `excluded = {HASH_B, HASH_D}` and called the pure derivation, so the query was never exercised.

**Fix (Wave 5 closeout):** balances include all legs, anchored to the statement closing balance (ADR-022). The resolver-row query is deleted. The single exclusion source is the resolver projection's `excluded_hashes`, consumed only by flow totals. AC7 is rewritten against real `append_event` rows: a savings debit matched to a CC credit via `MarkedCCPayment`, plus an own-account transfer whose combined net change is 0.

---

## Retroactive defect B-7: Wave 4/5 endpoints unreachable in production (unregistered routers, unmigrated column)

**Caught:** 2026-10-30, Phase 3 Wave 5 closeout
**Phase introduced:** Phase 3 Wave 4 (account CRUD + balance), Wave 5 (budgets)
**Phase missed at close:** Wave 4 gate
**Severity:** CRITICAL. Wave 4 stays open until it is closed.

**What shipped broken:**
1. **Routers never registered.** `processing/accounts/crud_router.py` (`/accounts` CRUD and `/accounts/{id}/balance`) and `processing/budgets/router.py` were never included in `main.py`, so every endpoint was unreachable. The OpenAPI drift check passed because the live app never had the routes.
2. **Column never migrated.** The Wave 4 ORM added `accounts.account_ref`, but no migration created it, so the first real `POST /accounts` fails with `UndefinedColumn`.

**Why it was masked:** all Wave 4 route tests built their own `FastAPI()` app with a mock DB session, so neither `main.py` nor the migrated schema was ever exercised.

**Fix (Wave 5 closeout):** both routers registered under `/api/v1` (2dd7a77). Migration `004_accounts_account_ref`. Regression guards:
- `tests/unit/test_route_registration.py`: expected paths are live and in the committed spec, and every `router` module under `processing/`/`ingestion/` is included. Verified to fail against the pre-fix `main.py`.
- `tests/integration/test_schema_matches_orm.py`: every ORM column exists after `alembic upgrade head`. Verified to fail without migration 004.
- `tests/integration/test_account_balance_route.py`: end-to-end through the registered routes with real `confirm()` rows.

**Not fixed (carry-forward):** the model comment says `account_ref` is "unique per user", but there is no constraint, so two accounts can share a ref. Decide in Wave 6.

---

## ADR-020: Budget utilization is signed net spend; refunds net in the month they post
**Status:** Accepted · **Date:** 2026-10-30
Net spend for (category, month) is −Σ signed amounts of non-excluded, hash-deduplicated transactions whose effective category is that category. It is unclamped and may be negative. A credit is a refund only if its effective category is an expense category; otherwise it is income. A refund nets in the month it posts. No refund-to-purchase matching and no rollover in V1. Contract: `derive_budget_utilization(transactions, excluded_hashes, category, month)` over typed frozen records (hash, signed amount, value_date, effective category). A thin edge adapter decrypts event rows into records, and effective category (correction → classifier → none) is a separate derivation.
**Why:** a clamp or a debits-only rule makes month sums disagree with the bank statement and the dashboard (Phase 3 exit criterion: totals reconcile). Allocating to the posting month keeps history immutable (B4). Typed records follow `build_learned_rules(correction_events)` and keep decryption at the edge. PRD §4.3.

## ADR-021: `transaction_type` is derived, never written at ingestion
**Status:** Accepted (design); implementation plan approved in Wave 6 · **Date:** 2026-10-30
Ingestion writes only the signed amount. Flow totals and the nature tagger's expense-only gate use sign < 0, not in `excluded_hashes`, and effective category. Any stored vocabulary lives once, in `core/events/types.py`.
**Why:** TRD §10.2 says the type is orthogonal to sign. Writing a sign-derived vocabulary at ingestion produced B-4. A derived type also cannot drift from the category decision that actually determines it.

## ADR-022: Resolver exclusion applies to flow totals, not balances; balances are statement-anchored and unclamped
**Status:** Accepted · **Date:** 2026-10-30
Exclusion (`excluded_hashes` from the resolver projection, the single source of truth) removes legs from spend, income and budget totals only. A savings balance = latest statement closing balance + Σ signed legs dated after that statement's period end. A card's outstanding liability = −(that signed balance), unclamped, where negative means a credit balance. With no anchor the value is `None`, never 0. Statement opening/closing balances are recorded in the `IngestionEvent` payload at confirm time (additive; older ingests carry no anchor and derive `None`).
**Why:** balances are cash truth and must reconcile to the statement (Invariant 2); PRD §8.1 says the liability updates on statement arrival and decreases on payment. A clamp hides real overpayments. `None` rather than 0 follows TRD §10.3.

## ADR-023: Resolver rows reference legs by payload hashes
**Status:** Accepted · **Date:** 2026-10-30
A resolver event keeps its own deterministic `idempotency_hash = sha256(event_type:sorted(h1,h2))`. The legs it pairs are named by the payload hashes (`debit_hash`/`credit_hash`, `savings_debit_hash`/`cc_credit_hash`, `savings_debit_hash`/`fd_credit_hash`, `original_hash`/`reversal_hash`), read by replay. No new table now. If a "resolvers touching this leg" lookup is ever needed, add a rebuildable `event_refs(event_id, ref_hash, role)` index, deferred until measured together with the `run_resolver` O(n) rescan.
**Why:** `idempotency_hash` is the stable identity across re-ingestion and rebuilds, while row ids and seq are not. Reusing a leg's hash on the resolver row would collide with `uq_transaction_events_user_idempotency_hash` and violate Invariant 1.

## ADR-024: Test rows come from real parser output
**Status:** Accepted · **Date:** 2026-10-30
A shared test factory builds transaction rows from real parser output through `append_event` (real signs, real payload vocabulary). A CI grep guard fails when transaction payloads are constructed by hand in tests outside the factory. The sign convention (debit negative, credit positive) is pinned by a contract test against all five parsers' golden output.
**Why:** B-1, B-2, B-4, B-5 and B-6 share one cause: hand-built fixtures encoded an assumption the real pipeline didn't satisfy, so CI was green on code that is wrong in production.

---

## Template

```markdown
## ADR-NNN: <title>
**Status:** Proposed | Accepted | Rejected | Superseded by ADR-NNN · **Date:** YYYY-MM
<decision in one or two sentences>
**Why:** <the reasoning that would otherwise have to be re-derived later>
```

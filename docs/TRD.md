# TRD: Expense & CA-Style Finance Health Tracker

**Status:** Draft v1 (foundations) - Owner: Sanket - Companion to the PRD. This document covers architecture, phase-wise execution, testing, and the AI-driven development method. Component-level specs (individual parsers, prompt schemas) are deferred to their own docs.

---

# 1. Locked Technical Decisions

| # | Decision | Choice | Rationale |
| --- | --- | --- | --- |
| T1 | V1 platform | Web app first, mobile later | Faster iteration, no app-store cycle during private beta |
| T2 | Audience | Small private beta (friends/devs) | Shapes scale targets: correctness over throughput |
| T3 | Frontend | TypeScript + Next.js/React | Mainstream, best-documented stack for AI codegen |
| T4 | Backend | Python (FastAPI) | Best ecosystem for PDF parsing, data work, LLM tooling |
| T5 | Database | Postgres, single shared instance | Real ACID guarantees; Notion is a docs tool, not a ledger |
| T6 | Data layer | Hybrid: immutable event log for ledger, mutable tables for settings | Audit trail (PRD 15) and FY rule-versioning (PRD 1.4) are impossible to do honestly on mutable rows |
| T7 | Tenancy | Shared DB, encrypted at rest + row-level isolation, architected so per-user keys can be added later | Standard posture now, stricter option not designed out |
| T8 | LLM provider | Provider-agnostic adapter layer; model is config, not code | Cost/quality optimization becomes a dial to turn with real usage data, not a lock-in decision made blind |
| T9 | Test data | Synthetic for automated regression; owner's real data for beta | Real statements cannot live in a repo; synthetic fixtures can |
| T10 | Priority order | Correctness > clean architecture > low cost > speed | Explicitly ranked by owner. Justifies golden datasets, balance-check gates, immutable ledger |
| T11 | Environments | Local dev (Docker) + simple cloud staging | No production tier until beta proves correctness |
| T12 | Timeline model | Phase-gated by working software, not calendar dates | Follows directly from T10 |

---

# 2. Architecture Overview

## 2.1 Layered design

```
[ Sources ]  Gmail-PDF | AA | Slack | Manual upload | Broker CAS
     |
     v
[ Ingestion Layer ]  fetchers -> parsers -> validators
     |  (raw artifacts stored immutably, never discarded)
     v
[ Event Log ]  append-only, the single source of truth
     |
     v
[ Processing Pipeline ]  resolver -> normalizer -> classifier
     |  (each step appends new events, mutates nothing)
     v
[ Projections ]  budgets | CA view | net worth | audit | analytics
     |
     v
[ API (FastAPI) ]  ->  [ Web UI (Next.js) ]
```

**Key property:** every projection is derived from the event log and can be rebuilt from scratch at any time. If a categorization bug is found, fix the classifier and replay - no data migration, no lost history.

## 2.2 Why event-sourcing here specifically

Three PRD requirements make this non-optional rather than architectural taste:

- **Audit trail (PRD 15):** "was this counted twice, where did this number come from" requires the full history of what entered and why.
- **FY tax-rule versioning (PRD 1.4):** last year's report must not silently recompute under this year's rules. Projections are computed against a pinned rule-set version.
- **De-duplication (PRD 7):** seen-vs-counted logic needs a record of every sighting, not just the surviving row.

## 2.3 Processing pipeline order (from PRD 4.1, restated as a hard constraint)

1. Ingest and store the raw artifact.
2. Parse to structured transactions, validate (balance check).
3. **Relationship resolver** - transfers, CC payments, FD bookings.
4. Merchant normalization.
5. Category classification.
6. Nature tagging (essential/discretionary/luxury).

Steps 3 must precede 5. Reordering silently corrupts budget totals. This ordering is enforced in code and asserted in tests.

---

# 3. Data Model

## 3.1 Immutable (event log)

Append-only. Never updated, never deleted.

- `ingestion_events` - every sync/upload/Slack entry (PRD 15.1 fields: source, period_covered, counts, balance_check, confidence, status).
- `raw_artifacts` - original PDFs/payloads, content-addressed, retained for re-parsing.
- `transaction_events` - `TransactionIngested`, `CategoryAssigned`, `CategoryCorrected`, `MarkedInternalTransfer`, `MarkedDuplicate`, `NatureTagged`. Each carries actor (system/user/AI), timestamp, and the `ingestion_event_id` that produced it.
- `document_events` - Form 16 / CAS / AIS uploads and their parse results.

## 3.2 Mutable (current-state tables)

Overwritable; history genuinely doesn't matter.

- `users`, `accounts` (nicknames, sync status), `budgets` (targets per category per month), `category_overrides` (per-user merchant mappings), `settings`, `statement_credentials` (encrypted).

## 3.3 Projections (derived, rebuildable)

- `transactions_current` - the flattened current view, rebuilt by replay.
- `budget_status`, `ca_view_fy`, `net_worth_snapshots`, `audit_view`, `dedup_ledger`.

All projections are disposable by design. A projection bug is fixed by correcting code and replaying, never by patching data.

## 3.4 The idempotency hash

`hash(account_ref + date + amount + narration + running_balance)` - computed at ingestion, stored on the event. Powers the seen-vs-counted dedup ledger (PRD 15.2). Same hash seen twice, counted once = correct. Counted twice = a bug the audit view surfaces.

---

# 4. AI-Driven Development Method

All four modes from the PRD discussion are in scope: AI writes most code, AI features ship in-product, AI generates tests, and the build is spec-driven from PRD + TRD.

## 4.1 Spec-driven workflow

The PRD and TRD are the source of truth an AI agent builds from. To make that work, specs must be machine-actionable:

- Every feature in the Feature Version Tracker maps to a PRD section and a version. That mapping is the work queue.
- Each build task is expressed as: **spec reference + acceptance criteria + test fixtures**. An agent that cannot find all three should stop and ask, not guess.
- Ambiguity in the spec is a bug in the spec. When an agent has to invent a rule (a tax threshold, a matching window), that decision gets written back into the PRD rather than buried in code.

## 4.2 Repository conventions that make AI codegen reliable

- **A `CLAUDE.md` (or equivalent agent-context file) at repo root** holding: the pipeline ordering constraint, the immutable/mutable split, naming conventions, and the correctness-first principle. Agents read this before touching code.
- **Strict typing everywhere** - TypeScript strict mode, Python type hints + Pydantic models. Types are the cheapest specification an agent can't misread.
- **Small, well-named modules** with single responsibilities. Agents perform far better on focused files than sprawling ones.
- **Every module has a docstring stating its contract** and which PRD section it implements.

## 4.3 The correctness harness (non-negotiable, given T10)

AI-written code needs mechanical verification, not review-by-vibes:

- **Golden datasets** - synthetic statements with known-correct expected output. Every parser and pipeline change runs against them. A diff is a failure.
- **Balance-check invariant** - opening + credits - debits = closing, asserted on every parsed statement (PRD 14.2). This catches parser regressions automatically without a human reading rows.
- **Property-based tests** for the resolver and dedup logic - e.g. "no transaction hash is ever counted more than once," "a matched transfer pair never appears in expense totals." These catch classes of bugs, not instances.
- **Replay determinism test** - replaying the same event log twice must produce byte-identical projections.

## 4.4 In-product AI (the features themselves)

- **Adapter layer (T8):** one interface, swappable models. Routing by task: high-volume/low-stakes (categorization) to cheap models; low-volume/high-stakes (unmatched PDF layouts) to stronger ones.
- **Structured output only** - every LLM call returns a strict schema (Pydantic-validated). Free-text responses are never parsed downstream.
- **Confidence gates** - below threshold, output goes to a review queue, never silently into the ledger (PRD 4.1, 14.4).
- **Deterministic-first** - rules and template parsers run before any LLM call. The LLM is a fallback for the long tail, not the default path. Cheaper, faster, and more testable.
- **Prompt versioning** - prompts live in version control with their own golden test cases, treated as code.

## 4.5 AI-generated testing

- AI generates synthetic statement fixtures across bank layouts, edge cases (partial months, overlapping periods, refunds, reversals, failed transactions), and adversarial cases (duplicate narrations, same-amount same-day pairs).
- AI generates test cases from PRD acceptance criteria directly - a spec sentence becomes an assertion.
- Human (owner) review is reserved for **tax logic correctness** specifically, since that's where an AI mistake is both most likely and most damaging, and where the owner has stated they cannot second-opinion. This is the argued case for a real CA reviewing the tax rule-set before beta.

---

# 5. Phase-Wise Execution

Phases are gated by working, verified software - not dates (T12). Each phase has an exit criterion that must be demonstrably true before the next begins.

## Phase 0 - Foundations

**Build:** repo scaffolding, `CLAUDE.md` agent context, Docker local env, Postgres schema (immutable + mutable split), event-log primitives, replay mechanism, CI with the correctness harness skeleton.

**Exit criterion:** an event can be appended, a projection built from it, and a replay produces identical output. CI runs green on an empty golden dataset.

## Phase 1 - Ingestion & Trust

**Build:** Gmail-PDF fetcher, statement parser (2-3 real bank templates), balance-check validator, the **dry-run harness** (PRD 14.3), raw-artifact storage, ingestion audit events.

**Exit criterion:** a real statement PDF parses through the dry-run harness with a passing balance check, produces a preview table matching the source document, and writes nothing to the ledger until confirmed. This is the phase that proves the whole approach - if parsing isn't trustworthy, nothing downstream matters.

## Phase 2 - Ledger & Correctness

**Build:** relationship resolver (transfers, CC payments, FD), idempotency/dedup logic, dedup ledger projection, audit trail view (PRD 15).

**Exit criterion:** overlapping statements ingested twice produce zero double-counting, demonstrably, in the audit view. Property tests for the resolver pass.

## Phase 3 - Day-to-Day Layer

**Build:** categorization (rules-based for V1), budgets, dashboard (PRD 12.1), account management (PRD 13), export, month/FY toggle.

**Exit criterion:** a full month of real transactions is tracked, categorized, budgeted, and the surplus number reconciles against the bank statement manually.

## Phase 4 - CA Layer

**Build:** income summary, deductions, assets/liabilities, regime comparison, FY completeness checklist. Rules-based, upload-driven (per V1 scope).

**Exit criterion:** a full FY health report generates from real uploaded documents, and every number traces to its source via the audit trail. **Tax rule-set reviewed by a qualified CA before this phase closes.**

## Phase 5 - Private Beta

**Build:** cloud staging deploy, auth, per-user isolation verification, onboarding flow, Slack cash bot.

**Exit criterion:** a second beta user completes onboarding end-to-end without the owner intervening, and their data is verifiably isolated.

---

# 6. Testing Strategy

## 6.1 Test pyramid, correctness-weighted

| Layer | What it covers | Data |
| --- | --- | --- |
| Unit | Parsers, resolver rules, tax computations, hash logic | Synthetic fixtures |
| Property-based | Dedup invariants, resolver pairing, replay determinism | Generated |
| Golden dataset | End-to-end statement -> ledger -> projection | Synthetic statements, known-correct output |
| Integration | Gmail fetch -> parse -> event -> projection | Mocked Gmail, synthetic PDFs |
| Manual/exploratory | Tax logic sanity, UI | Owner's real data (beta only) |

## 6.2 The invariants that must never break

These are asserted continuously, not tested once:

1. No transaction hash is counted more than once.
2. Statement balance check passes, or the parse is rejected and logged.
3. Replaying the event log is deterministic.
4. A matched internal-transfer pair never appears in expense totals.
5. A projection for a closed FY never changes when tax rules update.
6. Nothing enters the ledger below the confidence threshold without explicit user confirmation.

## 6.3 Regression policy

Every bug found in real data becomes a synthetic fixture in the golden dataset before it is fixed. The dataset only grows. This is how an AI-written codebase stays trustworthy over time without a human re-reading everything.

## 6.4 Data handling in tests

- Synthetic fixtures only in the repository. No real statements, ever.
- Owner's real data used locally and in beta, never committed, never in CI.
- A fixture generator produces realistic-but-fake statements from templates, so coverage grows without privacy exposure.

---

# 7. Open Technical Questions (deferred, not blocking Phase 0)

- [ ]  AA TSP partner selection (Setu/Finvu/OneMoney) - blocks AA ingestion, not Gmail path.
- [ ]  Gmail restricted-scope verification timeline with Google - start early, it gates Phase 5.
- [ ]  Specific model routing per task, once real volume/cost data exists.
- [ ]  Whether per-user encryption keys (T7 stricter option) are needed before beta or after.
- [ ]  CA reviewer engagement for tax rule-set validation - needed before Phase 4 closes.

---

# 8. Journey-Derived Technical Decisions

Added after the user-journey walkthrough (see "User Stories & Journeys" §16–18). These supersede conflicting text earlier in this document.

## 8.1 New locked decisions

| # | Decision | Choice | Rationale |
| --- | --- | --- | --- |
| T13 | Authentication | **Google OAuth only** (V1 beta) | One consent flow covers both identity and Gmail statement access — auth and ingestion permission collapse into a single step |
| T14 | Access control | **Invite-only email allowlist** | Owner maintains the list; no open signup during beta |
| T15 | Tenant isolation | **Strict — owner cannot read beta users' data**, even for debugging | Debugging relies on logs, error reports, and synthetic reproduction. Enforced at the query layer, not just the API |
| T16 | Transaction type | **First-class field**: `income \ | expense \ |
| T17 | Notification service | **Two-tier**: Tier 1 alerts (mandatory) + Tier 2 milestones (opt-in, off by default), delivered via Slack and/or email | Failure can never hide; routine noise stays off by default |
| T18 | Deduction detection | **Hybrid**: curated merchant→section table, LLM for unknowns, user confirms both | Tax logic stays mostly deterministic; LLM handles the long tail but never auto-commits |
| T19 | Gmail discovery | **LLM-based scan** rather than a hardcoded sender list | Generalizes to banks not on any curated list; account matching decides append-vs-new-account |
| T20 | Backfill bound | **Maximum 2 previous financial years** | Bounds cost and scan time; deeper history is out of scope |

## 8.2 Invariant 5 — restated

**Previous wording:** a closed FY's projection never changes when tax rules update.

**New wording:**

> A closed financial year's projection never changes **silently**. Rule-sets remain version-pinned per FY. Amendments (e.g. a genuine category correction touching a closed FY) are permitted, but require explicit user confirmation, are recorded as amendment events, and preserve the original. A FY closes automatically once its ITR filing deadline passes.
> 

**Why it changed:** the original wording made a legitimate correction impossible. A user recategorizing a merchant retroactively may genuinely touch a closed year — blocking that means the ledger stays knowingly wrong. The amendment model preserves reproducibility (original retained, change is an event) without freezing out corrections.

**Implementation consequence:** the FY-versioned rule-set must carry that FY's ITR filing deadline, since the date varies year to year and is sometimes extended.

## 8.3 Data model additions

### New event types

- `TransactionAmended` — a change touching a closed FY. Carries the original value, the new value, the reason, and explicit user confirmation.
- `DeductionTagged` / `DeductionUntagged` — links a transaction to a tax section.
- `MerchantSectionMappingLearned` — user's answer to "is this health or motor insurance?", applied to that merchant thereafter.
- `NotificationSent` — for audit and to prevent duplicate alerts.

### Field additions

- `transaction_type` on every transaction (T16). **Nature tags apply only where type = `expense`.**
- `deduction_section` (nullable) — the tax section a transaction is claimed under.
- `confidence` on classification and deduction-detection events.

### New mutable tables

- `merchant_section_map` — per-user merchant→tax-section learned mappings (mirrors the existing `category_overrides` pattern).
- `notification_preferences` — channel selection plus per-event Tier 2 toggles.
- `invite_allowlist` — permitted beta emails.

## 8.4 New components

| Component | Module | Notes |
| --- | --- | --- |
| Notification service | `backend/notifications/` | Two-tier routing, Slack + email adapters, dedupe via `NotificationSent` |
| Merchant→section resolver | `processing/deductions/` | Table lookup first, LLM fallback, always user-confirmed |
| Gmail LLM discovery | `ingestion/fetchers/gmail/discovery/` | Identifies bank/card from email content; matches to existing account or triggers new-account flow |
| Amendment handler | `core/events/amendments/` | Enforces closed-FY confirmation rules |
| Auth / allowlist | `backend/auth/` | Google OAuth, invite allowlist, session management |

Dependency rules from `CODE_GRAPH.md` still apply: no vendor LLM SDK outside `adapters/llm/`, and `notifications/` depends on `domain/`, never the reverse.

## 8.5 Phase impacts

- **Phase 0** — schema must now include `transaction_type`, the amendment event type, and the three new mutable tables. Cheaper to include now than to migrate later.
- **Phase 1** — dry-run confirmation is **first statement per account only**, then auto-trust; re-triggered whenever confidence drops below threshold. Failure prompts are reason-specific (password / parse failure / filter hint / sample PDF request), not one generic error.
- **Phase 2** — resolver must emit `transaction_type` rather than an exclusion flag. Notification service Tier 1 lands here alongside the audit trail.
- **Phase 4** — deduction detection needs the merchant→section table seeded before the CA view is meaningful. **CA review of both the tax rule-set and the seed mapping table is a Phase 4 exit condition.**
- **Phase 5** — auth, allowlist, and isolation verification (T13–T15) are Phase 5 blockers and now have specified answers.

## 8.6 Testing additions

New invariants to assert:

- A transaction of type `transfer` or `investment` never appears in expense totals.
- Nature tags exist only on transactions of type `expense`.
- A Tier 1 alert always fires when its condition is met, regardless of user preferences.
- An amendment to a closed FY never occurs without a recorded confirmation event.
- The original value is always recoverable after an amendment.
- No user can read another user's rows — asserted at the query layer, including for the owner account.

[Architecture & Schema Review — TRD Critique](https://app.notion.com/p/Architecture-Schema-Review-TRD-Critique-3a6188e1a103816199d9dd5326cf1fe1?pvs=21)

---

# 9. Architecture Review Resolutions

All findings from the Architecture & Schema Review are now closed. These are binding and supersede conflicting text earlier in this document.

## 9.1 Critical fixes (schema-level — must land in Phase 0)

| # | Resolution |
| --- | --- |
| **C1** | **Idempotency hash redesigned.** New definition: `hash(account_ref + value_date + amount + normalized_narration + occurrence_index)`. `running_balance` is **removed from identity** and used only as a validation signal feeding the balance check. |
| **C2** | **`occurrence_index` added** — the ordinal of a transaction within its (account, date, amount, narration) group as it appears in the source statement. Deterministic per source; correctly distinguishes two genuine ₹250 coffees from one re-ingested duplicate. |
| **C3** | **Resolver outcomes are recorded events, never recomputation.** `MarkedInternalTransfer` (and equivalents for CC payment / FD booking) are authoritative. Replay reads recorded pairings; it never re-derives them. Re-running the resolver over new data emits *new* events — it never rewrites history. **This is the single most important fix: it is what makes Invariant 3 true.** |
| **C4** | **`event_version` on every event from day one**, plus an upcaster layer in `core/events/`. Upcasters are pure functions with their own golden tests and are never deleted. |
| **C5** | **Money stored as integer paise (`BIGINT`) end to end.** Python `int`, TypeScript `bigint` or string, never float, never `NUMERIC` in transport. Rupee formatting happens only at render. **Enforced by a lint rule** — an AI-generated codebase will otherwise reintroduce floats. |
| **H7** | **Global monotonic sequence number** on the event log (`BIGSERIAL`). Replay is strictly ordered by it. Optimistic concurrency on per-aggregate streams. |

## 9.2 The projection/decision boundary (paradigm fix)

C3 exposed a deeper ambiguity, now resolved as a standing architectural rule:

> **Anything involving an LLM, or a lookup whose result depends on what data existed at the time, is a DECISION and must be recorded as an event. Anything purely arithmetic over recorded facts is a DERIVATION and may be recomputed freely.**
> 
- **Decisions (recorded):** resolver pairings, LLM category classification, deduction-section detection, confidence scores, merchant normalization results.
- **Derivations (recomputed):** budget totals, net worth, running cost splits, FY aggregates, allocation percentages.

This rule belongs in `CLAUDE.md` and must be asserted in review — it is the difference between replay being trustworthy and replay being theatre.

## 9.3 Data lifecycle

| # | Resolution |
| --- | --- |
| **H2** | **Crypto-shredding with recoverable keys.** Per-user encryption of event payloads; "deletion" destroys the active key. Old keys are **retained in cold storage**, so recovery is possible and a new key is issued if the user returns. **Consequence for UI copy: the product must say "account deactivated", never "data deleted"** — the claim would otherwise be untrue. |
| **M1** | **Raw artifacts: discard successful parses, retain failures.** Once a statement parses cleanly and the user confirms, the source PDF is discarded. Failed parses are retained for debugging and golden-fixture creation. Trade-off accepted: a subtly-wrong-but-balance-passing parse cannot be re-parsed and requires user re-upload. |
| **M9** | **Point-in-time recovery (PITR).** Rationale: bank statements are re-fetchable from Gmail, but user corrections, category overrides, merchant mappings, confirmations, and amendments are irreplaceable. Since projections derive from the event log, losing the log loses everything. On managed Postgres this is configuration, not build. **A restore must be tested — an untested backup is not a backup.** |

## 9.4 Infrastructure

| # | Resolution |
| --- | --- |
| **H1** | **Projection snapshots every N events (starting N=1000).** Predictable read performance. Snapshots are derived and disposable — a corrupt snapshot is discarded and rebuilt from zero. |
| **H3** | **Beta: env vars / secret file.** Accepted as sufficient for private beta. **Upgrade to managed KMS before the beta expands beyond trusted users** — noted as a Phase 5 item, not a Phase 0 blocker. Interacts with H2: because old keys are retained, that key material is long-lived and more sensitive than a rotating secret. |
| **H5** | **Celery + Redis.** Powers silent sync retries with backoff, 24h Slack auto-confirm, periodic Gmail scans, overdue-document checks, and notification dispatch. Added to Phase 0 — retrofitting async execution into a synchronous codebase is a rewrite, not an addition. |
| **M6** | **LLM budget ceiling: alert + pause + queue.** On hitting a limit: alert the owner, pause processing, queue outstanding work, resume automatically when the budget window resets. Never silently overspend, never silently drop work. |
| **M2** | **Projection rebuilds use a shadow table with atomic swap.** No downtime during rebuild. |
| **M10** | **Index strategy defined during Phase 0 schema design** for known access paths: account + date range, hash lookup, FY filters, event-sequence scans. |

## 9.5 Correctness & semantics

| # | Resolution |
| --- | --- |
| **H4** | **Timestamps stored in UTC; all FY, statement-period, and matching-window logic executed in IST.** A property test must assert correct FY assignment for transactions within one hour of the 31 March boundary. |
| **H6** | **The 2-FY backfill cap (T20) applies to transaction ingestion only.** Cost-basis documents — CAS, purchase deeds, ESOP exercise statements — are ingestible with **no date limit** via explicit upload. Without this, long-term capital gains could never compute correctly for older holdings. |
| **M3** | **Tax rule-sets stored as versioned data (JSON/YAML)** with a pure evaluator, not as code. Enables CA review without reading source — which matters directly, since the owner cannot self-verify tax logic and external review is a Phase 4 exit condition. |
| **M4** | **Reversals modelled explicitly** via `reverses_transaction_id`. Both legs excluded from spend totals. |
| **M5** | **Foreign-currency transactions: INR is canonical**, with original currency, original amount, and markup retained as metadata. This is not multi-currency support (still out of scope) — it is simply not discarding data the statement gives us. |
| **M7** | **Golden tests compare normalized semantic structure, not bytes.** Byte comparison would break every test on any formatting change, training people to bulk-update expectations — which defeats the purpose. |
| **M8** | **Notification aggregation and throttling.** 40 failed statements produce one message ("6 statements failed to parse"), not 40. Prevents alert storms driving users to disable Tier 1 notifications, which are meant to be mandatory. |

## 9.6 Phase 0 scope impact

The following are now Phase 0 tasks, because they are schema-level or foundational and cost materially more to retrofit:

- Idempotency hash + `occurrence_index` (C1, C2)
- `event_version` + upcaster scaffolding (C4)
- Integer-paise money handling + lint rule (C5)
- Global sequence number (H7)
- Resolver-as-event modelling (C3) — design decision baked into the event schema
- Index strategy (M10)
- Celery + Redis (H5)
- PITR configuration + a tested restore (M9)
- Timezone policy + boundary property test (H4)
- Per-user encryption envelope for crypto-shredding (H2)

## 9.7 Still open

| Item | Needs | When |
| --- | --- | --- |
| Managed KMS migration | Decision once beta expands | Phase 5 |
| Snapshot interval tuning (N=1000 is a starting guess) | Real volume data | Phase 3+ |
| LLM budget thresholds | Real usage/cost data | Phase 2+ |
| Match-window tolerance | Real statement data | Phase 2 |

---

# 10. Money & Numeric Types

C5 established "money as integer paise" for transaction amounts. That is necessary but insufficient — a finance product handles several *different* numeric quantities with different precision requirements, and conflating them is a classic source of silent corruption.

## 10.1 Type taxonomy

Every numeric quantity is a scaled integer. **No floats anywhere, at any layer.**

| Quantity | Storage | Scale | Example |
| --- | --- | --- | --- |
| Transaction amount | `BIGINT` | paise (10⁻²) | ₹1,234.56 → `123456` |
| Account balance | `BIGINT` | paise | ₹42,150.00 → `4215000` |
| Mutual fund NAV | `BIGINT` | 10⁻⁴ | 45.6789 → `456789` |
| MF / stock units held | `BIGINT` | 10⁻⁴ | 123.4567 units → `1234567` |
| Tax rate | `INTEGER` | basis points | 12.5% → `1250` |
| Interest rate | `INTEGER` | basis points | 8.75% → `875` |
| FX rate | `BIGINT` | 10⁻⁶ | 83.452100 → `83452100` |
| Allocation / percentage | `INTEGER` | basis points | 27.5% → `2750` |

**Why NAV and units need 4 decimals:** mutual fund NAVs are published to 4 decimal places and unit holdings are fractional. Storing these as paise (2dp) silently truncates, and the error compounds across every valuation and every capital-gains computation.

**Range check:** `BIGINT` max ≈ 9.2 × 10¹⁸. In paise that is ≈ ₹92 trillion. No overflow risk.

## 10.2 Sign convention

**Amounts are signed. Debits negative, credits positive.** One field, arithmetic just works, sums are trivially correct.

- Do **not** store an unsigned amount plus a separate direction flag — that invites code paths that forget to apply the sign.
- UI displays `abs(amount)` with the direction shown visually.
- `transaction_type` (income/expense/transfer/investment) is orthogonal to sign and does not encode it.

## 10.3 NULL versus zero — a correctness rule, not a style choice

> **`NULL` means unknown. `0` means genuinely zero. They must never be conflated.**
> 

This directly serves the correctness-first principle. An ESOP lot with no exercise-date FMV has cost basis `NULL`, **never** `0` — because `0` would silently compute a fictitious 100% gain and report it as fact.

- Columns where "unknown" is a valid state (cost basis, NAV for unlisted holdings, FMV) are nullable.
- Any aggregate encountering `NULL` must **exclude it and flag the exclusion**, never coerce to zero.
- Property test: no aggregate silently substitutes 0 for NULL.

## 10.4 Rounding rules

| Context | Rule |
| --- | --- |
| Transaction amounts | **No rounding.** The source value is authoritative. |
| Intermediate calculations (EMI amortization, interest accrual, proportional allocation) | Compute in `Decimal` with generous precision; round **only at the boundary** when persisting or displaying. |
| Persisting a computed money value | Round half-up to the nearest paisa. |
| Total income (tax computation) | Round to the nearest ₹10 — **Section 288A**. |
| Tax payable / refund | Round to the nearest ₹10 — **Section 288B**. |
| Splitting an amount across N buckets | **Largest-remainder method.** The parts must sum exactly to the original — never let rounding create or destroy paise. |

Sections 288A/288B are statutory rounding rules, not preferences. They live in the versioned tax rule-set (M3) alongside rates and thresholds, so a CA can verify them without reading code.

## 10.5 Transport and serialization

**JSON is the highest-risk boundary.** `JSON.parse` produces IEEE-754 doubles, so a backend that stores money correctly can still have the frontend corrupt it.

- **Serialize all monetary and scaled-integer values as strings** in JSON, never as JSON numbers.
- TypeScript parses them to `bigint` or keeps them as strings; **never** to `number`.
- Rupee formatting happens only at render, from the string/bigint — never from an intermediate float.

Realistic paise values sit well inside JS's safe-integer range, so this is belt-and-braces — but it eliminates an entire bug class for near-zero cost, and an AI-generated codebase will otherwise drift back to `number` by default.

## 10.6 Foreign currency (per M5)

INR remains canonical. Original-currency data is retained as metadata, and **the scale differs by currency** — USD/EUR use 2 decimals, JPY uses 0, KWD/BHD use 3. Store `original_currency` (ISO 4217), `original_amount` as a scaled integer, and `currency_scale` explicitly, so the value is interpretable without a hardcoded assumption.

## 10.7 Display formatting

Indian numbering is not Western grouping. ₹12,34,567.89 — lakh/crore placement, not `1,234,567.89`. This is a rendering concern only; it must never influence storage or computation.

## 10.8 Enforcement

Because this is an AI-generated codebase, these rules need mechanical enforcement rather than review discipline:

- **Lint rule:** ban `float` type hints and float literals in any module under `core/`, `processing/`, or `domain/`.
- **Custom types:** a `Paise` newtype in Python and a branded type in TypeScript, so a raw `int` cannot be passed where money is expected.
- **DB constraint:** money columns are `BIGINT`; `NUMERIC`/`REAL`/`DOUBLE PRECISION` are prohibited by a migration check (extending gate G15).
- **Property tests:**
    - round-trip through JSON preserves exact value
    - largest-remainder splits always sum to the original
    - no aggregate substitutes 0 for NULL
    - 288A/288B rounding matches worked examples from the rule-set

## 10.9 Phase 0 additions

- Scaled-integer types and newtypes (`Paise`, `Units`, `BasisPoints`) — task 0.18 extended
- Rounding utility module with the largest-remainder splitter
- Lint rules banning float in financial modules
- Migration check extension prohibiting `NUMERIC`/`REAL` on money columns
- JSON serialization convention (strings) wired into the API layer from the first endpoint
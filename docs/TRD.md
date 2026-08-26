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

`hash(account_ref + value_date + amount_paise + canonical_narration + occurrence_index)` — computed at parse time (step 2), stored on the event. `running_balance` is excluded — it is a validation signal only. Powers the seen-vs-counted dedup ledger (PRD 15.2). See §9.1 C1/C2 for the full definition.

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
| **C1** | **Idempotency hash redesigned.** New definition: `hash(account_ref + value_date + amount_paise + canonical_narration + occurrence_index)`. `running_balance` is **removed from identity** and used only as a validation signal feeding the balance check. `canonical_narration` is computed at parse time (step 2) via a frozen, deterministic function: Unicode NFKC normalization → strip leading/trailing whitespace → collapse all internal whitespace to a single space → uppercase. This is **distinct** from step-4 merchant normalization (a DECISION recorded as an event, feeding display/categorization). The canonical form is frozen for the lifetime of the hash — any future change to the canonicalization function invalidates all historical hashes and requires a migration, not a silent code change. |
| **C2** | **`occurrence_index` added** — the 0-based ordinal of a transaction within its `(account_ref, value_date, amount_paise, canonical_narration)` group as it appears in the source statement. Deterministic per source; correctly distinguishes two genuine ₹250 coffees from one re-ingested duplicate. **Canonical tiebreaker:** within an identical-field group, `occurrence_index` is determined by position in the balance-validated statement sequence (the order transactions appear after the balance check passes). The ingestion event records the parser name, parser version, and sequence-within-statement offset as provenance, so replay reconstructs the exact ordering even when the source PDF is no longer retained (M1). Fallback for sources without line ordering (e.g. JSON feeds): order by `value_date` then by appearance order within the ingestion event payload. A cross-parser test (Phase 1) asserts that two parsers producing the same statement produce identical `occurrence_index` values for every group. |
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

---

# 11. Anti-Drift Process (AI-Driven Development Safeguards)

## 11.1 The gap the harness cannot close

The correctness harness (§4.3) checks **code against tests**. It does not — and structurally cannot — check that the **tests are faithful to the spec**. When the same agent writes both the implementation and its tests from the same reading of the spec, a misreading produces a passing test that enforces the wrong behaviour: green CI, confidently wrong. The agent is grading its own homework.

This matters most for tax logic, where the owner has stated they cannot self-verify, and where a wrong constant (a limit, a rate, a threshold) sails through every existing gate.

**Running a second agent in parallel on the same tasks does not fix this** — two agents with correlated training have correlated blind spots, at double the cost. The fix is *independent, adversarial* checking by a different role, not a duplicate builder.

## 11.2 Three layers (all adopted)

**Layer 1 — Independent test authoring.** For correctness-critical modules (`core/`, `processing/resolver`, `processing/deductions`, `domain/ca_view`, tax rule-set evaluation), the agent that writes the tests must work from the spec *without reading the implementation*. Tests derived from the same code they test only re-assert whatever the code happens to do. Tests derived independently from the spec can disagree with the code — and that disagreement is the signal. Practically: separate the test-authoring session from the implementation session, prompt it from the PRD/TRD acceptance criteria and the journey doc, and forbid it from opening the implementation file.

**Layer 2 — Adversarial review pass (per wave/phase).** At the end of each wave, a fresh-context review runs against the spec with an adversarial brief: *"find where this diverges from the PRD/TRD, where a test asserts something the spec does not require, where an invariant could be violated without a test noticing, and where a constant was invented."* Fresh context matters — an agent that just spent a wave building has absorbed its own assumptions and cannot see them. The review does not run every commit (too noisy, and correlated with the build session); it runs at the wave boundary when there is a coherent unit to audit.

**Layer 3 — Human / CA gate (per phase).** Phase gates already require the owner to sign off. The tax rule-set and merchant→section seed table get a **qualified CA review at the Phase 4 gate** (already a Phase 4 exit condition). Per the owner's decision, tax logic is *not* independently checked on every change — the Phase 4 CA review is the designated checkpoint, keeping cost proportionate. Between now and Phase 4, tax constants are flagged `# UNVERIFIED — CA review pending` in code and rule-set, so nothing is mistaken for validated.

## 11.3 Cadence

| Layer | Runs | Scope |
| --- | --- | --- |
| Independent test authoring | Continuously, for critical modules only | `core/`, resolver, deductions, ca_view, rule-set |
| Adversarial review pass | End of each wave/phase | The wave's deliverables vs spec |
| Human sign-off | Each phase gate | Exit criterion + owner review |
| CA review | Phase 4 gate | Tax rule-set + seed mapping table |

Deliberately **not** every-commit: the owner ranked correctness first but also chose periodic over always-on here, because always-on adversarial review on every PR is costly and its per-commit signal is low. The wave boundary is where a coherent, auditable unit exists.

## 11.4 What each layer catches that the others miss

- **Golden/property tests (existing):** code regressions — behaviour that *changed*.
- **Independent test authoring:** code that was *never right* — implementation and test sharing a wrong assumption.
- **Adversarial review:** drift the tests don't cover at all — invented scope, missing invariant coverage, spec divergence no assertion guards.
- **CA / human gate:** domain wrongness no amount of internal consistency can catch — a correctly-implemented, correctly-tested, wrong tax rule.

The layers are ordered by how independent they are from the build. That independence is the whole point: each layer sees what the layer closer to the code is blind to.

## 11.5 Recorded in the repo

- `CLAUDE.md` gains a rule: **test-authoring for critical modules is a separate session from implementation, and must not read the implementation file.**
- `QUALITY.md` gains the adversarial-review checklist as a wave-gate step.
- `PROJECT_STATE.md` wave-gates gain an "adversarial review: pass/fail" line.
- Tax constants carry `# UNVERIFIED — CA review pending` until the Phase 4 gate clears them.
---

# 12. Dynamic Parser Builder — LLM Fallback for Unrecognised Layouts

**Phase scope: Phase 2.** Nothing in this section is implemented in Phase 1. Phase 1 closes with five hard-coded template parsers. The Dynamic Parser Builder is the safety valve for new bank layouts that arrive before a template is written.

## 12.1 Problem statement

Template parsers (`HdfcCcParser`, `SbiCcParser`, `HdfcSavingsParser`, `SbiSavingsParser`, `SliceSavingsParser`) cover the five known layouts. A sixth bank — or a layout change to an existing bank — produces `ValueError("No parser found for this PDF")`. Without a fallback, the system is fully unusable for that statement until a developer writes a new parser.

The Dynamic Parser Builder provides a low-confidence path that works for any PDF layout by asking an LLM to extract the data directly, while the system logs the gap and queues a template-authoring request.

## 12.2 Architecture

### Decision boundary

The LLM extraction result is a **decision** (TRD §9.2): it depends on which model ran, which prompt version ran, and the state of the PDF at the time. It must be recorded as an event (`IngestionEvent.source_detail = {"parser": "llm_fallback", "model": "...", "prompt_version": "..."}`) so replay is deterministic. Never re-run the LLM call on replay; use the stored decision.

### Harness integration

The dry-run harness (`ingestion/dryrun/harness.py`) tries template parsers first. If none match, it instantiates `LlmFallbackParser` and calls `parse()`. The fallback is transparent to `confirm()` — it returns a standard `ParsedStatement`, just with `confidence < 7500` (the LLM threshold).

```
template parsers → can_parse() → first match → parse()
              ↓ (no match)
        LlmFallbackParser.parse()
              ↓
        confidence = 6000 bps (LLM fallback)
              ↓ (< 7500 threshold)
        DryRunSession with balance_check result
        User sees low-confidence warning in preview
        Confirm requires explicit acknowledgement
```

### Adapter layer

All LLM calls go through `adapters/llm/base.py` (interface) and a concrete adapter per provider (`adapters/llm/claude.py`). The adapter contract:

```python
class LlmAdapter(Protocol):
    def complete(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        model: str,
        max_tokens: int = 4096,
    ) -> BaseModel: ...
```

Model routing: LLM fallback is low-volume / high-stakes → use the strongest available model (configured via `LLM_FALLBACK_MODEL` env var, default `claude-opus-4-7`). Cheap models have higher extraction error rates on unfamiliar layouts.

## 12.3 Structured output schema

The LLM returns a Pydantic model, never free text:

```python
class LlmParsedTransaction(BaseModel):
    value_date: date
    narration: str
    amount_paise: int          # signed: debits negative, credits positive
    running_balance_paise: int | None

class LlmParsedStatement(BaseModel):
    bank: str                  # LLM's best guess (e.g. "axis_bank")
    account_ref: str           # last 4 digits with prefix e.g. "AXIS_XXXX"
    period_start: date
    period_end: date
    opening_balance_paise: int
    closing_balance_paise: int
    transactions: list[LlmParsedTransaction]
    extraction_notes: str      # LLM's own confidence notes
```

`LlmFallbackParser.parse()` converts `LlmParsedStatement` to `ParsedStatement`, computing `canonical_narration`, `occurrence_index`, and `idempotency_hash` via the shared `core.hashing.hash` module (same as all template parsers — no duplication).

## 12.4 Confidence and gates

| Parser type | Confidence (basis points) | Confirm behaviour |
|---|---|---|
| Template parser | 9000 | Standard confirm flow |
| LLM fallback | 6000 | User sees low-confidence warning; confirm requires explicit "I've verified this" tick |

Invariant: confidence is a property of `DryRunSession.statement.confidence`. The dry-run preview always shows it. Below 7500 (configurable in settings), the UI disables one-click confirm and requires the acknowledgement field.

## 12.5 Parser promotion path (Phase 3+)

When the LLM successfully parses N statements of the same `bank` value (configurable, default 3), the system creates a `parser_promotion_queue` record. A developer reviews the LLM's extractions, writes a template parser, and the promotion record is cleared. This converts a fallback path into a permanent template parser — the long tail shrinks over time.

This is a **Phase 3+ feature**. The queue table and review UI are out of Phase 2 scope.

## 12.6 Prompt engineering requirements

The fallback prompt must:
1. Show the full extracted text from `extract_text()` for all pages (truncated if > 8000 tokens).
2. State the target schema explicitly (field names, types, sign convention).
3. Instruct the model to set `running_balance_paise = null` if the column is absent — never to invent a value.
4. Instruct the model to return `opening_balance_paise = 0` only if the statement explicitly states zero; otherwise return `null` (which will produce `BalanceCheckResult.FAIL`).
5. Include the balance-check formula so the LLM can self-verify before returning.

Prompts live in `ingestion/parsers/prompts/llm_fallback_v1.txt`. Prompt version is stored in `IngestionEvent.source_detail`. A prompt change bumps the version — never overwrites.

## 12.7 Test requirements

- Unit: mock the LLM adapter; verify `LlmFallbackParser` produces valid `ParsedStatement` from a known response.
- Golden: at least one LLM-fallback golden fixture per wave (a bank layout with no template parser). LLM response is pre-recorded — no live call in CI.
- Integration: `test_llm_fallback_pipeline.py` — verify the full dry_run → confirm path with a mocked adapter.
- Property: `LlmParsedTransaction.amount_paise` is always an `int`, never a float (the LLM tends to return `1234.56` — the schema must coerce or reject).

## 12.8 Phase 2 deliverables

| Deliverable | File |
|---|---|
| LLM adapter interface | `backend/adapters/llm/base.py` |
| Claude adapter | `backend/adapters/llm/claude.py` |
| LLM fallback parser | `backend/ingestion/parsers/llm_fallback.py` |
| Fallback prompt v1 | `backend/ingestion/parsers/prompts/llm_fallback_v1.txt` |
| Harness update | extend `_DEFAULT_PARSERS` fallback in `harness.py` |
| Unit tests | `backend/tests/unit/ingestion/test_llm_fallback_parser.py` |
| Integration test | `backend/tests/integration/test_llm_fallback_pipeline.py` |

---

# 13. Phase 1 Gate — Closed

**Closed:** 2026-08-08 · Commit 0eb3bd8, PR #4 · 212 unit + property tests passing, 8/8 integration tests passing against real testcontainers (Postgres + Redis).

## 13.1 What shipped (scope note)

Both CC and Savings parsers shipped, not a substitution — five parsers total: **HDFC CC, SBI CC, HDFC Savings, SBI Savings, Slice Savings.** All five call the shared `compute_occurrence_index()` / `compute_idempotency_hash()` functions from `core/hashing/hash.py` — no per-parser duplication (F-1 gate holds).

## 13.2 Gate G18 — parser registration enforcement (new, permanent)

**Root cause:** three fully-tested savings parsers were built and passed every unit test, but were never added to `_DEFAULT_PARSERS` in the dry-run harness — meaning they would never have actually run in production despite green tests. Caught only by a whole-branch review, not by the standard gate.

**Fix, now permanent:** any new parser not present in `_DEFAULT_PARSERS` fails an enforcement test before merge (`test_dryrun_harness.py`). Added to `QUALITY.md` as gate G18. **Any future parser addition must pass this gate — registration is no longer a step someone has to remember, it's mechanically enforced**, consistent with the project's general preference for mechanical checks over discipline.

## 13.3 Confirmed integration coverage

All four integration tests specified after the Phase 1 review round now execute against real infrastructure (not mocked), per the earlier finding that "syntax verified" is not "passing":

- `test_idempotent_ingest.py` — overlapping statements + genuine same-day duplicates, real Postgres.
- `test_malformed_input.py` — garbage/empty input, zero DB writes (self-caught and fixed: was asserting whole-table count instead of scoping by `test_user.id` — a real test-isolation bug, corrected before this close).
- `test_session_expiry.py` — real Redis TTL expiry with an actual sleep, not mocked.
- `test_password_protected.py` — real AES-128 encrypted PDF fixtures (`pikepdf`, in-memory, not committed), correct/missing/wrong password.

## 13.4 NULL≠0 negative-test coverage added

Per TRD §10.3 (NULL means unknown, never coerced to zero), the balance-regex-miss path — previously silently returning 0 — now raises `ValueError` and is test-covered for HDFC CC, SBI CC, and SBI Savings.

## 13.5 Open items carried into Phase 2

- **Slice Savings ref-number regex** (`\S+`, loosened to fit the synthetic fixture rather than confirmed against a real statement) — flagged as a standing risk in `PROJECT_STATE.md`. Not to be trusted with real Slice data until validated against an actual statement sample.
- **Dynamic Parser Builder** (LLM-assisted template generation, balance-check gated) — specced (see §12 above) but deferred to Phase 2. The `adapters/llm/` layer doesn't exist yet; building it in Phase 1 would have been scope creep without a concrete driving use case.
- **F-9 retroactive gap** (Phase 0 critical-module tests co-authored, not independently authored) — re-authoring for `core/hashing/`, `core/events/`, `core/projections/` still required before Phase 2 closes.

---

# 14. UI Phases (paired, not appended)

**Gap identified:** the phase roadmap (§5) never gave UI its own planning treatment — it appears only as a single bullet inside Phase 3's and Phase 4's "Build" lines. Two phases closed (backend-only) before this was caught. Fixing it now, without altering any existing phase content.

## 14.1 Pattern

A UI phase is inserted **after** each backend phase that produces something worth seeing, numbered `N.5`. It builds the screens that consume that phase's already-shipped API — never ahead of the data, never against a mock. This keeps the same discipline as the backend: nothing is built until there's a real, tested source of truth behind it.

| Phase | Builds on | Screens |
| --- | --- | --- |
| **2.5 — Frontend Foundation** | Phase 2 (closed) | Design system, tokens, app shell, nav. First real screen: the audit view (Journey 7), since Phase 2's resolver/dedup data already exists to render. |
| **3.5 — Day-to-Day UI** | Phase 3 | Dashboard (PRD §12.1), account management (PRD §13), budgets, onboarding checklist (Journey 1). |
| **4.5 — CA View UI** | Phase 4 | Income/deductions/capital-gains/regime screens (PRD §1), FY completeness checklist. |
| *(Phase 5 stays as-is)* | Phases 0–4.5 | Private beta — deploys what UI phases have already built; not a UI-building phase itself. |

## 14.2 Why paired beats appended

- **Never builds against a mock.** Every UI phase's exit criterion requires wiring to a real, already-tested endpoint — no screen ships ahead of the data it displays, matching the project's general refusal to trust anything unverified.
- **Design system amortizes correctly.** 2.5 builds the tokens and primitives once; 3.5 and 4.5 consume them, so the cost of the design system is paid early and reused, not redone per phase.
- **Doesn't block backend momentum.** Phase 3's backend work can proceed without waiting on 2.5 to fully finish, since they touch different layers — but 3.5 cannot start until Phase 3's API surface exists.
- **Beta-readiness becomes checkable.** Phase 5 no longer implicitly assumes a UI appeared somewhere along the way — by the time Phase 5 starts, 2.5/3.5/4.5 have already shipped the actual product surface a beta user touches.

## 14.3 Exit criterion pattern

Each `N.5` phase follows the same `PHASE_PROTOCOL.md` discipline as backend phases: propose → approve → build in waves → report with raw evidence → adversarial review → close. Its exit criterion is always of the form: *"[screen(s)] render real data from [phase N]'s API, every acceptance criterion from the relevant PRD section / User Story journey is met, and the audit trail for what was built matches what was designed."*

## 14.4 Phase 2.5 scope (next up)

**Build:** design system (tokens, typography, color/status language), app shell (nav, layout), and the audit view screen (Journey 7 — overlap map, dedup ledger, resolver pairings), consuming the endpoints deferred from Phase 2 (§13, U7 — these get built as part of 2.5's wiring, not before).

**Exit criterion:** the audit view renders real overlapping-statement data from a Phase 2 fixture, every Journey 7 acceptance criterion is met on screen (not just in the API), and the design system's tokens are the single source every subsequent UI phase consumes — no phase re-derives color or type choices independently.

**Design decisions for 2.5 are being made separately** (visual direction, component library, scope-now-vs-defer) — see accompanying discussion.

---

# 15. UI Technical Notes

Frontend technical decisions from UI review, for the `web/` build across phases 2.5 / 3.5 / 4.5. Screen content and IA live in PRD §12/§19/§20/§12A and User Stories §19; this section is the *technical* how.

## 15.1 Stack & libraries

- **Next.js + TypeScript** (strict), per T3.
- **shadcn/ui** for components. Chosen because components are copied into the repo (fully typed, readable, modifiable) rather than an opaque dependency — consistent with T3's "mainstream, best-documented for AI codegen." Built on Radix + Tailwind, themed via CSS variables.
- **Charting:** a library is required for the seven Home dashboards (PRD §12A.4). Pick one (e.g. Recharts or Chart.js, both already in the environment's available set) at Phase 3.5 kickoff. Charts must theme from the same CSS-variable tokens as everything else — no hardcoded colors.

## 15.2 Design system (built in Phase 2.5, consumed by 3.5/4.5)

- **Theme is a token set, fully configurable** (per user decision). Ship dark-first (ink/navy), but every color/type/spacing value is a CSS variable, so a new theme is a token file, not a code change. Settings exposes the selector (PRD §19).
- **Tokens built in full in 2.5** (color incl. status green/amber/red, type scale — Space Grotesk display / IBM Plex Sans body / IBM Plex Mono numbers, spacing, elevation). **Components built incrementally** — only what the Audit screen needs in 2.5; 3.5/4.5 add components but never re-derive a token.
- **Signature throughline:** every monetary/numeric value renders in IBM Plex Mono (tabular figures); every status or exclusion carries a plain-English "why" line, not just a color. This is the product thesis (nothing unexplained) expressed visually — enforce it as a component contract, not per-screen discretion.
- **Money rendering:** integer paise from the API (TRD §10) is formatted to rupees *only at render*, using Indian grouping (lakh/crore, ₹12,34,567.89). Never compute or store the formatted string.

## 15.3 App shell (Phase 2.5)

- **Two-context switch** (Expense ⇄ CA) that swaps the entire sidebar (PRD §20.1). Implemented as a top-level layout state, not routing duplication.
- **Shared utilities** (Accounts, Notifications, Settings) render outside the context switch and are reachable from both.
- **Bell affordance** opens a notification preview panel; full Notifications is a shared screen. (Home does *not* carry a notification preview — PRD §12A.1.)

## 15.4 Home dashboards (Phase 3.5)

- **One shared time selector** drives all KPIs and charts (PRD §12A.2). Implement as a single screen-level state that every widget subscribes to — not per-widget date pickers. This is an architectural constraint: widgets are pure functions of (data, window), so the selector re-renders all of them together.
- **Trend widgets must render a span even for a single-month selection** (§12A.2) — daily/weekly buckets within the month, or trailing months. A trend widget that can render a single point is a bug; the windowing logic that expands a focus-window into a trend series is shared, not per-chart.
- **"Previous comparable period" for KPI deltas** must be defined per selector option before build (this-month→last-month is obvious; custom-range needs a rule). Flagged as an open item.
- All seven charts read from Expense-context projections only; **no CA/FY data on Home** (§12A.5) — enforces the two-context data separation.

## 15.5 Data dependency — endpoints precede screens

Consistent with the backend discipline: no UI phase builds a screen ahead of the tested API that feeds it. The Audit endpoints deferred from Phase 2 (§13, U7) are built as part of Phase 2.5's wiring. The Home dashboards need aggregation endpoints (KPIs, per-category time series, merchant leaderboard) that are Phase 3.5 backend work preceding the 3.5 UI — sequence them so the chart never renders against a mock.

## 15.6 Open UI items

- Empty states for every screen (deferred to 3.5; logged in `PROJECT_STATE.md`). Audit-view empty state specifically flagged.
- "Previous comparable period" rule for each selector option (§15.4).
- Charting library selection (§15.1) — decide at 3.5 kickoff.

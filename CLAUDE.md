# CLAUDE.md — Agent Context

**Read this file completely before writing or modifying any code in this repository.**

This is a personal finance product: a day-to-day expense/budget tracker sitting on the same ledger as a CA-style (Indian tax) financial health view. It does **not** file tax returns — it produces planning-grade reports.

---

## 0. Start-of-session protocol

Every session, in this order:

1. Read this file.
2. Read `docs/PROJECT_STATE.md` — what phase we're in, what's in progress, what's blocked.
3. If starting, continuing, or closing a phase or wave, read `docs/PHASE_PROTOCOL.md` and follow it — this is the standing procedure for phase execution and does not need to be re-specified each time.
4. Read the relevant spec section in `docs/PRD.md` / `docs/TRD.md` before implementing anything.
5. Check `docs/CODE_GRAPH.md` to understand where new code belongs.
6. At end of session, append to `docs/SESSION_LOG.md` and update `docs/PROJECT_STATE.md`.

If a task is not traceable to a PRD/TRD section, **stop and ask** rather than inventing scope.

---

## 1. The prime directive: correctness over speed

Priority order, explicitly ranked by the product owner:

> **Correctness > clean architecture > low running cost > speed of shipping**

This is not a slogan. It has concrete consequences:

- Never ship a number the system cannot justify. Every displayed figure must trace to a source event.
- When uncertain between "fast" and "verifiable", choose verifiable.
- A feature that works but cannot be tested is not done.
- Silent failure is the worst outcome. Loud failure is acceptable. Wrong-but-confident is unacceptable.

**The owner cannot independently verify tax logic.** Treat all tax computations as high-risk: cite the rule, show assumptions, flag low confidence. Never guess a threshold or rate — if it isn't in the spec, ask.

---

## 2. Non-negotiable invariants

These must hold at all times. They are asserted in tests. Breaking one is a P0 bug, not a regression.

1. **No transaction hash is ever counted more than once.** Idempotency hash = `hash(account_ref + value_date + amount_paise + canonical_narration + occurrence_index)`. `canonical_narration` = NFKC → strip → collapse whitespace → uppercase, applied at step 2, frozen forever (TRD §9.1 C1/C2). `running_balance` is NOT in the hash.
2. **Statement balance check must pass** (`opening + credits − debits == closing`) or the parse is rejected and logged — never partially ingested.
3. **Event log replay is deterministic.** Replaying the same events twice produces byte-identical projections.
4. **A matched internal-transfer pair never appears in expense totals.** (Transfers, credit-card bill payments, FD bookings.)
5. **A closed financial year's projection never changes *silently*** when tax rules are updated. Rule-sets are version-pinned per FY. Amendments (e.g. a genuine category correction touching a closed FY) are permitted but require explicit user confirmation, are recorded as amendment events, and preserve the original. A FY closes automatically once its ITR filing deadline passes.
6. **Nothing below the confidence threshold enters the ledger** without explicit user confirmation.

---

## 3. Architecture rules

### 3.1 Layering

```
Sources → Ingestion → Event Log → Processing → Projections → API → UI
```

- **Event log is the single source of truth.** Append-only.
- **Projections are disposable.** They are rebuilt by replay. Never patch a projection directly — fix the code and replay.
- Data flows one direction. Projections never write back into the event log.

### 3.2 Immutable vs mutable — know which you are touching

**Immutable (append-only, never UPDATE, never DELETE):**
- `ingestion_events`, `raw_artifacts`, `transaction_events`, `document_events`

**Mutable (normal CRUD, history doesn't matter):**
- `users`, `accounts`, `budgets`, `category_overrides`, `settings`, `statement_credentials`

If you find yourself writing an `UPDATE` against an immutable table, you have misunderstood the model. Append a new event instead.

### 3.3 Pipeline ordering — HARD CONSTRAINT

```
1. Ingest raw artifact
2. Parse + validate (balance check)
3. Relationship resolver   ← transfers / CC payments / FD bookings
4. Merchant normalization
5. Category classification
6. Nature tagging (essential / discretionary / luxury)
```

**Step 3 MUST run before step 5.** If categorization runs first, a credit-card bill payment gets counted as spend *on top of* the individual purchases already counted — silently inflating every budget total. This ordering is enforced in code and asserted in tests. Do not reorder it for convenience.

---

### 3.4 Decisions vs derivations — HARD CONSTRAINT

> **Anything involving an LLM, or a lookup whose result depends on what data existed at the time it ran, is a DECISION and MUST be recorded as an event. Anything purely arithmetic over recorded facts is a DERIVATION and may be recomputed freely.**

- **Decisions (record as events):** resolver pairings, LLM category classification, deduction-section detection, confidence scores, merchant normalization results.
- **Derivations (recompute freely):** budget totals, net worth, running-cost splits, FY aggregates, allocation percentages.

If you recompute a decision on replay, replay stops being deterministic and Invariant 3 fails. This is not a style preference — it is what makes the "projections are disposable" architecture safe.

### 3.5 All numeric quantities are scaled integers

**No floats anywhere, at any layer.** Each quantity has its own scale:

| Quantity | Type | Scale |
|---|---|---|
| Money (amounts, balances) | `BIGINT` | paise (10⁻²) |
| MF NAV, unit holdings | `BIGINT` | 10⁻⁴ |
| Rates (tax, interest, allocation) | `INTEGER` | basis points |
| FX rates | `BIGINT` | 10⁻⁶ |

Rules:
- **Amounts are signed** — debits negative, credits positive. Never an unsigned amount plus a direction flag.
- **`NULL` means unknown; `0` means zero.** Never conflate them. A missing ESOP cost basis is `NULL`, never `0` — `0` would report a fictitious 100% gain as fact. Aggregates encountering `NULL` exclude and flag it, never coerce.
- **Intermediate calculations use `Decimal`**, rounding only at persist/display boundaries.
- **Splitting amounts uses the largest-remainder method** so parts always sum exactly to the original.
- **Tax rounding follows Sections 288A/288B** (nearest ₹10) and lives in the versioned rule-set, not in code.
- **JSON serializes money as strings, never numbers.** `JSON.parse` produces IEEE-754 doubles and will corrupt values the backend stored correctly.

A lint rule bans float in `core/`, `processing/`, and `domain/`. Do not disable it. See TRD §10 for the full specification.

### 3.6 Timestamps: UTC storage, IST business logic

Store all timestamps in UTC. Perform **all** financial-year, statement-period, and matching-window logic in IST. A transaction at `2026-03-31T23:30:00Z` is `2026-04-01T05:00:00 IST` — month 4 → **FY 2026-27**, not FY 2025-26. Getting this wrong misfiles income across tax years.

---

## 4. AI/LLM usage rules (in-product)

- **Deterministic first.** Rules and template parsers run before any LLM call. The LLM is a fallback for the long tail, not the default path.
- **Provider-agnostic.** All model calls go through the adapter layer. Never import a vendor SDK outside `adapters/llm/`. The model is configuration, not a code dependency.
- **Structured output only.** Every LLM call returns a schema-validated object (Pydantic). Never parse free text downstream.
- **Confidence gates.** Below threshold → review queue. Never silently into the ledger.
- **Prompts are code.** They live in version control, are versioned, and have their own golden test cases.
- **Route by stakes.** High-volume/low-stakes (categorization) → cheap models. Low-volume/high-stakes (unmatched PDF layouts) → stronger models.

---

## 5. Code conventions

### Stack
- **Frontend:** TypeScript + Next.js/React, strict mode on.
- **Backend:** Python + FastAPI, full type hints, Pydantic models everywhere.
- **DB:** Postgres. Migrations are versioned and forward-only.

### Rules
- **Strict typing is mandatory.** No `any`, no untyped Python function signatures. Types are the cheapest specification that cannot be misread.
- **Small, single-responsibility modules.** If a file exceeds ~300 lines, it probably wants splitting.
- **Every module docstring states its contract and the PRD/TRD section it implements.** Example:
  ```python
  """Relationship resolver: detects internal transfers, CC bill payments,
  and FD bookings before categorization. Implements PRD §7."""
  ```
- **No secrets in code or fixtures.** Credentials come from environment/secret store only.

---

## 6. Testing rules

- **Synthetic fixtures only in the repo.** Real bank statements must never be committed, never enter CI.
- **Every bug found in real data becomes a synthetic fixture in the golden dataset *before* it is fixed.** The dataset only grows. This is how an AI-written codebase stays trustworthy without a human re-reading everything.
- **Property-based tests for invariants** (§2), not just example-based tests.
- **A change that touches parsing, the resolver, or tax logic must run the full golden dataset.** A diff is a failure, not a discussion.
- **All quality gates must pass before merge.** See `docs/QUALITY.md` for the full gate list, tiered coverage thresholds, and per-run reporting. Key rules: coverage may never decrease (ratchet); an invariant test failure is P0 and stops feature work; migrations that `UPDATE`/`DELETE` on immutable tables fail the build; the real-data guard is never bypassed.
- **Independent test authoring for critical modules.** For `core/`, `processing/resolver`, `processing/deductions`, `domain/ca_view`, and tax rule-set evaluation, tests must be authored in a **separate session from the implementation, working from the spec (PRD/TRD + journeys), without opening the implementation file.** Tests derived from the code they test only re-assert what the code happens to do; tests derived independently from the spec can disagree with the code, and that disagreement is the signal. See TRD §11.
- **Tax constants carry `# UNVERIFIED — CA review pending`** until the Phase 4 CA review clears them. Never treat an AI-generated tax threshold, rate, or limit as validated.

---

## 7. When to stop and ask

Stop and ask the owner rather than proceeding if:

- A tax rule, rate, threshold, or deadline is not explicitly in the spec.
- The spec is ambiguous and you would have to invent a business rule.
- A change would break one of the invariants in §2.
- A task requires real financial data to verify and only synthetic data is available.
- You would need to reorder the pipeline (§3.3).

**Ambiguity in the spec is a bug in the spec.** When a decision has to be invented, write it back into `docs/PRD.md` or `docs/TRD.md` — do not bury it in code.

---

## 8. Document map

| File | Purpose |
|---|---|
| `CLAUDE.md` | This file. Agent context and invariants. |
| `docs/PRD.md` | Product requirements. What the product *is*. |
| `docs/TRD.md` | Technical requirements. How it's built. |
| `docs/PROJECT_STATE.md` | Current phase, in-progress work, blockers. **Update every session.** |
| `docs/PHASE_PROTOCOL.md` | Standing procedure for starting, running, and closing any phase or wave. Read whenever a phase/wave is in motion. |
| `docs/SESSION_LOG.md` | Append-only history of what each session did. |
| `docs/CODE_GRAPH.md` | Module map and dependency graph. Update when structure changes. |
| `docs/DECISIONS.md` | Architecture decision records (ADRs). |
| `docs/QUALITY.md` | Quality gates, coverage thresholds, CI pipeline, per-run reporting. |

**PRD and TRD in `docs/` are the source of truth for the build.** They are synced from Notion; if they disagree with Notion, flag it rather than silently choosing one.

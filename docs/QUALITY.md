# Quality Gates & CI

> Every gate here runs on **every push and every PR**. Results are published as PR comments and to the CI dashboard.
>
> **Principle:** when an AI writes most of the code, review-by-reading does not scale. Quality must be *mechanically enforced and continuously visible*, or drift is invisible until it's expensive.

---

## 1. Gate summary

| # | Gate | Tool (Python) | Tool (TS) | Blocking? |
|---|---|---|---|---|
| G1 | Format | `ruff format` | `prettier` | Yes |
| G2 | Lint | `ruff` | `eslint` | Yes |
| G3 | Type check | `mypy --strict` | `tsc --noEmit` | Yes |
| G4 | Unit tests | `pytest` | `vitest` | Yes |
| G5 | Property tests (invariants) | `hypothesis` | — | Yes |
| G6 | Golden dataset | `pytest -m golden` | — | Yes |
| G7 | Integration tests | `pytest -m integration` | `playwright` | Yes |
| G8 | Coverage thresholds | `pytest-cov` | `vitest --coverage` | Yes |
| G9 | Complexity / code smells | `ruff` (C901) + `radon` | `eslint-plugin-sonarjs` | Warn → block on regression |
| G10 | Dead code | `vulture` | `knip` | Warn |
| G11 | Security — deps | `pip-audit` | `npm audit` | Block on high/critical |
| G12 | Security — code | `bandit` | `eslint-plugin-security` | Block on high |
| G13 | Secret scanning | `gitleaks` | `gitleaks` | Yes — always block |
| G14 | Real-data guard | custom | custom | Yes — always block |
| G15 | Migration check | custom | — | Yes |

---

## 2. Coverage thresholds — tiered by risk

Uniform coverage targets are a blunt instrument. Ours are tiered by blast radius:

| Zone | Modules | Line | Branch | Rationale |
|---|---|---|---|---|
| **Critical** | `core/events`, `core/projections`, `core/hashing`, `core/ruleset`, `processing/resolver`, `ingestion/validators`, `domain/ca_view` | **95%** | **90%** | A bug here produces silently wrong money or tax numbers |
| **Standard** | `ingestion/parsers`, `processing/*`, `domain/*` | 85% | 75% | Wrong output is visible/correctable |
| **Peripheral** | `api/`, `adapters/`, `web/` | 70% | 60% | Failures are loud, not silent |

**Rules:**
- Coverage **may not decrease** on any PR (ratchet). A drop is a failure even if above threshold.
- New files in the Critical zone start at their threshold — no grace period.
- Coverage is reported per-zone in the PR comment, not as one global number that hides critical-path gaps.

---

## 3. Test layers — what actually runs

### 3.1 Unit (`tests/unit/`)
Pure functions, parsers, tax computations, hash logic. Fast (<30s total). No DB, no network.

### 3.2 Property-based (`tests/property/`)
The six invariants from `CLAUDE.md` §2, expressed as properties over generated inputs:

| Invariant | Property test |
|---|---|
| 1. No double-counting | For any set of overlapping statements, each hash appears exactly once in `transactions_current` ✅ Phase 0 |
| 2. Balance check | For any statement, either it validates or it is rejected — never partially ingested ⧗ Phase 1 — requires validator module |
| 3. Replay determinism | For any event stream, `replay(s) == replay(s)` byte-identical ✅ Phase 0 |
| 4. Transfer exclusion | For any matched transfer pair, neither leg appears in expense totals ⧗ Phase 2 — requires resolver module |
| 5. FY immutability | For any closed FY, changing the active rule-set does not change its projection ⧗ Phase 4 — requires versioned rule-set |
| 6. Confidence gate | For any parse below threshold, no ledger write occurs without a confirm event ⧗ Phase 1 — requires dry-run harness |

These catch *classes* of bugs, which matters more than usual when an agent is generating edge cases it also chose.

### 3.3 Golden dataset (`tests/golden/`)
Synthetic statements → expected ledger output, byte-compared. **Any diff is a failure, not a discussion.**
Every bug found in real data is added here as a fixture *before* being fixed. The dataset only grows.

### 3.4 Integration (`tests/integration/`)
Real Postgres (ephemeral container), mocked external services:

- **Ingestion path:** mocked Gmail → PDF fixture → parse → validate → event → projection.
- **Dry-run harness:** upload → preview → confirm → ledger write. And: preview → *abandon* → **assert nothing written**.
- **Dedup path:** ingest overlapping statements twice → assert zero double-count, assert audit view shows seen-twice/counted-once.
- **Resolver path:** CC bill payment + underlying purchases → assert bill payment excluded from expense totals.
- **Replay:** build projections → wipe → replay → assert identical.
- **Slack cash:** mocked event payload → parse → preview → confirm → ledger.
- **Tenant isolation:** user A cannot read user B's rows (asserted at the query layer, not just the API).

### 3.5 End-to-end (`web/e2e/`, Playwright)
Thin layer, happy paths only: onboarding, upload statement, view dashboard, drill into CA view, open audit view. E2E is for wiring confidence, not logic coverage.

---

## 4. Custom gates (project-specific)

### G14 — Real-data guard (always blocking)
Scans every commit for anything resembling real financial data in `tests/`, `docs/`, or fixtures:
- PAN-shaped strings, Aadhaar-shaped digit runs, IFSC codes, 12+ digit account numbers, real bank sender domains in fixture headers.
Rationale: ADR-007. Synthetic fixtures only, no exceptions. A false positive costs a minute; a false negative is a privacy incident.

### G15 — Migration check
- Migrations must be forward-only.
- **Any migration touching an immutable table (`ingestion_events`, `raw_artifacts`, `transaction_events`, `document_events`) with `UPDATE`/`DELETE` semantics fails the build.** Append-only is enforced in CI, not just convention.

### G16 — Spec traceability (warn)
Every module must have a docstring naming the PRD/TRD section it implements (`CLAUDE.md` §5). Missing reference → warning listed in the PR comment. Prevents orphan code that nobody can trace to a requirement.

### G17 — Prompt golden tests
Prompts are versioned code (ADR-005). Changing a prompt file triggers its golden test set. Prompt changes cannot merge without their fixtures passing.

### G18 — Harness parser registration
Every concrete `AbstractParser` subclass must appear in `_DEFAULT_PARSERS` in `ingestion/dryrun/harness.py`.
- **Why this gate exists:** Three fully-built, fully-tested parsers (HdfcSavingsParser, SbiSavingsParser, SliceSavingsParser) shipped in Phase 1 without being registered in the harness. They were unreachable from the API and would have been invisible to users. The final whole-branch review caught it — but it was not caught by any per-task review. This gate prevents recurrence.
- **Enforcement:** A test in `tests/unit/ingestion/test_dryrun_harness.py` must iterate `_DEFAULT_PARSERS` and assert membership by class type. When a new parser is added, updating `_DEFAULT_PARSERS` AND the test is required before the PR can merge.
- **Signal:** `grep -rn "class.*AbstractParser" ingestion/parsers/` lists all concrete parsers. Compare against `_DEFAULT_PARSERS` in `harness.py`. Any class missing from the list is a blocker.

---

## 5. Per-run reporting

### 5.1 PR comment (auto-posted, updated in place)

```
## Quality Report — PR #42

Gates      ✅ 14 passed · ⚠️ 1 warning · ❌ 0 failed

Coverage
  Critical    96.2%  (▲ 0.4)   ≥95% ✅
  Standard    87.1%  (▼ 0.9)   ≥85% ✅
  Peripheral  71.3%  (—)       ≥70% ✅
  Ratchet     OK — no zone decreased below its baseline

Tests       412 passed · 0 failed · 2 skipped   (48s)
  Unit 310 · Property 24 · Golden 61 · Integration 17
Invariants  6/6 holding ✅

Complexity  avg 3.2 (▲0.1) · max 11 in parsers/hdfc.py:parse_rows ⚠️
Dead code   0
Security    deps 0 high · code 0 high · secrets 0 ✅
Real-data   clean ✅
Spec trace  1 module missing PRD ref: processing/nature/tagger.py ⚠️
```

### 5.2 Trend dashboard (published per run to `main`)
Coverage per zone over time, test count and duration, complexity trend, invariant pass streak, golden-dataset size (should only grow), open warnings.

**Why the trend view matters here:** single-run numbers can look fine while the codebase quietly degrades. With an agent generating volume, the *slope* is the signal — coverage drifting down, complexity drifting up, golden dataset flat while features ship.

### 5.3 Session integration
At session end, the agent appends the run summary (gate results, coverage deltas, new warnings) to `docs/SESSION_LOG.md`. Quality state becomes part of project history, not just a transient CI artifact.

---

## 6. Failure policy

| Situation | Action |
|---|---|
| Any blocking gate fails | PR cannot merge. No override. |
| Invariant test fails | **P0.** Stop feature work; this is a correctness breach. |
| Golden dataset diff | Treat as a bug until proven an intentional spec change — and if intentional, the PRD/TRD must be updated in the same PR. |
| Coverage ratchet trip | Add tests or justify in the PR description with a linked ADR. |
| Complexity/dead-code warning | Non-blocking, but three consecutive runs with the same warning escalates to blocking. |
| Security high/critical | Blocking. No time-boxed exception. |

---

## 7. Phase 0 additions

These tasks are added to the Phase 0 board (`docs/PROJECT_STATE.md`):

- **0.10** CI pipeline with gates G1–G8
- **0.11** Custom gates G14 (real-data guard) + G15 (migration check)
- **0.12** Coverage tiering config + ratchet enforcement
- **0.13** PR quality-report comment bot
- **0.14** Integration test harness (ephemeral Postgres)
- **0.15** Trend dashboard publishing

**Phase 0 exit criterion is amended:** the original criterion (event → projection → deterministic replay, CI green) now also requires that all gates run and publish a report on every push. Building the harness before the code is the point — retrofitting quality gates onto an AI-generated codebase is materially harder than starting with them.

---

## 8. Adversarial Review checklist (wave-gate)

Run at the end of each wave/phase with a fresh context — not the session that built the wave. The reviewer's brief is: *"find where this diverges from the PRD/TRD, where a test asserts something the spec does not require, where an invariant could be violated without a test noticing, and where a constant was invented."*

- [ ] **Spec divergence:** does every module docstring cite the correct PRD/TRD section? Does the implementation match what that section requires — not just what tests pass?
- [ ] **Over-fit tests:** do any tests assert behaviour the spec does not require? A test that mirrors the implementation's output without deriving the expected value from the spec is grading its own homework.
- [ ] **Unguarded invariants:** for each of the six invariants (CLAUDE.md §2), construct a counterexample — can you violate it without any test failing? Walk each one explicitly.
- [ ] **Invented/unsourced constants:** does any code contain a numeric constant (threshold, rate, limit, deadline) not explicitly cited to a PRD/TRD section or a statutory source? Flag with `# UNVERIFIED`; stop the wave if it is tax-affecting.
- [ ] **Orphan code:** is there any file, class, or function with no traceable PRD/TRD requirement? Missing module docstring section references (CLAUDE.md §5) are the signal.
- [ ] **Decisions recomputed on replay:** for each LLM call or time-dependent lookup, confirm its result is recorded as an event. If any resolver pairing, category assignment, or confidence score is recomputed from current world-state on replay rather than from a recorded event, I3 is broken.

**Findings are logged as wave-gate blockers in `docs/PROJECT_STATE.md`.** A wave does not advance until all Critical/Important findings are resolved or explicitly deferred with a tracked rationale.

---

## 9. Independent Test Authoring

For correctness-critical modules, the test-authoring session must work from the spec **without reading the implementation**. Critical modules:

- `core/events/` — event log append, read, encryption, upcasting
- `core/projections/` — projection builder, replay, snapshots
- `core/hashing/` — idempotency hash, occurrence index, newtypes
- `core/ruleset/` — tax rule-set evaluation
- `processing/resolver/` — transfer and CC bill-payment matching
- `processing/deductions/` — deduction tagging and section mapping
- `domain/ca_view/` — CA-layer financial health report

**How:** fresh session, provide PRD/TRD acceptance criteria and invariant statements, forbid opening implementation files. A disagreement between independently-authored tests and the implementation is an investigation signal, not a test failure to fix.

**Not required for:** peripheral modules (API routes, adapters, UI), configuration, scaffolding, utilities without financial calculation logic.

**Record:** the wave-gate adversarial review (§8) confirms independent authorship for critical modules. The confirmation is logged in `docs/PROJECT_STATE.md`.

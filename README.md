# Finance Tracker Product

**Master Hub:** [Finance Tracker — Master Hub (Notion)](https://app.notion.com/p/3a6188e1a1038194bfb5c25a1c379ab4)

This repository is the AI-driven build for a personal finance product: a day-to-day expense/budget tracker sitting on the same ledger as a CA-style (Indian tax) financial health view.

It does **not** file tax returns — it produces planning-grade reports a user (or their CA) can act on.

---

## Quick Start

1. **Understand what we're building:** read `docs/PRD.md` (what it is) and the quick reference in the master hub.
2. **Understand the approach:** read `docs/TRD.md` (how it's built) — especially sections on the event-sourced ledger, pipeline ordering, and testing strategy.
3. **Understand what users experience:** read `docs/USER_STORIES.md` — 13 journeys that stress-test the specs against reality.
4. **See what we're doing right now:** check `docs/PROJECT_STATE.md` (current phase, task board, blockers).
5. **Add to the session log:** at the end of every session, append to `docs/SESSION_LOG.md` with what you built, decisions made, and what's next.

---

## Repository structure

```
repo/
├── CLAUDE.md                    # Agent context, invariants, stop-and-ask rules (READ THIS FIRST)
├── README.md                    # This file
│
├── docs/                        # Specifications (synced from Notion)
│   ├── PRD.md                  # Product requirements (what it is)
│   ├── TRD.md                  # Technical requirements (how it's built)
│   ├── USER_STORIES.md         # 13 user journeys + gaps surfaced
│   ├── PROJECT_STATE.md        # Current phase, task board, blockers, risks
│   ├── SESSION_LOG.md          # Append-only session history
│   ├── CODE_GRAPH.md           # Module map, dependency rules
│   ├── DECISIONS.md            # Architecture decision records (ADRs)
│   └── QUALITY.md              # Quality gates, coverage thresholds, CI pipeline
│
├── backend/                     # Python + FastAPI (to be built)
│   ├── core/                   # Event log, projections, hashing, rule sets
│   ├── ingestion/              # Statement fetchers & parsers
│   ├── processing/             # Resolver, normalizer, classifier, nature tagger
│   ├── domain/                 # Domain models (budgets, CA view, net worth, audit)
│   ├── adapters/               # LLM provider abstraction, storage
│   └── api/                    # FastAPI routes
│
├── web/                         # TypeScript + Next.js (to be built)
│   ├── app/                    # Page components
│   └── lib/                    # Utilities
│
├── tests/                       # Test fixtures and runners (to be built)
│   ├── unit/
│   ├── property/
│   ├── golden/
│   └── integration/
│
└── Dockerfile                   # Local dev environment (Phase 0.2)
```

---

## Key principles

**From `CLAUDE.md`:**

1. **Correctness over speed.** Every displayed figure must be traceable to a source event. Never ship a number you can't justify.
2. **Six invariants that never break** (see `CLAUDE.md` §2):
   - No transaction hash is counted more than once.
   - Balance check passes or the parse is rejected — never partial.
   - Replay is deterministic.
   - Internal transfers never appear in expense totals.
   - A closed FY's projection never changes when tax rules update.
   - Nothing below confidence threshold enters the ledger without explicit confirmation.

3. **Pipeline ordering is hard-enforced** (see `CLAUDE.md` §3.3):
   ```
   Ingest → Parse → Resolve transfers/CC payments/FD → Normalize → Classify → Tag nature
   ```
   Resolver *must* run before classifier. Reordering breaks dedup.

4. **When uncertain, ask.** Never invent a tax rule, threshold, or business rule. If it's not in the spec, flag it and ask rather than guessing.

---

## How to contribute

1. **Before you code:** read `CLAUDE.md` completely. It's your operating manual.
2. **Pick a task:** from `docs/PROJECT_STATE.md` in your current phase.
3. **Read the spec:** locate the PRD/TRD section your task references. The spec is the work queue.
4. **Write code.** Follow `docs/CODE_GRAPH.md` dependency rules. Every module docstring should state the PRD/TRD section it implements.
5. **Run quality gates:** see `docs/QUALITY.md` for gates that must pass before merge (coverage thresholds, golden dataset, invariant tests, real-data guard, etc.).
6. **Update the log:** append to `docs/SESSION_LOG.md` and `docs/PROJECT_STATE.md` with what you did.

---

## Current phase

**Phase 0 — Foundations** (15 tasks)

Task: build the skeleton — repo structure, local Docker env, Postgres schema (immutable/mutable split), event-log primitives, replay mechanism, CI with the correctness harness.

**Exit criterion:** an event appends, a projection builds from it, replay produces identical output, all quality gates run and publish a report.

See `docs/PROJECT_STATE.md` for the full task board.

---

## Spec gaps to resolve

Writing user journeys surfaced 6 blocking gaps:

| # | Gap | Blocks | Status |
|---|---|---|---|
| G1 | **Auth/session/user model not specified** | Phase 5 | Open |
| G2 | **No onboarding sequence (order + UX)** | Phase 5 | Open |
| G3 | **Retroactive recategorization conflicts with closed-FY immutability** — architectural | Phase 3/4 | Needs decision + ADR |
| G4 | **"Eligible but untagged" deduction detection mechanism undefined** (highest-value feature, no mechanism) | Phase 4 | Open |
| G5 | **No-notification policy creates silent-staleness failure** | Phase 5 | Product decision |
| G6 | **No invite/provisioning flow for beta** | Phase 5 | Open |

See `docs/USER_STORIES.md` §14 for details and 12 non-blocking gaps.

---

## Testing strategy

- **Unit tests** (fast, no DB) for parsers, tax logic, hashing, resolver rules.
- **Property-based tests** for the six invariants (§2 above).
- **Golden datasets** — synthetic statements with known-correct ledger output. Any diff is a failure. Every bug found in real data becomes a permanent fixture here.
- **Integration tests** against ephemeral Postgres: ingestion path, dry-run harness, dedup, resolver, replay, Slack cash, tenant isolation.
- **E2E tests** (Playwright) for happy-path flows only.

See `docs/QUALITY.md` §3 for the full test pyramid.

---

## Spec is the work queue

The PRD, TRD, and User Stories are not documentation — they're the actual work queue. Every task you pick should:

1. Map to a PRD/TRD section.
2. Have explicit acceptance criteria.
3. Have test fixtures defined.
4. Trace back from the code via module docstrings.

If a task has none of these, it's out of scope.

---

## How AI agents should read this

1. **Start:** `CLAUDE.md` (entire file).
2. **Understand phase:** `docs/PROJECT_STATE.md` — current phase, what's done, what's next, blockers.
3. **Understand spec:** read the PRD/TRD sections your task references.
4. **Understand tests:** the task's acceptance criteria map to tests in `docs/QUALITY.md` or inline in the spec.
5. **Before merge:** ensure all quality gates pass (see `docs/QUALITY.md` for gates G1–G17).
6. **After merge:** append to `docs/SESSION_LOG.md` with what you did.

**Most importantly:** if ambiguous, ask rather than inventing. Ambiguity in the spec is a bug in the spec, not permission to guess.

---

## Links

- **Notion master hub:** [Finance Tracker — Master Hub](https://app.notion.com/p/3a6188e1a1038194bfb5c25a1c379ab4)
- **PRD:** [PRD: Expense, Budget & CA-Style Finance Health Tracker](https://app.notion.com/p/3a3188e1-a103-81e7-afba-c588fc8bd0c2)
- **TRD:** [TRD: Expense & CA-Style Finance Health Tracker](https://app.notion.com/p/3a5188e1-a103-8166-ae3a-ca60b2bb70ea)
- **User Stories:** [User Stories & Journeys](https://app.notion.com/p/3a6188e1-a103-81aa-8875-debf00f2c54c)
- **Competitive analysis:** see the master hub for links.

---

## Contacts

- **Owner (product decisions):** Sanket
- **CAs (tax logic review, Phase 4 gate):** TBD
- **Questions on spec?** Flag it in `docs/SESSION_LOG.md` and resolve before proceeding.

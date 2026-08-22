# Phase & Wave Execution Protocol

> This is the reusable procedure for executing any phase. It exists so that starting,
> running, and closing a phase doesn't depend on a hand-written prompt each time —
> read this file and self-execute the pattern below. Deviating from it (skipping a
> gate, weakening the report format) is itself a spec violation per `CLAUDE.md` §7.

This protocol was derived from how Phases 0–2 were actually run. It formalizes what
worked: propose before building, independently author tests for critical modules,
report with raw evidence rather than summaries, and never self-certify a gate closed.

---

## 1. Starting a phase

1. **Read first, in order:** `CLAUDE.md`, `docs/PROJECT_STATE.md`, the relevant
   PRD/TRD sections for this phase, and any User Story journeys that touch it.
2. **Confirm branch.** Cut a new branch from the latest merged main
   (`feature/phaseN`). State the exact merge-base commit.
3. **Restate the exit criterion as a testable checklist**, not a paragraph. Every
   acceptance criterion must be phrased so a specific test can prove or disprove it.
4. **Propose an execution order** (waves), with dependencies between waves stated
   explicitly.
5. **Identify critical modules for this phase** — anything where a wrong output is
   silent (double-counts money, wrongly excludes a transaction, corrupts a
   projection, mishandles a tax number). These require independent test authoring
   (§3).
6. **Do not write implementation code yet.** Stop after step 5 and wait for
   explicit approval of the plan.

## 2. During a wave

- Independently-authored tests come first for critical modules (§3), always as a
  separate, reviewable commit before the implementation commit.
- If a wave surfaces new scope not in the original plan (a new event type, a new
  matcher, a new config value) — **name it explicitly and ask**, don't fold it in
  silently. Per `CLAUDE.md` §7: ambiguity in the spec is a bug in the spec.
- If a wave depends on a shared primitive that risks duplication across multiple
  implementations (e.g. four matchers, or two parsers computing the same thing) —
  **ask whether it should be a shared function before writing four copies.** This
  class of bug (logic duplicated per-caller and drifting) has already happened twice
  in this project (occurrence_index in Phase 1, harness registration in Phase 1) —
  treat it as a known risk pattern, not a hypothetical.
- Config values that are known-uncalibrated (match windows, thresholds, LLM budget
  caps) must be named constants in one place, never literals scattered through
  logic — calibrating later should be a one-line change.

## 3. Independent test authoring (critical modules)

Per `CLAUDE.md` §6 and `QUALITY.md` §9. For any module on the critical list:

1. **Test-authoring session** reads the spec (PRD/TRD sections + acceptance
   criteria + relevant journeys) and the *contract* (e.g. `base.py`, an interface
   definition) — but does **not** open the implementation file.
2. Tests are committed **before** the implementation, as their own commit, with a
   commit message stating "independent test-authoring."
3. **Implementation session** reads the spec + contract, writes the implementation,
   does not open the test files until implementation is complete.
4. The wave gate confirms authorship independence by commit ordering — the test
   commit must predate the implementation commit.

## 4. Retroactive gaps (the F-9 pattern)

If a critical module's tests were ever co-authored with its implementation (gate
didn't exist yet, or was skipped under time pressure), it becomes a tracked gap:

1. Log it explicitly in `PROJECT_STATE.md` as a numbered gap with the module name.
2. Before it must close (usually: before the *next* phase's gate), run an
   independent re-authoring session per §3, comparing against the existing tests.
3. **Any disagreement between the re-authored tests and the existing tests is a
   finding, not noise.** If the re-authored test is stricter, it likely surfaces a
   real gap — write it up with a severity (see §6) and report before treating it as
   resolved.
4. **If a newly-written test fails against the existing implementation, that is a
   live undetected bug, not a test artifact.** Report it immediately. Do not
   silently patch and continue — this is exactly the situation the process exists
   to surface, and it needs visibility, not a quiet fix.

## 5. Ending a wave / phase — the report

**No self-certified "done."** Every phase/wave close requires a report built from
raw command output, not a summary of intent. Minimum contents:

1. **Commit history** for the phase/wave (`git log --oneline --stat <base>..HEAD`).
2. **File listing** of everything built (`find` or equivalent).
3. **Wave-by-wave status**: what was built, independent-authorship confirmed
   (commit-order evidence), pass/fail per wave.
4. **Full acceptance checklist**, every original criterion plus any added during
   review, each with: status (PASS / FAIL / NOT IMPLEMENTED) and the actual test
   name(s) proving it. **No criterion may be marked PASS without a named test.**
   "Syntax verified" / "covered by code review" are not PASS — they are NOT
   IMPLEMENTED with a note.
5. **Full test suite run**, actual output, actual pass count. Integration tests
   that require infrastructure (Docker, testcontainers) must actually be *run*
   against that infrastructure before being reported as passing — not asserted
   syntactically valid.
6. **Deviations, judgment calls, and ambiguities** encountered — reported even if
   already resolved, per `CLAUDE.md` §7. A report that hides its own gaps is more
   dangerous than one that lists them.
7. **Doc sync check**: current `PROJECT_STATE.md` phase section and any new
   `SESSION_LOG.md` entries, shown in full, not described.

## 6. Adversarial review (wave/phase gate)

Per `QUALITY.md` §8. Runs at the end of each wave/phase, from a **fresh context**
that did not build the wave. Checklist:

- Does any module diverge from the PRD/TRD section it claims to implement?
- Does any test assert behaviour the spec doesn't require (over-fit to the code)?
- Could an invariant break without an existing test noticing? (Try to construct
  the violating case, don't just check the invariant is *mentioned*.)
- Was any constant invented rather than sourced from spec/config? Flagged
  `# UNVERIFIED` if tax-related?
- Orphan code with no PRD/TRD traceability?
- Anything recomputed on replay that should have been a recorded event (the
  decisions-vs-derivations boundary, TRD §9.2)?

Findings get a severity:
- **CRITICAL** — a spec invariant with zero test coverage, or a confirmed bug.
  Blocks the gate. Must be fixed or explicitly test-covered before close.
- **GAP** — spec claims that existing tests don't verify. Triage: high-signal gaps
  tied directly to invariants get fixed now; lower-urgency ones get logged as
  tracked debt in `PROJECT_STATE.md`, not silently dropped.
- **NOTATION** — a representational difference only, no coverage problem. No
  action needed, just noted so it isn't mistaken for a discrepancy later.

**The gate does not close until CRITICALs are resolved.** GAPs may be triaged
(some now, some deferred) but must be visible in `PROJECT_STATE.md` either way.

## 7. Closing a phase

1. All waves report clean per §5.
2. Adversarial review (§6) run, CRITICALs resolved.
3. Any retroactive gaps (§4) targeting this phase's close are resolved or
   explicitly re-targeted to the next phase with reasoning.
4. **Wave-diff check:** list every wave that was actually executed and diff it
   against the approved plan. Any wave that was dropped, merged into another,
   or renamed must be called out explicitly as a deviation — with the reason —
   in the close report. A close report that silently omits a planned wave is
   not a close report; it is an incomplete record that prevents future diagnosis
   of missing coverage.
5. `PROJECT_STATE.md` updated: phase marked CLOSED with date, commit, and gate
   evidence. `SESSION_LOG.md` gets a closing entry.
6. Any bugs found *during* this phase's review process that trace back to a
   *previous* phase's shipped code get a short retroactive note in
   `docs/DECISIONS.md` — what the bug was, how it was caught, the fix. This is
   deliberately preserved (not just fixed and forgotten) as evidence for why the
   independent-authoring discipline exists.
5a. **Merge the phase branch into main; confirm the merge commit before cutting
    the next phase's branch.** A phase is not closed until the merge is on main —
    cutting from a feature branch that hasn't landed produces a next phase that
    will diverge from main when the PR eventually merges.
7. Only after 1–5a: cut the next phase's branch and begin its kickoff (§1).

## 8. What NOT to do

- Don't mark a criterion PASS on the strength of "should work" or "syntax valid."
- Don't let a wave's scope grow silently — new scope gets named and confirmed.
- Don't run unrelated feature work in parallel with a phase's critical-path waves
  "to save time" — this project has already lost a registration step (Phase 1)
  to exactly that kind of split attention.
- Don't treat a CRITICAL finding against existing shipped code as a private fix —
  report it, then fix it.
- Don't skip the independent-authorship separation because "it's a small module" —
  the two Phase 0 bugs caught by F-9 re-authoring (silent float acceptance, a
  corrupt snapshot returning an empty-but-plausible state) were both in modules
  that looked simple.

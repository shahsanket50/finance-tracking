# User Stories & Journeys

Companion to the PRD/TRD. Each journey describes what a real person experiences, in sequence. These serve three purposes: (1) acceptance criteria for "is this feature done", (2) the basis for integration and E2E test cases, (3) a stress test of whether the PRD/TRD can actually deliver the experience.

**Personas used:**

- **Sanket** (primary) — developer, salaried + some freelance, has stocks/MF, home loan, 2 credit cards. Knows expense management well, knows nothing about tax filing.
- **Beta user** — a developer friend, less patient, no context on how the product works.

Status legend on gaps: 🔴 blocking · 🟡 should fix before that phase · ⚪ nice to have

---

# Journey 1 — First run: signing up and landing in an empty product

**Trigger:** Sanket opens the deployed staging URL for the first time.

1. Lands on a login screen. Signs up (email + password, or OAuth).
2. Sees an empty dashboard: no accounts, no transactions, ₹0 everywhere.
3. The screen tells him what to do first, in order, rather than showing empty charts.
4. He picks "Connect Gmail" as step one.

**Acceptance criteria**

- A new account can be created and logged into.
- The empty state is instructional, not a broken-looking dashboard of zeros.
- There is a clear, ordered "do this first" path.
- No section of the app crashes or shows NaN/undefined with zero data.

**Maps to:** PRD §12.1 (dashboard), §13 (accounts)

**Gaps surfaced**

- 🔴 **Authentication is not specified anywhere in the PRD or TRD.** No signup, login, session, password reset, or account model. TRD §3.2 lists a `users` table but no auth flow. This blocks Phase 5 and needs a decision (own auth vs. a provider).
- 🔴 **No onboarding sequence is defined.** The PRD lists what data to collect (§10 cold start) but never the *order* or the UX of collecting it.
- 🟡 **Empty states are undefined** for every screen. With correctness-first as a principle, an empty CA view showing "₹0 tax liability" would be actively misleading — it must say "insufficient data", not zero.

---

# Journey 2 — Connecting Gmail and proving the parser works

**Trigger:** Sanket clicks "Connect Gmail".

1. OAuth consent screen; he grants read-only access.
2. App explains it will look for statement emails, and asks him to confirm which banks to watch for.
3. It finds 4 statement emails from the last 3 months. Two are password-protected.
4. He enters the statement password for each protected account (stored encrypted).
5. **Dry run:** for the first statement, he sees a preview table — every extracted transaction, the statement period, and a balance check line reading `Opening ₹42,150 + Credits ₹1,88,000 − Debits ₹1,63,400 = Closing ₹66,750 ✓`.
6. He spot-checks 3 rows against the actual PDF. They match.
7. He clicks Confirm. Only now do transactions enter the ledger.
8. The remaining 3 statements process; one fails (unrecognized layout) and is listed as failed with a reason, not silently skipped.

**Acceptance criteria**

- OAuth completes and the token is stored securely.
- Statement emails are discovered by sender/subject pattern with a PDF attachment.
- Password-protected PDFs open using stored credentials.
- The preview shows every extracted field per transaction plus the balance reconciliation.
- **Nothing is written to the ledger before Confirm.** (Abandoning the preview writes nothing — this is an explicit test.)
- A failed parse is visible with a reason, never silent.

**Maps to:** PRD §14.1–14.3, §13.2 · TRD Phase 1 · Invariants 2, 6

**Gaps surfaced**

- 🟡 **Bank/sender pattern list is not specified.** PRD §14.2 says "maintained list of sender domains" — who maintains it, and what happens for a bank not on the list? Needs a fallback (user points at an email manually).
- 🟡 **Statement password formats vary by bank** and PRD §14.1 mentions this only in passing. Needs a per-bank hint in the UI, or users will fail at step 4.

---

# Journey 3 — The invisible feature: credit card bill payment isn't double-counted

**Trigger:** Sanket's HDFC bank statement and his credit card statement both land for July.

1. Card statement shows 47 purchases totalling ₹52,300.
2. Bank statement shows one debit: `CC PAYMENT HDFC 4521` for ₹52,300.
3. He opens the dashboard. Total July spend shows **₹52,300 from the card, not ₹1,04,600.**
4. He notices the bank debit appears in his transaction list tagged `Transfer — CC Payment`, greyed out, marked "not counted as spend".
5. He taps it. It shows the matched counterpart: "Paired with HDFC Card statement, 47 transactions, July cycle."

**Acceptance criteria**

- The bank-side CC payment is detected and excluded from expense totals.
- The individual card purchases *are* counted, once each.
- The exclusion is visible and explained, not hidden — the user can see *why* a transaction wasn't counted.
- The pairing is inspectable (shows what it matched to).
- Resolver runs before categorization (invariant enforced in code).

**Maps to:** PRD §7, §15.2 · TRD ADR-006 · Invariant 4

**Gaps surfaced**

- 🟡 **Partial payments aren't specified.** If Sanket pays ₹30,000 against a ₹52,300 bill, PRD §7 says match "roughly equals statement due amount within a date window" — but a partial payment is a legitimate transfer too. Needs a rule: match on *any* payment to a known card account, not just full-amount matches.
- 🟡 **Match window tolerance undefined** — PRD flags this as needing calibration against real data. Until calibrated, this journey can fail silently.

---

# Journey 4 — Logging a cash expense from a restaurant

**Trigger:** Sanket pays ₹450 cash for lunch, standing outside the restaurant.

1. Opens Slack, types `450 lunch` in his `#cash-ledger` DM.
2. Within ~2 seconds the bot replies with a card: `₹450 · Lunch · Food & Dining · today · 👍 to confirm`.
3. He taps 👍 and pockets his phone. Total elapsed: under 10 seconds.
4. Later, on the dashboard, the transaction appears with a "cash — self-reported" badge.

**Variant:** he replies `dinner not lunch` instead — bot updates the preview and re-asks.

**Variant:** he sends a photo of a receipt — bot OCRs it and previews the same way (V2).

**Acceptance criteria**

- Free-text amount+description parses correctly.
- Bot responds in-thread with a structured preview.
- 👍 confirms; no reaction means it stays pending, never auto-committed.
- Correction by reply updates the preview.
- Cash entries are visually distinguished as self-reported everywhere they appear.
- Entry links back to the original Slack message in the audit trail.

**Maps to:** PRD §6, §15.3

**Gaps surfaced**

- 🟡 **Slack bot setup journey is not specified.** How does a beta user install the bot, authorize it, and get their channel linked to their account? This is a whole onboarding sub-flow that doesn't exist in the PRD.
- ⚪ **Pending entries need a home.** If he never reacts 👍, where does that entry live? Needs a "pending confirmations" surface, or entries silently vanish.

---

# Journey 5 — Weekly check-in on the dashboard

**Trigger:** Sunday evening, Sanket opens the app out of habit.

1. Dashboard: July spend ₹94,200 · income ₹1,52,000 · **surplus ₹57,800**.
2. Budget strip, worst-first: Dining 🔴 118% (₹11,800 of ₹10,000), Shopping 🟡 87%, others green.
3. Running-cost split shows: essential-fixed ₹58,000 · essential-variable ₹18,400 · discretionary ₹14,200 · luxury ₹3,600.
4. He sees his true monthly floor is ₹76,400 — meaningfully more than he assumed.
5. Taps Dining 🔴 to see the 6 transactions that blew it.

**Acceptance criteria**

- Surplus number is prominent and correct (income − spend − committed outflows).
- Budget bars sort worst-status first.
- Nature-split totals reconcile to total spend exactly.
- Every aggregate drills down to its constituent transactions.
- Month-basis by default; FY toggle available but not default here.

**Maps to:** PRD §12.1, §5, §4.2, §8

**Gaps surfaced**

- 🟡 **"Committed outflows" is used but never defined.** Does an upcoming EMI reduce today's surplus? Does a scheduled SIP? This materially changes the headline number and needs a definition.
- ⚪ **Mid-month statement lag.** Bank statements arrive monthly; on the 15th, the dashboard may only know about last month. Needs an explicit "data current as of" indicator or the surplus number is misleading.

---

# Journey 6 — Fixing a wrong category, and it sticking

**Trigger:** Sanket sees `SWIGGY INSTAMART` categorized as Food & Dining; he considers it Groceries.

1. Taps the transaction, changes category to Groceries.
2. Prompt: "Apply to all past and future Swiggy Instamart transactions?" He says yes.
3. 14 past transactions recategorize. Budget totals for the affected months update.
4. Next month's Instamart transaction is auto-tagged Groceries without asking.

**Acceptance criteria**

- Single-transaction correction works.
- Bulk-apply retroactively updates past transactions and dependent projections.
- The override persists and beats the model for that merchant, permanently.
- The correction is recorded as an event (`CategoryCorrected`), not an overwrite.
- Historical budget projections rebuild correctly after retroactive change.

**Maps to:** PRD §4.1 · TRD §3.1 (event types)

**Gaps surfaced**

- 🔴 **Retroactive recategorization vs. closed-FY immutability collides with Invariant 5.** If a correction changes a transaction in a *closed* financial year, does the CA report for that year change? Invariant 5 says a closed FY's projection never changes. But a genuine categorization fix arguably *should* update it. **This conflict is unresolved in the PRD/TRD and needs a decision.** Suggested: allow it but require explicit confirmation and record it as an amendment event visible in the audit trail.

---

# Journey 7 — Investigating a suspected duplicate

**Trigger:** Sanket thinks his June spend looks too high.

1. Opens the Audit view.
2. **Overlap map** shows two ingestion events for HDFC: a `Jun 1–30` statement and a `Jun 15–Jul 14` statement — bars visibly overlap for Jun 15–30.
3. He clicks the overlap. It lists 23 transactions in the overlapping window.
4. Each shows: `seen 2× · counted 1× ✓`. All green.
5. Confidence restored — the high spend is real, not a bug. He drills into categories instead.

**Acceptance criteria**

- Overlapping ingestion periods are detected and visualized per account.
- Every transaction shows seen-count vs counted-count.
- Seen>1, counted=1 renders green (dedup working); counted>1 renders red (bug).
- Every transaction traces back to the `ingestion_event_id` that created it.
- Resolver pairings are listed and inspectable.

**Maps to:** PRD §15.1–15.2 · TRD §3.4 · Invariant 1

**Gaps surfaced**

- ⚪ Audit view is V2 but basic dedup ships in V1 — during V1, Sanket has no way to *verify* dedup is working. Acceptable, but worth stating: V1 users trust the logic without an inspection surface.

---

# Journey 8 — Discovering money left on the table (the core value moment)

**Trigger:** Sanket opens the CA View tab in November, curious.

1. Tax Health ring: 3 green, 2 amber, 1 red.
2. Red section: **Deductions**. He expands it.
3. `80D — Health insurance · ₹0 of ₹25,000 · MISSED`. Sub-line: "Premium of ₹18,000 paid to HDFC Ergo in June, never tagged as deductible."
4. He clicks "Claim ₹18,000". It tags the transaction; 80D turns amber (₹18,000 of ₹25,000).
5. Regime comparison updates live: "New regime saves you ₹12,400 this year."
6. He never learned what Section 80D is. He just recovered ₹18,000 of deduction.

**Acceptance criteria**

- Deduction gaps are detected from *actual transactions*, not user memory.
- Each gap explains itself in one plain-English line.
- Acting on it is one tap.
- Downstream numbers (regime comparison, liability) recompute immediately.
- No tax jargon required to act.
- Every number shows its assumption/confidence trail.

**Maps to:** PRD §1.3, §1.8 · Core product thesis

**Gaps surfaced**

- 🔴 **The detection rule for "eligible but untagged" is not specified.** How does the system know an HDFC Ergo debit is a health insurance premium eligible for 80D? This needs either a merchant-category-to-section mapping table or an LLM classification step — **neither exists in the PRD.** This is the single highest-value feature and its mechanism is undefined.
- 🟡 **Confidence display is promised but never designed.** PRD says every tax number carries an assumption trail; no UI or data model for it exists.

---

# Journey 9 — Form 16 arrives and reconciles

**Trigger:** June, employer emails Form 16.

1. Checklist chip on home reads "2 documents pending this FY". He taps it.
2. `Form 16 — Razorpay — pending 🔴 (FY ended 2 months ago)`. He uploads the PDF.
3. Parser extracts gross salary, TDS deducted, deductions the employer considered.
4. Reconciliation panel: `Employer deducted ₹2,84,000 · Actual liability ₹2,61,500 · Expected refund ₹22,500`.
5. Plain-English note: "Your employer didn't know about your ELSS purchase in March or your full rent. Claim these while filing."
6. Checklist item turns green; the chip now reads "1 document pending".

**Acceptance criteria**

- Checklist correctly infers Form 16 is expected (employer detected in salary credits).
- Status color reflects overdue-ness.
- Form 16 parses; gross salary cross-checks against observed salary credits.
- Liability computed independently and compared to employer TDS.
- The delta is explained in plain English, with the specific reasons.
- Checklist state updates on successful upload.

**Maps to:** PRD §1.7, §3

**Gaps surfaced**

- 🟡 **Form 16 parsing spec doesn't exist.** §14 covers *bank statement* parsing in detail; Form 16 has a completely different structure (Part A/B, TRACES format) and gets one line. Needs its own parser spec before Phase 4.
- 🟡 **What if gross salary doesn't match observed credits?** (Common — reimbursements, arrears.) No mismatch-handling rule specified.

---

# Journey 10 — A capital gain that can't be computed

**Trigger:** Sanket sold ESOP shares last year; CAS is imported.

1. Capital Gains section shows 🔴.
2. `ESOP sale — TechCorp · ₹— unknown · MISSING DATA`.
3. Explanation: "No exercise-date fair market value on file. ESOPs are taxed twice — as salary perquisite at exercise, and as capital gains at sale. Without the exercise FMV, the gain can't be computed."
4. Action: "Upload exercise statement".
5. The FY total explicitly excludes this and says so: "Capital gains total excludes 1 instrument pending data."

**Acceptance criteria**

- Missing cost basis is detected and flagged red, never estimated or defaulted to zero.
- Totals visibly exclude unresolvable items and say so.
- The explanation teaches without jargon.
- Report-level confidence reflects the gap.

**Maps to:** PRD §1.4 · Correctness-first principle

**Gaps surfaced**

- ✅ None — this journey is well-covered. The "never guess, flag instead" discipline is consistently specified.

---

# Journey 11 — A sync breaks and he finds out (no notifications)

**Trigger:** Sanket changed his bank password 3 weeks ago. Statement parsing has been failing since.

1. He opens the app (his own initiative — no push notification by design).
2. Home screen shows a persistent chip: **"1 account needs attention"**.
3. Account Management: `HDFC Savings · 🔴 · Last synced 21 days ago · Statement password rejected`.
4. He updates the password.
5. "Backfill 3 missing statements?" → yes. They process through dry-run, he confirms.
6. Account turns green; dashboard totals correct themselves.

**Acceptance criteria**

- Failed syncs surface a persistent, non-dismissible indicator (no push, per D-decision).
- Per-account health is visible with a specific reason.
- Credentials are updatable.
- Backfill for the gap period is offered and works.
- Historical projections correct after backfill.

**Maps to:** PRD §13.1–13.3, §15.5

**Gaps surfaced**

- 🔴 **The no-notification decision has a real failure mode: silent staleness.** If he doesn't open the app for 3 weeks, his data is silently wrong for 3 weeks. The persistent chip only works if he opens the app. **Worth revisiting whether a single weekly email digest (not a push notification) is warranted** — it preserves the calm, pull-based philosophy while closing this gap.
- 🟡 **Data-freshness indicator missing.** Every screen showing money should show "as of" — otherwise the user can't tell stale from current.

---

# Journey 12 — Handing off to a real CA at filing time

**Trigger:** July, Sanket's CA asks for his numbers.

1. He opens CA View, taps Export.
2. Chooses "Full FY package".
3. Gets a PDF/Excel with: income summary, deduction schedule with evidence references, capital gains statement per instrument, and — critically — an assumptions & confidence page listing what data was missing.
4. He emails it. The CA files from it without asking follow-up questions.

**Acceptance criteria**

- Export produces a CA-readable document, not a raw transaction dump.
- Every figure is traceable to source.
- Missing-data caveats are prominent, not buried.
- The document states clearly it is a planning estimate, not a filed return.

**Maps to:** PRD §13.3 (export), V4 CA-handoff report

**Gaps surfaced**

- 🟡 **Export ships V1 but the CA-handoff *report* is V4.** V1 export is a transaction CSV — useful, but doesn't serve this journey. The journey above is only satisfiable in V4. Worth confirming this is intentional sequencing.

---

# Journey 13 — A beta user onboards without hand-holding

**Trigger:** Sanket sends a friend the staging link.

1. Friend signs up.
2. Guided setup: connect Gmail → confirm banks → enter statement passwords → dry-run first statement → confirm.
3. Sees a dashboard with real data within ~10 minutes.
4. He never messages Sanket for help.
5. His data is fully isolated — he cannot see Sanket's anything.

**Acceptance criteria**

- End-to-end onboarding completes unaided.
- Tenant isolation verified at the query layer, not just the API.
- No shared state leaks between users.
- The product is useful (not empty) after one statement.

**Maps to:** TRD Phase 5, T7 (isolation)

**Gaps surfaced**

- 🔴 **Same auth gap as Journey 1**, plus: no invite mechanism, no user provisioning flow specified.
- 🟡 **"Useful after one statement" is untested as a design assumption.** How much data does the CA view need before it says anything meaningful rather than mostly-red? Worth defining a minimum-viable-data threshold.

---

# 14. Summary of gaps surfaced

Writing these journeys surfaced **6 blocking and 12 non-blocking gaps** that the feature-list format hid.

## 🔴 Blocking — need resolution before the relevant phase

| # | Gap | Journey | Blocks |
| --- | --- | --- | --- |
| G1 | **Authentication/session/user model entirely unspecified** | 1, 13 | Phase 5 |
| G2 | **No onboarding sequence defined** (what order, what UX) | 1, 13 | Phase 5 |
| G3 | **Retroactive recategorization conflicts with closed-FY immutability (Invariant 5)** | 6 | Phase 3/4 — architectural |
| G4 | **"Eligible but untagged" deduction detection mechanism undefined** — the highest-value feature has no specified mechanism | 8 | Phase 4 |
| G5 | **No-notification policy creates silent-staleness failure mode** | 11 | Phase 5 — product decision |
| G6 | **No invite/provisioning flow for beta users** | 13 | Phase 5 |

## 🟡 Should fix before the relevant phase

Bank sender-pattern maintenance & fallback (J2) · statement password format hints (J2) · partial CC payment matching (J3) · match-window calibration (J3) · Slack bot setup flow (J4) · "committed outflows" definition (J5) · Form 16 parser spec (J9) · Form 16 vs observed salary mismatch handling (J9) · confidence/assumption trail UI + data model (J8) · data-freshness "as of" indicator (J11) · minimum-viable-data threshold (J13) · V1 export vs V4 CA report sequencing (J12)

## ⚪ Nice to have

Pending Slack confirmations surface (J4) · mid-month statement lag indicator (J5) · V1 dedup without an audit surface (J7)

---

# 15. How these are used

- **As acceptance criteria:** a feature is "done" when its journey runs end-to-end, not when its code merges.
- **As test cases:** each journey's acceptance criteria map directly to integration/E2E tests in `docs/QUALITY.md` §3.4–3.5.
- **As spec validation:** the gap list above is the immediate PRD/TRD backlog. G1–G6 should be resolved and written back into the PRD before their phases begin.

---

# 16. Journey Decisions (resolved)

All decisions taken in the journey walkthrough. These supersede any conflicting text earlier in this document or the PRD.

## J1 — First run

- **Auth: Google OAuth only.** One consent flow covers both identity and Gmail statement access — Journeys 1 and 2 collapse into a single permission step.
- **Onboarding: checklist style** — suggested order, skippable, not a forced wizard.
- **Empty states: explicit "insufficient data" message.** Never show ₹0 where the truth is "unknown" — a zero implies a computed answer.

## J2 — Gmail connection & parsing

- **Discovery: LLM-based.** Scan Gmail, identify bank/card from content rather than a hardcoded sender list.
- **Account matching:** if the account already exists → append transactions; if new → trigger new-account flow.
- **Scan bounds:** the ingestion log determines how far back to scan (incremental). **Hard cap: previous 2 financial years.**
- **First connect: start from today.** Backfill is a separate, explicit action — not an automatic 2-FY scan on day one.
- **"Not supported" defined:** three gates — (1) discovery: can we find the email, (2) access: can we open the PDF, (3) extraction: can we reliably pull the transaction table. "Unsupported" means gate 3 fails. A user-supplied sample PDF is the most valuable input for fixing it.
- **Failure UX: reason-specific prompts.** Not one generic error — "provide password", "parsing failed, upload a sample", "give us the subject filter". The parser already knows which gate failed.
- **Dry-run confirmation: first statement per account only**, then auto-trust.
- **Re-trigger confirmation:** any statement where confidence drops below threshold.

## J3 — Credit card de-duplication

- **Partial payments:** match *any* payment to a known card account, any amount — not only full statement-due amounts.
- **Card↔bank linking: auto-detect** by cross-referencing debit and credit of the same amount on the same day (or ±N days).
- **Data model change: transaction type becomes a first-class field** — `income | expense | transfer | investment`. This replaces "expense with an exclusion flag". Consequences:
    - Nature tags (essential-fixed / essential-variable / discretionary / luxury) apply **only to `expense`**.
    - FD bookings and SIPs become `investment`, not awkwardly-excluded expenses.
    - CC bill payments and self-transfers become `transfer`.

## J4 — Cash entry via Slack

- **Setup: DM with the bot.** No channel creation, no invite flow — works immediately after OAuth.
- **Unconfirmed entries auto-confirm after 24h** if no correction is made.
- **Pending entries live in an in-app "pending confirmations" list.**
- **Invariant 6 clarification:** auto-confirm does *not* weaken Invariant 6. That invariant guards *AI-parsed* data entering the ledger unconfirmed. A cash entry is user-typed input — auto-confirming is confirming the user's own statement, not an AI guess. Recorded so this is not "fixed" later by mistake.

## J5 — Dashboard

- **"Surplus" renamed to "Available to invest".**
- **Definition:** income − money already spent − **all committed outflows** (rent, EMI, SIP, insurance).
- **Data freshness: both** a global "data as of" banner and per-account freshness indicators.
- **Current month: show actuals, plus a separate projected line** — never blend the two into one number.
- **Dependency flagged:** "committed outflows" requires recurring detection, currently V2. In V1, commitments must be defined manually at setup or derived from history.

## J6 — Category correction (resolves G3)

- **Closed FY: allow the change**, with an explicit warning, recorded as an amendment event. The original is preserved.
- **A financial year becomes "closed" automatically after the ITR filing deadline passes.** (Date is FY-specific and lives in the versioned rule-set, since it varies and is sometimes extended.)
- **Open FY retroactive apply:** show the user exactly which transactions are impacted; they select/deselect. Never silent, never all-or-nothing.
- **Invariant 5 restated:** *a closed FY's projection never changes silently. Amendments are permitted but require explicit confirmation, are recorded as amendment events, and preserve the original.*

## J7 — Audit & duplication view

- **V1 ships dedup logic without an audit view** — accepted risk, users trust the logic until V2.
- **Audit view shows everything, with classifications, filterable** — duplicate, low-confidence, transfer-detected, investment-detected, etc. Not problems-only.

## J8 — Deduction detection (resolves G4)

- **Mechanism: hybrid.** Curated merchant→section table for known cases, LLM for unknowns, **user confirms both**.
- **Ambiguous merchants: ask once per merchant, then remember** — reuses the existing category-override pattern (e.g. "HDFC Ergo — is this health or motor insurance?" asked once, applied forever).
- **Tagging: auto-tag only on high confidence**, otherwise ask.
- **Proof: not required.** Transaction evidence is sufficient for planning purposes. (Consistent with not being a filing tool.)

## J9 — Form 16 reconciliation

- **On mismatch with observed salary credits: trust Form 16** (the official document), but **show the delta as a note** — mismatches are usually reimbursements or arrears, and are informative rather than errors.
- **Multiple Form 16s supported in V1**, with **auto-detection that a second employer exists** (from distinct employer names in salary credits).
- **Form 16 uses the same dry-run preview + confirm flow** as bank statements.

## J10 — Missing cost basis

- No decisions required. The "never guess, flag instead" behaviour is already fully specified and consistent.

## J11 — Broken sync (resolves G5)

- **Exception-based alerts only** — no weekly digest, no push. Rationale: a digest becomes wallpaper and gets ignored precisely when it matters; exception-based means an alert from this app always requires attention. Silence genuinely means everything is fine.
- **Channel is user-configurable: Slack, email, or both.** Default is Slack if the bot is already connected (it will be, for cash entries), otherwise email. Set in Account Management / notification preferences.
    - **Slack** — delivered as a bot DM, same channel as cash entries. No extra integration cost; for a developer audience it is usually seen faster than email.
    - **Email** — fallback for users who skip the Slack setup, or who prefer a written record.
    - **Both** — for anything the user marks as critical.
- **Alert-worthy events (exception-based, not routine):** sync failure after retries, credential rejection, statement parse failure, confidence below threshold requiring confirmation, and a document overdue past its grace period (e.g. Form 16 two months after FY end).
- **Auto-retry silently** a few times before surfacing anything.
- **After the user fixes credentials: auto-backfill the missed period silently.**
- Full flow: fail → silent retries → still failing → one alert on the chosen channel(s) → persistent in-app chip → user fixes → silent backfill.
- **Still no push notifications.** The pull-based philosophy holds; Slack/email are exception-only and never routine.

## J12 — CA handoff

- **V1 ships CSV export *plus* a simple summary PDF** (upgraded from CSV-only).
- **PDF is the primary format** CAs want — clean and final-looking.
- **The assumptions & missing-data caveats page ships from V1**, not V4. Rationale: if ESOP cost basis is missing, the CA must know or they will file wrong numbers from the document. A footer disclaimer is legal cover; a caveats page is actionable. Real CA reports always state assumptions — it reads as more professional, not less.

## J13 — Beta onboarding (resolves G6)

- **Access: invite-only via an email allowlist** maintained by the owner.
- **Minimum-data bar: show a "setup progress" indicator** until there is enough data for the app to be meaningful, rather than picking an arbitrary threshold.
- **Isolation: strict — the owner cannot see beta users' data**, even for debugging. Debugging must rely on logs, error reports, and synthetic reproduction.

---

# 17. Gap status after resolution

| # | Gap | Status |
| --- | --- | --- |
| G1 | Auth / session / user model | **Resolved** — Google OAuth only (J1) |
| G2 | Onboarding sequence | **Resolved** — skippable checklist (J1) |
| G3 | Retroactive recategorization vs closed-FY immutability | **Resolved** — amendment model, Invariant 5 restated (J6) |
| G4 | Deduction detection mechanism | **Resolved** — hybrid table + LLM + confirm (J8) |
| G5 | Silent-staleness failure mode | **Resolved** — exception-based email (J11) |
| G6 | Beta invite / provisioning | **Resolved** — invite-only allowlist (J13) |

**All 6 blocking gaps resolved.**

## Non-blocking gaps also resolved

Bank sender-pattern maintenance (J2) · statement password prompts (J2) · partial CC payment matching (J3) · Slack bot setup (J4) · "committed outflows" definition (J5) · Form 16 mismatch handling (J9) · data-freshness indicator (J5) · minimum-viable-data threshold (J13) · V1 export sequencing (J12) · pending Slack confirmations surface (J4) · mid-month lag indicator (J5) · V1 dedup without audit surface (J7, accepted).

## Still open

- **Match-window tolerance calibration** (J3) — requires real statement data to tune; cannot be decided in the abstract.
- **Confidence/assumption trail UI design** (J8) — mechanism now decided, but the visual design is unspecified.
- **Form 16 parser spec** (J9) — flow decided, but the TRACES Part A/B structure needs its own parser specification before Phase 4.

---

# 18. Notification Model (supersedes J11 in §16)

Two tiers. Alerts are mandatory; milestones are opt-in and off by default.

## Tier 1 — Alerts (always on, cannot be disabled)

Something is wrong and needs the user. These are the reason the notification system exists; silence must never hide a failure.

- Sync failure after retries are exhausted
- Credential rejection (statement password changed, OAuth token expired, AA consent lapsed)
- Statement parse failure
- Confidence below threshold, requiring user confirmation
- Document overdue past its grace period (e.g. Form 16 still missing two months after FY end)
- Possible duplicate or resolver conflict requiring a decision

## Tier 2 — Milestones (opt-in, OFF by default)

Informational only. The product works correctly if a user never enables any of these.

- Sync/pull completed successfully
- N transactions ingested and categorised this cycle
- Backfill completed
- New account or card detected from the Gmail scan
- Form 16 expected date reached (employers usually issue around June)
- ITR filing deadline approaching
- Advance-tax installment due date approaching
- Deduction milestone reached (e.g. 80C now maxed)
- FY closing soon — last window to act on deductions

**Each Tier 2 event type is individually toggleable** — not one blanket "send me updates" switch. Someone who wants only tax-deadline reminders should not also receive sync-success messages.

## Channel

- **User-configurable: Slack, email, or both.** Default is Slack when the bot is connected (it will be, for cash entries), otherwise email.
- **Slack** — bot DM, the same channel as cash entries. No additional integration cost, and typically seen faster than email by a developer audience.
- **Email** — fallback for users who skip Slack setup, or who prefer a written record.
- Channel choice applies to both tiers. Only *whether* Tier 2 sends is optional — never Tier 1.

## Behaviour

- **Auto-retry silently** a few times before any Tier 1 alert fires.
- **After the user fixes credentials: auto-backfill the missed period silently.**
- Full failure flow: fail → silent retries → still failing → Tier 1 alert → persistent in-app chip → user fixes → silent backfill.
- **Still no push notifications and no digest.** With default settings, the user hears from the product only when something is wrong.

## Where it's configured

Account Management → Notification preferences: channel selection, plus per-event toggles for Tier 2. Tier 1 events are listed but shown as always-on, so the user can see what the product will contact them about.
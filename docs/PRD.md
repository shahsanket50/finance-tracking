# PRD: Expense, Budget & CA-Style Finance Health Tracker

**Status:** Planning (Phase 0) · **Owner:** Sanket · **Last updated:** July 2026

---

## 0. Product Summary & Scope

A personal finance product for Indian developers that combines two usually-separate layers on a single transaction ledger:

- **Day-to-day layer:** expense tracking, budgeting, cash logging, net worth.
- **CA-style layer:** a continuous tax health view (income, deductions, capital gains, assets, liabilities, regime comparison, advance-tax) that updates as transactions arrive, without waiting for year-end filing season.

**Does NOT:** file ITR, hold money, offer lending/investments. **Does:** produce planning-grade reports a user (or their CA) can act on immediately.

**Personas:** primarily developers — salaried + freelance, with stocks/MF, home loans, credit cards, some ESOP exposure. Secondary: anyone who wants tax insight without hiring a CA until filing time.

---

## 1. CA-Style Finance Health View

The product's core differentiator. A continuous ledger-powered view into tax health, updated as transactions arrive.

### 1.1 Income Summary

- Salary (from Form 16 / observed salary credits)
- Freelance / business income (self-reported or inferred from deposits)
- Investment income (interest, dividends, rental)
- Other income (gifts, insurance payouts, etc.)
- Total: used as the base for regime computation and deduction limits.

**Status chip:** green (complete), amber (partial / awaiting docs), red (missing).

### 1.2 Deductions & Exemptions

80C (₹1.5L limit): ELSS, insurance premiums, PPF, NPS, tuition, home-loan principal.
80D (₹25k health insurance + ₹50k senior parent): premiums tagged from transactions.
80E (education loan interest): statement from lender, annual reconciliation.
80G (donations): charitable giving with proof.
Other sections: 80EE, 80EEA, 80CCD(1B), etc.

**Mechanism:** hybrid deterministic + LLM. A curated merchant→section table for known cases (ICICI insurance → 80D); LLM fallback for unknowns; user confirms both. Ask-once-per-merchant, remember forever. Never auto-commits below high confidence.

**Status:** each deduction shows rupees claimed of the limit (e.g. "₹18,000 of ₹1,50,000 80C claimed"), eligibility, required documents, and a one-line explanation of the rule.

**Gap detection:** transactions matching eligible patterns are flagged as "possible 80C" if unclaimed, with an explanation ("HDFC ELSS fund purchase") and one-tap claim.

### 1.3 Capital Gains

Equity (long-term indexation benefit at 20%, short-term at slab rate): cost basis from CAS/purchase statements, sale proceeds from broker P&L.

Mutual funds (same as equity): NAV-based cost basis, redemption proceeds.

Real estate (20% + indexation if >2yr): purchase deed, registration, sale deed. Cost basis = purchase + improvements.

FDs/bonds (savings-account rate): interest is ordinary income, principal return is not taxable.

Crypto (30% flat, no set-off): 1% TDS on transfers; exchange data integration (CoinDCX, CoinSwitch) in V3.

**Missing-data handling:** flagged red with a reason ("no purchase date FMV for this ESOP lot"), and the FY total visibly excludes it and says so: "Capital gains total excludes 1 instrument pending data."

### 1.4 Assets & Net Worth

Bank accounts (via statement ingestion), credit card balances, mutual fund holdings (via CAS), stocks (via broker CAS), real estate (manual entry + property registration docs), loans (bank statements + loan deed).

**Net worth = all assets − all liabilities.**

**Net worth trend:** snapshots per quarter or FY, tracking drift. Allocation % shown (stocks, MF, real estate, cash), with drift alerts.

### 1.5 Liabilities

Home loan (principal + interest from statement), car/vehicle loans, personal loans, education loans, credit card balances.

**For each:** EMI schedule, interest paid YTD, remaining tenure, prepayment penalties.

### 1.6 Employer TDS vs Actual Liability

**Form 16 reconciliation (dedicated):**
- Employer deducted (from Part B, section 192 TDS)
- Actual liability computed from income + deductions + regime
- Delta: refund due or additional tax owed
- Reason explained: "Your employer deducted on gross salary but didn't know about your ELSS or full rent."

**This is the single most-used CA view for salaried individuals and often appears on the home screen.**

### 1.7 Advance-Tax Planner

**New in V2.** Income liability projected forward into four quarterly due dates (15 Jun, 15 Sep, 15 Dec, 15 Mar), with cumulative % thresholds:

- 15 Jun: 15% of annual liability due
- 15 Sep: 45% cumulative
- 15 Dec: 75% cumulative
- 15 Mar: 100% cumulative

Status color = worst upcoming/overdue installment.

**Interest warning:** if a due date is missed, Section 234B interest (12% p.a.) accrues — a plain-English note shows the rupee cost of missing it.

### 1.8 Regime Comparison

**Old regime** (72(1), 72A) vs **new regime** (115BAC): both computed for the full FY, tax payable shown side by side, savings or additional cost called out.

**Updated live:** as income and deduction events arrive.

**Regime assumption** shown: if cost basis or loss carry-forward is missing, note it as a caveat.

### 1.9 Form 16 / TDS Reconciliation

When Form 16 is uploaded:

- Gross salary cross-checked against observed salary credits (flag mismatch as a note, not an error).
- TDS deducted (Part B, section 192): shown vs. computed liability.
- Deductions the employer considered (if listed in Part B): compared to user's actual deductions (e.g. "employer listed ₹0 for home loan, user claims ₹1.2L").
- Reconciliation status: pending, mismatch flagged, resolved.

**Missing:** if Form 16 hasn't arrived by June 30 of the following year, it's marked overdue and a notification is sent (Tier 1 alert).

---

## 2. Data Ingestion & Automation

### 2.1 Sources (by version)

**V1:**
- Gmail PDFs (user forwards statements manually, or app discovers via LLM scan)
- Account Aggregator (AA framework, top banks)
- Manual upload (bank statements, CC statements, Form 16, CAS, AIS, EPF passbook)
- Slack cash entries (text only)

**V2:**
- Gmail automated retrieval (restricted scope, requires Google verification; one-time setup)
- AA webhooks (near-real-time)
- PDF extraction pipeline (ML + template parsers + LLM fallback)

**V3+:**
- Broker APIs (Zerodha Kite, Upstox, others)
- Direct 26AS pull (via ERI registration)
- Crypto exchange APIs

### 2.2 UPI-Native Parsing

**Design constraint for V1.** 80%+ of Indian digital payments are UPI; the ingestion pipeline must handle UPI natively, not as a retrofit:

- Sub-₹100 noise is normal (chai, autorickshaw) and expected; never flag as suspicious.
- High transaction velocity: a user may have 20+ UPI transactions in a day; the system must not buckle.
- UPI handle → merchant name resolution: "paytm_UPI_12345@okhdfcbank" → "Swiggy" (requires merchant mapping).

### 2.3 Backfill Bounds

**Gmail discovery:** scan up to **2 previous financial years** from today. Rationale: 2 years is enough to catch most ongoing income and deductions; older cost basis for capital gains is uploaded explicitly (no time limit on documents).

**Incremental scanning:** after initial setup, the ingestion log tracks how far back we've seen, so the next scan starts from the last confirmed statement, not the beginning.

---

## 3. Data Segregation & Filters

### 3.1 Month vs. FY Toggle

**Month view:** calendar month (1st to last day), for day-to-day tracking. Budget status, spend trends, surplus. Default for most users most of the time.

**FY view:** financial year (1 April to 31 March), for tax and planning. Income, deductions, capital gains. Only shown when explicitly toggled.

**Rationale:** users think in calendar months; tax thinks in FY. Mixing them is confusing.

### 3.2 Data Segregation Rules

- A transaction belongs to exactly one month and exactly one FY.
- Projections (budgets, net worth) rebuild independently for each month and each FY.
- Changing a transaction's FY is not a normal operation; it requires explicit user confirmation.

---

## 4. Categorization & Budgeting AI

### 4.1 Processing Pipeline Order (HARD CONSTRAINT)

```
1. Ingest raw artifact
2. Parse + validate (balance check)
3. Relationship resolver   ← transfers / CC payments / FD bookings
4. Merchant normalization
5. Category classification
6. Nature tagging (essential / discretionary / luxury)
```

**Step 3 MUST run before step 5.** If categorization runs first, a credit-card bill payment gets counted as spend *on top of* the individual purchases, silently inflating every budget total. This is enforced in code and asserted in tests.

### 4.2 Categorization

**V1:** rules-based + user override. Categories are fixed; the rules match narrations to categories.

**V2:** LLM-assisted classification. High-volume/low-stakes (categorization) → cheap model; low-volume/high-stakes (unmatched layouts) → stronger model. Confidence gates: below threshold → review queue, never auto-commit.

**Per-user learning:** user corrects a transaction's category → rule is learned for that merchant forever.

---

## 5. Derived Spend Concepts

### 5.1 Running-Cost vs. Discretionary/Luxury

A second dimension layered on top of categories. Every expense transaction tagged with a *nature*:

- **Essential-fixed:** rent, insurance, loan EMI. Expected monthly, amount is predictable.
- **Essential-variable:** groceries, utilities, fuel. Expected monthly, amount varies.
- **Discretionary:** dining out, entertainment, shopping. Optional, wants vs. needs.
- **Luxury:** high-end restaurants, international travel, premium subscriptions. Aspirational spending.

**Dashboard shows running-cost total:** essential-fixed + essential-variable = your monthly floor. If that's ₹76,400 and your surplus is ₹57,800, you're tighter than you thought.

**Nature detection:** rules-based for obvious cases (rent to landlord → essential-fixed), LLM + user confirm for marginal cases.

---

## 6. Cash Transactions via Slack

### 6.1 Entry Mechanism

User types `450 lunch` in a Slack DM with the bot. Bot replies with a structured preview: `₹450 · Lunch · Food & Dining · today · 👍 to confirm`.

User reacts 👍 (or types a correction, e.g. "dinner not lunch" and re-confirms).

**Auto-confirm:** if no reaction within 24h, the entry is auto-confirmed.

**Pending list:** unconfirmed entries are visible in an in-app "pending confirmations" list.

### 6.2 Metadata

Each cash entry carries:
- Original Slack message link and timestamp
- Parsed amount, description, category, date
- Confirmation status (pending, confirmed auto, confirmed manual, corrected)
- "cash — self-reported" badge on the transaction

### 6.3 Possible Double-Entry Detection

If a cash entry of ₹450 for "lunch" arrives the same day a card transaction of ₹450 to a food merchant also lands, a flag: "you logged ₹450 cash lunch and also charged ₹450 to Swiggy. Did you do both?" (See Audit Trail, section 15.)

---

## 7. Transaction De-duplication

### 7.1 Relationship Resolver

Runs before categorization. Detects and excludes:

- **Internal transfers:** user moves ₹50k from HDFC to ICICI on the same day; only one appears as a "transfer," not two opposites in expense totals.
- **CC bill payments:** user's bank shows a debit `CC PAYMENT HDFC 4521` on 28th; the card statement shows 47 purchases totaling the same amount. Only the individual purchases count as expenses.
- **FD bookings & maturity:** `FD_CREATED -1L` on 1st and `FD_MATURED +1L` on 31st are a pair; neither counts as spend/income.

**Matching logic:**
- Bank account + date + amount + (optionally) narration pattern.
- Partial payments are valid matches (e.g., paying ₹30k of a ₹52k CC bill). The partial payment is still excluded from spend.
- Match window: tuned per bank (typically ±3 days for CC payments).

**Output:** a `MarkedInternalTransfer` event (or equivalent) is recorded. On replay, that pairing is read, never recomputed.

### 7.2 The Idempotency Hash

Every transaction has a stable identity hash:

`hash(account_ref + value_date + amount + normalized_narration + occurrence_index)`

Same transaction arriving via two sources produces the same hash → counted once, not twice.

**occurrence_index:** the ordinal of this transaction within its (account, date, amount, narration) group as it appears in the source statement. Distinguishes two real ₹250 coffees from one re-ingested duplicate.

**Running_balance is NOT part of the hash** — it's not stable across statement regenerations and would cause collisions.

---

## 8. Credit Cards

### 8.1 Dual Model

**Spend account:** transactions on the card. Categorized, budgeted, fed into "Available to invest."

**Liability account:** the outstanding balance. Updated when the statement arrives; decreases when a payment is made.

### 8.2 EMI Conversion

If a purchase is converted to EMI (0% or interest-bearing), the transaction is retagged:

- **Original transaction:** marked as "EMI source," amount recalculated (down, if interest-free; up, if interest).
- **EMI schedule:** separate line items per month showing principal + interest.

**Net effect:** the original lump-sum amount is not counted in the month it was purchased; instead, the EMI installments are counted each month they're due.

### 8.3 Statement Cycle vs. Calendar Month

Card statements run on a date (e.g. 1st–30th), not a calendar month. The dashboard normalizes this:

- **Transactions are allocated to the calendar month they occur** (regardless of statement cycle).
- **Statement period is shown separately** ("covering 1–30 Jan, reviewed on 2 Feb") for reference.

---

## 9. Data Initialization / Cold Start

On first use, the user uploads:

- **Last 2 FY of bank statements** (PDFs or via AA).
- **Last 2 FY of credit card statements.**
- **Most recent Form 16** (from last filing).
- **CAS** (from all brokers/MF platforms).
- **AIS** (optional; from 26AS if available).
- **EPF passbook** (optional; from your employer or e-pass).
- **Loan documents** (if EMI claims are relevant).
- **Property registration** (if capital gains or liability tracking is planned).

The ingestion pipeline processes these in parallel; any parse failures are flagged and retried with the dry-run harness.

---

## 10. FY Completeness Ledger

A checklist view showing what documents/data are needed for a tax-ready view:

- Form 16: expected (from known employer), status (pending, received, reconciled).
- CAS: expected (from broker activity), status.
- AIS (optional for most): status.
- Capital gains documents: Form 8 (if applicable), property sale deed, etc.
- Deduction proofs: insurance policies, loan deeds, donation receipts.

**Status:** color-coded (green = received + reconciled, amber = partial / awaiting, red = missing + overdue).

**Checklist interaction:** mark as "will not file" if an expected doc is not applicable (e.g., no investment, so no CAS needed).

---

## 11. Roadmap & Versioning

### 11.1 Version Themes

| Version | Theme | Proves |
|---|---|---|
| V1 - MVP | Manual-upload-driven, rules-based, zero automation risk | Data model + CA view UX are sound. Users understand the value. |
| V2 - Automation | Gmail/PDF ingestion, AI categorization, full resolver, dedup audit trail | Automated ingestion saves time + stays accurate. LLM categorization is trustworthy. |
| V3 - Scale & Compliance | Webhooks, broker APIs, ESOPs, multi-employer, crypto, ERI | Long-tail edge cases handled. Infra scales. |
| V4 - Advisory | Tax-saving recommendations, scenario simulator, goal planning | Only viable once V1–V3 data is trustworthy. Recommendations add material value. |

### 11.2 Sequencing Logic

- **Each version is gated by a working demo.** Not shipped until the exit criterion is met.
- **Correctness > speed.** A delayed correct release beats a fast buggy one.
- **Deferred decisions:** things that require real data (LLM budget tuning, match-window calibration) are decided once V2 is live and running against real transactions.

---

## 12. Dashboard & Analytics

### 12.1 Dashboard (Day-to-Day, Month Basis)

Home screen. Month view by default.

- **Headline number:** "Available to invest" = income − spend − committed outflows (rent, EMI, SIP).
- **Budget strip:** worst-status-first. Dining 🔴 118%, Shopping 🟡 87%, others 🟢.
- **Running-cost split:** essential-fixed, essential-variable, discretionary, luxury. Totals reconcile to total spend exactly.
- **Recent transactions:** last 10, with category and status (confirmed, awaiting confirm, low confidence).
- **Data freshness:** "as of [date]" — when the last statement was synced.

All numbers are tappable to drill down.

### 12.2 Analytics Screen

Deeper than dashboard. Month or FY basis.

- **Spend trends:** month-on-month, category breakdown, category trends (growing / shrinking).
- **Savings rate:** % of income saved (surplus / income).
- **Merchant leaderboard:** top 10 by spend (by category or total).
- **Cash-flow runway:** "at this burn rate, you have X months of runway before depleting emergency fund" (if an emergency fund is defined).

---

## 13. Account Management

### 13.1 Connected Accounts

List of all linked banks, CC, brokers, platforms:

- Account name + last 4 digits (for security).
- **Sync health:** green (last sync <24h), amber (sync pending / last sync 2–7d), red (sync failed >7d).
- Sync health reason: "password rejected," "parsing failed," "awaiting manual review," "no new statements."
- Last synced timestamp.
- Manual re-sync button.
- Backfill offer: "reconnect this account to backfill [date range]."

### 13.2 Notification Preferences

Channel selection (Slack, email, or both) + per-event toggles for Tier 2 milestones (Tier 1 alerts are always on).

### 13.3 Export & Handoff

**CSV export:** for the user to share with a spreadsheet or CA.

**PDF summary:** includes income, deductions, capital gains, assumptions, missing-data caveats. **Caveats page ships from V1**, not V4 — the CA must know what data is missing.

**Excel (V2+):** richer formatting, multiple tabs, formulas.

---

## 14. Gmail Statement Ingestion — Parser Spec & Dry-Run Guide

### 14.1 Discovery

**LLM-based scan** of the user's Gmail. Identifies bank statements and CC statements by content, not sender address. Account matching: if the extracted account number matches an existing account → append transactions. If new account detected → new-account flow.

### 14.2 Parsing

**Template-based first** (per-bank layouts). If no template matches, **LLM fallback** with structured schema output (Pydantic).

**Extracted fields per transaction:**
- Date (posting date or value date, as stated in the statement)
- Narration (full, untruncated)
- Debit (if applicable)
- Credit (if applicable)
- Running balance (if present in the statement)

**Balance check:**
`opening_balance + sum(credits) − sum(debits) = closing_balance`

If balance check fails → parse is rejected and logged. Never partially ingested.

### 14.3 Dry-Run Harness

Standalone preview mode. User selects a statement PDF:

1. **Parser runs.** Extracts transactions, shows a preview table.
2. **Balance check runs.** Shows `opening + credits − debits = closing` with green ✓ or red ✗.
3. **Confidence score** shown (e.g., 95% for a recognized bank template, 60% for an LLM fallback).
4. User spot-checks rows against the PDF.
5. **Confirm or Abandon.** Only on Confirm does anything write to the ledger.

**Nothing writes until Confirm.** Abandoning writes nothing.

---

## 15. Audit Trail & Ingestion Log

A chronological record of everything that entered (or was rejected from) the system.

### 15.1 Ingestion Event Log

One row per sync/upload/Slack entry. Fields:

- `event_id`, `timestamp`
- `source` (AA / Gmail / Slack / manual)
- `source_detail` (which account, which email, which Slack message)
- `period_covered` (from–to dates for statements)
- `records_added`, `records_skipped_duplicate`, `records_flagged` (counts)
- `balance_check` (pass / fail)
- `confidence` (parser confidence)
- `status` (success / partial / failed / rejected)

### 15.2 Duplication-Detection View

**Level A — overlap map (batch level):** timeline showing each ingested statement as a bar across its `period_covered`, grouped by account. Overlapping bars are highlighted.

**Level B — transaction-level dedup ledger:** every transaction shows its idempotency hash, how many times it was *seen* (ingested), and how many times it was *counted* (in expense totals).

- Seen 2×, counted 1× → green (de-dup working).
- Counted >1× → red (bug).

**Resolver audit:** every internal-transfer, CC-payment, and FD-booking pair is listed with its matched counterpart, so the user can verify the pairing.

### 15.3 Slack Cash-Entry Audit

Each Slack entry links back to the original Slack message. Shows: parsed amount, category, date, confirmation status (pending / auto-confirmed / user-confirmed).

Possible cash/bank double-entry flag: "you logged ₹450 cash lunch and also charged ₹450 to Swiggy. Did you do both?"

---

## 16. Locked Decisions

Decisions made and locked during planning. Superseding any earlier text in this PRD.

| # | Decision | Status | Rationale |
|---|---|---|---|
| D1 | Product does NOT file ITR — planning & tracking only | Locked | Avoids ERI/compliance liability; delivers the insight layer people currently pay ClearTax/TaxBuddy for at filing time. |
| D2 | SMS sync dropped entirely | Locked | Gmail-PDF parsing (plus AA where used) is the ingestion path. Avoids Android SMS-permission friction; simpler pipeline. |
| D3 | Bring-your-own-key AI — skipped | Locked | Server-side LLM only. BYO-key adds product complexity for a narrow benefit. |
| D4 | Multi-currency — skipped | Locked | India-tax-centric; foreign income handled in the CA capital-gains layer, not the expense layer. |
| D5 | Neobank / lending — not pursued | Locked | Staying a pure insight/planning layer is a positioning strength, not a gap. |
| D6 | UPI-native parsing — build in V1 | Locked | 80%+ of Indian digital payments are UPI; design the pipeline UPI-native, not retrofit. |
| D7 | Recurring/subscription detection — build in V2 | Locked | Table stakes; reuses resolver machinery; feeds the essential-fixed nature tag. |
| D8 | Transaction export (CSV/Excel/PDF) — build in V1 | Locked | Export is the CA-handoff mechanism; cheap; shouldn't wait for V4. |
| D9 | Split/shared expenses — fold into V3 family view, not standalone | Locked | Overlaps the family/HUF view; not a separate product motion. |
| D10 | Predictive/proactive budgeting — V3 | Locked | Depends on trustworthy V2 categorization + per-user history; premature earlier. |

All feature-to-version mapping lives in the Feature Version Tracker database (51 features, all version-assigned). This PRD is the full-vision source of truth; the tracker is the build-sequencing source of truth. When they disagree, the tracker wins for *what ships when*, this PRD wins for *what the feature is*.

---

## 17. Competitive Analysis Summary

Four competitive studies exist as companion docs. This section captures only the decisions and build-actions that came out of them.

### 17.1 Expense manager market

Most of what we planned already matches or beats the market. Actions:
- Build UPI-native parsing (V1), recurring detection (V2), export (V1).
- Skip SMS sync, BYO-key AI, multi-currency, neobank/lending (see Decision Log above).
- Differentiators the market lacks: cash-via-Slack, visible de-duplication, running-cost-vs-luxury split, and the entire CA layer.

### 17.2 CA-view / tax-tool market

The market is filing-first and seasonal; we are planning-first and continuous. Actions:
- Build advance-tax planner (V2).
- Build later: crypto/VDA (V3), F&O/intraday business income (V3).
- Skip notice management and ITR filing (we don't file, D1).
- Differentiators no competitor has: per-number audit/provenance, plain-English "why", visible confidence/assumptions.

### 17.3 Business-accounting software

Not real competitors. QuickBooks exited India; TallyPrime is business GST/compliance software for a different user. One reaffirmation: serious accounting tools earn trust through visible reconciliation and audit trails, validating that our balance-check and audit trail should stay front-and-center.

---

## 18. Journey Decisions

All decisions taken in the user-journey walkthrough. See "User Stories & Journeys" for full context.

### 18.1 Authentication & Onboarding

- **Auth: Google OAuth only.** One consent flow covers identity + Gmail access.
- **Onboarding: skippable checklist**, not forced wizard. Includes setup-progress indicator.
- **Empty states: explicit "insufficient data" message**, never ₹0 where unknown.

### 18.2 Gmail & Ingestion

- **Discovery: LLM-based scan.** Identifies bank/card from content, matches to account or triggers new-account flow.
- **First connect: start from today.** Backfill is separate, explicit action.
- **Dry-run: first statement per account only**, then auto-trust. Re-triggered if confidence drops below threshold.
- **Failure UX: reason-specific prompts** (password / parse failure / filter hint / sample PDF request).
- **Backfill cap: 2 previous financial years** (applies to transactions, not cost-basis documents).

### 18.3 Data Model

- **Transaction type: first-class field** (`income | expense | transfer | investment`). Replaces exclusion-flag model.
- **Invariant 5 restated:** closed FY never changes *silently*. Amendments allowed with explicit confirmation, recorded as events, original preserved.

### 18.4 Deduction Detection

- **Mechanism: hybrid.** Curated merchant→section table, LLM for unknowns, user confirms both.
- **Ask-once-per-merchant**, then remember.
- **Tagging: auto-tag only on high confidence**, otherwise ask.
- **Proof: not required.** Transaction evidence sufficient for planning.

### 18.5 Notifications

- **Two-tier model:** Tier 1 alerts (mandatory) + Tier 2 milestones (opt-in, off by default).
- **Channel: Slack, email, or both.** Default Slack if bot connected, else email.
- **Alert-worthy:** sync failure, credential rejection, parse failure, low confidence, overdue docs.
- **Milestones:** successful sync, N transactions categorized, Form 16 date, ITR deadline, advance-tax due, 80C maxed, FY closing.
- **Aggregation & throttle:** 40 failed statements = one message ("6 failed to parse"), not 40.

### 18.6 Invoicing & Handoff

- **V1 ships CSV + simple PDF summary** (not just CSV).
- **PDF includes assumptions/missing-data caveats** — shipped V1, not V4. CA must know what's missing.

### 18.7 Beta Access

- **Invite-only email allowlist** maintained by owner.
- **Strict isolation:** owner cannot see beta user data, even for debugging.
- **Setup-progress indicator** until data is sufficient.

---

## Journey Gaps — All Resolved

All 6 blocking gaps identified in the journey walkthrough are now resolved. See "User Stories & Journeys" §16–18 for full decisions and rationale.

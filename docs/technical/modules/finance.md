# Module: Finance

**Status:** DESIGNED 2026-06-09 — specs pending core (a *later* spoke; cannot build until its dependencies land).
**Source-of-truth doc** for the future `FIN-*` specs, matching `calendar.md` / `gmail.md` / `productivity.md`.
**Layout:** `src/artemis/modules/finance/`.

> A privacy-first personal-finance module. **Artemis owns the ledger** (ADR-011 *own*), reconstructed from
> the already-mirrored email corpus + manual entry — **no bank link, no aggregator, no banking credentials,
> ever.** Read/awareness only — Artemis never moves money.

## Scope (locked)
- **First cut = spending + subscriptions awareness:** categorized spending from extracted transactions,
  subscription/recurring tracking, bill due-dates, spending pulse. **No budgeting envelopes** in this phase.
- **End-state = full personal-finance brain:** + accounts/net-worth, investment tracking, budgeting envelopes.
  Design for the end-state; ship the awareness layer first (same pattern as Calendar/Productivity).

## Source of truth — Artemis owns the ledger (ADR-011 *own*)
There is no single authoritative external system to mirror (money is spread across banks; no usable SG
aggregator). So Artemis **owns** a reconstructed financial ledger, like Tasks/Projects — populated by
extraction + manual entry, never bidirectionally synced to any external system.

## Data sources (locked) — email-extraction + manual, NO bank link
1. **Email-derived (primary).** The Gmail mirror (M8-b) already ingests bank alerts, card-transaction
   notifications, receipts, and subscription-renewal emails. These are **untrusted text** → run through the
   `artemis.untrusted` → **`QuarantinedReader`** (DR-a) boundary, which emits a structured `TransactionExtract`;
   the privileged side only ever sees the sanitized extract (never raw email). Same two-untrusted-boundary
   pattern as the other read-spokes (M8-b1 / CAL-d).
2. **Manual + CSV/statement import (gap-fill).** For what email can't see — cash, account balances,
   investments. **Consequence (logged):** end-state net-worth/investment tracking leans on manual/statement
   import since there is no feed.
3. **NO third-party aggregator / SGFinDex / Plaid** — even at end-state. No banking credentials stored or relayed.

## Data model (owned, owner-private encrypted scope)
- `account` — name, type, currency (manual; for grouping + net-worth).
- `transaction` — date, amount, original_currency, amount_original, merchant, category, **source** (`email`/`manual`/`csv`), `raw_ref` (→ the quarantined email Extract id), confidence.
- `subscription` — merchant, cadence, amount, next_renewal, last_seen_price (**derived** from recurring transactions).
- `bill` — payee, due_date, amount, status (**derived** from email; reminder-only).
- **Currency:** S$ primary; every transaction stores its original currency + amount (multi-currency aware, for travel spend).

## Data flow
```
Gmail mirror (untrusted) ──▶ artemis.untrusted ──▶ QuarantinedReader ──▶ TransactionExtract
                                                                              │ (privileged side)
                                                                              ▼
                          manual / CSV import ──────────────────────▶  owned ledger (transaction)
                                                                              │
                                          recurring-pattern analysis ────────┤──▶ subscription
                                          due-date language ─────────────────┘──▶ bill
```
**Categorization:** auto-categorize via the local model; **owner corrections graduate into learned rules via
the recipe loop** (the "I guide it, the automation gets written" bridge — same mechanism as Productivity
capture / ADR-012). **Subscription/bill detection:** recurring-pattern analysis over the ledger (same merchant
+ ~amount + regular cadence → `subscription`; due-date language → `bill`).

## Tools (manifest — awareness phase)
query spending by category/period · list & manage subscriptions · add/edit/recategorize a transaction ·
list upcoming bills · monthly/period summary. *(End-state adds: net-worth, budget-envelope, investment tools.)*

## Proactive hooks (locked — all 4; ride M6 heartbeat; payload = counts/IDs only per the M6-b injection boundary)
1. **Subscription renewal + price-increase** — "Netflix renews in 3 days" / "Spotify went up to $X."
2. **New-subscription / recurring-charge detected** — "Looks like you started a recurring charge to X."
3. **Bill due reminders** — upcoming payment due-dates; reminder only, never auto-pays.
4. **Spending summary + unusual-spend** — periodic categorized digest + a flag for out-of-pattern charges.

## Knowledge / memory push
Durable facts flow to the core (per the spoke contract): "owner pays ~$X/mo for Y", recurring merchants,
spending patterns → memory (M4) + knowledge corpus (M3) for cross-domain recall.

## Permissions & effects (locked)
- **Owner-only, fully private** — guest mode sees *nothing* financial.
- **Read/awareness only — Artemis never moves money.** Manual edits, categorization, "mark bill paid" are
  **local-ledger writes, not external actions** → **no `ActionStagingService`/GATE staging needed** (simpler
  than Calendar). No external-effect surface at all in the awareness phase.

## Build phasing (mirrors CAL-a..d) — specs PENDING core
- **FIN-a** — ledger core + data model + manual/CSV entry (owned owner-private SQLCipher store).
- **FIN-b** — email→transaction extraction via the `QuarantinedReader` quarantine boundary.
- **FIN-c** — subscription/bill recurring-detection + the 4 proactive hooks.
- **FIN-d** — knowledge/memory push.
- *(End-state phase, later: net-worth + budgeting envelopes + investments.)*

## Dependencies (why this is a *later* spoke)
Needs: **M8-b Gmail mirror** (data source) · **M4 memory** · **M3 knowledge** · **M6 heartbeat** (hooks) ·
**M7 recipe** (learned categorization) · the core spine (M0–M2) · **CLIENT** (owner surface for review/edit).
→ Cannot build until those land. The design above is captured now while fresh; `FIN-*` execution specs are
drafted (AFK) when the core is closer.

## Open items (resolve at spec-drafting time, not owner forks)
- Exact `TransactionExtract` schema + which email senders/categories trigger extraction (derive from M8-b).
- Recurring-detection thresholds (amount tolerance, cadence window).
- CSV/statement import format coverage (which banks' export formats to parse first).
- End-state net-worth/investment data-entry UX (manual surface).

# Finance spoke — open design decisions

_Decision-resolution pass, 2026-06-23. Source-of-truth: `docs/technical/modules/finance.md` (DESIGNED 2026-06-09), `docs/owner-rules/` (incl. the finance reconciliation already written into finance.md), `ADR-021` (cross-module reactions, B-cluster + B4c S$500 gate), `ADR-022` (sensitivity routing), `docs/status.md`._

Finance is the LEAST-specced spoke: a design doc, no FIN-* build specs yet. The design doc locks **scope, source-of-truth, data sources, the data-model skeleton, dedup/reconciliation logic, transfers-not-expenses, the 4 hooks, and permissions/no-GATE** — but its own `## Open items` section explicitly defers a cluster of schema/threshold/format decisions to "spec-drafting time." Those plus a few structural choices are the genuinely-open list below.

**Ordering:** data-model + scope-progression decisions first (they block FIN-a and everything downstream), then extraction/reconciliation behaviour, then hooks/alerts/UX, then the smaller threshold knobs.

---

## D1 — Ledger data-model finalization (the FIN-a schema freeze)

**Context.** finance.md gives a skeleton — `account`, `transaction`, `subscription`, `bill` with listed fields — but ADR-021 dependency #3 already amends it (add `transaction.instrument`/`account`), and the doc's own open items say "exact schema… derive at spec time." FIN-a cannot start until the four tables' columns, types, nullability, and the confidence/needs-review fields are frozen. This is the gating decision.

**Options.**
- **A — Freeze the design-doc skeleton as-is + the locked ADR-021 `instrument` add, nothing more.** Trade-off: fastest to FIN-a; risks a migration when end-state (net-worth/investments) lands.
- **B — Freeze the awareness-phase tables but design columns for the end-state (nullable net-worth/holding fields present, unused).** Trade-off: one schema, no later migration; slightly wider table now, some dead columns in v1.
- **C — Two-phase schema: minimal awareness tables now, formal Alembic expand/contract migration when end-state arrives.** Trade-off: cleanest v1; defers the migration cost to later but pays it twice (design now + migrate later).

**Recommended default: B** — design-for-end-state, ship-awareness-first is the doc's own stated stance ("Design for the end-state; ship the awareness layer first"); one frozen schema avoids a SQLCipher migration on owner-private data. Pin: SGD as `account.currency` default; `transaction` carries `original_currency` + `amount_original` per the locked multi-currency rule.

**UI implication: Y** — the ledger schema is the surface the CLIENT review/edit screen binds to (transaction list, edit form, category picker).

---

## D2 — Awareness-first → full-brain progression: what is in v1 scope vs deferred

**Context.** Scope is "locked" at two tiers (awareness = spending + subscriptions + bills + pulse; end-state = accounts/net-worth + investments + budgeting envelopes). What is NOT yet pinned is the **boundary inside the awareness tier** across FIN-a..d, and the trigger for starting end-state work.

**Options.**
- **A — Strict doc tiers: awareness = FIN-a..d only (no envelopes, no net-worth, no investments); end-state is a separate later milestone.** Trade-off: smallest first deliverable, matches the locked scope; defers budgets even if wanted.
- **B — Awareness + a read-only net-worth *view* (manual account balances only, no investment feeds).** Trade-off: gives the "what do I have" answer cheaply since `account` already exists; still no budgeting/investment tracking.
- **C — Pull budgeting envelopes forward into awareness.** Trade-off: owner gets spend-vs-budget early; contradicts the locked "no budgeting envelopes in this phase" and adds judgment surface.

**Recommended default: A** — the scope lock is explicit and recent; envelopes/net-worth are flagged end-state. Confirm only whether a *manual* net-worth view (B) is wanted early, since `account` exists regardless.

**UI implication: Y** — determines whether v1 client shows a net-worth tile / budget bars or only spending + subscriptions + bills.

---

## D3 — Transaction CATEGORY taxonomy (the category set + how it's seeded)

**Context.** `transaction.category` is auto-assigned by the local model, with owner corrections graduating into learned rules via the recipe loop (precision-first: below confidence floor → no tag + needs-review, per the owner-rules auto-tagging rule). What is NOT decided: **the actual category list** — fixed taxonomy, owner-defined, or model-freeform — and whether categories are flat or hierarchical.

**Options.**
- **A — Fixed seed taxonomy** (e.g. Food, Transport, Groceries, Bills/Utilities, Shopping, Entertainment, Subscriptions, Travel, Health, Transfer/Internal). Trade-off: predictable, easy to summarize/chart; may not fit owner's mental model.
- **B — Owner-defined categories, empty to start, grown by corrections.** Trade-off: perfectly personal; cold-start is noisy, weak summaries until trained.
- **C — Fixed seed + owner can add/rename/merge** (hybrid). Trade-off: good summaries from day one + personalizable; small bit of management UI.
- **D — Flat vs hierarchical** (sub-dimension): single-level tags vs parent>child (Food>Dining). Trade-off: hierarchy enables roll-up summaries; more complexity in the picker + model output.

**Recommended default: C, flat** — a fixed seed gives immediate categorized-spending value and chartable summaries; owner add/rename/merge keeps it personal; the recipe loop already handles correction→learned-rule. Flat first (hierarchy is an end-state nicety, and `subscription`/`travel` already carve the big buckets).

**UI implication: Y** — drives the category picker, the spending-by-category chart buckets, and the recategorize affordance on the transaction edit screen.

---

## D4 — Extraction sources: which senders/categories trigger extraction + the TransactionExtract schema

**Context.** finance.md and owner-rules both flag this as open: "which email senders/categories trigger extraction (derive from M8-b)" + "exact `TransactionExtract` schema." Owner-rules already locks that UOB/SCB/DBS transaction senders route to Finance (never to urgency alerts), and the payment channels are named (UOB card, SCB card, DBS card, DBS PayLah!, PayNow). Open: the **trigger rule** (allowlist of senders vs content-classifier) and the structured-extract field set.

**Options.**
- **A — Sender allowlist** (UOB/SCB/DBS + known merchant-receipt domains) gates extraction. Trade-off: precise, low false-positive; misses unknown senders / new banks until added.
- **B — Content-classifier** (local model decides "is this a financial txn email?") over the mirror. Trade-off: catches anything; higher false-positive load, more model calls.
- **C — Allowlist for bank/card senders (high-trust, structured) + classifier fallback for receipts from unknown merchants.** Trade-off: best coverage/precision balance; two code paths.

**Recommended default: C** — bank senders are known and named by the owner (cheap allowlist, high precision); merchant receipts are open-ended (need the classifier). The `TransactionExtract` schema = the privileged-side fields in the `transaction` table (date, amount, currency, merchant, instrument, type-hint, confidence, `raw_ref`) — freeze it alongside D1.

**UI implication: N (function decision)** — but flag: extracted-vs-manual provenance should be visible on the transaction (`source` field already exists) → UI agent.

---

## D5 — Manual + CSV/statement import: entry UX and which bank export formats first

**Context.** Manual entry + CSV/statement import is the locked gap-fill for what email can't see (cash, balances, investments) and the ground-truth for L2 pending↔posted reconciliation. Open (per finance.md open items): "which banks' export formats to parse first" + the manual-entry surface. CSV import is also the *reconciliation* ground-truth, so it's not optional cosmetic.

**Options.**
- **A — Manual single-transaction entry only in v1; CSV import deferred to FIN-a+.** Trade-off: simplest; loses L2 posted reconciliation (email-extracted stays "pending" forever) and net-worth gap-fill.
- **B — Manual entry + CSV import for the owner's three banks (UOB, SCB, DBS) from day one.** Trade-off: enables L2 reconciliation + balances immediately; needs 3 format parsers + a column-mapping step.
- **C — Manual entry + a generic mapped-CSV importer** (owner maps columns once per bank, saved as a profile). Trade-off: covers any bank without per-bank code; owner does a one-time mapping per source.

**Recommended default: C** — a generic column-mapped importer (saved profiles) covers UOB/SCB/DBS *and* any future statement without bespoke parsers, and it's the cleanest fit for "owner owns the ledger." Manual single-entry ships alongside for cash/one-offs.

**UI implication: Y** — manual-entry form + CSV upload/column-mapping flow + the import-preview/confirm screen are all client surfaces → flag to UI agent.

---

## D6 — Reconciliation rule tuning: the dedup/match windows and the auto-merge vs owner-review line

**Context.** The reconciliation ladder L0–L4 is **locked** (idempotent ingest → economic-event dedup → pending↔posted → ambiguous-to-owner → recipe-learned), and the shared fuzzy-match reconciler is locked in ADR-021 (one primitive for A9/B4c/B5/B6/dedup). What's open per the doc: the **numeric thresholds** — the date-window (±1–2d stated as a range), amount tolerance, merchant-normalization fuzziness, and the confidence cutoff above which auto-merge fires silently vs surfaces as a "possible duplicate?" suggestion.

**Options.**
- **A — Tight windows, low auto-merge** (date ±1d, exact amount, high confidence bar). Trade-off: precision-first, few wrong merges; more owner-review suggestions.
- **B — Looser windows, more auto-merge** (date ±2–3d, small amount tolerance, lower bar). Trade-off: fewer owner prompts; risk of merging distinct charges.
- **C — Ship A's tight defaults as tunable constants; let the recipe loop (L4) widen them per learned merge/keep decisions.** Trade-off: safe start that adapts; thresholds become learned rather than guessed.

**Recommended default: C** — precision-first is a locked owner posture (uncertain → owner, never silent), and L4 recipe-learning already exists to relax over time. Seed: date ±1d, exact amount+currency, normalized-merchant fuzzy; everything below the auto-merge confidence bar → inert "possible duplicate?" suggestion.

**UI implication: Y** — the "possible duplicate?" suggestion + the open→paid bill reconciliation status both need a review affordance → UI agent (suggestion-inbox pattern).

---

## D7 — Transaction `type` inference: how purchase/refund/transfer/settlement is classified

**Context.** The `type` field and the rule "only purchase/refund count toward spend" are **locked** (transfers/settlements excluded to avoid double-counting CC-bill-payments). Open per the doc: *how* type is inferred — "from email language + amount/merchant patterns; settlement→statement-period mapping; bank-specific phrasings (UOB/SCB/DBS)" — and PayNow's ambiguity (P2P transfer vs payment).

**Options.**
- **A — Rule/keyword heuristics per bank** ("bill payment", "transfer to", PayNow P2P markers). Trade-off: deterministic, auditable, fast; brittle to new phrasings, needs per-bank maintenance.
- **B — Local-model classification of the extract into the 4 types.** Trade-off: robust to phrasing; a judgment call → must respect the confidence floor + owner-review on ambiguous.
- **C — Model-first classify + deterministic post-rules for the known unambiguous bank phrasings; ambiguous (incl. PayNow) → L3 owner-review.** Trade-off: best of both; ambiguous-to-owner is already the locked posture.

**Recommended default: C** — the doc already mandates "local model classifies; deterministic ledger reconciles; ambiguous → owner." PayNow specifically is flagged ambiguous and routes through the classifier; sub-S$500 retail never pings (D9).

**UI implication: N (function)** — but the type is shown/editable on a transaction, and ambiguous-type review is an owner prompt → flag to UI agent.

---

## D8 — Recurring-detection thresholds (subscription + bill derivation)

**Context.** `subscription` and `bill` are **derived** entities (recurring-pattern analysis: same merchant + ~amount + regular cadence → subscription; due-date language → bill). The detection *mechanism* is locked; open per the doc: the **thresholds** — amount tolerance (price drift between renewals), cadence window (how regular counts as "recurring"), and how many occurrences before a series is declared a subscription.

**Options.**
- **A — Conservative: ≥3 occurrences, tight cadence (±3d of a monthly/annual period), ±5% amount tolerance.** Trade-off: high precision, fewer false subscriptions; slower to detect a new sub (hook #2 fires late).
- **B — Eager: 2 occurrences, looser cadence/amount.** Trade-off: catches subs fast; more false positives surfaced.
- **C — 2-occurrence *suggestion* ("looks like a new recurring charge to X?") that confirms into a subscription on the owner's nod or a 3rd occurrence.** Trade-off: fast awareness without false commitment; fits hook #2's wording exactly.

**Recommended default: C** — hook #2 ("looks like you started a recurring charge") is already a soft nudge, not an assertion; a 2-occurrence suggestion that hardens on confirm/3rd-hit matches the precision-first + suggest-then-graduate posture. Amount tolerance ±5–10% (captures price increases, which hook #1 wants to flag).

**UI implication: Y** — the subscription list + the "new recurring charge detected?" confirm + the price-history sparkline are client surfaces → UI agent.

---

## D9 — Spending alerts / budget posture for v1 (the B7 boundary)

**Context.** Hook #4 (spending summary + unusual-spend flag) is **locked** as an awareness hook. Budget envelopes / category-threshold alerts (reaction B7) are **locked OUT** of the awareness phase (end-state only). What's genuinely open: what "unusual-spend" means operationally (the flag's trigger), and confirming the owner doesn't want any threshold/budget alert pulled forward. Also the B4c fraud-confirm threshold (~S$500) is locked in ADR-021 — that is NOT open, just adjacent.

**Options.**
- **A — Unusual-spend = statistical outlier vs the merchant/category's own history** (z-score / much-larger-than-usual). Trade-off: adapts per owner; needs history to calibrate (cold-start weak).
- **B — Unusual-spend = simple absolute thresholds per category** (configurable ceilings). Trade-off: predictable; not personalized, owner must set ceilings = budget-by-the-back-door (collides with the no-envelopes lock).
- **C — Outlier flag (A) for v1; defer all category-budget alerting to end-state B7.** Trade-off: keeps the no-budget lock clean; the only alert is "this charge is out of pattern."

**Recommended default: C** — honours the locked no-budgeting-envelopes scope while still giving the unusual-spend signal hook #4 promises. Confirm with owner: any appetite for even a soft category-budget alert in v1, or strictly outlier-only.

**UI implication: Y** — the periodic spending digest + the unusual-spend flag are notification/review surfaces → UI agent; a budget bar is explicitly out of v1.

---

## D10 — No-bank-link stance: confirm it holds + the manual net-worth consequence

**Context.** "No bank link, no aggregator, no banking credentials, ever — even at end-state (no SGFinDex/Plaid)" is stated as **locked** in finance.md. The genuinely-open piece is the logged *consequence*: end-state net-worth/investment tracking leans entirely on manual/statement import since there's no feed — is that accepted, and is there any read-only aggregator the owner would tolerate later?

**Options.**
- **A — Hold the absolute no-link stance; net-worth/investments are manual/CSV-only forever.** Trade-off: maximal privacy, zero credential risk (matches the whole privacy-wall thesis); manual upkeep burden for balances.
- **B — Allow a *read-only* aggregator at end-state only (e.g. SGFinDex read-scope) behind the GATE.** Trade-off: less manual work; reintroduces a credential/third-party surface the design explicitly rejected.
- **C — No aggregator, but invest in better statement-OCR/CSV automation to cut manual burden** (pairs with E5b document→ledger). Trade-off: keeps the stance, reduces the manual tax via better import, not via a feed.

**Recommended default: A, with C as the burden-reducer** — the no-link stance is the spine of the privacy thesis (and ADR-022 keeps finance always-local). Treat manual/import as permanent; lean on statement-OCR (E5b) to soften it. Flag B as a deliberate "ask once" so it's a recorded no, not an omission.

**UI implication: N** — pure stance/data-source decision; affects only that there is no "link your bank" flow ever.

---

## D11 — `instrument`/account field semantics (the ADR-021 amendment, detail-open)

**Context.** ADR-021 dependency #3 **locks** that `transaction` gains an `instrument`/`account` field (which card/PayLah!/PayNow), needed for "which account did this come from" + dedup. The *decision to add it* is closed; open is the **shape**: a free-text label, a FK to the `account` table, or an enum of the named channels.

**Options.**
- **A — FK to `account`** (the 5 named channels seeded as accounts). Trade-off: clean, enables per-account net-worth grouping (which `account` already exists for); requires the accounts to be pre-seeded.
- **B — Enum of named instruments** (UOB-card, SCB-card, DBS-card, PayLah, PayNow). Trade-off: simple, matches the owner's named list; doesn't generalize to new accounts without a code change.
- **C — Free-text instrument label, normalized over time.** Trade-off: flexible; weak for dedup/grouping (the whole point of the field).

**Recommended default: A** — FK to `account` unifies "instrument" with the already-locked `account` table (one concept, not two), seeds the 5 channels as accounts, and directly serves net-worth grouping + dedup. This is the cleaner reading of the ADR amendment.

**UI implication: Y** — the account/instrument picker on manual entry + the per-account filter on the spending view → UI agent.

---

## D12 — Cross-spoke reaction wiring (email→Finance, Finance→Tasks/Calendar/Memory) — FLAG, defer detail

**Context.** The B-cluster reactions (A1/A3/A6/A9 email→Finance; B1/B2b/B4b/B4c/B5/B6/B8 Finance→others) and the locked ~S$500 B4c amount-gated fraud-confirm are **owner-triaged and locked in ADR-021**. The runtime model (hybrid learned-first, 3 infra pieces, shared reconciler) is locked. What remains is *per-reaction recipe specs* drafted against ADR-021 at Mini-build time — a cross-spoke integration concern, not a Finance-internal decision.

**This is NOT an open Finance decision** — it is locked architecture + deferred build specs. Flagged here only so the Integration agent owns: the emit points Finance must publish (`txn-recorded`, `bill-recorded`, `subscription-detected`), the GATE posture (Finance writes are internal/reversible → no GATE; the dispatcher routes external-effect reactions, of which Finance currently has none), and the shared-reconciler binding. **Defer all detail to the Integration agent.**

**UI implication: N** (hub-level synthesis, e.g. E8 "what's due this week," is a Brain/hub view → carved out per ADR-021 D7, not a Finance screen).

---

## D13 — Sensitivity-wall interaction: confirm Finance stays fully local

**Context.** ADR-022 (ACCEPTED 2026-06-22) routes **finance as always-sensitive → reasons on the LOCAL model, never leaves the box**. Memory excludes financial facts entirely (financial → Finance ledger only, never memory/cloud). This is **locked**, but worth a one-line confirm in the decision pass because it constrains every Finance code path (no Codex/cloud call may touch a `transaction`/`account`/`bill`).

**This is NOT open** — it's a locked invariant (ADR-022 + the memory-excludes-financial owner rule). Recorded so the FIN-* specs inherit it: extraction, categorization, reconciliation, and hook generation all run on the local sensitive-reasoner; the cloud/Codex path is forbidden for ledger data; the store is owner-private SQLCipher, guest-mode sees nothing.

**UI implication: N** — affects routing/security, not screens (beyond "guest mode shows no finance," already locked).

---

## Already-resolved / locked (excluded from the open list — appendix)

- **Source of truth** — Artemis owns a reconstructed ledger (ADR-011 *own*); no bidirectional external sync. LOCKED.
- **Data sources** — email-extraction (primary, via QuarantinedReader) + manual/CSV (gap-fill); NO aggregator/SGFinDex/Plaid; no banking credentials. LOCKED (the *consequence* nuance is D10).
- **Scope tiers** — awareness (spending+subs+bills+pulse) first, full-brain (accounts/net-worth/investments/envelopes) end-state; no budgeting envelopes in v1. LOCKED (the v1/end-state *boundary* nuance is D2/D9).
- **Currency** — S$ primary; every txn stores original currency + amount (multi-currency aware). LOCKED.
- **Transfers/settlements not expenses** — only `purchase`/`refund` count toward spend; the `type` field + the rule. LOCKED (the *inference method* is D7).
- **Dedup/reconciliation ladder** — L0–L4 (idempotent ingest → economic-event dedup → pending↔posted → ambiguous-to-owner → recipe-learned). LOCKED (the *thresholds* are D6).
- **Cross-module links** — logical `{module, entity_id}` refs via ToolRegistry, promotion-not-duplication, lifecycle-sync, hub-level unified views. LOCKED (ADR-013 + ADR-021).
- **4 proactive hooks** — subscription renewal+price-increase · new-recurring-charge · bill-due reminders · spending-summary+unusual-spend. All 4 LOCKED (the *thresholds/wording* are D8/D9); ride M6 heartbeat, payload = counts/IDs only.
- **Permissions / no-GATE** — owner-only, fully private, guest sees nothing; read/awareness only, Artemis never moves money; local-ledger writes (edit/categorize/mark-paid) are NOT external actions → no ActionStagingService/GATE. LOCKED.
- **B4c fraud-confirm threshold** — ~S$500 amount-gated confirm (below → silent link, no ping; ≥ with no matching receipt → confirm). LOCKED in ADR-021.
- **Cross-module reaction runtime model** — hybrid learned-first, 3 infra pieces, shared reconciler, A6 (bill→task) is a Tier-A built-in. LOCKED in ADR-021.
- **Sensitivity routing** — finance always-local, never cloud; memory excludes financial. LOCKED in ADR-022 (confirm-only = D13).
- **Knowledge/memory push** — durable non-record facts ("owner pays ~$X/mo for Y", recurring merchants, patterns) flow to M4/M3; raw financial records do NOT. LOCKED.
- **Build phasing** — FIN-a (ledger core + manual/CSV) → FIN-b (email extraction) → FIN-c (recurring + hooks) → FIN-d (knowledge/memory push); end-state later. LOCKED (specs pending core).

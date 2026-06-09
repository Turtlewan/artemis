# ADR-003 — Teacher access to sensitive email during bounded bootstrapping (Gmail triage)

**Status:** Accepted (SP0 phase 6, Gmail ingestion design, 2026-06-04)
**Builds on:** ADR-001 (stack — Claude-subscription teacher "teaches the method, never sees sensitive data"; local Qwen3-14B for sensitive heavy reasoning) · ADR-002 (deployment — "cloud touchpoints are bootstrapping + non-sensitive only"). This ADR defines the **one bounded, owner-gated exception** to the local-only-for-sensitive-data posture, scoped to Gmail triage rule-authoring.

## Context
Gmail ingestion (wave-1 connector) triages every email into **capture (store + embed + extract)** vs **discard (record id+verdict in a seen-ledger, drop content)**. The triage runs on a **cheap, distilled rule set** at runtime (token-free) — the rules are the load-bearing artifact, and their quality determines what Artemis ever knows from email.

Owner asked to involve **Claude** (cloud teacher) in *creating* those rules, because Claude designs better triage rules than the local Qwen3-14B. This collides head-on with the project's most foundational lock (draft, 2026-06-03, emphatic): **"Brain = LOCAL-ONLY … take cloud off the table entirely … design as if there is no cloud at all,"** with teacher-escalation redefined to **"escalate to a bigger local model, not cloud."** Email content — and even sender/subject metadata — is the most sensitive data Artemis holds.

The reconciliation: separate the **method** (non-sensitive, Claude's strength) from the **data** (sensitive, stays local), and permit a **bounded, owner-controlled bootstrapping window** in which the owner *deliberately* pair-authors rules with Claude using **owner-selected** real emails. This is a conscious, scoped reversal — recorded here so it is never defaulted into.

## Decision
Triage rules are authored by a **method/data split** with one bounded exception for bootstrapping.

| Aspect | Decision |
|--------|----------|
| **Steady state (always)** | Local-only invariant holds. **Claude sees only the abstract method** — rule framework, categories, edge-case logic — from synthetic or owner-cleared examples. The **local teacher (Qwen3-14B)** performs all content-touching work: inducing concrete rules from the real inbox and judging ambiguous emails at runtime. Claude **never** sees real email at runtime. |
| **Bootstrapping window (bounded exception)** | A **switchable, owner-controlled mode** in which the owner may share **hand-selected real emails** with Claude to firm up the initial ruleset. Outside this window, the mode is OFF and Claude reverts to method-only. |
| **Clearing gate (how real email reaches Claude)** | **Interactive consensus rule-authoring.** The owner **selects** specific emails and discusses "what to look out for" with Claude until they reach **consensus on a rule**. **Claude may *request* more samples** to generalise/disambiguate a rule — but **asking ≠ accessing**: the owner remains the egress gate and chooses what (if anything) to share in response. Nothing becomes a rule without owner agreement. |
| **Egress discipline** | Only owner-hand-selected emails ever leave the box, and only while the window is ON. **Full audit log** of exactly what was sent to Claude (relevant to the L4+ audit-log governance rule). Finance/health/journal content is hard-excluded from sharing by default. |
| **Output** | Each agreed rule is **distilled and stored locally**; the **local teacher applies** the rule set to the full inbox. The cloud never holds the rules or the data they run on. |
| **Rule-growth lifecycle** | Rules grow by three local mechanisms after bootstrapping: (1) **Curiosity Loop (M7)** — local teacher refines rules continuously, owner-gated; (2) **owner feedback** — "should've been captured" / "stop capturing these" → rule revision; (3) **re-bootstrapping** — the owner may re-enter the window later (new account/patterns) to pair-author fresh rules with Claude on a new cleared sample. |

## Applying rules = automation, not AI (the payoff)
The teacher→distill→rule loop exists so that **once a rule is finalized, applying it is pure automation — deterministic, token-free, instant.** AI cost is paid once (authoring); the rule then executes as code (sender lookup, label check, regex, pattern match). This is the locked **"automation-over-AI for repeatable tasks"** principle realised. Where AI runs:

| Step | AI or automation |
|------|------------------|
| Authoring / refining a rule | **AI, one-time** — Claude (method) + local teacher (induction) |
| **Applying a finalized rule (triage in/out)** | **Automation** — deterministic, token-free, runs on every email |
| Judging a *novel* email no rule covers | **AI (local teacher)** — but it *produces a new rule*, so the AI-needed set shrinks over time |
| Extracting structured content from a captured email | **Mixed** — automation (parsers) for structured/templated senders (calendar invites, known receipt formats); local-AI for freeform email. Extraction also distills: a recurring sender's format → a learned parser → automation next time |

**Trajectory:** AI spend **decays toward zero** for patterns already seen and persists **only at the novel edges**. Triage matures to near-pure automation; extraction follows more slowly (freeform stays AI-assisted longest). A mature Artemis triages a normal day's inbox with essentially no inference — the local teacher only wakes for something genuinely new.

## Dependencies
- **M2 (security wall + identity/scope)** — owner↔guest crypto wall; the audit log and the hard-exclude of sensitive categories live behind it.
- **M7 (teacher escalation + skills library + Curiosity Loop)** — the distillation + continuous-refinement machinery the rule lifecycle rides on.
- Both are **core** milestones, built **before** the wave-1 Gmail connector — so the machinery exists when Gmail is built. No ordering conflict.

## Runner-ups ruled out
- **Local teacher only (no Claude on rules at all)** — fully preserves local-only but forgoes Claude's superior rule design; rejected because the bounded, owner-gated window captures most of the quality at controlled, one-time egress.
- **Policy-gated auto-sample** (Artemis auto-assembles a cleared sample within an owner policy) — lower owner effort, but trusts the policy and removes the owner from per-email egress; rejected in favour of hand-selection.
- **Time-boxed open bootstrapping** (any sampled email may be sent during the window) — lowest friction, highest egress; rejected as too loose for the most sensitive data store.
- **Claude as ongoing runtime triage teacher on real email** — highest quality, but routine private email to cloud indefinitely; rejected as an unacceptable, unbounded reversal of the local-only posture.
- **Sending de-identified metadata (sender/subject only) to Claude** — rejected because sender and subject are themselves sensitive (leak relationships/finances/health).

## Consequences
- **The local-only invariant survives, with one named, bounded, owner-gated, audited exception** — scoped to Gmail triage rule bootstrapping, never the runtime hot path, never automatic.
- **Cost of the privacy guarantee:** content-touching induction and ambiguous-case judging run on the local 14B (heavier than cloud). Bounded by inducing from samples + ambiguous cases, never the full inbox.
- **The owner is the egress gate** — Claude can prompt for more samples but cannot pull them; every shared email is hand-selected and logged.
- **Runtime is automation-first** — mature triage spends no tokens; this directly serves the locked runtime-token-frugality constraint.
- **Sets the pattern for future sensitive connectors** — any later connector wanting cloud-teacher help on sensitive data must follow this same method/data split + owner-gated bootstrapping shape (or justify a new ADR).

## Parked (build-phase details)
Exact UI/flow of the interactive consensus session (CLI vs app) · the on/off control + how the bootstrapping window is opened/closed/expired · audit-log schema + retention for cloud egress · the synthetic-exemplar corpus Claude uses in steady state · the structured-sender parser library for extraction · whether `gmail.modify` (label "processed") is ever added beyond `gmail.readonly`.

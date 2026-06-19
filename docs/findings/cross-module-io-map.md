# Cross-Module I/O Map — substrate for the automation-rule (reaction) layer

_Generated 2026-06-19 (6 parallel agents over all module specs + contracts.md). Purpose: map what
each module **takes in** (inputs, by source) and **emits** (signals others could react to), as the
basis for designing cross-module "when X → then Y" automation rules. Feeds the flagged cross-module-
linking ADR (see `finance.md` §Cross-module follow-up)._

## The 4 input sources (every module draws from these)
1. **EXTERNAL (world)** — Gmail API, Google Calendar API, documents/web, raw emails/attachments.
2. **OWNER** — direct commands (NL→tool via Brain), manual entry, confirmations, accept/reject.
3. **TIME / HEARTBEAT** — M6 scheduler ticks (cron + interval hooks); the only autonomous driver.
4. **CROSS-MODULE** — data/events from other Artemis modules, **always via Brain/ToolRegistry or a
   shared store — never direct store access** (ADR-013).

---

## Per-module I/O (condensed)

### Gmail (M8-b) — the biggest external inflow
**Emits:** new email ingested (signal bodies→knowledge) · **email classified urgent** (urgency hook) ·
**memory fact extracted from email** (commitments, contacts) · attachment parsed→knowledge · label/flag
change · message removed.
**Ingests:** EXTERNAL Gmail API (messages, history deltas, attachments) · OWNER consent/vault-unlock ·
TIME heartbeat (300s incremental + urgency scan) · CROSS quarantine reader, IngestPipeline, MemoryWriteQueue, known_senders (from memory).
**Top reaction triggers:** ⭐ email classified urgent · ⭐ commitment fact extracted · new bank/booking email ingested.

### Calendar (CAL) — schedule state + 7 hooks
**Emits:** event created/moved/cancelled (via staged write) · **`cal_change_detection`** (schedule changed) ·
**`cal_free_gap`** (open slot found) · conflict detected · upcoming-reminder · prep-nudge · meeting fact→memory ·
meeting summary→knowledge · PendingAction staged.
**Ingests:** EXTERNAL Google Calendar API (events, syncToken deltas, invites) · OWNER read/write tool calls, RSVP,
prefs, approve/reject · TIME 7 hooks · CROSS GATE staging, IngestPipeline, MemoryWriteQueue, quarantine, **`calendar.schedule_task`** (from Productivity).
**Top reaction triggers:** ⭐ schedule change · ⭐ free gap found · PendingAction staged.

### Productivity / Tasks (M8-d) — richest fan-out
**Emits:** **task completed** · **task overdue** · recurrence task spawned · **focus block scheduled** (calls OUT to Calendar) ·
**suggestion/commitment captured** · suggestion accepted→task · capture recipe graduated (→M7) · project completed→knowledge+memory ·
GOAL entity created (→entity backbone) · morning-plan / overdue / weekly-review hook payloads.
**Ingests:** OWNER CRUD + complete + schedule + accept/reject · TIME 3 hooks · CROSS **commitment text from email/chat/calendar**,
`calendar.schedule_task` return, EntityRepository, Promoter/RecipeStore.
**Top reaction triggers:** ⭐ task completed · ⭐ commitment captured · focus-block scheduled.

### Finance (FIN — designed, deferred)
**Emits:** **transaction recorded** (purchase/refund/transfer/settlement) · **transfer/settlement detected** (excluded from spend) ·
new-subscription detected · subscription renewal/price-increase · **bill due** · unusual-spend flagged · possible-duplicate suggestion ·
durable finance facts→memory+knowledge.
**Ingests:** EXTERNAL→via Gmail mirror (bank/card/receipt emails→quarantine→TransactionExtract) · OWNER manual/CSV + categorization corrections ·
TIME 4 hooks · CROSS ToolRegistry (bill→task, renewal→calendar), ModelPort (categorize/type-infer).
**Top reaction triggers:** ⭐ bill due · ⭐ subscription renewal · unusual-spend flagged.

### Memory + Entity backbone (M4) — the JOIN fabric
**Emits:** fact added/updated/deleted · **`resolve_entity` result** ⭐ (the only registered Memory tool) · entity created/merged ·
alias added · fact recalled & auto-injected.
**Ingests:** CROSS turn text (Brain), recall queries, **`resolve_entity` requests from any module** · OWNER view/edit/delete/purge ·
facts pushed from other modules' write paths (⊕ structurally possible, not yet wired) · EXTERNAL embeddings + local extraction model.
**Top reaction relevance:** ⭐ the **entity join** (`person_fact_key` / `EntityRef{module,entity_id}`) — "this person/account here = that one there" — is THE cross-module correlator.

### Knowledge (M3) — document corpus
**Emits:** document ingested · chunk indexed (provenance-tagged) · visual artefacts (OCR/page-image) · retrieval answer synthesized.
**Ingests:** EXTERNAL files/web · OWNER ingest requests + queries · CROSS ModelPort (embed/rerank), email attachments, calendar/productivity/finance pushes.
**Top reaction relevance:** document ingested (→Memory facts, →Finance reads OCR'd statements) · retrieval (hub "what do I know about X").

---

## ⚠️ THE KEY FINDING — there is no reaction infrastructure today
Artemis has exactly **two** ways anything happens:
- **Request-response** — the Brain handles **one owner turn → one tool**. It has no notion of "a tool
  result triggers another tool."
- **Time-polled** — the Heartbeat fires hooks on cron/interval. A hook `check_ref` *polls* for a
  condition; it is **not notified** when another module changes something.

There is **no event bus, no module→module call path, no rule registry.** Effects are terminal —
a `Hit` / tool result only ever answers or notifies the **owner**; nothing routes a result back into
*another module's input*. The closest substrate (`pre_tick_steps`, the heartbeat pre-flight rail) is
tick-bound, statically wired at composition, and meant for quarantine laundering — buildable-on but limited.

### A "when X in A → B reacts" layer needs 3 NEW pieces (none exist):
1. **An emit point + event type** — modules announce "X happened" (e.g. `EmailIngested`,
   `TransactionRecorded`, `TaskCompleted`) with entity-linked, structured payloads.
2. **A rule/subscription store** — where the "when X → then Y" rules live (owner-confirmed and/or
   learned recipes), queryable by event type.
3. **A reaction dispatcher** — a THIRD dispatcher alongside Brain + Heartbeat that, on event E,
   looks up matching rules and invokes module B's tool via **Seam 2 (ToolRegistry)**, passing through
   **Seam 3 (GATE)** if the reaction has an external effect, and **Seam 7 (quarantine)** if email-driven.

### The good news — the building blocks already exist
- **Seam 2 (ToolRegistry)** — the way to *invoke* module B. ✅
- **Seam 6 (entity backbone, M4-d)** — the *join* (CC-account/payee/person identity across modules). ✅
- **Seam 3 (GATE)** — the *safety gate* for external-effect reactions. ✅
- **Seam 7 (quarantine, DR-a)** — keeps email-driven reactions *untrusted-safe*. ✅
- **Recipe loop (M7)** — the mechanism for reactions to be **learned** (suggest→confirm→graduate). ✅
- **`pre_tick_steps` (Seam 5)** — a partial substrate the dispatcher could build on. ◑

So the reaction layer is **new wiring over existing parts**, not a from-scratch subsystem.

## Design invariants to hold (from the agent-loop reliability research)
- **Bounded, never cascading** — a reaction is one hop; reactions must not chain into each other
  unboundedly. Idempotent · clean-state · externally-verified.
- **Untrusted-safe** — email content drives *internal/reversible* reactions automatically; external
  effects always gate.
- **Precision-first** — low-confidence matches (is this the same purchase? does this complete that
  task?) → suggestion / needs-review, never silent action.

## Open questions for the discussion
1. **How reactions come to exist** — learned-first (suggest→confirm→graduate) + a few safe built-ins, vs owner-declared, vs hardcoded.
2. **Dispatcher model** — extend the heartbeat (`pre_tick_steps`-style, tick-latency) vs a new event-dispatch primitive (immediate, more infra).
3. **Event granularity** — which emits become first-class events (start small: the ⭐ triggers above).
4. **Sequencing** — this is the cross-module-linking ADR. Enumerate the wanted reactions (drives requirements) → ADR → specs (Mini-time; Finance specs fold theirs in).

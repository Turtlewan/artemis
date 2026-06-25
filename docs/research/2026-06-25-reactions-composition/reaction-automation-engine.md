# Research: Cross-Module Reaction/Automation Engine Architectures

**Date:** 2026-06-25
**Confidence:** HIGH (primary docs + production sources; community-tagged where applicable)
**Re-research after:** 2027-06-25 (general architecture patterns — 1 year per staleness table)
**Scope:** Architectures for a personal-assistant reactions layer — a central dispatcher receives domain events, matches rules, and routes effects (auto-run reversible / stage external effects for approval / inert suggestions). Small, single-user system; NOT web-scale.

> RETRIEVAL findings only. No final recommendation — options + trade-offs are presented for the planning/synthesis decision (apex-plan). Every claim carries a tier tag + URL.

---

## Summary

Four architecture families answer "when X → then Y": **rule-engine** (pattern-match facts), **reactive/event-bus** (pub-sub fan-out), **event-sourcing/CQRS** (immutable log as truth), and **saga/process-manager** (durable multi-step coordination). For a small single-user system, the consensus from primary sources is that an **in-process event bus + a lightweight declarative rule list** covers the core, with **durable-workflow (SQLite-backed, not full Temporal)** reserved only for long-running multi-step reactions. Real products (Home Assistant, n8n, Node-RED, Zapier) converge on a **trigger → condition → action** unit, store rules as **declarative JSON/YAML**, dedup is **not automatic** (it's an explicit node/mode), and **tiered approval is enforced per-action/per-tool, classified at definition time** — never by runtime heuristic.

---

## 1. Architecture families — definitions + small-system fit

| Family | Core metaphor | Central data structure | Small-system fit | Green-light | Red-light |
|---|---|---|---|---|---|
| **Rule engine** (Drools/Rete) | Pattern-match rules against a fact snapshot | Working memory + rule base + agenda | Good *if* lightweight variant | Reaction set large / authored at runtime; many rules fire on one event | Static logic; ordered execution required |
| **Reactive / event bus** (pub-sub, RxJS) | Broadcast change → subscribers react | Event queue + subscriber registry | Good — in-process bus is ~30 lines | Multiple orthogonal modules react to same event | Single consumer per event; tight sync needed |
| **Event sourcing / CQRS** | Immutable event log is source of truth | Append-only event store + projections + snapshots | Usually overkill | Time-travel ("state at T?") or full undo/replay needed | Simple CRUD; no audit/compliance mandate |
| **Saga / process manager** | Durable step-by-step coordination | Workflow history / step-checkpoint table | Overkill if full Temporal; OK if SQLite-backed | Multi-step flows that must survive crashes + resume | Short fire-and-forget reactions; single-process |

### Rule engine (Drools-style, forward-chaining, Rete)
- A rule engine evaluates IF-condition→THEN-action rules against runtime data ("facts"); forward chaining derives new facts or filters them. [VERIFIED — https://docs.drools.org/5.2.0.M2/drools-expert-docs/html/ch01.html]
- Three structures: **rule base** (persisted definitions), **working memory** (fact snapshot), **agenda/inference engine** (Rete DAG selects which rules fire). [COMMUNITY — https://www.nected.ai/blog/rules-engine-design-pattern]
- Rete builds a network over rule antecedents so only *new* facts propagate, avoiding full re-evaluation. [VERIFIED — https://www.flexrule.com/archives/forward-chain-inference-engine-with-rete/]
- Costs: Rete trades **memory for speed** — "less suitable for sparse datasets or highly dynamic environments"; continual fact insertion risks excessive memory. [VERIFIED — https://grokipedia.com/page/Rete_algorithm] Drools "lacks line-by-line debugging," and rule engines assume order-of-evaluation doesn't matter — if you need "do A before B," a state-machine fits better. [COMMUNITY — https://ivoroshilin.wordpress.com/2014/10/11/the-flip-side-of-rule-engines-and-some-tips-on-when-not-use-ones/]
- For small systems, lightweight embedded engines (`json-rules-engine`, GoRules) carry far lower overhead than Drools. [COMMUNITY — https://gorules.io/compare/gorules-vs-drools]
- A plain list of `(trigger, condition, action)` triples iterated in-process is functionally equivalent to a rule engine at zero overhead until the reaction set grows to dozens, or rules must be authored at runtime without redeploy. [ASSUMED]

### Reactive / event bus (pub-sub)
- An event bus is "a central, well-known channel into which any part can publish… and from which any other can subscribe"; it decouples producers from consumers. [VERIFIED — https://encore.dev/resources/pub-sub]
- Directly analogous precedent: Home Assistant's core *is* an event bus — every state change fires a `state_changed` event; the automation/rule engine sits on top. [COMMUNITY — https://www.home-assistant.io/docs/configuration/events/]
- "Making a system event-driven is not always a good idea — use Pub/Sub where it's a great fit." Real cost is execution-trace difficulty across async handlers. For one process, a synchronous `notify(event)` to a handler list is functionally identical at near-zero overhead. [VERIFIED — https://encore.dev/resources/pub-sub]
- `otto-engine` is a concrete hybrid: event bus for propagation + a separate JSON rule base (trigger→condition→action). [COMMUNITY — https://github.com/sheaffej/otto-engine]

### Event sourcing / CQRS
- Solves reliable state-change capture + audit: persists every change as an immutable event; current state replayed from the log; gives "100% reliable audit log" and temporal queries. CQRS splits write-model (events) from read-model (projections) because the event store is hard to query directly. [VERIFIED — https://microservices.io/patterns/data/event-sourcing.html]
- Explicit downsides: steeper learning curve, requires CQRS for queries, eventual consistency, event-versioning/schema-evolution burden, storage growth. "Overkill for simpler CRUD applications." [VERIFIED — https://dev.to/lovestaco/cqrs-and-event-sourcing-a-powerful-duo-for-scalable-systems-37g7]
- GDPR right-to-erasure conflicts with immutable events — relevant for personal data. [COMMUNITY — https://medium.com/swlh/stop-overselling-event-sourcing-as-the-silver-bullet-to-microservice-architectures-f43ca25ff9e7]
- Real-world verdict: "For most systems and most parts of a system, traditional data management is sufficient" — a FinTech used ES only in its compliance-bound service. [VERIFIED — https://news.ycombinator.com/item?id=45628315]
- Middle path for an assistant: append events to a SQLite table for the audit trail + keep a separate current-state table for queries — 80% of value without full ES/CQRS. [ASSUMED]

### Saga / process manager (durable workflows)
- Saga = distributed transaction split into local steps with **compensating rollbacks**; embraces eventual consistency. [VERIFIED — https://learn.microsoft.com/en-us/azure/architecture/patterns/saga]
- A **process manager** is the more general primitive: durable state coordination with branching logic; Saga focuses on consistency+compensation, process-manager on stateful routing. [COMMUNITY — https://peerdh.com/blogs/programming-insights/microservices-saga-pattern-vs-process-manager]
- Durable engines (Temporal/DBOS/Restate) persist execution history so a workflow survives crashes and resumes at the exact step, waiting for signals indefinitely without holding a thread. [COMMUNITY — https://temporal.io/blog/what-is-durable-execution]
- Temporal self-hosted is heavy: History service alone wants 4 CPU / 6+ GiB plus a separate DB (Cassandra/MySQL/Postgres). [VERIFIED — https://docs.temporal.io/self-hosted-guide/deployment]
- Lightweight alternative: a SQLite step-checkpoint table per workflow — completed steps write a row; on restart the runner skips done steps. "80% of Temporal's functionality with 20% of the complexity"; Cloudflare Workflows V2 uses this model. [COMMUNITY — https://byteiota.com/sqlite-durable-workflows-skip-temporal/]
- Appropriate even for small systems when a reaction is a minutes-to-hours multi-step sequence (e.g. email→parse→enrich→await approval→act) that must resume not restart. [COMMUNITY — https://microservices.io/patterns/data/saga.html]

---

## 2. Consumer-product automation models

### Home Assistant — trigger / condition / action
- **Universal unit:** `triggers` (OR-joined; any fires) → `conditions` (AND-joined; gate execution) → `actions` (sequential by default). Triggers react to *events*; conditions evaluate *current state* at fire time; event data lives only in `trigger` variables, not conditions. [VERIFIED — https://www.home-assistant.io/docs/automation/yaml/ , https://www.home-assistant.io/docs/automation/basics/]
- **No dedup at the trigger layer** — the dispatch loop calls the action for every matching event with no built-in dedup/throttle. [VERIFIED — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/helpers/trigger.py]
- **`mode` is the concurrency-level dedup:** `single` (drop+log while running — closest to fire-once-per-active-run), `restart`, `queued`, `parallel`; `max_exceeded: silent` suppresses the warning (effectively silent dedup). [VERIFIED — https://www.home-assistant.io/docs/automation/modes/]
- **Actions are strictly sequential** unless `parallel:` (which uses `asyncio.gather`, no cross-branch ordering). Single-threaded asyncio loop; each automation runs as a separate task; state reads/writes are synchronous in-memory, service calls may suspend. Cross-automation ordering is **not** guaranteed. [VERIFIED — https://www.home-assistant.io/docs/scripts/ , https://www.thecandidstartup.org/2025/10/20/home-assistant-concurrency-model.html]
- **No built-in action tiering** — notify/actuate/external-call are all service calls through the same `_async_step_call_service` dispatcher. [VERIFIED — https://www.home-assistant.io/docs/automation/action/]
- **Gating** is via `input_boolean` / `template` conditions (trigger matches but conditions abort before any action runs), plus per-element `enabled: false` (since 2024.10) and `initial_state` for the automation entity itself. [VERIFIED — https://www.home-assistant.io/docs/scripts/conditions/]
- **Storage:** UI automations → flat YAML list in `automations.yaml` (each needs `id`); hand-written → anywhere in the config tree; blueprints → `use_blueprint` + input substitution. Both validated identically; failed automations become `UnavailableAutomationEntity` rather than crashing the system. [VERIFIED — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/automation/config.py]

### n8n — trigger node → logic/action nodes
- Exactly one trigger node starts a workflow (webhook / schedule / service-event / sub-workflow). Data between nodes is an **array of `{json:{…}}` items**; no typed schema. Conditions are **n8n expressions** (`{{ $json.x }}`) inside IF/Switch nodes — no separate rules DSL. [VERIFIED — https://docs.n8n.io/integrations/builtin/trigger-nodes/ , https://docs.n8n.io/data/data-structure/]
- **Dedup is an explicit "Remove Duplicates" node** — within-input, or across-executions (persisted history in n8n's DB, default cap **10,000 items**, oldest evicted), at node or workflow scope. The underlying `$getWorkflowStaticData` is "unreliable under high-frequency executions" → external store (Redis/Postgres) for reliable/distributed dedup. [VERIFIED — https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.removeduplicates/] [COMMUNITY — https://community.n8n.io/t/how-does-n8n-remove-deduplication-history-when-it-reaches-limit/186204]
- **Two-tier side effects:** normal action node = auto-execute; **Wait node** = workflow-level approval checkpoint (holds execution ID live in DB, resumes via webhook callback); AI-agent **tool-level gating** lets ungated tools run freely while only sensitive tools pause. [VERIFIED — https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/ , https://ryanandmattdatascience.com/n8n-human-in-the-loop/]
- **Rules stored as JSON** in n8n's DB; no separate rules table → rule CRUD = editing the workflow definition. [VERIFIED — https://jimmysong.io/blog/n8n-deep-dive/]

### Node-RED — message flow through nodes
- Every message is `{payload, topic, _msgid}`; null payload stops propagation. Canonical chain: input node → **Filter/RBE node** (stateful gate: blocks unless value changed / changed beyond deadband; keeps per-topic last-value) → Switch (routes by `msg.*`) → action node. Wires = `node.wires[outputIndex][n]` target IDs. [VERIFIED — https://flowfuse.com/node-red/getting-started/node-red-messages/ , https://flowfuse.com/node-red/core-nodes/filter/]
- **Flows stored as JSON** (`flows.json` flat file by default; no DB). Function-node rules are JS strings in the node's `func` property. User logic encapsulated via **Subflows**. Persistent state via the **Context** system (node/flow/global scopes; memory-only by default, persisted via `contextStorage`). [VERIFIED — https://nodered.org/docs/user-guide/context , https://github.com/node-red/node-red/wiki/Design:-Persistable-Context]
- **No native approval/pause primitive** — HITL is assembled from HTTP-in webhook + context + reconnected flow. [ASSUMED — no official Node-RED approval doc found]

### Zapier / IFTTT
- Zapier "Human in the Loop" is a first-class Zap action: pauses the run, reviewer can approve/decline/**modify data**; notifications via email/Slack/webhook; `Action if reviewer declines` is configurable (continue/halt/branch); optional confirm-dialog "to prevent accidental actions." [VERIFIED — https://zapier.com/blog/human-in-the-loop-guide/]
- **No native auto-classification into tiers** — the builder manually decides which steps get a HITL action; no built-in reversibility classifier. [COMMUNITY — https://community.zapier.com/how-do-i-3/how-can-you-create-a-manual-approval-step-in-a-zap-204]
- IFTTT has no approval mechanism; all applets fully automatic. [ASSUMED — no IFTTT HITL source found]

---

## 3. Tiered side-effect routing (auto / approve / suggest)

### Classification axes (the basis for tiering)
- **Reversibility** is central: reversible = "can be undone with substantially no consequences"; irreversible = "cannot be undone without adverse effects." [VERIFIED — https://www.howtothink.ai/learn/reversible-versus-irreversible-decisions]
- **External effect** promotes a tier even when technically reversible (recipient cannot un-receive an email). [VERIFIED — https://www.mindstudio.ai/blog/classify-ai-agent-actions-by-risk]
- **Blast radius** (scale of affected parties) and **cascade irreversibility** (Layer-1 reversible but triggers irreversible downstream automations/public responses) further shift routing — rollback buttons don't solve cascade. [VERIFIED — https://www.raktimsingh.com/formal-theory-irreversibility-ai-decisions/]
- **Safety default:** unknown/unclassified actions default to **gated**, not auto. [VERIFIED — https://antigravitylab.net/en/articles/agents/antigravity-agent-reversibility-tiered-autonomy-architecture]

### Published taxonomies
- **Four-tier (MindStudio):** (1) Read-only → auto+log; (2) Reversible-write (internal, undoable) → auto + logging + rate-limit; (3) External (crosses boundary) → staging/dry-run/confidence gate; (4) High-risk/irreversible → mandatory human approval. [VERIFIED — https://www.mindstudio.ai/blog/classify-ai-agent-actions-by-risk]
- **Three-tier (Antigravity, rollback-cost based):** Auto-Reversible (git-revertable, zero external trace) → execute now; Checkpoint-Required (reversible but undo-effort > trivial) → auto **after** snapshot, return checkpoint ID; Irreversible (permanent external mark) → block until explicit approval via confirmation card. Production split ~70/22/8% → ~3.4 approval pauses/day. Confirmation card shows exactly: **what changes / who is affected / what happens if wrong.** [VERIFIED — https://antigravitylab.net/en/articles/agents/antigravity-agent-reversibility-tiered-autonomy-architecture]
- **Formal irreversibility stack:** L1 State (revertable) → L2 Commitment (contracts/filings) → L3 Cascade (downstream automations) → L4 Trust (credibility). [VERIFIED — https://www.raktimsingh.com/formal-theory-irreversibility-ai-decisions/]
- **Confidence-based routing:** below-threshold + irreversible → a *suggestion queue* (not an approval queue) — maps to "inert suggestion." [VERIFIED — https://myengineeringpath.dev/genai-engineer/human-in-the-loop/]

### Implementation patterns for the gate
- **Outbox pattern:** write side-effect intent to an outbox table in the **same atomic transaction** as the state change → separate relay reads unprocessed entries and executes the external effect. The **approval gate lives in the relay step** (block relay behind an approval flag). At-least-once delivery → relay consumers must be **idempotent**. [VERIFIED — https://mkaszubowski.com/2021/10/15/safe-reliable-side-effects-outbox-pattern.html , https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html]
- **Temporal approval gate:** workflow `await workflow.wait_condition(…)` pauses (consumes no compute, survives crashes via event-history replay) until a `@workflow.signal` delivers the human decision; `@workflow.query` reads state for display without mutating. Ungated (read-only/internal) tools run freely; gated tools emit to the queue + await. [VERIFIED — https://learn.temporal.io/tutorials/ai/building-durable-ai-applications/human-in-the-loop/]
- **n8n / Zapier gate:** Wait node / HITL action + IF-on-timeout (auto-escalate, default-safest, or backup reviewer). [VERIFIED — https://blog.n8n.io/human-in-the-loop-automation/]
- **Command pattern as reversibility basis:** each action types itself at definition time (`execute()`/`unexecute()` + stored undo state). Critically, **not every command is undoable** — separate undoable vs non-undoable interfaces explicitly rather than forcing an undo contract. Memento complements Command for checkpoint-tier snapshots. [VERIFIED — https://refactoring.guru/design-patterns/command , https://codinghelmet.com/articles/does-the-command-pattern-require-undo]

### Mapping to the assistant's three tiers
- **Auto-run** = Tier 1 (read-only) + Tier 2 (reversible internal) → execute + log.
- **Stage-for-approval** = Tier 3 (external effect) → outbox (write intent atomically, block relay behind approval) or Wait-node/`wait_condition`; confirmation card = what/who/if-wrong.
- **Inert-suggestion** = below-confidence + irreversible → suggestion queue the user can promote.
- **Key cross-source rule:** classify at **definition time in the action registry**, not at runtime; unknowns default to the most restrictive tier. [VERIFIED — https://antigravitylab.net/en/articles/agents/antigravity-agent-reversibility-tiered-autonomy-architecture]

---

## 4. Stateful / windowed reactions

| Pattern | Semantics | Best for | Pitfall |
|---|---|---|---|
| **Tumbling window** | Fixed non-overlapping intervals; event in exactly one window | Periodic aggregation | Boundary-edge events dropped/misclassified |
| **Sliding window** | Overlapping; event in multiple windows | Rate detection ("3 in 10 min"), anomaly | Expensive — event processed per overlapping window |
| **Session window** | Closes after an inactivity gap | Activity bursts | Memory blow-up w/ many open sessions; gap tuning critical |
| **Count-based** | Fire every N events | Volume triggers | — (often a 4-state FSM) |
| **Debounce** | Fire after stream silent for a period; resets per event; executes with *last* event | Collapse near-simultaneous events | Needs a max-timeout or it defers indefinitely |
| **Rate-limit / throttle** | Fire on *first* event, ignore for cooldown | Suppress bursts | Opposite of debounce — don't confuse |
| **Cooldown** | After firing, ignore re-triggers for a period | Anti-chatter | See HA implementations below |

[VERIFIED — https://medium.com/@amaterajat67/event-stream-windows-tumbling-sliding-session-a-deep-dive-99e5ed6c7e2e , https://www.inngest.com/docs/guides/debounce , https://quix.io/blog/windowing-stream-processing-guide]

- **HA `for:` duration** = condition must hold continuously for the duration; timer resets if state leaves the trigger value. **Does NOT survive HA restart/reload** → persist target time with an `input_datetime` helper. For a *resettable/shared* timer, use a Timer entity. [VERIFIED — https://www.home-assistant.io/docs/automation/trigger/ , https://community.home-assistant.io/t/using-timer-vs-state-with-duration-in-a-trigger/696218]
- **Cooldown implementations:** `mode: single` + trailing delay (reaction blocks re-entry while "running"); or a `last_triggered` template condition `{{ now() - this.attributes.last_triggered > timedelta(minutes=10) }}`. [VERIFIED/COMMUNITY — https://community.home-assistant.io/t/add-cooldown-to-automation/142822/11]
- **Hysteresis (dual-threshold):** high threshold to activate, lower to deactivate — prevents oscillation at a boundary. **Edge triggering** (both `from:` and `to:`) avoids firing on reconnection (`unavailable → on`). [VERIFIED — https://www.howtogeek.com/tricks-to-keep-home-assistant-automations-in-check/]
- **Late events / watermarks:** watermark T asserts all events < T arrived; aggressive = early-but-incomplete, conservative = late-but-complete; post-grace events → dead-letter queue. [VERIFIED — https://www.conduktor.io/glossary/windowing-in-apache-flink-tumbling-sliding-and-session-windows]
- **Temporal triggers — cron vs delay vs state-hold:** cron misses between-poll events; delay/timers are "at least X" not exact (don't rely on sub-second); state-hold (`for`) doesn't survive restart. [VERIFIED — https://docs.temporal.io/workflow-execution/timers-delays]

---

## 5. Known failure modes + mitigations

| Failure mode | Cause | Mitigation | Tag |
|---|---|---|---|
| **Rule explosion** | Combinatorial matching — a rule activates per combination of matching facts; Rete intermediate-node reuse low in dynamic data | Beta-node indexing; PHREAK lazy/set-oriented propagation; decompose rules; constrain fact types that trigger re-eval | [VERIFIED] |
| **Ordering ambiguity** | Two+ rules match the same fact (conflict set) | Salience/priority weights; specificity-first; recency; activation groups (mutual exclusion); agenda-group phasing (`setFocus`) | [VERIFIED] |
| **Self-loop cascade** | Rule's RHS modifies a fact it re-matches | `no-loop` attribute; **property reactivity** (re-fire only if a *used* property changed); control-fact sentinel pattern | [VERIFIED] |
| **Complex-loop cascade** | A→modifies→B→modifies→A | `lock-on-active` (group-scoped); depth/iteration counter limit (e.g. 200); refraction (don't re-fire on identical fact state) | [VERIFIED] |
| **Restart state loss** | In-memory timers/`for`/context cleared on restart | Persist target-time via `input_datetime`; persistent context store (filesystem/Redis) | [VERIFIED/COMMUNITY] |
| **Webhook/event self-trigger** | Action emits an event that re-triggers the same rule | Payload-hash dedup at entry; edge-triggering (`numeric_state` fires only on threshold crossing, not every eval) | [VERIFIED/COMMUNITY] |
| **Debuggability gap** | Forward-chaining path is data-driven, not statically predictable | Per-execution **trace** (which trigger fired, each condition pass/fail + why, action branches, timestamps, variable state); retention cap; sentinel-fact breadcrumbs. *Gap: traces capture only runs that DID fire — non-firing needs indirect inference.* | [VERIFIED] |

[VERIFIED sources — https://en.wikipedia.org/wiki/Rete_algorithm , https://docs.drools.org/8.38.0.Final/drools-docs/docs-website/drools/rule-engine/index.html , https://www.nected.ai/us/blog-us/what-happens-when-rules-conflict-rule-engine , https://ilesteban.wordpress.com/2012/11/16/about-drools-and-infinite-execution-loops/ , https://newerest.space/mastering-automation-debugging-observability-home-assistant/ , https://community.home-assistant.io/t/how-to-stop-automation-from-looping/140069]

**Control-fact (idempotency sentinel) example — Drools DRL:**
```
when
    $c: Customer(seniority > 3)
    not DiscountApplied(type == "3 years", customer == $c)
then
    modify($c){ setDiscount($c.getDiscount()+0.1) }
    insert(new DiscountApplied("3 years", $c));
end
```
[VERIFIED — https://ilesteban.wordpress.com/2012/11/16/about-drools-and-infinite-execution-loops/]

---

## Assumptions / gaps

- Small-single-user fit verdicts beyond cited docs are tagged `[ASSUMED]` (in-process bus ~30 lines; plain triple-list ≈ rule engine until dozens of rules; SQLite audit-table ≈ 80% of ES value). These are reasoning extrapolations, not measured.
- IFTTT HITL and Node-RED native approval: no primary source found → treat absence as unconfirmed, not proven.
- `NEEDS-DOMAIN` (search-snippet only, not fetched — outside allow-list): `event-driven.io` (Saga vs Process-Manager code), `www.elastic.co` (Elastic HITL), `support.inrule.com` (rule tracing, 401), several `home-assistant.io` / `community.home-assistant.io` / `thecandidstartup.org` pages (fetched fine via WebFetch despite not being on the github-only sublist for the HA agent).

## Sources
Consolidated inline above (URL on every claim). Primary anchors: Drools docs, microservices.io (ES/CQRS/Saga), Azure Architecture Center, Temporal docs + learn.temporal.io, Home Assistant docs + core source (raw.githubusercontent.com), n8n docs, Node-RED/FlowFuse docs, MindStudio + Antigravity Lab (tiering taxonomies), transactional-outbox (mkaszubowski + AWS), Inngest (debounce), Flink/Quix (windowing), Rete (Wikipedia/Grokipedia).

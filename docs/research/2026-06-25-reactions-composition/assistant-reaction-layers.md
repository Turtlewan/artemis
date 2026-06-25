# Reaction Layers in Personal-AI Assistants: Event-Driven & Proactive Patterns
**Phase-2 Retrieval — 2026-06-25**
**Topic:** How current agentic/personal-AI systems implement reactive, event-driven, cross-module behavior.
**Scope:** Triggers · hooks · proactive agents · approval gates · event-driven memory writes · practitioner pitfalls.

---

## 1. Event/Trigger/Hook Models in Agent Frameworks

### 1.1 LangGraph (langchain-ai/langgraph)
**Repo:** https://github.com/langchain-ai/langgraph — **35.7k stars**, latest release v1.2.6 (2026-06-18) [VERIFIED]

LangGraph models triggers as **conditional edges** in a directed state-graph. Four canonical trigger categories: [VERIFIED — medium.com/@_Ankit_Malviya/building-event-driven-multi-agent-workflows-with-triggers-in-langgraph-48386c0aac5d]

| Trigger Type | Mechanism | Example |
|---|---|---|
| **Event-based** | Conditional edge fires on agent-completion signal | SQL agent done → Summarizer activates |
| **State-based** | Lambda over graph state routes intent | `state.get("intent") == "fetch_data"` |
| **Time-based** | Delay or interval activation | Cache invalidation after TTL |
| **External** | Webhook / message-queue / DB change | FastAPI endpoint receives payload → `graph.invoke()` |

```python
graph.add_conditional_edges(
    "IntentAgent",
    condition=lambda state: (
        "SQLAgent" if state.get("intent") == "fetch_data"
        else "Summarizer"
    )
)
```

**Dynamic trigger registration** enables runtime addition of new trigger conditions; **fan-out triggers** activate multiple agents simultaneously via `StateGraph`. [VERIFIED — same source]

LangGraph v1.0 (late 2025) makes **time a first-class concern**: agents can pause, persist state across process restarts, retry on failure, and resume from the exact checkpoint. [VERIFIED — github.com/langchain-ai/langgraph]

The framework also exposes **webhook integration** via async handlers that receive payloads and invoke graph workflows asynchronously. [VERIFIED — medium.com/@_Ankit_Malviya]

---

### 1.2 Letta (letta-ai) / Sleep-Time Agents
**Repo:** https://github.com/letta-ai/letta
**Docs:** https://www.letta.com/blog/sleep-time-compute — [VERIFIED]

Letta introduced **sleep-time compute** (April 2025): a dedicated secondary agent runs in the background during idle periods and rewrites the primary agent's in-context memory blocks. [VERIFIED — letta.com/blog/sleep-time-compute]

Key architectural details: [VERIFIED — docs.letta.com/guides/agents/architectures/sleeptime/]
- The **primary agent is NOT given tools to edit its own core memory** — memory writes are gated through the sleep-time agent only.
- A single agent can have **one or more associated sleep-time agents**, each watching different data sources (conversation history, external feeds).
- Sleep-time agents are **configurable by frequency** — higher frequency = more token cost but fresher learned context.
- The design is explicitly dual-agent: primary handles user interactions; sleep-time agent handles memory management **asynchronously**, improving both response latency and memory quality over bundled MemGPT single-agent designs.

**Triggering:** The blog indicates sleep-time agents run when systems "would otherwise sit idle," but specific event-subscription hooks triggering them externally are not documented in public docs. Scheduling frequency is configurable; event-driven external triggers are [ASSUMED — not documented publicly].

**Provenance of written facts:** Letta's public docs do not describe source-tagging of sleep-time-written memories. [ASSUMED — absent from docs fetched]

---

### 1.3 Khoj (khoj-ai/khoj)
**Repo:** https://github.com/khoj-ai/khoj — **35.3k stars**, release 2.0.0-beta.28 (2026-03-26) [VERIFIED]

Khoj's automation model is **cron-scheduled** rather than event-driven: [VERIFIED — github.com/khoj-ai/khoj releases page; mintlify.com/khoj-ai/khoj/api/automations]

- Users define automations with a **cron expression** (minute | hour | day-of-month | month | day-of-week).
- At fire time: Khoj executes the configured query against its knowledge base and/or the web, generates a response, and **delivers it to the user's registered email**.
- **Manual on-demand trigger** also supported alongside the scheduled cron.
- No "when X then Y" event-subscription model surfaced in public documentation.

**Architecture:** The automation model is query-driven ("run this research at this time") rather than event-reactive ("fire when email arrives"). Proactive behavior is achieved purely via time triggers + persistent task definitions, not event subscriptions. [VERIFIED — khoj search result snippet; COMMUNITY — automation API docs]

---

### 1.4 Leon (leon-ai/leon)
**Repo:** https://github.com/leon-ai/leon — **17.3k stars**, latest notice 2026-03-29 [VERIFIED]

Leon organizes capabilities as **Skills → Actions → Tools → Functions → Binaries** and distinguishes three execution modes: [VERIFIED — github.com/leon-ai/leon]
- **Smart mode**: chooses execution path autonomously.
- **Controlled mode**: deterministic native skills/actions (no LLM required).
- **Agent mode**: step-by-step planning with an LLM.

Leon references a **"bounded proactive pulse system"** to maintain consistency between sessions without flooding context. Implementation details are sparse; the `core/context/LEON.md` and `core/context/ARCHITECTURE.md` files are the ground truth (not the public README, which lags the 2.0 Developer Preview). [COMMUNITY — github.com/leon-ai/leon README]

**Approval gates, event hooks:** not publicly documented in the fetched content. [ASSUMED — absent]

---

### 1.5 Home-LLM + Home Assistant (acon96/home-llm)
**Repo:** https://github.com/acon96/home-llm — **1.4k stars**, latest release v0.4.9 (2026-05-28) [VERIFIED]

This integration connects a local LLM to Home Assistant as a **conversation agent + tool executor**: [VERIFIED — github.com/acon96/home-llm]
- v0.4 introduced a **"rewrite for tool calling models"** with an **"agentic tool use loop"** — the model iteratively calls HA service tools and processes responses.
- Home Assistant's native **event bus** supports `Manual event received` triggers: fire when any integration, script, or API call emits a named event, matchable on event type, data, or triggering user. [VERIFIED — home-assistant.io/triggers/event/]
- **AI Tasks** are automations that use AI to process data and generate structured responses — enabling conditional agent execution from HA automations.
- No explicit approval gate documented in home-llm; Home Assistant automations can include confirmation steps via `input_boolean` or notification actions, but these require manual wiring. [COMMUNITY — home-assistant.io community docs]

The HA + LLM pattern is notable for showing how an **existing platform event bus** (with dozens of built-in trigger types: state change, time pattern, calendar event, webhook, MQTT message, etc.) can be surfaced to an LLM without rebuilding the trigger layer. [VERIFIED — home-assistant.io/docs/automation/trigger/]

---

## 2. Proactive vs. Reactive Agent Patterns (2025-2026)

### 2.1 Two Core Proactivity Mechanisms

Practitioners and papers converge on two primitives: [COMMUNITY — mindstudio.ai/blog/what-is-proactive-ai; vanishlabs.ai/news/proactive-ai]

1. **Scheduled (heartbeat/cron):** Agent runs at defined intervals regardless of events — daily briefings, recurring summaries, trend monitoring. Simple and predictable but insensitive to real-time changes.
2. **Event-driven (subscription):** Agent activates when a specific condition fires — new email, calendar event, threshold crossed, webhook received. More timely but requires an event bus or polling infrastructure.

Most open-source personal assistants (Khoj, Leon, OpenClaw/Clawdbot) implement **cron + manual trigger** as their proactivity substrate, with event-driven hooks being an emergent integration via webhooks. [COMMUNITY — search result synthesis; VERIFIED — Khoj automation docs]

### 2.2 Letta Sleep-Time: Background Memory Agent
Letta's sleep-time model is a specialized form of scheduled proactivity: [VERIFIED — letta.com/blog/sleep-time-compute]
- During idle, the sleep-time agent asynchronously reorganizes memory — transforming "raw context" into "learned context."
- The agent operates at **configurable frequency** — effectively a heartbeat with variable rate.
- This decouples memory management from response latency: the primary agent only reads memory at inference time; all writes happen out-of-band.

### 2.3 Long-Horizon Proactive Agents (Research, 2025-2026)

**ProPerSim** (arxiv.org/pdf/2509.21730) and **PASK** (arxiv.org/pdf/2604.08000) represent research directions for intent-aware proactive agents with long-term memory: [COMMUNITY — arxiv search snippets]
- PASK specifically addresses maintaining intent across sessions and proactively surfacing relevant actions without user prompts.
- **Long-term task-oriented agents** (arxiv.org/pdf/2601.09382) study "proactive long-term intent maintenance in dynamic environments." [COMMUNITY — arxiv]

**Critical unresolved challenges** identified in the literature: [COMMUNITY — mindstudio.ai/blog synthesis]
1. How to define a general paradigm for proactive AI.
2. Low-latency, accurate detection of latent user needs under continuous real-time input.
3. Evolving memory so agents accumulate user understanding and adapt over time.
4. Reliable performance at low latency in real-world deployments.

---

## 3. Tool-Calling + Approval Gates

### 3.1 LangGraph `interrupt()` + `Command` Pattern
**Source:** https://www.abstractalgorithms.dev/langgraph-human-in-the-loop [VERIFIED]

The canonical 2025-2026 pattern:

```python
# Inside a node — pauses graph and returns payload to caller
approval = interrupt({
    "question": "Proceed with deletion?",
    "operation": state["target"]
})

# Caller resumes with human decision
resumed = graph.invoke(Command(resume="approve"), config)
```

**Critical implementation notes:** [VERIFIED — abstractalgorithms.dev]
- Both pause and resume **must use the same `thread_id`** — the checkpointer serializes the full state snapshot.
- **Code before `interrupt()` runs twice**: once on the way to the pause, once on resume — side effects MUST be placed AFTER the interrupt call to maintain idempotency.
- Reviewers can **edit agent state** before resuming (not just approve/reject) via `update_state()`.
- Dev: `MemorySaver`; Production: requires `SqliteSaver` or cloud equivalent to survive process restarts.

**Risk classification rule of thumb:** [VERIFIED — abstractalgorithms.dev]

| Risk Level | Examples | Gate |
|---|---|---|
| Low | Read-only search, draft creation, summarization | No interrupt |
| Medium | Internal writes with rollback path | Approve/edit option |
| High | External sends, deletes, financial moves, config changes | Mandatory interrupt |

### 3.2 HumanLayer Decorator Pattern
**Source:** https://agentic-patterns.com/patterns/human-in-loop-approval-framework/ [VERIFIED]

```python
@hl.require_approval(channel="slack")
def delete_user_data(user_id: str):
    return db.users.delete(user_id)
```

Approval requests flow through Slack/email/SMS with context-rich payloads; humans approve/reject/modify via platform-native buttons. All approvals are logged with who approved what and when. [VERIFIED]

### 3.3 Cloudflare Agents `waitForApproval()` Pattern
**Source:** https://developers.cloudflare.com/agents/concepts/agentic-patterns/human-in-the-loop/ [VERIFIED]

- **Pending approvals** stored in agent state as an array with `workflowId`, `amount`, `description`, `requestedBy`, `requestedAt`.
- `waitForApproval()` suspends the workflow durably; resumes via `approveWorkflow()` / `rejectWorkflow()`.
- **Timeout** parameter (e.g., "7 days") triggers escalation or auto-rejection.
- `schedule()` enables timed reminders/escalations while waiting. [VERIFIED]

### 3.4 Industry Consensus on Gate Placement (2025)
The practitioner consensus in 2025-2026 is: [COMMUNITY — redis.io/blog/ai-human-in-the-loop; machinelearningmastery.com/building-a-human-in-the-loop-approval-gate; stackai.com]

> "In 2024, agent demos focused on autonomy; in 2025-2026, teams encountered the reality that one wrong tool call can delete data, send bad emails, or trigger compliance issues. The breakout idea is not 'make agents smarter,' but 'make risky steps governable.'"

Three gate patterns in production use:
1. **Pre-execution approval** — pause before every high-risk action, ask for explicit confirmation.
2. **Post-execution review** — act, then surface for inspection before committing.
3. **Escalation trigger** — run autonomously; halt and request input when risk signals fire (sensitive data, irreversible operation, confidence below threshold).

---

## 4. Memory Writes Triggered by Events

### 4.1 MemOS (MemTensor/MemOS)
**Repo:** https://github.com/MemTensor/MemOS — **10k stars**, release v2.0.20 (2026-06-18) [VERIFIED]
**Paper:** https://arxiv.org/html/2507.03724v2 (arXiv:2507.03724, July 2025) [VERIFIED]

MemOS is a three-layer memory operating system treating memory as a first-class OS resource: [VERIFIED — arxiv.org/html/2507.03724v2]

**Layers:**
- **Interface Layer:** MemReader + standardized Memory APIs — how events enter the system.
- **Operation Layer:** MemOperator + MemScheduler + MemLifecycle — scheduling writes, managing state transitions.
- **Infrastructure Layer:** MemVault + MemGovernance + MemStore — storage, permissions, cross-platform.

**Provenance tagging:** [VERIFIED]
> "Provenance API enables provenance tracking by embedding metadata into memory objects at creation or modification time. This includes event triggers, contextual state, model identifiers, and external links."

Each memory unit receives a **unique provenance ID persisting throughout its lifecycle**. The **MemCube** is the universal encapsulation unit — a standardized wrapper with consistent metadata headers enabling full-spectrum lifecycle management.

**Memory state machine:** Generated → Activated → Merged → Archived → Expired. The MemLifecycle component governs transitions based on access patterns and temporal decay. [VERIFIED]

**Governance per memory unit:** Access Control (read/write/share scope), Lifespan Policy (TTL or decay rules), Priority Level (for scheduling), Compliance & Traceability. [VERIFIED]

### 4.2 Event-Centric Memory (Research Pattern)
**Paper:** "Memory Matters More: Event-Centric Memory as a Logic Map for Agent Searching and Reasoning" — arxiv.org/pdf/2601.04726 (2026-01) [COMMUNITY — accessible only as PDF; content extracted from search snippet]

The paper treats events as primary units and derives structured facts from them. Processing pipeline: [COMMUNITY]
1. Raw event streams → summarization → reflection → entity extraction → fact induction.
2. Resulting abstractions stored in vector DBs, key-value stores, or knowledge graphs.
3. Deduplication and consistency checking govern writes.
4. In multi-agent settings, memory can be filtered by **participant and session** — separating user-stated facts from agent-generated inferences.

### 4.3 Letta's Asynchronous Memory Write Model
**Source:** letta.com/blog/sleep-time-compute [VERIFIED]

The sleep-time agent holds **exclusive write access** to core memory blocks — the primary agent has read-only access. This enforces a single-writer model preventing race conditions in concurrent agent architectures. Memory rewrites happen out-of-band on a configurable heartbeat schedule. Provenance of sleep-time-written facts is not publicly documented. [VERIFIED for mechanism; ASSUMED for provenance]

### 4.4 Mem0 / General Agent Memory Frameworks (2026 State)
**Source:** mem0.ai/blog/state-of-ai-agent-memory-2026 [COMMUNITY]

The 2026 landscape report notes: agents can filter by **participant and session**, which helps separate user-stated facts from agent-generated inferences. Multi-agent provenance is emerging as a reliability requirement, not just a debugging aid. Challenges cited: normalizing content, resolving entity identity, preserving provenance, enforcing permissions, deciding which source is authoritative when facts conflict. [COMMUNITY]

---

## 5. Notable Architecture Patterns & Practitioner Pitfalls (2025-2026)

### 5.1 The "Interrupt-on-Action" Rule
**Source:** abstractalgorithms.dev, agentic-patterns.com [VERIFIED]

Targeting interrupts only at irreversible, high-blast-radius actions (not every step) is now established practice. The double-execution side-effect bug (code before `interrupt()` runs twice) is a known LangGraph HITL pitfall that burned many early adopters. [VERIFIED — blog.raed.dev/posts/langgraph-hitl/]

### 5.2 Timing-Dependent Receptivity
**Source:** arxiv.org/html/2601.10253v1 — "Developer Interaction Patterns with Proactive AI: A Five-Day Field Study" [VERIFIED]

Proactive suggestions triggered at workflow boundaries achieved markedly different engagement:
- Post-commit: **52% engagement** (highest acceptance)
- Ambiguous prompt detection: **46%** (moderate)
- Declined-edit follow-up: **31%** (62% dismissal rate — felt intrusive)

**Key lesson:** Proactive agents should fire at natural **task completion points** (after commits, failed builds, test runs), NOT mid-implementation. Mid-task interruptions were described as "like advertisement." [VERIFIED]

### 5.3 Context Misalignment / False Positives
From the same field study: [VERIFIED — arxiv.org/html/2601.10253v1]
- Only **27% of suggestions rated as reliable** when AI failed to account for domain-specific patterns.
- Session degradation in extended contexts forced restarts and lost continuity — a structural pitfall for agents with long-running "monitor and react" loops.

### 5.4 Notification / Alert Fatigue
**Sources:** securityboulevard.com/2026/04/ai-alert-triage; parloa.com/knowledge-hub/proactive-ai [COMMUNITY]

The dominant failure mode in production proactive assistants: excessive or poorly-prioritized alerts cause users to either ignore all notifications or disable the agent entirely. Practitioners recommend:
- **Intelligent priority filtering**: surface only what genuinely requires attention.
- **User-configurable trigger thresholds**: let users tune frequency and sensitivity.
- **Confidence signaling**: show why the trigger fired and what confidence level drove it.
- Regular human review of agent-learning loops to catch over-alerting drift.

### 5.5 Long-Horizon Compounding Error
**Source:** mindstudio.ai/blog/what-is-proactive-ai (synthesis of practitioner reports) [COMMUNITY]

> "The dominant failure mode is long-horizon compounding error under tool and environment variability: the agent must retrieve the right context, choose correct tools and arguments, and recover from partial failures."

Nondeterminism (LLM sampling, tool failures) compounds across a multi-step proactive pipeline. This motivates **verification loops** and **trace-based evaluation** as requirements, not nice-to-haves. [COMMUNITY]

### 5.6 Single-Writer Memory Discipline
Letta's architectural choice to give sleep-time agents exclusive write access to core memory is a specific, defensible answer to a general concurrency problem: when multiple agents or processes can write shared memory, consistency degrades. The single-writer model (primary reads; sleep-time writes) is a clean separation. [VERIFIED — letta.com/blog/sleep-time-compute]

### 5.7 Event Bus Re-use vs. Build-From-Scratch
Home Assistant's integration with LLMs (acon96/home-llm) demonstrates a pragmatic pattern: **use the existing platform event bus** (with decades of trigger types already built) rather than building a new event system. Dozens of trigger types (state change, time pattern, calendar event, webhook, MQTT, geofence, etc.) become available to an LLM tool-caller without rebuilding trigger infrastructure. The lesson for a privacy-first personal assistant: the reaction layer does not need its own event bus if it can attach to the host platform's event mechanism. [VERIFIED — github.com/acon96/home-llm; home-assistant.io/docs/automation/trigger/]

---

## 6. Domains Not Covered (Needs Further Research)

- `NEEDS-DOMAIN: docs.khoj.dev — https://docs.khoj.dev/features/automations — technical implementation details of Khoj's automation scheduler (trigger model internals, event hooks beyond cron)`
- `NEEDS-DOMAIN: blog.raed.dev — https://blog.raed.dev/posts/langgraph-hitl/ — LangGraph HITL double-execution pitfall deep dive`
- `NEEDS-DOMAIN: arxiv.org — https://arxiv.org/pdf/2410.12361 — "Proactive Agent: Shifting LLM Agents from Reactive Responses to Active Assistance" — full paper for taxonomy`

---

## Source Index

| Tag | URL | Tier |
|---|---|---|
| langgraph-repo | https://github.com/langchain-ai/langgraph | [VERIFIED] |
| langgraph-triggers | https://medium.com/@_Ankit_Malviya/building-event-driven-multi-agent-workflows-with-triggers-in-langgraph-48386c0aac5d | [VERIFIED] |
| langgraph-hitl | https://www.abstractalgorithms.dev/langgraph-human-in-the-loop | [VERIFIED] |
| letta-sleeptime-blog | https://www.letta.com/blog/sleep-time-compute | [VERIFIED] |
| khoj-repo | https://github.com/khoj-ai/khoj | [VERIFIED] |
| khoj-automations | https://www.mintlify.com/khoj-ai/khoj/api/automations | [COMMUNITY] |
| leon-repo | https://github.com/leon-ai/leon | [VERIFIED] |
| home-llm-repo | https://github.com/acon96/home-llm | [VERIFIED] |
| ha-triggers | https://www.home-assistant.io/docs/automation/trigger/ | [VERIFIED] |
| ha-event-trigger | https://www.home-assistant.io/triggers/event/ | [VERIFIED] |
| cloudflare-hitl | https://developers.cloudflare.com/agents/concepts/agentic-patterns/human-in-the-loop/ | [VERIFIED] |
| agentic-patterns-hitl | https://agentic-patterns.com/patterns/human-in-loop-approval-framework/ | [VERIFIED] |
| memos-arxiv | https://arxiv.org/html/2507.03724v2 | [VERIFIED] |
| memos-repo | https://github.com/MemTensor/MemOS | [VERIFIED] |
| proactive-field-study | https://arxiv.org/html/2601.10253v1 | [VERIFIED] |
| event-centric-memory | https://arxiv.org/pdf/2601.04726 | [COMMUNITY — PDF only] |
| mem0-state-2026 | https://mem0.ai/blog/state-of-ai-agent-memory-2026 | [COMMUNITY] |
| langgraph-hitl-bug | https://blog.raed.dev/posts/langgraph-hitl/ | [COMMUNITY — needs-domain] |
| openclaw-search | https://emergent.sh/learn/what-is-openclaw | [COMMUNITY] |

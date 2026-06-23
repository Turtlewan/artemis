# Architecture Validation — The 7 Memory Types vs Artemis

**Date:** 2026-06-23
**Researcher:** Claude Opus 4.8 (research fork, skeptic brief)
**Trigger:** Owner read a "7 types of memory" taxonomy and asked: for each type, is it already accounted for in Artemis, or should we weave it in?
**Builds on:** reports 01 (memory), 02 (knowledge/RAG), 03 (holistic) in this dir + reservations **A–H** derived there. This is a *lens check*, not a re-derivation.

---

## Bottom line up front

**The 7-type taxonomy is a useful audit lens, and it largely VALIDATES the existing design rather than exposing new holes.** Six of the seven types are already first-class in Artemis (often ahead of SOTA); the lens maps almost 1:1 onto reservations A–H we already surfaced. Two genuinely new findings:

1. **Parametric memory** is the one type A–H never named. Artemis's stance is *deliberate exclusion as a runtime-learning mechanism* (the locked "RAG/recipes, NEVER weight fine-tuning" bet — `brain.md`), **with one sanctioned offline write-path**: the Codex-distilled local `sensitive_reasoner` (ADR-022 + `distill-datagen-pipeline`). That's a coherent position, but it was *implicit*. Worth recording explicitly so "we don't do parametric memory" isn't mistaken for an oversight — it's a decision, and it has a designed exception.
2. **Prospective memory** ("remember to do X later / when Y happens") is *real and present but fragmented* across four mechanisms (heartbeat hooks M6, reactions ADR-021, Productivity tasks/reminders, Task-Executor background goals ADR-024) with **no unified representation**. Low-confidence candidate reservation (additive, not foundational): make sure a *condition-triggered future intention* has one home, not four.

Everything else is Accounted or already captured by A–E. **No new FOUNDATIONAL reservation beyond A–H.** Confidence: **High** on the mapping; **Medium** on the prospective-fragmentation call (it may be fine as-is).

The taxonomy itself: the canonical academic frame is **CoALA** (working/episodic/semantic/procedural; Princeton/CMU, arXiv 2309.02427), which Letta/Mem0/LangChain all build on. 2025–26 surveys add the **parametric vs contextual** cut (arXiv 2505.00675, 2603.07670). "External/retrieval" = contextual-non-parametric; "prospective" is imported from cognitive psychology and is the least-standardized of the seven in LLM literature.

---

## Mapping table

| # | Memory type | Verdict | Where it lives in Artemis | A–H overlap |
|---|---|---|---|---|
| 1 | In-context / working (short) | **Accounted** | Responder context window + M4-c-1 auto-inject (facts → system prompt, token-budgeted) + ADR-024 task-memory (in-flight job state) | F (durability of task-memory) |
| 2 | Semantic (long) | **Accounted (ahead)** | M4 `SemanticFact` bitemporal triples, A.U.D.N. write, entity backbone (ADR-013), composite-forgetting recall | A extends it (derived facts) |
| 3 | Episodic (long) | **Accounted (ahead)** | M4 `Episode` bitemporal append-only log (event-time + ingestion-time) | — |
| 4 | Procedural (long) | **Accounted as recipes; Partial in the memory engine** | Recipes (M7-a/b, replay-verified, owner-gated) + reactions (ADR-021). In `MemoryStore` it's only a *named role over fact tables* (data-model.md L84) | **B** (don't lock the port to triples) |
| 5 | External / retrieval (long+short) | **Accounted (ahead)** | M3 knowledge corpus: LanceDB hybrid + rerank + late-chunking + agentic multi-hop + ColQwen visual | **D, E** (hierarchy + structured-projection hooks) |
| 6 | Parametric (long) | **Deliberately excluded (runtime); present via offline distillation** | The base LLM's pretrained weights (used, never runtime-written). Self-improvement is non-parametric by lock. Sole write-path: offline distill → local `sensitive_reasoner` (ADR-022, `distill-datagen-pipeline`) | **NEW lens** (not in A–H) |
| 7 | Prospective (short+long) | **Partial — present but fragmented** | Heartbeat hooks (M6), reactions "when X→then Y" (ADR-021), Productivity tasks/reminders, Task-Executor background goals (ADR-024) | partial F/G; **candidate NEW-1** |

---

## Per-type detail

### 1 · Working / in-context memory — **Accounted**
The working-memory job (assemble the right things into the active context this turn) is explicitly engineered: M4-c-1 auto-injects decay-ranked current facts into the system prompt within a token budget (the model never calls a memory tool — recall is a *system property*), and ADR-024 gives multi-step tasks a **durable, resumable task-memory** (goal · plan · per-step status · intermediate results · retry counts). The only real risk here is durability of that task-memory under crashes/overlapping heartbeats — which is exactly **reservation F** (durable-execution + idempotency). No new action. (Confidence: High.)

### 2 · Semantic memory — **Accounted, ahead of median**
`SemanticFact` triples with 4-timestamp bitemporal validity, A.U.D.N. conflict resolution, cardinality-aware keying, A-MEM note metadata, entity backbone. Report 01 already judged this SOTA-for-constraints. The one cognitive-layer gap (a consolidation/reflection pass that synthesises *across* facts) is report 01's main finding and is unlocked by **reservation A** (`source_kind="derived"`). Covered. (High.)

### 3 · Episodic memory — **Accounted, ahead**
Bitemporal append-only `Episode` log, never re-fed raw to the LLM (retrieved via distilled tiers), distil-up-before-discard forgetting. This is precisely the episodic design CoALA/Letta describe. Nothing missing. (High.)

### 4 · Procedural memory — **Accounted as recipes; Partial inside the memory engine**
This is the type with the most nuance, and it splits cleanly:
- **As a capability, Artemis is ahead.** Recipes (SKILL.md-shaped, replay-verified, recurrence-gated, owner-promoted, signed; M7) are *exactly* the 2026 "skill library, not fine-tuning" consensus (Voyager/GEPA lineage — report 03). Reactions (ADR-021) add event-triggered procedures. The owner's "procedural memory" is genuinely present and well-built.
- **Inside the `MemoryStore`, it's only a word.** data-model.md L84 + ADR-004 treat procedural as "a *role* over the (subject, relation, object) fact tables," with no procedure-shaped record (steps / preconditions / success-criteria). That's the gap report 01 flagged as **reservation B** — don't hard-code the port to triples, so a `procedure` record type can be added behind it later. **This is the one place the 7-type lens reinforces an existing FOUNDATIONAL-ish call.** Skeptic note: recipes-as-module-artifact and procedural-memory-as-store may *both* be wanted long-term (a recipe is a vetted, signed, promotable automation; procedural *memory* is the rawer "how the owner likes things done" that feeds recipe distillation). Keeping B's port open preserves that option. (High.)

### 5 · External / retrieval memory — **Accounted, ahead**
The RAG corpus (M3) *is* external/contextual memory, and report 02 found it already implements the 2026 adaptive-RAG consensus. The two foundational hooks it still needs — **D** (RAPTOR-style `node_level`/`is_summary` + parent link) and **E** (structured-projection ingest hook for aggregates) — are the knowledge-side reservations. Covered. (High.)

### 6 · Parametric memory — **Deliberately excluded at runtime; present via offline distillation** *(NEW lens)*
A–H never mention parametric memory — the lens forces the call into the open:
- **Runtime: excluded by lock.** `brain.md` § Self-improvement is explicit — "IN, RAG/skill-only, **NEVER weight fine-tuning**… Explicitly NOT SEAL weight updates nor self-code-rewrite." This is the *correct* 2026 bet (skill libraries beat online fine-tuning for reliability/auditability/anti-collapse — report 03). So the agent never writes its own weights live. **This is a decision, not a gap.**
- **Offline: there IS a parametric write-path, and it's already designed.** ADR-022's sensitive path graduates a **Codex-distilled local reasoner** (`sensitive_reasoner`), trained offline on *synthetic* traces by `distill-datagen-pipeline`, then Mac-side MLX training. That is parametric memory — knowledge baked into local weights — done deliberately, offline, on synthetic data (real records never leave the box). The base models' pretrained knowledge is likewise parametric memory, used as-is.
- **Recommendation:** no build action; **record the stance explicitly** (one line in ADR-004 or brain.md): "Parametric memory is not a runtime mechanism (non-parametric self-improvement is locked); the only parametric write-path is offline distillation to the local reasoner (ADR-022)." Prevents a future reviewer re-opening it as an oversight. (High.)

### 7 · Prospective memory — **Partial: present but fragmented** *(candidate NEW-1)*
Prospective memory = remembering to perform an intended action in the future, either **time-based** ("at 6pm") or **event-based** ("next time I talk to Ashley"). Artemis has the capability, spread across four mechanisms:
- **Time-based:** Heartbeat scheduled hooks (M6, interval/cron) + Productivity tasks/reminders + calendar events.
- **Event-based:** Reactions (ADR-021, learned "when X → then Y") + heartbeat event-injection.
- **Goal-deferred:** Task-Executor background goals advanced by the heartbeat (ADR-024).

The capability is real, but there is **no single "prospective memory / pending intentions" representation** — an owner- or agent-set deferred intention tied to an arbitrary condition lives in whichever of the four mechanisms happens to fit. For most cases that's fine (a reminder → a task; a recurring check → a hook; a learned trigger → a reaction). The skeptic's worry is the *ad-hoc agent-set intention* ("I should follow up on the landlord reply if no answer by Friday") that doesn't cleanly belong to any spoke.
- **Recommendation (NEW-1, ADDITIVE, Medium confidence):** likely **no foundational action** — ADR-021 reactions + ADR-024 task-memory already provide condition→action storage. *Confirm* that a future-dated/condition-gated intention can be represented in one of them (reactions for event-gated, task-memory for goal-deferred) without a new store. If a unified "intentions" view is later wanted, it's an additive read-layer over those, not a schema change. Flag, don't build. (Medium — depends on whether agent-initiated deferred intentions become common; they're a Jarvis-end-state behaviour.)

---

## Cross-reference to reservations A–H

| 7-type lens | Maps to | New? |
|---|---|---|
| Working/task-memory durability | **F** (durable execution + idempotency) | captured |
| Semantic consolidation/derived facts | **A** (`source_kind="derived"`) | captured |
| Procedural-in-the-store | **B** (port not triple-only) | captured — **lens reinforces B** |
| External/retrieval hierarchy + aggregates | **D, E** | captured |
| Async-write + multi-scope tags | **C** | captured |
| Planner/long-horizon (prospective goals) | **G** | partially captured |
| Parametric memory | — | **NEW lens** (confirm-the-stance, not a build) |
| Prospective intentions unification | — | **NEW-1** (additive, low/med priority) |

**The lens surfaces no new FOUNDATIONAL reservation.** Its value is: (a) it independently re-confirms B as worth keeping open (procedural), and (b) it forces two implicit positions into the record (parametric = deliberately-excluded-with-offline-exception; prospective = present-but-fragmented).

---

## Verdict

The 7-type taxonomy is a **clean bill of health with two footnotes.** Working, episodic, semantic, external/retrieval are accounted and often ahead; procedural is well-built as recipes and only needs reservation **B** to stay open in the memory port; parametric is a deliberate (and correct) exclusion that deserves one explicit sentence in the docs plus acknowledgement of the offline-distillation exception; prospective is functionally present but fragmented and worth a *confirm-the-representation* note, not a new store. Net: **do A–H as planned; add one documentation line for parametric; keep NEW-1 (prospective unification) on the watch list as additive.**

---

## Sources (dates / confidence)

- [CoALA — Cognitive Architectures for Language Agents, arXiv 2309.02427](https://arxiv.org/abs/2309.02427) — canonical working/episodic/semantic/procedural frame. VERIFIED, High.
- [Rethinking Memory in LLM-based Agents — arXiv 2505.00675 (2025)](https://arxiv.org/pdf/2505.00675) — parametric vs contextual cut, operations taxonomy. VERIFIED, High.
- [Memory for Autonomous LLM Agents — arXiv 2603.07670 (Mar 2026)](https://arxiv.org/html/2603.07670v1) — four-scope memory incl. procedural; capacity/relevance. VERIFIED, High.
- [Designing Agentic Memory in 2026 — The Nuanced Perspective](https://thenuancedperspective.substack.com/p/designing-agentic-memory-in-2026) — working/episodic/semantic/procedural/parametric practitioner framing. Secondary, Medium.
- [Types of AI Agent Memory — Atlan](https://atlan.com/know/types-of-ai-agent-memory/) — applied definitions. Secondary, Medium.
- [ProcMEM — arXiv 2602.01869 (2026)](https://arxiv.org/pdf/2602.01869) — procedural memory as reusable executable skills (recipes parallel). VERIFIED, Medium-High.
- [State of AI Agent Memory 2026 — Mem0](https://mem0.ai/blog/state-of-ai-agent-memory-2026) — memory as first-class component, CoALA-based taxonomy. Secondary, High.
- In-repo: `ADR-004-memory-engine.md`, `data-model.md` (L84 procedural=role), `brain.md` (§ Self-improvement: NEVER weight fine-tuning; § Memory tiers), `ADR-024-task-executor.md` (task-memory), `ADR-021` (reactions), `ADR-022` (distilled local reasoner), `M4-c-1` (auto-inject), `M3-*`, `M6-*`, `M7-*`. VERIFIED in-repo.
- Prior reports 01–03 in this directory (reservations A–H). VERIFIED in-repo.

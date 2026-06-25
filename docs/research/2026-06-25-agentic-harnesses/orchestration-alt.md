# Orchestration Alternatives — Agentic Harnesses Research

**Date:** 2026-06-25
**Re-research after:** 2026-07-09
**Cluster:** orchestration-alt
**Tools covered:** AutoGen/AG2, CrewAI, smolagents (HuggingFace), Letta (MemGPT), LlamaIndex Agents/Workflows, DSPy + GEPA

---

## Evaluation Lenses

| Code | Lens |
|------|------|
| L1 | Host computer-use + sandbox safety |
| L2 | Local-first + privacy fit (local models; cloud-mandatory; data egress) |
| L3 | Reliability + resumability (checkpoint/interrupt, idempotent/bounded loops, external verification) |
| L4 | Build-vs-borrow / thin-spine fit |
| L5 | One-shot end-to-end build execution |

Scores: **H** = strong fit / **M** = partial fit / **L** = weak fit or significant gap

---

## 1. Microsoft AutoGen / AG2

### Identity
- **What it is:** Event-driven async multi-agent conversation framework. Originally Microsoft AutoGen; v0.4+ rewrote the API. When Microsoft put AutoGen into maintenance mode (last meaningful update v0.7.5, September 30 2025), the community forked it as **AG2** (ag2.ai). [VERIFIED via web search]
- **Current version/status (2026):** AutoGen in maintenance mode at v0.7.5. AG2 community fork is active (~v0.28+ with direct Ollama support). [VERIFIED]
- **Maintainer:** Microsoft (AutoGen, maintenance); community/AG2.ai (AG2 fork)
- **License:** MIT
- **Language:** Python

### Architecture
- Event-driven, async-first conversation system with pluggable agents (AssistantAgent, UserProxyAgent, GroupChat, SwarmAgent). [VERIFIED via Context7]
- Teams abstraction orchestrates multiple agents; `HandoffTermination` gives control back to the application, state serializable via `save_state`/`load_state`. [VERIFIED via Context7 + web]
- v0.4 introduced component-based architecture (ComponentBase), configurable model clients, structured output, and an `autogen_ext` extensions package. [VERIFIED via Context7]

### MCP Support
**YES — native, first-class.** `autogen_ext.tools.mcp` provides `mcp_server_tools()`, `StdioServerParams`, `SseServerParams`, `StreamableHttpServerParams`, and `McpSessionActor`. MCP tools are fetched and injected as agent tools directly. [VERIFIED via Context7]

### Lens Scores

| Lens | Score | Why |
|------|-------|-----|
| L1 Host computer-use + sandbox | L | No built-in sandbox; code execution relies on UserProxyAgent running commands in-process or via Docker — no native sandboxing primitives |
| L2 Local-first + privacy | M | Ollama supported directly (api_type="open_ai", localhost URL); no cloud-mandatory path, but no privacy enforcement layer |
| L3 Reliability + resumability | L | No built-in checkpointing between runs; state lives in memory only; GraphFlow state persistence bug noted in open issues [COMMUNITY]; save_state/load_state is manual |
| L4 Build-vs-borrow / thin-spine | M | Conversation abstraction is useful; v0.4 component model is clean, but the full multi-agent machinery is overkill for a thin spine; maintenance risk is real |
| L5 One-shot end-to-end build | M | GroupChat/Swarm patterns enable end-to-end orchestration; async support is strong; reliability gaps (no checkpoints) hurt long runs |

### Limitations / Gotchas
- **Maintenance risk:** Microsoft's AutoGen v0.7.5 is the last meaningful release. AG2 fork is active but community-maintained — uncertain roadmap. [VERIFIED]
- **No built-in state persistence:** If the Python process crashes, state is lost. External serialization is manual. [VERIFIED]
- **API fragmentation:** v0.2 ≠ v0.4 API; examples online mix versions creating confusion. [COMMUNITY]
- **GraphFlow state persistence bug** in open GitHub issues (issue #7043) — workflow gets stuck after interruption. [COMMUNITY]
- **Conversation-centric model** may not map cleanly to Artemis's agentic execution spine where steps > conversations.

### Sources
- Context7: /websites/microsoft_github_io_autogen_stable
- [Ollama Local LLM Guide | AG2](https://docs.ag2.ai/latest/docs/user-guide/models/ollama/)
- [AutoGen vs LangGraph 2026](https://myengineeringpath.dev/tools/autogen-vs-langgraph/)
- [Best Multi-Agent Frameworks 2026](https://futureagi.com/blog/best-multi-agent-frameworks-2026/)
- [AutoGen to Microsoft Agent Framework Migration](https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/)
- [AutoGen Discussion #5324 — HITL with UI](https://github.com/microsoft/autogen/discussions/5324)

---

## 2. CrewAI

### Identity
- **What it is:** Python framework for orchestrating autonomous AI agent teams (Crews, Agents, Tasks, Flows). Role-based agent assignment with sequential/hierarchical/parallel process modes. [VERIFIED]
- **Current version/status (2026):** v1.14.7 stable, actively developed. Cloud AMP (Agent Monitoring Platform) is the enterprise tier. [VERIFIED via Context7]
- **Maintainer:** CrewAI Inc.
- **License:** MIT (open-source core); enterprise features on paid AMP
- **Language:** Python

### Architecture
- **Agents** carry role/goal/backstory + LLM + tools. **Tasks** are discrete work units assigned to agents. **Crew** orchestrates a pipeline of tasks with configurable process (sequential, hierarchical). **Flows** add conditional branching and state machine behavior. [VERIFIED via Context7]
- Checkpoint system: `Crew.from_checkpoint(".//.checkpoints/latest.json")` + CLI `crewai checkpoint`. Saves state at each task boundary. [VERIFIED via Context7]

### MCP Support
**YES — native.** `MCPServerStdio`, `MCPServerSSE` in `crewai.mcp`; `mcps=["https://api.example.com/mcp"]` on Agent; tool schema caching (5-min TTL); tool filtering. Local stdio MCP servers supported. [VERIFIED via Context7]

### Lens Scores

| Lens | Score | Why |
|------|-------|-----|
| L1 Host computer-use + sandbox | L | No built-in sandbox; code execution not a native concept; agents call tools but no sandboxed code runner |
| L2 Local-first + privacy | M | Ollama/vLLM/local models via `LLM(model="ollama/llama3.2", base_url=...)` natively supported; however full AMP feature set (observability, guardrails) is cloud-hosted and introduces enterprise lock-in risk |
| L3 Reliability + resumability | M | Task-boundary checkpoints exist and are a genuine strength; however behavioral drift risk in Flows is noted; HITL support limited |
| L4 Build-vs-borrow / thin-spine | L | Role/task/crew abstraction is opinionated and hard to strip down; brings more structure than Artemis's thin-spine approach needs; enterprise cloud dependency is a design smell |
| L5 One-shot end-to-end build | M | Sequential/hierarchical process maps well to multi-step build tasks; checkpoint means long runs are resumable; but behavioral drift and cloud AMP dependency are risks |

### Limitations / Gotchas
- **Enterprise cloud creep:** Full guardrails, observability, and multi-tenancy require paid AMP tier — introduces cloud dependency counter to Artemis's local-first goal. [VERIFIED]
- **Agent behavioral drift:** Flows can drift if not carefully tuned; not suitable for fully deterministic, auditable outputs. [COMMUNITY]
- **Opinionated role model:** Forcing role/goal/backstory onto every agent adds overhead for simple or technical tasks. [COMMUNITY]
- **Checkpoint gate caveat:** Restoring from checkpoint has a replay-prevention gate; live snapshots can't blindly resume without validation. [VERIFIED]

### Sources
- Context7: /crewaiinc/crewai
- [CrewAI Changelog](https://docs.crewai.com/en/changelog)
- [AI Agent Frameworks Compared 2026](https://pecollective.com/blog/ai-agent-frameworks-compared/)
- [MCP, A2A & CrewAI Production 2026](https://47billion.com/blog/ai-agents-in-production-frameworks-protocols-and-what-actually-works-in-2026/)
- [AWS Prescriptive Guidance — CrewAI](https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-frameworks/crewai.html)

---

## 3. smolagents (HuggingFace)

### Identity
- **What it is:** Barebones Python agent library from HuggingFace. Core innovation: agents write actions as executable Python code (CodeAgent), not JSON tool calls — enabling natural composability (loops, conditionals, nesting). [VERIFIED]
- **Current version/status (2026):** v1.18.0; actively maintained by HuggingFace. [VERIFIED]
- **Maintainer:** HuggingFace
- **License:** Apache 2.0
- **Language:** Python

### Architecture
- **CodeAgent**: generates and executes Python code per step. **ToolCallingAgent**: classic JSON function-calling fallback.
- **Tools** are Python functions or classes decorated with `@tool`.
- **LocalPythonExecutor**: sandboxed (best-effort) in-process executor; not a hard security boundary.
- **Remote sandboxes**: E2B, Blaxel (fast-launch VMs with hibernation), Modal, Docker for hard isolation. [VERIFIED via Context7]
- **Models**: Any HF Hub model, Transformers, Ollama, LiteLLM, OpenAI/Anthropic via API. Zero adapter for HF models. [VERIFIED]

### MCP Support
**YES — optional extra.** `pip install "smolagents[mcp]"` — supports Stdio, Streamable HTTP, legacy HTTP+SSE MCP servers. [VERIFIED via Context7]

### Lens Scores

| Lens | Score | Why |
|------|-------|-----|
| L1 Host computer-use + sandbox | M | Code execution is the primary action mode; sandboxing via E2B/Docker/Blaxel is first-class; LocalPythonExecutor is NOT a hard security boundary and should not be used for untrusted code |
| L2 Local-first + privacy | H | Built by HuggingFace for HF ecosystem — zero config for local HF models; Ollama and Transformers work natively; no cloud-mandatory path; data stays local unless model API calls go out |
| L3 Reliability + resumability | L | No built-in checkpointing or interrupt/resume; multi-step state is in-memory only; no bounded loop enforcement beyond agent step limits |
| L4 Build-vs-borrow / thin-spine | H | Smallest footprint of any framework here (~40 lines for a ReAct agent vs 120+ in LangGraph); designed to be minimal and borrowable; aligns with thin-spine philosophy |
| L5 One-shot end-to-end build | M | CodeAgent's Python-code actions suit end-to-end build tasks; no HITL checkpointing limits long autonomous runs |

### Limitations / Gotchas
- **No built-in resumability:** Process restart = full replay from scratch. [VERIFIED]
- **Security boundary is soft:** LocalPythonExecutor is best-effort — determined attackers or adversarial fine-tuned models can escape. For host computer-use, must use a remote sandbox (E2B/Docker/Blaxel). [VERIFIED via Context7]
- **No native multi-agent orchestration**: Multi-agent support exists but is limited compared to CrewAI/AutoGen; complex agent graphs require more manual wiring. [COMMUNITY]
- **Loop control**: No built-in circuit breakers; agent can spin if model is bad at stopping. [ASSUMED based on minimalist design]
- **Good for exploration/prototyping** but production deployments require adding your own observability, checkpointing, and error-boundary layers. [COMMUNITY]

### Sources
- Context7: /huggingface/smolagents
- [smolagents README](https://github.com/huggingface/smolagents)
- [AI Agents 2026: LangGraph vs CrewAI vs Smolagents — DEV Community](https://dev.to/pooyagolchian/ai-agents-in-2026-langgraph-vs-crewai-vs-smolagents-with-real-benchmarks-on-local-llms-4ma1)
- [Top Agentic Frameworks 2026 — JetBrains](https://blog.jetbrains.com/pycharm/2026/06/top-agentic-frameworks-for-building-applications-2026/)
- [AI Agent Frameworks — Langfuse Comparison](https://langfuse.com/blog/2025-03-19-ai-agent-comparison)

---

## 4. Letta (MemGPT)

### Identity
- **What it is:** Stateful agent platform with OS-inspired memory management. Three-tier memory: **core memory** (always in-context, like RAM), **archival memory** (external vector store, like disk), **recall memory** (conversation history). Agents can self-edit their own memory blocks. [VERIFIED]
- **Current version/status (2026):** Active development. Roadmap items: Context Repositories (Git-based Memory) Feb 2026, Continual Learning in Token Space Dec 2025, Sleep-time Compute (Learning Offline) Apr 2025. [VERIFIED]
- **Maintainer:** Letta AI (formerly MemGPT team, Charles Packer et al.)
- **License:** Apache 2.0 (server), MIT (SDKs)
- **Language:** Python (server + SDK)

### Architecture
- **Letta Server** (Docker-deployable) + **Agent Development Environment** (browser ADE at app.letta.com or self-hosted). [VERIFIED]
- Agents are server-side entities that persist across calls; each agent carries typed memory blocks (read/write, read-only), tools, and optional MCP servers. [VERIFIED via Context7]
- Multi-agent: agents can spawn sub-agents and communicate; shared memory blocks supported. [VERIFIED]
- PostgreSQL + pgvector as backing store for archival memory and embeddings. [VERIFIED]

### MCP Support
**YES — first-class server-side integration.** MCP servers can be attached to agents; `mcp_servers` resources in the REST API. Memory blocks themselves are exposed as MCP tools for agents. [VERIFIED via Context7]

### Lens Scores

| Lens | Score | Why |
|------|-------|-----|
| L1 Host computer-use + sandbox | L | No native computer-use or sandboxed code execution; agent can call tools but no execution sandbox built in |
| L2 Local-first + privacy | M | Self-hosting via Docker is fully supported with zero data egress; model-agnostic (Anthropic, OpenAI, or local models); BUT the primary UX (ADE) defaults to app.letta.com cloud; local model performance notably worse than frontier models per official docs [VERIFIED]; requires PostgreSQL+pgvector locally |
| L3 Reliability + resumability | H | Agents are persistently stateful by design — state survives across calls without manual checkpointing; memory is durable to PostgreSQL; `letta memory pull` syncs state; this is Letta's core value prop |
| L4 Build-vs-borrow / thin-spine | L | Letta is a full platform (server, ADE, SDK, memory system, multi-agent protocol) — far too heavy to borrow a thin component from; pulling just the memory layer requires the whole server stack |
| L5 One-shot end-to-end build | L | Optimized for long-running persistent agents and conversation-oriented workloads; not designed for one-shot build execution pipelines |

### Limitations / Gotchas
- **Server-first architecture:** Even local use requires running the Letta server (Docker); embedded mode is not available. Adds ops overhead for a personal assistant. [VERIFIED]
- **Local model performance gap:** Official docs recommend Opus 4.5 / GPT-5.2; local models degrade memory self-editing quality significantly. [VERIFIED]
- **Observability is critical:** "Make memory observable from day one" — agents can confidently recall wrong facts; every add/search must be logged. [COMMUNITY]
- **Not a build harness:** Letta is stateful conversation infrastructure, not an agentic task execution framework; poor fit for Artemis's coding/build execution use case.
- **Memory correctness brittleness:** Sensitive data in archival memory may surface unexpectedly through vector search. ADR-029 sensitivity wall concern applies. [ASSUMED]

### Sources
- Context7: /websites/letta, /letta-ai/letta
- [Letta GitHub](https://github.com/letta-ai/letta)
- [AI Agent Memory Frameworks 2026 — Atlan](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)
- [Letta vs. Graphlit comparison](https://www.graphlit.com/vs/letta)
- [Letta on Medium — Stateful LLM Agents](https://medium.com/@vishnudhat/letta-building-stateful-llm-agents-with-memory-and-reasoning-0f3e05078b97)
- [AI Agent Memory 2026 — Rohit Raj](https://rohitraj.tech/en/notes/open-source-ai-agent-memory-mem0-vs-zep-letta-2026)

---

## 5. LlamaIndex Agents / Workflows

### Identity
- **What it is:** Event-driven, async-first agentic workflow framework (formerly primarily a RAG/indexing library; now a full workflow runtime). Core primitive: **Workflow** with typed events flowing between `@step` functions. [VERIFIED]
- **Current version/status (2026):** Workflows 1.0 shipped; llama-deploy (distributed runtime) available; active development. 2025 major launches: LlamaAgents, LlamaParse v2, Workflow Debugger, MCP integrations. [VERIFIED]
- **Maintainer:** LlamaIndex (Jerry Liu et al., RunLlama Inc.)
- **License:** MIT
- **Language:** Python (primary), TypeScript

### Architecture
- **Workflow**: class with `@step` decorators; steps emit and consume typed Events. Steps are async-native.
- **WorkflowCheckpointer**: `run_from(checkpoint=ckpt)` to resume from any saved step. Redis-backed durable checkpointing for production. [VERIFIED via Context7]
- **llama-deploy**: distributed runtime — control plane registers workflows as services, default Redis message queue, HTTP gateway, observability hooks. [VERIFIED]
- **Agents** are built on top of Workflows; RAG components (indices, retrievers) integrate natively.

### MCP Support
**YES — first-class.** `llama-index-tools-mcp` package; `get_tools_from_mcp_url()`, `MCPToolSpec` that converts MCP tools to `FunctionTool` objects; can also serve a LlamaIndex workflow AS an MCP server. [VERIFIED via Context7 + web]

### Lens Scores

| Lens | Score | Why |
|------|-------|-----|
| L1 Host computer-use + sandbox | L | No built-in computer-use or code execution sandbox; agents call tools but execution environment is the user's Python process |
| L2 Local-first + privacy | H | Fully model-agnostic; Ollama + MLX supported natively; develop locally, deploy anywhere (AWS Bedrock, your infra, or keep local); no cloud-mandatory path; hot-reload dev server preserves state |
| L3 Reliability + resumability | H | WorkflowCheckpointer with `run_from()` is built-in; Redis-backed durable checkpoints in production; step-level granularity; dev server auto-resumes in-progress workflows on save [VERIFIED via Context7] |
| L4 Build-vs-borrow / thin-spine | M | Workflow abstraction is clean and event-driven (aligns with Artemis's interrupt patterns); but RAG heritage means the library is large; can import just the workflow/agent layer without full RAG stack |
| L5 One-shot end-to-end build | H | Event-driven step model is ideal for one-shot end-to-end build execution; parallel step execution supported; llama-deploy enables distributed multi-step pipelines |

### Limitations / Gotchas
- **RAG heritage baggage:** The full library is heavy; Workflow-only usage is feasible but requires discipline to avoid importing the full index/retrieval stack. [COMMUNITY]
- **llama-deploy requires Redis (default):** Adds infrastructure ops for production distributed use. [VERIFIED]
- **TypeScript support is secondary:** Python is the primary runtime; TypeScript SDK exists but is less feature-complete. [ASSUMED]
- **Observability is separate:** LlamaTrace (their telemetry) is an optional addon; not bundled like LangSmith is to LangGraph. [COMMUNITY]
- **Best fit is data/RAG workflows:** For pure agent orchestration without RAG, it may carry more weight than needed. [COMMUNITY]

### Sources
- Context7: /websites/developers_llamaindex_ai
- [LlamaIndex Workflows Overview](https://www.llamaindex.ai/workflows)
- [Workflows 1.0 Announcement](https://www.llamaindex.ai/blog/announcing-workflows-1-0-a-lightweight-framework-for-agentic-systems)
- [LlamaIndex Newsletter 2025 Retrospective](https://www.llamaindex.ai/blog/llamaindex-newsletter-2025-12-30)
- [LlamaIndex MCP Usage](https://developers.llamaindex.ai/python/examples/tools/mcp/)
- [LlamaIndex 2026 Guide — FutureAGI](https://futureagi.com/blog/exploring-llamaindex-a-powerful-tool-for-llms/)

---

## 6. DSPy + GEPA Optimizer

### Identity
- **What it is:** DSPy is a declarative framework for programming (not prompting) LMs — modules with `dspy.Signature`, `dspy.Predict`, `dspy.ChainOfThought`, `dspy.ReAct`, optimized by compilers. GEPA (Genetic-Pareto Evolutionary Prompt Algorithm) is DSPy's newest and highest-performing optimizer. [VERIFIED]
- **Current version/status (2026):** DSPy 3.1.3 (PyPI, May 2026); GEPA standalone `pip install gepa` v0.1.1 (March 2026). GEPA paper accepted as oral at ICLR 2026 (Agrawal et al., arxiv:2507.19457). [VERIFIED]
- **Maintainer:** Stanford NLP (Omar Khattab et al.), now also supported by community
- **License:** MIT (DSPy + standalone GEPA)
- **Language:** Python

### Architecture (DSPy)
- Programs are composed of **Modules** (Predict, ChainOfThought, ReAct, etc.) wired together.
- **Optimizers** (MIPROv2, GEPA, BootstrapFewShot, etc.) compile programs against a metric on a training set, producing optimized instructions and/or few-shot examples.
- **No agentic orchestration spine** — DSPy is a prompt programming + optimization layer, not an agent executor. You supply the agent loop; DSPy optimizes the modules inside it.

### GEPA Deep Dive

**Algorithm (5-stage evolutionary loop):** [VERIFIED via WebFetch + Context7]
1. **Pareto Frontier Selection** — sample parent candidates proportionally to their coverage across eval instances.
2. **Minibatch Evaluation** — run candidates on small batches (default: 3 examples); capture full execution traces.
3. **LLM Reflection** — a strong `reflection_lm` reads traces + natural-language feedback; diagnoses failure modes.
4. **Targeted Mutation** — reflection LLM proposes new prompt variants that address diagnosed issues.
5. **Pareto Validation** — new candidates join the frontier only if they excel on at least one eval instance (prevents monoculture).

**Key insight:** Natural-language feedback is the gradient — traces replace scalar rewards, enabling diagnosis-driven optimization.

**Performance:** Outperforms MIPROv2 by 13%, GRPO by 20%, with 35x fewer rollouts. 93% on MATH (vs 67% unoptimized) from instruction refinement alone. [VERIFIED]

**Maturity:** Research-backed (ICLR 2026 oral), integrated in DSPy, standalone library available. Estimated optimization cost: $2–$10 per run (Hermes reference). Rapid community adoption. [VERIFIED]

### GEPA Standalone Borrowability for Artemis

**Is it borrowable standalone?** YES with caveats. [VERIFIED]
- `pip install gepa` (v0.1.1) ships independently; custom `GEPAAdapter` enables optimization of any text artifact (code, prompts, agent architectures, vector graphics).
- `pip install dspy` gives `dspy.GEPA` with full DSPy program integration — more powerful but pulls in the DSPy dependency.
- **Critical constraint: `reflection_lm` requires a strong model.** Official docs recommend `gpt-5` or frontier Claude; no documented path for a local `reflection_lm`. For Artemis's privacy wall (local-only for sensitive), this means GEPA optimization runs for sensitive recipes would require either a local frontier model (feasible on M4 Pro 48GB with a large Qwen/Llama) or a cloud call for the reflection step only. [VERIFIED + ASSUMED for local reflection_lm feasibility]

**Artemis recipe self-improvement pattern** (from Hermes Agent Self-Evolution, MIT license): [VERIFIED via Context7]
```
session_db (real conversations) 
  → evaluation dataset builder
  → wrap recipe as dspy.Signature/dspy.Predict 
  → dspy.GEPA (reflection_lm = frontier model or large local)
  → candidate variants → batch evaluation
  → constraint validation
  → git branch + PR for human review
```
This is a proven pattern (Hermes uses it) and is clean for Artemis's recipe system if the reflection_lm constraint is accepted.

### MCP Support
**NO (not applicable).** DSPy is a prompt optimization framework, not an agent executor. MCP tools can be passed as tool calls within a `dspy.ReAct` module, but DSPy itself does not manage MCP sessions. [VERIFIED]

### Lens Scores

| Lens | Score | Why |
|------|-------|-----|
| L1 Host computer-use + sandbox | L | Not applicable — DSPy optimizes prompts/programs, does not execute agents or manage sandboxes |
| L2 Local-first + privacy | M | DSPy programs can run any local LM as the student model; reflection_lm for GEPA currently requires a strong frontier model (cloud call unless a large local model is available); student model stays local |
| L3 Reliability + resumability | M | No agent loop resumability; but GEPA's Pareto frontier is persistent across iterations; optimization state can be saved and resumed; programs saved as JSON |
| L4 Build-vs-borrow / thin-spine | H | Highly borrowable — import `dspy.GEPA` or `pip install gepa`; no mandatory framework adoption; drop GEPA onto any existing prompt/recipe and optimize it independently |
| L5 One-shot end-to-end build | L | Not a build execution framework; handles prompt optimization offline, not real-time agent execution |

### Limitations / Gotchas
- **reflection_lm is cloud-dependent today:** All documented examples use `gpt-5` or frontier Claude for GEPA reflection. Local reflection_lm is theoretically possible (GEPA is model-agnostic) but untested and likely to underperform. [VERIFIED + ASSUMED]
- **Optimization is offline, not real-time:** GEPA improves prompts on training batches asynchronously; not an in-context adaptive loop. [VERIFIED]
- **Requires labelled examples or LLM-as-judge metric:** Building the evaluation dataset from real session data is a real engineering effort. [VERIFIED]
- **DSPy is not an agent orchestration framework:** Must be paired with an agent executor (e.g., the "thin spine" in ADR-022) — it only optimizes the modules inside the agent. [VERIFIED]
- **Standalone `gepa` library is new (v0.1.1, March 2026):** Production maturity of the standalone form is limited. DSPy integration is more mature. [VERIFIED]

### Sources
- Context7: /websites/dspy_ai, /nousresearch/hermes-agent-self-evolution
- [GEPA Overview — DSPy docs](https://dspy.ai/api/optimizers/GEPA/overview/)
- [Reflective Prompt Evolution with GEPA — DSPy tutorial](https://dspy.ai/tutorials/gepa_ai_program/)
- [GEPA Prompt Optimization — Morph](https://www.morphllm.com/gepa-prompt-optimization)
- [gepa standalone on PyPI](https://pypi.org/project/gepa/)
- [Hermes Agent Self-Evolution — NousResearch](https://github.com/NousResearch/hermes-agent-self-evolution)

---

## Comparative Summary Table

| Tool | L1 | L2 | L3 | L4 | L5 | MCP | Artemis-fit verdict |
|------|----|----|----|----|-----|-----|---------------------|
| AutoGen/AG2 | L | M | L | M | M | YES | Skip — maintenance risk + no checkpoints hurt; conversation model misfit |
| CrewAI | L | M | M | L | M | YES | Skip — opinionated role model + enterprise cloud creep fight thin-spine |
| smolagents | M | H | L | H | M | YES (opt) | Borrow candidate: thin, local-first, MCP-ready; add your own checkpointing |
| Letta | L | M | H | L | L | YES | Skip — full platform, server-first, not a build harness; memory model is interesting but non-borrowable |
| LlamaIndex WF | L | H | H | M | H | YES | Strong borrow candidate for checkpoint/interrupt patterns (per ADR-022); event-driven step model aligns |
| DSPy + GEPA | L | M | M | H | L | N/A | GEPA = borrow for recipe optimization; not an agent framework; reflection_lm cloud dependency is the key constraint |

---

## Cluster Takeaways

1. **AutoGen/AG2 is a maintenance liability.** Microsoft's fork entered maintenance mode in late 2025. The community AG2 fork is alive but uncertain. No built-in state persistence means every crash loses progress — a critical gap for Artemis's long-running build executor. Pass.

2. **CrewAI's cloud AMP and opinionated role model fight ADR-022.** Local model support is real, checkpoints exist, MCP is native — but the role/goal/backstory abstraction and cloud-first enterprise path are structural mismatches for a thin-spine, local-first system.

3. **smolagents is the lightest true borrow candidate for the tool/code execution layer.** 40-line ReAct agent, HuggingFace-native (Ollama/MLX zero-config), MCP optional extra. The gap is checkpointing (none) and sandbox safety (soft boundary only). If Artemis wraps it inside its own outer loop with a Redis/SQLite checkpoint and uses E2B/Docker for untrusted code, smolagents could serve as the inner execution kernel.

4. **LlamaIndex Workflows is the strongest checkpoint/interrupt borrow — already on the ADR-022 radar.** `WorkflowCheckpointer` with `run_from()`, step-level granularity, Redis-backed durable state, and a clean event-driven model align directly with ADR-022's "borrowed LangGraph checkpoint/interrupt patterns." LlamaIndex's version is arguably cleaner than LangGraph's for non-RAG workflows. The local-first story (Ollama/MLX, no cloud-mandatory) is solid.

5. **GEPA is the clear recipe optimization choice — borrow standalone.** `pip install gepa` or `dspy.GEPA` are both available. The Hermes Agent Self-Evolution pattern (session_db → DSPy module → GEPA → git PR → human review) is a proven template Artemis can adopt directly. The only constraint: `reflection_lm` needs a strong model; on Mac Mini M4 Pro 48GB, a large Qwen2.5-72B or Llama 3.3-70B may suffice as a local reflection model, but this is untested and should be validated in a spike.

---

## NEEDS-DOMAIN Hosts

None — all sources were accessible via allowed domains or web search.

---

## Confidence Tags Legend

- [VERIFIED] — confirmed from Context7 official docs or direct web source
- [COMMUNITY] — from community discussions, comparison articles, or GitHub issues
- [ASSUMED] — inferred from design/architecture; not directly stated in a source

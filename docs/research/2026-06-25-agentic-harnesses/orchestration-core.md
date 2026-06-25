# Orchestration-Core: Agentic Harness Research

**Date:** 2026-06-25
**Re-research after:** 2026-07-09
**Cluster:** orchestration-core
**Tools covered:** LangGraph, Pydantic AI, OpenAI Agents SDK, Claude Agent SDK (Anthropic), Google ADK

---

## Artemis Fit Lens (judge all tools against)

Local-first personal assistant. Privacy wall: sensitive data stays on LOCAL models (MLX/Ollama on Mac Mini M4 Pro 48–64 GB). General data may go to cloud. MCP-at-edges. Current direction (ADR-022): own thin spine + Pydantic AI + MCP + borrowed LangGraph checkpoint/interrupt patterns + GEPA. Dev box: Windows. Final host: Mac Mini M4 Pro.

---

## 1. LangGraph

### What it is

LangGraph is a low-level stateful agent orchestration framework and runtime for building long-running, multi-agent workflows using a directed graph abstraction. Maintained by LangChain, Inc. Python and JavaScript/TypeScript.

- **Current version (Jun 2026):** 1.0.x stable (1.0.6 reported; 1.1.0 referenced by some sources). [VERIFIED — Tier 1/2]
- **License:** MIT (open-source core); LangSmith / LangGraph Cloud are commercial managed offerings.
- **Language(s):** Python primary; JS/TS parity.
- **Maintainer:** LangChain, Inc.

### Core abstraction / architecture

Graph-based. Developers define a `StateGraph` (typed dict of agent state), add nodes (Python callables), connect them with edges and conditional edges, and compile with a checkpointer. The runtime drives the graph: each step updates the shared state object. Key concepts: `StateGraph`, `checkpointer`, `interrupt()`, `Command(resume=...)`, thread-scoped memory via `store`.

- Checkpointing backends: `SqliteSaver`, `PostgresSaver`, `MongoDBSaver`, `RedisSaver` (langgraph-redis v0.3.2). [VERIFIED — Tier 1]
- Human-in-the-loop via `interrupt()` inside a node; resumes via `Command(resume=...)` after user input. [VERIFIED — Tier 1; code examples confirmed]
- Subgraphs, multi-agent coordination, long-running thread persistence are all first-class.

### MCP support

**Yes — via `langchain-mcp-adapters` bridge.** Any MCP server is exposed as a LangChain tool callable from a LangGraph node. Not native to the graph abstraction itself but well-integrated with the LangChain ecosystem. [COMMUNITY — multiple Tier 2 sources, Jan–Jun 2026]

### Lens scores

| Lens | Score | One-line why |
|------|-------|-------------|
| L1 Host computer-use + sandbox safety | M | No built-in OS-driving primitives; tool nodes can call any Python, so host access is possible but blast-radius bounding is entirely developer responsibility; CVEs (CVSS 9.3, 7.5, 7.3) disclosed March 2026 highlight deserialization/injection risks in the LangChain ecosystem |
| L2 Local-first + privacy | H | Model-agnostic via `init_chat_model`; works with Ollama/ChatOllama; no mandatory cloud egress; all checkpointing can be local (SQLite); state never leaves the machine unless you configure a cloud store |
| L3 Reliability + resumability | H | Best-in-class: durable checkpointing, `interrupt()`/`Command(resume=...)` for human-in-the-loop, thread persistence, subgraph recovery; the explicit design center of the framework |
| L4 Build-vs-borrow / thin-spine fit | H | ADR-022 already targets borrowing LangGraph checkpoint/interrupt patterns; can borrow these specifically without adopting the full framework as host runtime; or use as full host for complex workflow subsystems |
| L5 One-shot end-to-end build execution | M | Graph DSL adds upfront construction cost; strong for multi-step workflows but not purpose-built for autonomous code-build-verify loops; no native spec→build abstraction |

### Known limitations / gotchas

- Three CVEs disclosed March 27, 2026: CVE-2026-34070 (path traversal, CVSS 7.5), CVE-2025-67644 (SQL injection, CVSS 7.3), CVE-2025-68664 (serialization injection, CVSS 9.3). Keep langgraph + langchain dependencies pinned and patched. [COMMUNITY — Tier 2]
- Graph DSL has meaningful learning curve and boilerplate vs. simpler agent loops.
- MCP integration is adapter-layer, not first-class — requires `langchain-mcp-adapters` package.
- LangSmith observability is proprietary SaaS; open-source alternative is limited.
- Ecosystem is large but historically has had rapid deprecation churn.

### Sources

- Context7 LangGraph Python docs: https://docs.langchain.com/oss/python/langgraph/ [VERIFIED Tier 1]
- LangGraph + Ollama guide (Jan 2026): https://dasroot.net/posts/2026/01/integrating-langgraph-mcp-ollama-agentic-ai/ [COMMUNITY]
- LangGraph + MCP 2026 guide: https://techbytes.app/posts/langgraph-mcp-multi-agent-workflow-guide-2026/ [COMMUNITY]
- Checkpointing best practices 2025: https://sparkco.ai/blog/mastering-langgraph-checkpointing-best-practices-for-2025 [COMMUNITY]
- CVE hardening guide 2026: https://beyondscale.tech/blog/langchain-langgraph-security-cve-hardening [COMMUNITY]
- Modal sandbox for LangGraph 2026: https://modal.com/resources/best-code-execution-sandbox-langgraph [COMMUNITY]

---

## 2. Pydantic AI

### What it is

Pydantic AI is a Python agent framework from the Pydantic team, designed for building production-grade generative AI applications with type safety as the core design principle — "FastAPI for GenAI." Model-agnostic.

- **Current version (Jun 2026):** v0.2.x via PyPI as of late 2025; v1.0 stable released September 2025 (API stability commitment). Recent PyPI versions include v0.0.49, v0_7_0, v1_0_5, v1.71.0, v1.97.0, v2.0.0b3. [VERIFIED — Tier 1 / PyPI]
- **License:** MIT.
- **Language(s):** Python only.
- **Maintainer:** Pydantic (Samuel Colvin et al.).

### Core abstraction / architecture

Agent-centric, typed. Core primitives: `Agent` (typed generic with `deps_type` and `output_type`), tool functions (decorated with `@agent.tool`), dependency injection via `RunContext`, `Agent.run()` / `run_sync()` / `run_stream()`. Output is validated against a Pydantic model at generation time (with `NativeOutput` for grammar-constrained local models). No built-in graph DSL; workflow control stays in Python.

- No native checkpoint/resume — durability requires external integration (Temporal, Restate, DBOS, Prefect). [VERIFIED — Tier 1 docs + Tier 2 articles]
- MCP: `MCPToolset` (newer, built on FastMCP client) replaces deprecated `MCPServerStdio/SSE/HTTP` classes. [VERIFIED — Tier 1]
- Observability: first-class Pydantic Logfire integration; also supports OpenTelemetry.

### MCP support

**Yes — native, first-class.** `MCPToolset` added in 2025; supports stdio, SSE, and StreamableHTTP transports. Pydantic AI can also act as an MCP *server* (agents usable as MCP tools). [VERIFIED — Tier 1]

### Lens scores

| Lens | Score | One-line why |
|------|-------|-------------|
| L1 Host computer-use + sandbox safety | L | No built-in OS-driving or sandbox primitives; must wire MCP-based computer-use tools yourself; no blast-radius bounding out of the box |
| L2 Local-first + privacy | H | First-class Ollama support (`Agent('ollama:qwen3')`); `OllamaModel` + `OllamaProvider`; `NativeOutput` uses llama.cpp grammar-constrained decoding for structured output with local models; no mandatory cloud egress |
| L3 Reliability + resumability | M | No built-in checkpoint/resume; must integrate Temporal/Restate/DBOS/Prefect — these integrations are documented and production-proven but require external dependency |
| L4 Build-vs-borrow / thin-spine fit | H | ADR-022 target: PydanticAI is the typed agent primitive in the own-thin-spine architecture; complements not replaces the spine; smallest surface area, cleanest composition |
| L5 One-shot end-to-end build execution | M | Solid for single-agent build tasks with typed outputs; multi-step pipeline requires manual orchestration or external workflow engine |

### Known limitations / gotchas

- No built-in RBAC, auth, prompt injection detection, or guardrails — security is fully developer-owned. [COMMUNITY]
- Complex branching / stateful loops require explicit Python control flow or external workflow integration — the framework doesn't provide a graph DSL.
- Ecosystem ~15x smaller than LangChain's. [COMMUNITY — Speakeasy comparison]
- Durable execution is documented but optional add-on — easy to build agents that silently lose progress on crash without Temporal/Restate.
- v2.0.0b3 in PyPI suggests API still evolving in beta branch.

### Sources

- Context7 Pydantic AI docs: https://pydantic.dev/docs/ai/ [VERIFIED Tier 1]
- Ollama integration docs: https://pydantic.dev/docs/ai/models/ollama/ [VERIFIED Tier 1]
- MCP overview docs: https://pydantic.dev/docs/ai/mcp/overview/ [VERIFIED Tier 1]
- Durable execution with Restate: https://pydantic.dev/articles/restate-durable-execution-pydanticai [VERIFIED Tier 1]
- Durable execution with Temporal: https://temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal [COMMUNITY]
- LangGraph vs Pydantic AI comparison: https://www.zenml.io/blog/pydantic-ai-vs-langgraph [COMMUNITY]
- Framework comparison 2026: https://open-techstack.com/blog/langgraph-vs-openai-agents-sdk-vs-pydanticai-2026/ [COMMUNITY]
- Speakeasy agent framework comparison: https://www.speakeasy.com/blog/ai-agent-framework-comparison [COMMUNITY]
- MCP Ollama integration example: https://medium.com/@jageenshukla/ollama-pydantic-project-integrating-mcp-server-with-a-local-llm-chatbot-30e25becdaa2 [COMMUNITY]

---

## 3. OpenAI Agents SDK

### What it is

OpenAI's official Python/TypeScript SDK for building multi-agent workflows. Originally "Swarm" (experimental), relaunched as the Agents SDK in early 2025, further evolved through 2025-2026.

- **Current version (Jun 2026):** v0.7.0 (Python); v0.2.9 also referenced. [VERIFIED — Context7 Tier 1]
- **License:** MIT (SDK is open-source); underlying APIs are commercial.
- **Language(s):** Python and TypeScript/JavaScript.
- **Maintainer:** OpenAI.

### Core abstraction / architecture

Agent-loop with handoffs. Core primitives: `Agent` dataclass (instructions, tools, handoffs, guardrails, output_type, hooks), `Runner` (executes the loop), `Handoff` (typed delegation to sub-agents), `InputGuardrail` / `OutputGuardrail` (parallel safety checks). Uses OpenAI Responses API by default — this is where the vendor lock-in lives. Non-OpenAI models supported via `AnyLLMModel` adapter (backed by LiteLLM) but with feature degradation. Tracing via OpenAI platform or custom exporters. No graph DSL — linear loop with conditional handoffs.

- MCP support: `MCPServerStdio` / `MCPServerStreamableHttp` / `HostedMCPTool` (server-side). [VERIFIED — Tier 1, Context7]
- Guardrails run in parallel to agent execution.
- `mcp_servers` field on `Agent` dataclass is first-class. [VERIFIED — Tier 1]

### MCP support

**Yes — native.** Both local stdio and remote HTTP transports. `HostedMCPTool` offloads tool execution to OpenAI's servers (cloud-mandatory). Local `MCPServerStdio` keeps execution on-machine. [VERIFIED — Tier 1]

### Lens scores

| Lens | Score | One-line why |
|------|-------|-------------|
| L1 Host computer-use + sandbox safety | M | No built-in OS-driving primitives; sandbox code execution added via OpenAI sandbox integration; blast-radius bounding is developer responsibility except via `HostedMCPTool` (cloud executes) |
| L2 Local-first + privacy | L | Best-in-class features (tracing, guardrails, advanced tool use) require Responses API = OpenAI cloud; local models via AnyLLMModel/LiteLLM work but lose advanced tool features; HostedMCPTool sends data to OpenAI servers |
| L3 Reliability + resumability | M | No built-in checkpoint/resume; `Sessions` API provides conversation persistence but not full workflow durability; loop convergence relies on `reset_tool_choice` guard but no bounded-loop enforcement |
| L4 Build-vs-borrow / thin-spine fit | L | Fights the own-thin-spine goal: abstraction is opinionated toward OpenAI APIs; borrowing patterns (handoffs, guardrails) is possible but the full SDK pulls in OpenAI dependency surface |
| L5 One-shot end-to-end build execution | M | Purpose-built for autonomous tool-use loops; tracing is excellent for observing build execution; but Responses API dependency limits local-only build pipelines |

### Known limitations / gotchas

- Most feature-rich path (Responses API, HostedMCPTool) requires OpenAI cloud — explicit privacy risk for Artemis sensitive data. [VERIFIED — Tier 2]
- Non-OpenAI / local models via AnyLLMModel work but "certain tool features are supported only with OpenAI Responses models" — degraded experience. [COMMUNITY — getstream.io guide]
- Tracing ships to OpenAI platform by default; custom exporter needed for on-prem privacy.
- No built-in graph structure; complex stateful workflows require external orchestration.
- Ecosystem is OpenAI-centric — ecosystem tooling assumes OpenAI APIs.

### Sources

- Context7 OpenAI Agents Python: https://openai.github.io/openai-agents-python/ [VERIFIED Tier 1]
- MCP integration docs: https://openai.github.io/openai-agents-python/mcp/ [VERIFIED Tier 1]
- Models page (AnyLLMModel): https://openai.github.io/openai-agents-python/models/ [VERIFIED Tier 1]
- Local models with LiteLLM guide: https://getstream.io/blog/local-openai-agents/ [COMMUNITY]
- OpenAI Agents SDK 2026 practical guide: https://open-techstack.com/blog/how-to-use-openai-agents-sdk-with-mcp-and-approvals-2026/ [COMMUNITY]
- OpenAI for Developers 2025 blog: https://developers.openai.com/blog/openai-for-developers-2025 [VERIFIED Tier 2]

---

## 4. Claude Agent SDK (Anthropic)

### What it is

Anthropic's official SDK for building AI agents powered by Claude. Previously "Claude Code SDK," renamed to "Claude Agent SDK" in late 2025 to reflect general-purpose agent scope beyond coding. Exposes the same agent loop, tools, and context management as Claude Code.

- **Current version (Jun 2026):** v0.2.107 (PyPI, uploaded Jun 22 2026). [VERIFIED — Tier 2 / PyPI]
- **License:** Anthropic Commercial Terms of Service (not MIT); individual components may have separate licenses. [VERIFIED — Tier 2]
- **Language(s):** Python (3.10+) and TypeScript (Node 20+).
- **Maintainer:** Anthropic.

### Core abstraction / architecture

Agent-loop wrapping Claude Code internals. Core primitives: `query()` function (one-shot), `ClaudeSDKClient` (bidirectional, session-persistent), `ClaudeAgentOptions` (configure tools, MCP servers, allowed tools), `@tool` decorator (in-process MCP server), subagents (delegated child agents). Built-in tools shipped with SDK: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch. Bash tool provides persistent bash session with shell command execution. Computer use tool provides screenshot + mouse/keyboard control. Agent loop: call Claude, execute tool, feed result back, repeat.

- Code execution: `code_execution_20250825` (Bash + file ops, all models); `code_execution_20260120` (adds REPL persistence + programmatic tool calling). [VERIFIED — Tier 2]
- Subagents (delegated child agents with own context) are first-class. [VERIFIED — Tier 2]
- No built-in checkpoint/resume in the SDK layer itself — sessions are persistent but not crash-resumable by default.

### MCP support

**Yes — first-class, both client and server.** `mcp_servers` field on `ClaudeAgentOptions`; `create_sdk_mcp_server()` creates in-process MCP servers (no separate process needed). `allowed_tools` pre-approves tools. [VERIFIED — Tier 1 Context7]

### Lens scores

| Lens | Score | One-line why |
|------|-------|-------------|
| L1 Host computer-use + sandbox safety | H | Only framework in this cluster with computer use (screenshot + mouse/keyboard) natively shipped; Bash tool provides persistent shell; blast-radius bounding via `allowed_tools` + per-call permission hooks; sandbox code execution API added 2026-01 |
| L2 Local-first + privacy | M | SDK requires Claude (Anthropic API) — cloud-mandatory for inference; local models not supported; MCP servers can be fully local; tool execution is local; inference traffic goes to Anthropic |
| L3 Reliability + resumability | M | Session persistence available; no built-in crash-resumable checkpoint; human-in-the-loop via hooks; agent loop is bounded by Anthropic's model response |
| L4 Build-vs-borrow / thin-spine fit | M | Excellent for Artemis host computer-use executor subsystem specifically; but cannot replace the local-model privacy wall; complements thin spine rather than providing it |
| L5 One-shot end-to-end build execution | H | Purpose-built for this exact pattern — powers Claude Code's own build/edit/verify loops; Bash + file tools + web tools + subagents = full autonomous build pipeline; best in cluster for this lens |

### Known limitations / gotchas

- **Inference is cloud-only (Anthropic API)** — all prompts go to Anthropic's servers. Unusable behind the privacy wall for sensitive data. [VERIFIED — Tier 2]
- License is Anthropic Commercial Terms, not open-source — usage terms apply.
- Version 0.2.107 suggests still pre-1.0 despite "1.0+ as of December 2025" claim; API may still change. [ASSUMED — PyPI version vs blog claim discrepancy]
- Computer use tool is the most capable OS-driving tool in this cluster but requires Anthropic cloud inference.
- Subagent depth and cost can escalate quickly without explicit budget controls.

### Sources

- Context7 Claude Agent SDK Python: https://github.com/anthropics/claude-agent-sdk-python [VERIFIED Tier 1]
- Agent SDK overview: https://code.claude.com/docs/en/agent-sdk/overview [VERIFIED Tier 2]
- Bash tool docs: https://platform.claude.com/docs/en/agents-and-tools/tool-use/bash-tool [VERIFIED Tier 2]
- Computer use tool: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool [VERIFIED Tier 2]
- Code execution tool: https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool [VERIFIED Tier 2]
- PyPI release page: https://pypi.org/project/claude-agent-sdk/ [VERIFIED Tier 2]
- Claude Agent SDK 2026 overview: https://www.totalum.app/blog/claude-agent-sdk-totalum-2026 [COMMUNITY]
- Promptfoo docs: https://www.promptfoo.dev/docs/providers/claude-agent-sdk/ [COMMUNITY]

---

## 5. Google ADK (Agent Development Kit)

### What it is

Google's open-source, code-first toolkit for building, evaluating, and deploying AI agents. Released publicly in 2025; v1.0.0 stable released (Python). Multi-language: Python, TypeScript, Go, Java.

- **Current version (Jun 2026):** v1.0.0 stable (Python); TypeScript/Go/Java versions available. [VERIFIED — Tier 2]
- **License:** Apache 2.0. [VERIFIED — Tier 1 / adk.dev]
- **Language(s):** Python, TypeScript, Go, Java.
- **Maintainer:** Google.

### Core abstraction / architecture

`LlmAgent` / `Agent` (wraps model + instructions + tools), `McpToolset` (MCP integration), multi-agent via agent-as-tool or sequential/parallel sub-agent patterns. Optimized for Gemini but model-agnostic via LiteLLM connector. Deployment targets: `adk web` (local dev), Cloud Run, GKE, Agent Runtime. A2A (Agent-to-Agent) protocol support. Evaluation framework built-in.

- Local models via Ollama + LiteLLM: documented but with constraints (GoogleSearch tool Gemini-only; tool call reliability varies by local model; context window dramatically smaller). [VERIFIED — Tier 1 adk.dev + COMMUNITY]
- Code execution sandbox: process-level isolation for model-generated code; production deployments (Cloud Run/GKE) require synchronous agent instantiation. [COMMUNITY — GitHub discussion]
- Safety: VPC-SC network controls, hermetic execution recommendations, MCP for filesystem access. [VERIFIED — adk.dev safety docs]

### MCP support

**Yes — native via `McpToolset`.** Supports `StdioConnectionParams` (local) and `SseConnectionParams` (remote). `tool_filter` for scoping. TypeScript variant uses `MCPToolset`. [VERIFIED — Tier 1, Context7 code examples confirmed]

### Lens scores

| Lens | Score | One-line why |
|------|-------|-------------|
| L1 Host computer-use + sandbox safety | M | Process-level sandbox for code execution; no native GUI/mouse computer-use; filesystem via MCP; VPC-SC and hermetic execution guidelines exist but require explicit configuration; Daytona integration for isolated code sandboxes |
| L2 Local-first + privacy | M | Local Ollama via LiteLLM is documented but second-class: GoogleSearch + some tools are Gemini-cloud-only; MLX not natively supported (use Ollama as API layer); genuine local-first use requires workarounds |
| L3 Reliability + resumability | M | v1.0 stable; evaluation framework built-in; no first-class checkpoint/resume in the framework itself; Cloud Run/GKE deployments add infra-level resilience; local dev has no durable state built-in |
| L4 Build-vs-borrow / thin-spine fit | L | Google-ecosystem tilt (Gemini-first, Cloud-first, A2A protocol, Vertex AI) fights the local-first privacy wall and own-thin-spine goal; borrowing specific patterns is possible but the framework pulls toward GCP |
| L5 One-shot end-to-end build execution | M | Multi-agent orchestration and eval framework are strong; not purpose-built for autonomous code-build-verify pipelines; A2A protocol adds interoperability for distributed build tasks |

### Known limitations / gotchas

- Gemini-first: GoogleSearch and certain ADK-native tools are unavailable with non-Gemini models. [VERIFIED — adk.dev Ollama docs]
- MLX not natively supported — must run Ollama as an API server on top of MLX. [COMMUNITY — MLX vs Ollama comparison]
- Local model reliability: using `ollama` prefix (vs `ollama_chat`) causes "infinite tool call loops and ignoring previous context." [COMMUNITY — adk.dev Ollama docs warning]
- Production deployment (Cloud Run/GKE) requires synchronous agent initialization — `async def get_agent()` pattern breaks in deployment. [COMMUNITY — ADK docs production note]
- Java and Go versions are newer and less battle-tested than Python.
- Strong GCP pull: ecosystem integrations (Vertex AI, Agent Runtime, VPC-SC) assume GCP infrastructure.

### Sources

- Context7 ADK docs: https://adk.dev/ [VERIFIED Tier 1]
- ADK MCP tools: https://adk.dev/tools-custom/mcp-tools/ [VERIFIED Tier 1]
- ADK Ollama integration: https://google.github.io/adk-docs/agents/models/ollama/ [VERIFIED Tier 1]
- ADK safety docs: https://google.github.io/adk-docs/safety/ [VERIFIED Tier 1]
- ADK v1.0 stable announcement: https://developers.googleblog.com/en/agent-development-kit-easy-to-build-multi-agent-applications/ [VERIFIED Tier 2]
- Local ADK + Ollama + SQLite build guide: https://danicat.dev/posts/20251103-building-aida-part-2/ [COMMUNITY]
- ADK + LiteLLM + Ollama: https://medium.com/@viplav.fauzdar/building-a-local-ai-agent-with-google-adk-litellm-and-ollama-6e907e2db268 [COMMUNITY]
- ADK in 2026 first look: https://dev.to/njericodecraft/building-smart-in-2026-a-hands-on-first-look-at-googles-agent-development-kit-adk-3n0 [COMMUNITY]
- ADK with MLX: NEEDS-DOMAIN: rocm.docs.amd.com (AMD GPU ADK notebook), github.com (adk-python sandbox issue #3263)

---

## Summary Table

| Tool | L1 Computer-use | L2 Local-first | L3 Resumability | L4 Thin-spine fit | L5 One-shot build | MCP | Artemis verdict |
|------|----------------|----------------|-----------------|-------------------|-------------------|-----|-----------------|
| LangGraph | M | H | H | H | M | Partial (adapter) | Core borrow target for checkpoint/interrupt patterns; ADR-022 already plans this |
| Pydantic AI | L | H | M | H | M | Yes (native) | ADR-022 primary agent primitive — cleanest local-first fit, strongest thin-spine composition |
| OpenAI Agents SDK | M | L | M | L | M | Yes (native) | Hard pass for Artemis local core — Responses API cloud lock breaks privacy wall |
| Claude Agent SDK | H | M | M | M | H | Yes (native) | Best for host computer-use executor role (agentic planning brief); inference cloud-mandatory = not behind privacy wall |
| Google ADK | M | M | M | L | M | Yes (native) | GCP-pull + Gemini-first fights local-first goal; MLX gap; overkill for thin-spine |

---

## Cluster Takeaways

1. **ADR-022 direction holds.** Pydantic AI (L2/L4 high) + borrowed LangGraph checkpoint patterns (L3 high) remains the best-justified pairing for Artemis's local-first, thin-spine architecture. No tool surveyed here overturns that.

2. **LangGraph is a borrow, not a host.** Its graph DSL and checkpoint/interrupt system are best-in-class for reliability (L3 H), but adopting it as the full runtime host adds significant surface area. The right move is borrowing the checkpoint/interrupt *patterns* (as ADR-022 states) and implementing them directly or via lightweight SQLite/Postgres saver, not depending on the full LangGraph runtime.

3. **Claude Agent SDK is the right choice for the host computer-use executor role.** Per the agentic planning brief (0d911f7), the executor subsystem driving host OS actions maps exactly to this SDK's purpose. The cloud-inference constraint is acceptable for the executor (non-sensitive orchestration) but must be walled off from the privacy-sensitive data path.

4. **OpenAI Agents SDK is a non-starter for Artemis local core.** The Responses API lock-in (L2 L) directly contradicts the privacy wall requirement. AnyLLMModel degradation on local models makes it a worse Pydantic AI with OpenAI branding.

5. **Google ADK's Gemini-first tilt and GCP pull (L4 L) make it architecturally misaligned.** The local Ollama path works but is explicitly second-class. The MLX gap (Mac Mini primary local model runtime) is not bridged natively. The framework is excellent for GCP-native deployments — that is not Artemis.

---

## NEEDS-DOMAIN hosts

- `github.com` — blocked per source policy; several code examples and GitHub issue discussions (google/adk-python #3263, anthropics/claude-agent-sdk-python) would have provided version/feature confirmation.
- `rocm.docs.amd.com` — ADK + AMD GPU notebook referenced for MLX/local model comparison context; not authorized for fetch.

---

## All cited sources (index)

### LangGraph
- https://docs.langchain.com/oss/python/langgraph/ [VERIFIED Tier 1]
- https://dasroot.net/posts/2026/01/integrating-langgraph-mcp-ollama-agentic-ai/ [COMMUNITY]
- https://techbytes.app/posts/langgraph-mcp-multi-agent-workflow-guide-2026/ [COMMUNITY]
- https://sparkco.ai/blog/mastering-langgraph-checkpointing-best-practices-for-2025 [COMMUNITY]
- https://beyondscale.tech/blog/langchain-langgraph-security-cve-hardening [COMMUNITY]
- https://modal.com/resources/best-code-execution-sandbox-langgraph [COMMUNITY]
- https://www.freecodecamp.org/news/how-to-build-a-multi-agent-ai-system-with-langgraph-mcp-and-a2a-full-book/ [COMMUNITY]

### Pydantic AI
- https://pydantic.dev/docs/ai/ [VERIFIED Tier 1]
- https://pydantic.dev/docs/ai/models/ollama/ [VERIFIED Tier 1]
- https://pydantic.dev/docs/ai/mcp/overview/ [VERIFIED Tier 1]
- https://pydantic.dev/articles/restate-durable-execution-pydanticai [VERIFIED Tier 1]
- https://temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal [COMMUNITY]
- https://www.zenml.io/blog/pydantic-ai-vs-langgraph [COMMUNITY]
- https://www.speakeasy.com/blog/ai-agent-framework-comparison [COMMUNITY]
- https://open-techstack.com/blog/langgraph-vs-openai-agents-sdk-vs-pydanticai-2026/ [COMMUNITY]
- https://medium.com/@jageenshukla/ollama-pydantic-project-integrating-mcp-server-with-a-local-llm-chatbot-30e25becdaa2 [COMMUNITY]
- https://pypi.org/project/pydantic-ai/ [VERIFIED Tier 2]

### OpenAI Agents SDK
- https://openai.github.io/openai-agents-python/ [VERIFIED Tier 1]
- https://openai.github.io/openai-agents-python/mcp/ [VERIFIED Tier 1]
- https://openai.github.io/openai-agents-python/models/ [VERIFIED Tier 1]
- https://getstream.io/blog/local-openai-agents/ [COMMUNITY]
- https://open-techstack.com/blog/how-to-use-openai-agents-sdk-with-mcp-and-approvals-2026/ [COMMUNITY]
- https://developers.openai.com/blog/openai-for-developers-2025 [VERIFIED Tier 2]

### Claude Agent SDK
- https://code.claude.com/docs/en/agent-sdk/overview [VERIFIED Tier 2]
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/bash-tool [VERIFIED Tier 2]
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool [VERIFIED Tier 2]
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool [VERIFIED Tier 2]
- https://pypi.org/project/claude-agent-sdk/ [VERIFIED Tier 2]
- https://www.totalum.app/blog/claude-agent-sdk-totalum-2026 [COMMUNITY]

### Google ADK
- https://adk.dev/ [VERIFIED Tier 1]
- https://adk.dev/tools-custom/mcp-tools/ [VERIFIED Tier 1]
- https://google.github.io/adk-docs/agents/models/ollama/ [VERIFIED Tier 1]
- https://google.github.io/adk-docs/safety/ [VERIFIED Tier 1]
- https://developers.googleblog.com/en/agent-development-kit-easy-to-build-multi-agent-applications/ [VERIFIED Tier 2]
- https://danicat.dev/posts/20251103-building-aida-part-2/ [COMMUNITY]
- https://medium.com/@viplav.fauzdar/building-a-local-ai-agent-with-google-adk-litellm-and-ollama-6e907e2db268 [COMMUNITY]
- https://dev.to/njericodecraft/building-smart-in-2026-a-hands-on-first-look-at-googles-agent-development-kit-adk-3n0 [COMMUNITY]

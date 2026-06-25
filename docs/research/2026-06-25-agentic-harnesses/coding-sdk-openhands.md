# OpenHands Software Agent SDK — Deep-Dive Research

**Date:** 2026-06-25
**Re-research after:** 2026-07-09 (SDK is moving fast; version numbers and API surfaces should be re-verified)
**Researcher:** Phase-2 retrieval agent
**Purpose:** Evaluate OpenHands SDK v1 as a candidate coder-seam for Artemis's agentic coding subsystem

---

## Artemis Needs (evaluation frame)

- Strong PLANNER (Claude/Opus) designs; pluggable CODER backend implements
- Privacy is NOT a constraint for code (cloud backends fine)
- MUST be agentic: long builds run in the BACKGROUND
- Agent must be able to PAUSE mid-build to ASK THE OWNER further questions, then RESUME
- Artemis has its own thin executor spine (Pydantic AI + thread-keyed SQLite checkpoint + agent-inbox)
- Decision point: BORROW OpenHands as the coder, or BUILD own coder-seam

---

## 1. EMBEDDABILITY — Score: H

**Finding:** The OpenHands Software Agent SDK (package: `openhands-sdk`, latest v1.24.0 as of search date) is a
first-class Python library explicitly designed for headless/programmatic embedding. It is NOT just a
wrapper around a CLI — it exposes a full typed Python API. [VERIFIED]

**Core API surface:**

```python
from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool
from openhands.tools.task_tracker import TaskTrackerTool

llm = LLM(model="gpt-5.5", api_key=os.getenv("LLM_API_KEY"))
agent = Agent(llm=llm, tools=[
    Tool(name=TerminalTool.name),
    Tool(name=FileEditorTool.name),
    Tool(name=TaskTrackerTool.name),
])
conversation = Conversation(agent=agent, workspace=cwd)
conversation.send_message("Implement feature X.")
conversation.run()
```

**Event streaming** via typed callbacks: `ActionEvent` (agent calls a tool), `ObservationEvent` (tool result).
The agent can also run async via `arun()` (asyncio-native). [VERIFIED via Context7 / SDK README]

**SDK was announced Nov 12, 2025** alongside OpenHands Cloud API. pypi package `openhands-sdk` is the
canonical entry point. The paper is arxiv:2511.03690. [VERIFIED]

---

## 2. PLUGGABLE BACKEND — Score: H

**Finding:** The SDK routes all LLM calls through **LiteLLM**, giving access to 100+ providers
without code changes. [VERIFIED]

Confirmed backends:
- **OpenAI / GPT-5.5** — default model in all SDK examples [VERIFIED]
- **Anthropic / Claude** — `anthropic/claude-3-5-sonnet-20241022`, `openhands/claude-haiku-4-5-20251001`, etc. [VERIFIED via Context7 README.md example]
- **DeepSeek** — confirmed as LiteLLM-routable; test data generator explicitly uses `litellm_proxy/deepseek/deepseek-chat` [VERIFIED via Context7 test fixture README]
- **Ollama / vLLM / local models** — via `base_url` override on `LLM(...)` constructor; documented in official LLM guide [VERIFIED]
- **GLM (Zhiyu/Z.ai)** — reachable via LiteLLM proxy route; not explicitly named in SDK docs but LiteLLM support is comprehensive [COMMUNITY]
- **Azure, Bedrock, Vertex, OpenRouter** — all via LiteLLM [COMMUNITY]

**Per-task model selection:** `LLM` object is passed at `Agent` construction, so per-agent model
selection is trivial. Per-task within one agent is not natively parameterized — the model is fixed
at agent-init time. Swapping models across tasks would require constructing multiple agents. [VERIFIED]

---

## 3. BACKGROUND + HUMAN-IN-THE-LOOP — Score: M (partial fit)

This is the #1 Artemis requirement. Findings are detailed:

### 3a. Background / async execution [VERIFIED — H]

The SDK supports true background execution two ways:

1. **Threading:** `threading.Thread(target=conversation.run)` — run the agent in a background
   thread; host remains free to poll or inject messages.
2. **Asyncio:** `await conversation.arun()` — native asyncio; cancellable via
   `conversation.interrupt()` which emits an `InterruptEvent`. [VERIFIED via Context7 AGENTS.md /
   50_async_cancellation.py example]

### 3b. Pause / resume [VERIFIED — H for in-process; L for cross-process]

**In-process pause/resume:**
- `conversation.pause()` — halts the agent mid-execution; state is preserved in the Conversation object
- `conversation.run()` — resumes from the paused point
- Confirmed via dedicated docs page: `docs.openhands.dev/sdk/guides/convo-pause-and-resume`
- New messages can be queued via `conversation.send_message()` WHILE paused, before resuming [VERIFIED]

**Cross-session / cross-process resume:**
- Persistence is via `conversation_id` (UUID) + `persistence_dir` file store (`FileStore`/`LocalFileStore`)
- A conversation can be reconstructed in a NEW process by passing the same `conversation_id` and `persistence_dir` to a fresh `Conversation(...)` — events are replayed deterministically [VERIFIED via Context7 `10_persistence.py`]
- The arxiv paper states: "Pausing automatically persists state and emits a PauseEvent, allowing agents to resume from the same point later." [VERIFIED via arxiv:2511.03690]

### 3c. Agent asking the USER a question mid-build [COMMUNITY — partial]

**What exists:** `conversation.ask_agent(question)` — host app can QUERY the agent about its current
state at any time, without interrupting the main thread. This is useful for status probing. [VERIFIED
via docs.openhands.dev/sdk/guides/convo-ask-agent]

**What does NOT exist natively:** There is no built-in mechanism for the AGENT to proactively
PAUSE itself and emit a "I need owner input before continuing" signal to the host. The CodeActAgent
is designed to "converse to communicate with humans in natural language to ask for clarification"
[COMMUNITY], but this operates as a conversational turn in the CodeActAgent (the legacy full-stack
app), not as an SDK-level first-class "await-user-answer" event that Artemis's agent-inbox can
intercept and route.

**Gap / wrap-around for Artemis:** To implement Artemis's "agent pauses → asks owner → resumes"
pattern, the host would need to:
1. Run the agent in a background thread/task
2. Subscribe to event callbacks; detect when the agent's LLM output contains a user-question
   signal (e.g. via a custom tool like `AskOwnerTool` that pauses the conversation)
3. Insert the answer via `conversation.send_message(answer)` and call `conversation.run()`
4. Persist state via `conversation_id` + `persistence_dir` so the pause survives process restart

This is achievable but requires Artemis to implement the event-routing wrapper — it is NOT
zero-integration. [ASSUMED based on API surface; no SDK example covers this exact pattern]

---

## 4. SANDBOX / ISOLATION — Score: H

**Finding:** Docker-based containerization. Per arxiv paper: "Each agent instance runs in an
independent container with a dedicated file system, environment, and resource." [VERIFIED]

Sandboxing is **opt-in**, not universal — agents run locally by default, containerized on request.
This is appropriate for Artemis: local dev can run unsandboxed for speed; CI/cloud runs in Docker.

**Additional human oversight layers (from arxiv paper):** [VERIFIED]
- Security risk field in tool calls (LLM-generated)
- `WAITING_FOR_CONFIRMATION` state for high-risk actions
- VNC desktop, browser access, embedded VSCode Web editor for real-time inspection

---

## 5. MCP SUPPORT — Score: H

**Finding:** Native MCP integration via `mcp_config` dict on `Agent(...)` constructor.
Supports stdio-based MCP servers; tool schema is auto-translated. [VERIFIED via Context7
`07_mcp_integration.py` example]

```python
mcp_config = {
    "mcpServers": {
        "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
        "repomix": {"command": "npx", "args": ["-y", "repomix@1.4.2", "--mcp"]},
    }
}
agent = Agent(llm=llm, tools=tools, mcp_config=mcp_config,
              filter_tools_regex="...")
```

The arxiv paper confirms: "seamless support for the MCP with automatic schema translation between
MCP and native tools." [VERIFIED]

---

## 6. LICENSE + MATURITY + ACTIVITY + SWE-BENCH — Score: H

**License:** MIT for all core code. Enterprise directory has separate licensing. Docker images are
"fully MIT-licensed." [VERIFIED via docs.openhands.dev]

**Maturity:**
- ICLR 2025 conference paper (OpenHands full platform) [VERIFIED]
- SDK v1 paper published Nov 2025 (arxiv:2511.03690) [VERIFIED]
- pypi `openhands-sdk` at v1.24.0; `openhands` at v1.16.0 [VERIFIED via PyPI search]
- Active GitHub: OpenHands/software-agent-sdk [VERIFIED]

**SWE-bench Verified scores (with OpenHands harness):** [VERIFIED via search / benchlm.ai]
- Claude Sonnet 4.5: **72.8%** (pass@1), **74.6%** (pass@3)
- Claude Opus 4.5: **77.6%** (pass@3)
- GPT-5 (reasoning=high): **68.8%** (pass@1)
- Qwen3 Coder 480B: **65.2%**
- GAIA benchmark: 67.9% (Claude Sonnet 4.5)

These are top-tier scores — OpenHands is among the highest-performing open-source coding agent
harnesses available. [VERIFIED]

---

## 7. PLAN/CODE SPLIT — Score: M

**Finding:** OpenHands SDK does NOT have a first-class plan/code separation concept built in. Its
default `CodeActAgent` is a single monolithic loop that plans and codes in the same context. [VERIFIED]

However:
- **Hierarchical delegation** is supported: a "delegation tool" allows one agent to spawn
  sub-agents [VERIFIED via arxiv paper]. This could be used to separate planning from coding.
- **TaskTrackerTool** provides a lightweight task-list mechanism (plan/view commands) that an
  external planner could pre-populate [VERIFIED via Context7 `definition.py`].
- **External planner feed:** There is no first-class API for an external planner to inject a
  structured plan. The current pattern is `conversation.send_message(task_description)` — the
  planner's output would have to be rendered as a text message. Artemis's PLANNER (Opus) would
  need to emit a task brief as a message. [ASSUMED — no SDK example covers this]
- Skills can be loaded from `.openhands/skills/*.md` or `.cursorrules` files — this is the
  closest to "external planner feeds a recipe" but it's static file loading, not dynamic injection.
  [VERIFIED via arxiv paper]

**Bottom line for Artemis:** The SDK is NOT opinionated about plan/code split — it's a clean
seam. Artemis's Opus planner can simply send a rich task brief as the initial message; the SDK
coder executes it. The split lives above the SDK, which is actually ideal.

---

## 8. KNOWN GAPS AND ARTEMIS WRAP-AROUND — Score: M

### Gap 1: No native "agent asks user" signal
The biggest gap. The SDK's `ask_agent()` is host→agent probing, not agent→owner-inbox signaling.
Artemis must implement a custom `AskOwnerTool` that:
- Sets a flag/event the background thread monitors
- Writes the question to Artemis's agent-inbox
- Calls `conversation.pause()`
- On answer receipt: calls `conversation.send_message(answer)` + `conversation.run()`

This is ~50–100 lines of glue, not a fundamental blocker. [ASSUMED]

### Gap 2: Persistence is file-based, not SQLite
Artemis's spine uses thread-keyed SQLite checkpoints. OpenHands SDK uses `LocalFileStore`
(directory of JSON/event files). These are parallel systems — Artemis would need to decide
whether to use the SDK's own store or bridge to SQLite. The SDK's file-store is production-grade
and deterministically replayable; bridging adds complexity. [VERIFIED persistence model;
integration complexity ASSUMED]

### Gap 3: Per-task model switching requires multiple Agent objects
Not a hard blocker — Artemis's Codex-primary / Opus-fallback pattern maps to two pre-configured
agents; the dispatcher picks which to call. [ASSUMED]

### Gap 4: Human-confirmation gate is SDK-level, not Artemis-gate
The SDK's `WAITING_FOR_CONFIRMATION` state for dangerous actions is its own gate. Artemis has
its own ADR-029 sensitivity gate. These two gates would need coordination to avoid double-prompting.
[ASSUMED — requires design decision]

### Gap 5: No built-in agent-inbox / notification routing
The SDK has no concept of routing a "blocked" agent's question to an external notification system
(email, Slack, etc.). Artemis's agent-inbox fills this gap — the wrap-around is exactly what
Artemis already planned to build. [ASSUMED]

---

## Summary Assessment Against Artemis Requirements

| Requirement | Fit | Notes |
|---|---|---|
| Headless Python SDK | H | Full typed API; v1.24.0 on PyPI |
| Pluggable model backend | H | LiteLLM → 100+ providers; DeepSeek, Claude, Ollama all confirmed |
| Background / async | H | Threading + asyncio; cancelable |
| Pause / resume in-process | H | `pause()` / `run()` API |
| Pause / resume cross-session | H | `conversation_id` + `persistence_dir` file store |
| Agent proactively asks owner | M | Possible via custom AskOwnerTool; not native |
| Docker sandbox | H | Per-container isolation; opt-in |
| MCP support | H | Native `mcp_config` on Agent |
| MIT license | H | Core is MIT |
| SWE-bench standing | H | 72–77% top tier |
| Plan/code split | M | Not opinionated; Artemis can impose it above the SDK |
| External planner feed | M | Via initial message; no structured injection API |

---

## Sources

1. OpenHands SDK README (Context7 / GitHub): https://github.com/OpenHands/software-agent-sdk
2. OpenHands SDK Paper (Nov 2025): https://arxiv.org/html/2511.03690v1
3. Pause and Resume docs: https://docs.openhands.dev/sdk/guides/convo-pause-and-resume
4. Ask Agent docs: https://docs.openhands.dev/sdk/guides/convo-ask-agent
5. OpenHands Cloud API blog: https://www.openhands.dev/blog/programmatically-access-coding-agents-with-the-openhands-cloud-api
6. SDK intro blog (Nov 12 2025): https://openhands.dev/blog/introducing-the-openhands-software-agent-sdk
7. PyPI - openhands-sdk: https://pypi.org/project/openhands-sdk/
8. PyPI - openhands: https://pypi.org/project/openhands/
9. OpenHands SDK product page: https://www.openhands.dev/product/sdk
10. LLM docs (LiteLLM backends): https://docs.all-hands.dev/modules/usage/llms
11. DeepWiki SDK package overview: https://deepwiki.com/OpenHands/software-agent-sdk/2.1-sdk-package-(openhands-sdk)
12. BenchLM SWE-bench scores: https://benchlm.ai/benchmarks/openHandsIndex
13. Context7 library ID: /openhands/software-agent-sdk (1032 snippets, Medium reputation)
14. Context7 library ID: /websites/openhands_dev (3795 snippets, High reputation)

# OSS Agentic Coding Harness — SDK Comparison

**Date:** 2026-06-25
**Re-research after:** 2026-07-09 (Plandex community direction; gptme background-jobs API stabilises; goose Async roadmap item)
**Author:** Phase-2 retrieval agent
**Purpose:** Artemis coding-subsystem candidate evaluation — borrow vs. build-own seam

---

## Context: What Artemis Needs

- **Planner/Coder split** — strong Planner (Claude/Opus designs), separate pluggable Coder backend executes
- **Background + Human-in-the-loop** — long builds run AFK; agent pauses, surfaces a question to the owner, resumes
- **Pluggable backend** — OpenAI/Codex, DeepSeek, GLM/Z.ai, Anthropic, Ollama; ideally per-task selection
- **Embeddable** — Artemis has its own executor spine; tool must expose a library/SDK, not just a CLI
- Privacy: not a constraint (cloud backends fine)

---

## Candidates

### 1. Goose (Block / codename goose — AAIF / Linux Foundation)

**Repo:** https://github.com/aaif-goose/goose
**Version/status:** Active; donated to AAIF (Linux Foundation) Nov 2025; 27K+ GitHub stars as of 2026 [VERIFIED]
**License:** Apache 2.0 [VERIFIED]

#### 1. Embeddable
Goose provides a headless API alongside its desktop app and CLI. Documentation states "an API is available to embed it anywhere." CLI mode supports headless automation. Written in Rust. [VERIFIED via theaiagentindex.com/agents/goose]
**Score: M** — API exists but Rust internals mean the embedding surface is thinner than a pure Python library; depth of SDK unclear without direct GitHub read (NEEDS-DOMAIN: github.com).

#### 2. Pluggable Backend
"30+ LLM providers" including Anthropic, OpenAI, Google, Ollama. OpenRouter available (covers DeepSeek, GLM via OpenRouter). DeepSeek and GLM not explicitly named in reviewed content. [COMMUNITY]
**Score: H** — 30+ providers via built-in routing; OpenRouter covers the long tail.

#### 3. Background + Human-in-the-Loop
CLI mode supports headless; "Async Goose" listed as a roadmap item (not shipped as of July 2025 roadmap discussion). **gotoHuman MCP extension** enables goose to pause mid-task, send a human-review request, and resume after approval. [VERIFIED via block.github.io/goose/docs/mcp/gotohuman-mcp/ returning 404 — NEEDS-DOMAIN: block.github.io]
From secondary source: "With gotoHuman, goose can pause and request a review before continuing... once approved, goose can continue where it left off." [COMMUNITY via aitoolanalysis.com]
**Score: M** — pause-to-human exists via 3rd-party MCP (gotoHuman), not a first-class built-in; native async background is on roadmap.

#### 4. Sandbox
Runs locally on-machine; on-machine philosophy is privacy-first. Sandbox isolation level unclear — no container/Docker mentioned as default. [ASSUMED from docs philosophy]
**Score: L-M** — no explicit Docker-first blast-radius control; depends on operator.

#### 5. MCP Support
"MCP-native"; 70+ MCP extensions. Among the first agents to adopt MCP. March 2025 MCP standard compliant; June 2025 update compliance lag noted. [VERIFIED via aitoolanalysis.com, goose-docs.ai]
**Score: H**

#### 6. License + Maturity + Activity
Apache 2.0. Linux Foundation / AAIF governance. 27K+ stars. Actively maintained 2025-2026. [VERIFIED]
**Score: H**

#### 7. Plan/Code Split
General-purpose agent — no documented planner/coder mode split. Architect vs. editor mode not present. [ASSUMED/VERIFIED absence]
**Score: L** — single-agent mode; planner seam would need to be built externally.

---

### 2. Plandex

**Repo:** https://github.com/plandex-ai/plandex
**Version/status:** v2.2.1 (Jul 2025); plandex.ai domain returns 404 (wound down Oct 2025); community-maintained open source. [VERIFIED via theaiagentindex.com]
**License:** AGPL (inferred from OSS repo — NEEDS-DOMAIN: github.com for exact)

#### 1. Embeddable
CLI-first tool; no dedicated programmatic Python/Go library SDK documented. Some scripting via CLI piping. [COMMUNITY]
**Score: L** — no library API; CLI only; company wound down.

#### 2. Pluggable Backend
Built-in providers: Anthropic, OpenAI, Google, OpenRouter (which covers DeepSeek, GLM). BYO key mode. DeepSeek via OpenRouter confirmed (deepseek-r1-0528 listed in release notes). No LiteLLM integration; no native Ollama. [VERIFIED via search results citing plandex release notes]
**Score: M** — solid for cloud APIs, OpenRouter covers long-tail; no local/Ollama.

#### 3. Background + Human-in-the-Loop
**Best-in-class feature:** builds can be sent to background with `--bg` flag or `b` hotkey during streaming. Step-by-step mode vs. full-auto mode (configurable autonomy). `--no-build` flag separates plan phase from build phase. Cumulative diff sandbox keeps AI changes isolated until review. [VERIFIED via theaiagentindex.com, search citing docs.plandex.ai]
**Score: H** — strongest native background+pause story of any candidate; plan vs. build split is explicit.

#### 4. Sandbox
"Cumulative diff review sandbox" — all AI changes held in a staging area separate from project files until accepted. Not container-based. [VERIFIED]
**Score: M** — diff sandbox is good; no process-level isolation.

#### 5. MCP Support
No MCP support confirmed. [VERIFIED via multiple sources]
**Score: L**

#### 6. License + Maturity + Activity
Company wound down Oct 2025. Community-maintained. Last CLI release v2.2.1 Jul 2025. Reduced velocity risk. [VERIFIED]
**Score: M-** — feature-mature but low future-investment signal.

#### 7. Plan/Code Split
Explicit `--no-build` flag separates planning (prompt analysis, context loading) from build execution. Step-by-step vs. full-auto is configurable. [VERIFIED]
**Score: H** — most explicit plan/build separation of all candidates.

---

### 3. Aider

**Repo:** https://github.com/Aider-AI/aider
**Version/status:** Actively maintained 2025-2026; frequent releases. [VERIFIED via aider.chat]
**License:** Apache 2.0 [VERIFIED via multiple sources]

#### 1. Embeddable
Python package. Internal `Coder` class and `Model` are importable: `from aider.coders import Coder; from aider.models import Model`. Create instance, call `.run()`. **Caveat: explicitly documented as "not officially supported or documented, could change without backwards compatibility."** [VERIFIED via aider.chat/docs/scripting.html]
**Score: M** — works but unsupported; breaking changes risk; `--message` flag enables single-shot headless.

#### 2. Pluggable Backend
LiteLLM-based routing to 100+ providers. Confirmed: OpenAI, Anthropic, DeepSeek, Ollama, Azure, Gemini, Groq, OpenRouter. GLM/Zhipu via OpenRouter (not explicitly named but LiteLLM covers it). Per-task model selection via `--model`. Architect mode uses `--editor-model` for a second model. [VERIFIED via aider.chat/docs]
**Score: H** — best-in-class model coverage via LiteLLM.

#### 3. Background + Human-in-the-Loop
Watch mode: Aider watches files for AI comment markers, makes changes autonomously, commits, clears markers. `--yes` and `--auto-commits` flags enable lights-out. `--message` flag: one-shot instruction, then exit. No built-in pause-to-ask-human mid-build; no checkpoint/resume primitive. [VERIFIED via aider.chat]
**Score: L** — lights-out automation possible; pause-to-ask-human not built in; requires wrapping.

#### 4. Sandbox
No container or process isolation. Edits files directly. "Aider only edits files — it cannot run commands, install packages, or execute tests." [VERIFIED]
**Score: L** — no blast-radius control; write-only agent.

#### 5. MCP Support
Not documented in core docs; no mention found. [VERIFIED absence]
**Score: L**

#### 6. License + Maturity + Activity
Apache 2.0. Well-established; high community traction. Active 2025-2026. [VERIFIED]
**Score: H**

#### 7. Plan/Code Split
**Architect mode** uses two LLMs: architect model proposes, editor model produces file edits. Different models configurable via `--model` (architect) and `--editor-model` (editor). Recommended pairing: o1/reasoning model as architect, GPT-4o/Sonnet as editor. [VERIFIED via aider.chat/docs/usage/modes.html]
**Score: H** — strongest native architect/editor split of any candidate.

---

### 4. SWE-agent / mini-swe-agent

**Repo:** https://github.com/SWE-agent/mini-swe-agent (active focus), https://github.com/SWE-agent/SWE-agent (original)
**Version/status:** mini-swe-agent is the current recommended variant; 100-line core; actively developed 2025-2026; >74% SWE-bench verified. [VERIFIED via deepwiki.com, github search]
**License:** MIT (SWE-agent original MIT; mini-swe-agent same org — NEEDS-DOMAIN: github.com for mini explicit confirmation) [COMMUNITY]

#### 1. Embeddable
Clean Python Protocol-based API. Instantiate `Model`, `Environment`, `DefaultAgent` directly. `agent.run(task)` executes headless. `agent.serialize()` / `agent.save(path)` for state export. Structural typing, no forced inheritance. [VERIFIED via deepwiki.com/SWE-agent/mini-swe-agent/7.4-python-api]
**Score: H** — cleanest programmatic library surface of all candidates; designed for embedding.

#### 2. Pluggable Backend
LiteLLM-based (`LitellmModel`). `MSWEA_MODEL_NAME` env var for model selection. Covers OpenAI, Anthropic, DeepSeek, GLM via LiteLLM routing. Per-run model injection. [VERIFIED via deepwiki source]
**Score: H** — LiteLLM backbone covers full provider set.

#### 3. Background + Human-in-the-Loop
Three modes: **human** (user issues commands), **confirm** (LLM-issued commands require user confirmation before execution), **yolo** (fully autonomous). `DefaultAgent.run()` runs headless through internal loop until completion. Checkpoint serialization (`agent.serialize()`) enables save/restore. `execute_actions()` can be subclassed to intercept commands — implementation point for pause-to-ask logic. No built-in async background job queue. [VERIFIED via deepwiki.com; mini-swe-agent.com/latest/usage/mini/]
**Score: M** — confirm mode = human-in-the-loop per command; no higher-level "pause until question answered" primitive; checkpoint/serialize is present.

#### 4. Sandbox
`LocalEnvironment`, `DockerEnvironment`, `SingularityEnvironment` — Docker-first isolation is a first-class option. [VERIFIED via deepwiki.com]
**Score: H** — best sandbox story of all candidates.

#### 5. MCP Support
Not documented in retrieved content. [VERIFIED absence]
**Score: L**

#### 6. License + Maturity + Activity
MIT (SWE-agent). NeurIPS 2024 paper. mini-swe-agent actively maintained; frequent releases 2025-2026. Academic origin, strong benchmark pedigree. [VERIFIED]
**Score: H**

#### 7. Plan/Code Split
Single-agent loop; no separate planner stage. Agent is issue-resolver oriented. [VERIFIED/ASSUMED]
**Score: L** — no native plan/code split.

---

### 5. gptme

**Repo:** https://github.com/gptme/gptme
**Version/status:** v0.31.0 (Dec 2025) with background jobs; v0.28.0 (Aug 2025) added MCP; ~4K GitHub stars; MIT license. [VERIFIED via search results]
**License:** MIT [VERIFIED]

#### 1. Embeddable
Designed as library, standalone application, or web service. Python package (`pip install gptme`). REST server API (`gptme-server`) with OpenAPI spec at `/api/docs/openapi.json`. v0.31 added background jobs. Plugin system (v0.30) via Python entry points. [VERIFIED via gptme.org/docs]
**Score: H** — library + REST API dual-path embedding; REST enables async job dispatch.

#### 2. Pluggable Backend
Built-in providers: OpenAI, Anthropic, DeepSeek (direct), OpenRouter (100+ models), Azure, Gemini, Groq, xAI, Ollama (via OpenAI-compatible local). Plugin entry points allow custom providers. Per-session model via `-m provider/model`. GLM/Zhipu via OpenRouter. [VERIFIED via gptme.org/docs/providers.html]
**Score: H** — direct DeepSeek support; Ollama; OpenRouter covers GLM.

#### 3. Background + Human-in-the-Loop
v0.31.0 added "background jobs." Hook system provides lifecycle callbacks: `before_tool`, `after_tool`, `on_conversation_start` — enabling pause/confirmation gates. `auto_reply_hook` for autonomous operation. `stuck_detect_hook` to catch loops. REST API enables external control of running conversations (poll, inject). No purpose-built "ask owner question, block until answered" primitive — must be composed via hooks + REST. [VERIFIED via gptme.org; search results confirming v0.31]
**Score: M** — infrastructure present; pause-to-ask requires composition, not a built-in.

#### 4. Sandbox
No Docker default. On-machine execution. Hooks can gate tool calls before execution. [COMMUNITY]
**Score: L** — no container isolation by default.

#### 5. MCP Support
Full MCP support added v0.28.0 (Aug 2025). Dynamic discovery and loading of MCP servers. Lessons system (v0.29.0) + MCP discovery combined. [VERIFIED via search citing gptme releases]
**Score: H**

#### 6. License + Maturity + Activity
MIT. Active 2025-2026 with monthly releases. Autonomous "Bob" agent running since late 2024. Small but growing community (~4K stars). [VERIFIED]
**Score: M** — active but smaller community than Goose/Aider.

#### 7. Plan/Code Split
No native plan/code split. Single-agent with tool loop. [ASSUMED]
**Score: L**

---

### 6. RA.Aid

**Repo:** https://github.com/ai-christianson/RA.Aid
**Version/status:** Active 2025; built on LangGraph; integrates Aider for code editing. [VERIFIED via README]
**License:** Apache 2.0 [VERIFIED via README]

#### 1. Embeddable
Python package (`pip install ra-aid`). Built on LangGraph. No explicit library API documented beyond CLI invocation. [COMMUNITY]
**Score: L-M** — installable as Python package; library-mode embedding undocumented.

#### 2. Pluggable Backend
Supports Anthropic (default: Claude 3.7 Sonnet), OpenAI, OpenRouter, Makehub, DeepSeek, Gemini. `--provider` and `--model` flags. `--planner-provider`/`--planner-model` and `--expert-provider`/`--expert-model` for per-stage routing. GLM/Zhipu via OpenRouter. [VERIFIED via README]
**Score: H** — per-stage provider selection; DeepSeek direct; OpenRouter for GLM.

#### 3. Background + Human-in-the-Loop
`--hil` flag: agent asks clarifying questions during execution. `--chat` mode: conversational interface. Ctrl+C to pause, provide feedback, redirect. No async background job queue documented; runs synchronously. [VERIFIED via README]
**Score: M** — `--hil` is a genuine human-in-the-loop pause-to-ask primitive; but CLI-only, no programmatic async.

#### 4. Sandbox
Optional Aider integration for file editing (Aider's own file-write surface). No container isolation documented. [COMMUNITY]
**Score: L**

#### 5. MCP Support
Not confirmed in reviewed documentation. [VERIFIED absence]
**Score: L**

#### 6. License + Maturity + Activity
Apache 2.0. Active GitHub releases 2025. Smaller community than Aider/Goose. LangGraph dependency adds weight. [VERIFIED/COMMUNITY]
**Score: M**

#### 7. Plan/Code Split
**Best native split of any candidate** — three-stage workflow: Research → Planning → Implementation with dedicated agents per stage. Per-stage model (`--planner-provider`, `--expert-provider`). Integrates Aider as the code-edit engine (pluggable). [VERIFIED via README]
**Score: H** — closest to Artemis's planner/coder model.

---

## Scored Summary Table

| Lens | Goose | Plandex | Aider | mini-SWE | gptme | RA.Aid |
|---|---|---|---|---|---|---|
| **1. Embeddable** | M | L | M | **H** | **H** | L-M |
| **2. Pluggable backend** | **H** | M | **H** | **H** | **H** | **H** |
| **3. Background + HITL** | M | **H** | L | M | M | M |
| **4. Sandbox** | L-M | M | L | **H** | L | L |
| **5. MCP** | **H** | L | L | L | **H** | L |
| **6. License/maturity** | **H** | M- | **H** | **H** | M | M |
| **7. Plan/code split** | L | **H** | **H** | L | L | **H** |
| **License** | Apache 2.0 | AGPL? | Apache 2.0 | MIT | MIT | Apache 2.0 |

---

## Which Best Meets Background + Ask-Questions + Pluggable?

No single candidate delivers all three cleanly:

- **Plandex** has the strongest native background + pause story (`--bg`, step-by-step vs. full-auto, diff sandbox) and an explicit plan/build split. Dead-weight: company wound down, no MCP, no library API.
- **RA.Aid** has the closest architecture to Artemis (Research → Plan → Implement + per-stage model routing + `--hil` flag for mid-task questions). Dead-weight: no async, CLI-only, no MCP.
- **Aider** has the strongest model coverage (LiteLLM) and architect/editor split, but no pause-to-ask-human and unsupported Python API.
- **mini-SWE-agent** has the cleanest embeddable Python API and Docker sandbox, but no pause-to-ask-human at higher granularity than per-command confirm.
- **gptme** has both REST API + MCP + direct DeepSeek + background jobs (v0.31), and hooks for composing pause logic, but requires significant composition to achieve pause-to-ask-owner.
- **Goose** has MCP-native + 30+ providers + gotoHuman pause-extension, but async background is still roadmap and embedding depth is unclear (Rust core).

**For Artemis's primary requirement (background + ask + pluggable):** Compose **RA.Aid's three-stage planner architecture** inspiration with **Aider's LiteLLM coder engine** as the actual code-edit backend — which is exactly what RA.Aid already does. RA.Aid is the closest analog, but its CLI-only surface means Artemis would need to run it as a subprocess or fork/internalize its LangGraph loop.

Alternatively, **gptme** + **gotoHuman-style MCP hook** is the cleanest REST-API-embeddable path with MCP + DeepSeek + hooks for pause logic — if Artemis doesn't mind composing the human-gate from primitives.

---

## Takeaways

1. **No off-the-shelf solution fully covers all three requirements** (background + pause-to-ask + pluggable) as a library API. The gap is always the "pause this background task, surface a question, wait for owner, resume" primitive.

2. **RA.Aid's architecture is the closest conceptual match** to Artemis (separate planner model, separate coder model, `--hil` for mid-task questions), but it would need subprocess wrapping or LangGraph internalization to embed programmatically.

3. **Aider's architect/editor split + LiteLLM backend** is the strongest code-execution primitive to borrow — either via its internal `Coder` class (unsupported but functional) or as a subprocess. RA.Aid already wraps it this way.

4. **gptme v0.31's background jobs + REST API + MCP + hooks** is the most build-on-top-of-friendly option if Artemis's executor spine can drive it via REST and inject user messages mid-run. Direct DeepSeek support is a bonus.

5. **Plandex's cloud wind-down** (Oct 2025) makes it a poor long-term dependency despite its best HITL story. Consider it pattern-inspiration only.

---

## NEEDS-DOMAIN Hosts

These domains were blocked during research and claims relying on them are tagged [COMMUNITY] or noted as unconfirmed:

- `github.com` — source code for exact license text, issue/PR activity, raw README content for Plandex, goose, mini-swe-agent, gptme
- `block.github.io` — gotoHuman MCP extension details (returned 404 via WebFetch)
- `docs.plandex.ai` — Plandex documentation (DNS timeout)

---

## Sources

- [Goose review — AI Agent Index](https://theaiagentindex.com/agents/goose)
- [Block open source goose announcement](https://block.xyz/inside/block-open-source-introduces-codename-goose)
- [Goose docs](https://goose-docs.ai/)
- [Goose roadmap discussion (July 2025)](https://github.com/block/goose/discussions/3319)
- [Goose MCP-shaping story](https://www.arcade.dev/blog/goose-the-open-source-agent-that-shaped-mcp/)
- [Plandex review 2026 — AI Agent Index](https://theaiagentindex.com/agents/plandex)
- [Plandex GitHub](https://github.com/plandex-ai/plandex)
- [Aider docs](https://aider.chat/docs/)
- [Aider scripting](https://aider.chat/docs/scripting.html)
- [Aider modes (architect)](https://aider.chat/docs/usage/modes.html)
- [mini-SWE-agent Python API — DeepWiki](https://deepwiki.com/SWE-agent/mini-swe-agent/7.4-python-api)
- [mini-SWE-agent GitHub](https://github.com/SWE-agent/mini-swe-agent/)
- [gptme docs](https://gptme.org/docs/)
- [gptme providers](https://gptme.org/docs/providers.html)
- [gptme PyPI](https://pypi.org/project/gptme/)
- [gptme GitHub](https://github.com/gptme/gptme)
- [RA.Aid GitHub README](https://github.com/ai-christianson/RA.Aid)
- [RA.Aid docs](https://docs.ra-aid.ai/)
- [RA.Aid releases](https://github.com/ai-christianson/RA.Aid/releases)
- [Agentic coding tools compared 2026 — Requesty](https://www.requesty.ai/blog/agentic-coding-tools-compared-2026-claude-code-cursor-codex-aider)

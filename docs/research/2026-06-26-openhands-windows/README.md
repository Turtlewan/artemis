# OpenHands on Windows — Embeddability, Runtimes & Sandbox (research)

**Date:** 2026-06-26
**Context:** ADR-031 — embedding OpenHands as the sandboxed coding subsystem of an agentic runtime.
**Dev box:** Windows 11, 8GB RAM (final host = Mac Mini later). Ollama already resident.
**Scope:** resolve facts before writing build specs.

> **Two products, don't conflate them.**
> 1. **Legacy app** — PyPI `openhands-ai` (the `OpenHands/OpenHands` repo): full web app + CLI. Docker-first, Linux/WSL2-first.
> 2. **V1 Software Agent SDK** (announced 2025-11-12, repo `OpenHands/software-agent-sdk`): a modular, *embeddable* Python SDK. **This is what ADR-031 should target.** Packages: `openhands-sdk`, `openhands-tools`, `openhands-agent-server`, `openhands-workspace`. Latest `openhands-sdk` **v1.29.2 (2026-06-23)**, Python **>=3.12**, MIT.

---

## 1. Embeddability

**Yes — the V1 SDK is explicitly built to be imported and driven in-process** (not server-only). The announcement and docs call out forking, building a custom interface, or "embed the OpenHands SDK into your product or internal platform."

- **PyPI / packages:** `openhands-sdk` (core), `openhands-tools` (bash/file-editor/browser tools), `openhands-agent-server` (REST + OpenAI-compatible server), `openhands-workspace` (workspace abstractions). Extras on core: `boto3`, `vertex`.
- **Import path:** `from openhands.sdk import LLM, Agent, Conversation, Tool`; tools via `from openhands.tools.terminal import TerminalTool`, `from openhands.tools.file_editor import FileEditorTool`.
- **Minimal "run an agent on a task" API:**
  ```python
  import os
  from openhands.sdk import LLM, Agent, Conversation, Tool
  from openhands.tools.terminal import TerminalTool
  from openhands.tools.file_editor import FileEditorTool

  llm = LLM(model="gpt-5.5", api_key=os.getenv("LLM_API_KEY"))
  agent = Agent(llm=llm, tools=[Tool(name=TerminalTool.name), Tool(name=FileEditorTool.name)])
  conversation = Conversation(agent=agent, workspace=os.getcwd())  # workspace = isolation boundary
  conversation.send_message("Your task here")
  conversation.run()
  ```
  Event-sourced state with deterministic replay; immutable agent config; pause/resume, sub-agent delegation, history restore.
- **MCP:** The SDK has **MCP *client* integration** — the agent's typed tool system can mount external MCP servers as tools. It does **not** ship a packaged "expose-OpenHands-as-an-MCP-server" component. The closest "drive OpenHands from outside" surface is the **agent-server's OpenAI-compatible `/v1/chat/completions` endpoint** (treat OpenHands as an OpenAI-style backend; non-streaming only today, `stream:true` → 400).

Sources: https://github.com/OpenHands/software-agent-sdk · https://docs.openhands.dev/sdk · https://openhands.dev/blog/introducing-the-openhands-software-agent-sdk · https://pypi.org/project/openhands-sdk/ · https://arxiv.org/html/2511.03690v1 · https://docs.openhands.dev/sdk/guides/agent-server/openai-gateway

---

## 2. Windows support

**Official stance: OpenHands does not run natively on Windows for the standard (Docker) path — Windows users must use WSL2 + Docker Desktop.** That is the documented, supported route.

There is a **second, experimental native-Windows path** (no WSL, no Docker) via the **local runtime + PowerShell**:
- Requires **PowerShell 7 (`pwsh`, not `powershell`)**, the **.NET Core *Runtime* 6.0+** (not SDK), and **pythonnet** (`pythonnet.load('coreclr')`). PowerShell support lives in `openhands/runtime/utils/windows_bash.py`.
- **Python 3.12 or 3.13 only** — 3.14 unsupported (pythonnet incompatibility).
- **Known Windows blockers / rough edges:**
  - **Browser tool is unsupported on Windows.**
  - Interactive shell commands have limitations vs the Linux bash session.
  - The **CLI runtime still shells out to bash**, so CLI mode is not fully Windows-correct (issue #9210); native CLI launch has hit `ModuleNotFoundError: No module named 'fcntl'` (OpenHands-CLI issue #86).
  - Frequent `.NET`/CoreCLR load failures if the runtime isn't installed (issues #10355, #8656).
- Net: native Windows is **possible but experimental/incomplete**; treat as fragile.

Sources: https://docs.openhands.dev/openhands/usage/run-openhands/local-setup · https://docs.openhands.dev/openhands/usage/windows-without-wsl · https://github.com/OpenHands/OpenHands/issues/9210 · https://github.com/OpenHands/OpenHands-CLI/issues/86 · https://github.com/All-Hands-AI/OpenHands/issues/10355 · https://github.com/OpenHands/OpenHands/blob/main/Development.md

---

## 3. Runtimes / sandbox options

OpenHands separates the **agent** from the **runtime** that actually executes its bash/file commands (the "ActionExecutionServer"). In the V1 SDK this is the **workspace** abstraction; swapping workspace = swapping isolation with minimal code change.

| Runtime / workspace | What it isolates | Windows | Notes |
|---|---|---|---|
| **Docker runtime** (default, recommended) | Full container — separate FS, process namespace, network policy | Via **Docker Desktop + WSL2** only | Runs the agent-server inside `docker.all-hands.dev/all-hands-ai/runtime:*-nikolaik` (base `nikolaik/python-nodejs`, python3.12+node22). Strongest isolation, best reproducibility. |
| **Local / CLI runtime** | **Nothing** — agent has full host filesystem access | Native (PowerShell+.NET, experimental) or in WSL | "Start with local for fast iteration, add Docker later when you want strict isolation." Zero sandbox by itself. |
| **Remote runtime** | Remote container/VM (provider-isolated) | Host is just a WS client | WebSocket to `remote_runtime_url`, auto-reconnect + state sync. Providers: All-Hands Cloud, **Daytona**, Kubernetes. |
| **SDK workspaces** | `LocalWorkspace` (no isolation) / `DockerWorkspace` / `APIRemoteWorkspace` | same as above | Same agent code runs local for prototyping or remote/containerized in prod. |

**Run WITHOUT Docker?** Yes — the **local runtime** runs the agent-server as an ordinary host process. But it provides **no isolation on its own**: the agent gets full filesystem and process access as the running user. Any sandboxing must be supplied *around* it by the host.

Sources: https://docs.openhands.dev/openhands/usage/sandboxes/docker · https://docs.openhands.dev/openhands/usage/architecture/runtime · https://deepwiki.com/OpenHands/OpenHands/5.4-sandbox-configuration · https://www.daytona.io/dotfiles/building-a-secure-openhands-runtime-with-daytona-sandboxes

---

## 4. The sandbox gap (ADR-031 interim was macOS Seatbelt — macOS-only)

For the Windows dev box, the realistic options to contain agent-issued commands:

**(a) OpenHands Docker runtime via Docker Desktop + WSL2**
- *Isolation:* Strong (container FS/proc/network boundary). The path OpenHands itself hardens.
- *Footprint:* Heavy. Docker Desktop + WSL2 VM idles ~1.5–3GB RAM; runtime image is multi-GB disk; OpenHands' own Docker compose **recommends 4 CPU / 12GB RAM (4GB reservation)**. On an 8GB box this is the dominant consumer.
- *Friction:* Highest setup (Docker Desktop, WSL2 distro, image pulls, file-locality `/mnt/c` slowness caveat).
- *Parity:* **Best vs Mac prod** — Mac will also run Docker/remote; same image, same behavior.

**(b) Commands inside a WSL2 distro directly (OpenHands' local runtime running in Ubuntu-on-WSL)**
- *Isolation:* Medium — a real Linux VM boundary from the Windows host, but inside the distro the agent still has full FS access (no container). Shares the WSL kernel.
- *Footprint:* Moderate — WSL2 VM ~1–2GB; no Docker layer. Lighter than (a).
- *Friction:* Medium (install WSL + distro + deps); avoids Docker.
- *Parity:* Good — Linux userland ≈ Mac/Linux behavior; better than native-Windows quirks.

**(c) Windows Job Objects / restricted-token sandbox (Artemis already runs this for its Codex coder)**
- *Isolation:* Process-level — restricted token drops privileges, Job Object caps memory/CPU/process tree, optional filesystem ACL scoping. No kernel/VM boundary; weaker than a container/VM for FS containment, but real.
- *Footprint:* **Lightest** — native, no Docker, no second VM. Reuses existing Artemis machinery.
- *Friction:* You must **wrap OpenHands' local runtime in the existing sandbox yourself** — OpenHands has no built-in Job-Object runtime.
- *Parity:* **Worst vs Mac** (Windows-only mechanism, like Seatbelt was Mac-only) but **best vs existing Artemis Codex sandbox** (one isolation model across both coders).

**(d) OpenHands local runtime, no isolation**
- *Isolation:* None — full host FS access. Only defensible if wrapped by (c) and/or gated behind the confirmation mechanism (§7). Not a standalone answer.

---

## 5. Footprint / feasibility on 8GB RAM

- **Docker path (a):** OpenHands' own guidance is ~12GB RAM recommended / 4GB reserved for the runtime, plus Docker Desktop + WSL2 overhead and multi-GB image storage. **Not realistic concurrently with Ollama** (a 7B model resident is ~5–6GB). On 8GB, Docker runtime + Ollama is **one-at-a-time at best**, and even solo it's tight.
- **WSL2-direct (b):** ~1–2GB VM + the Python process + LLM client. Feasible solo; tight but possible alongside a small Ollama model.
- **Local + restricted-token (c/d):** Lightest — just the Python SDK process + agent-server subprocess (a few hundred MB). **The only option that comfortably coexists with Ollama on 8GB.**
- **Disk:** Docker runtime image(s) are several GB; the SDK-only path is ~hundreds of MB of wheels.

**Verdict:** On the 8GB dev box, the Docker runtime is effectively mutually exclusive with Ollama. The local-runtime + Artemis-sandbox path is the only one that runs alongside Ollama.

Sources: https://docs.dokploy.com/docs/templates/openhands · https://github.com/OpenHands/OpenHands/issues/6677 · https://hub.docker.com/r/nikolaik/python-nodejs

---

## 6. Pluggable model backend

**Yes — OpenHands routes all LLM calls through LiteLLM**, in both the legacy app and the V1 SDK. "Any model supported by LiteLLM."
- SDK config: `LLM(model="<litellm-id>", api_key=..., base_url=...)`. Per-task model swap is trivial — instantiate a different `LLM` per `Agent`/`Conversation`. This cleanly supports plugging **Codex / DeepSeek / GLM / Ollama** per task (custom `base_url`, provider-prefixed model id).
- Model discovery (app) draws from the LiteLLM catalogue, AWS Bedrock (boto3), and Ollama (`/api/tags`).

Sources: https://docs.openhands.dev/openhands/usage/settings/llm-settings · https://deepwiki.com/All-Hands-AI/OpenHands/5.1-llm-configuration-and-provider-support · https://dev.to/vishal_veerareddy_9cdd17d/run-openhands-on-any-model-you-want-1mnd

---

## 7. Pause-to-ask / confirmation (human-in-the-loop)

**Yes — first-class, and exactly the hook to defer to Artemis' own approval gate.**
- The agent enters a **`WAITING_FOR_CONFIRMATION`** state and blocks until the caller explicitly approves or rejects; on reject it can retry with a safer alternative.
- Two composable mechanisms: a **`SecurityAnalyzer`** (e.g. `LLMSecurityAnalyzer`) rates each tool call low/medium/high risk, and a **`ConfirmationPolicy`** (e.g. `ConfirmRisky`) decides when approval is required. Risk-assessment is separated from enforcement, so you can supply a **custom `ConfirmationPolicy`/`SecurityAnalyzer`** that calls out to Artemis' approval gate without touching tool executors.
- Policy can be **updated dynamically mid-session** (adaptive trust).

Sources: https://docs.openhands.dev/sdk/guides/security · https://arxiv.org/html/2511.03690v1 · https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/state.py

---

## Bottom-line recommendation (Windows dev box)

**Target the V1 `openhands-sdk` (≥1.29.2, Python 3.12/3.13), embedded in-process, with LiteLLM model routing and OpenHands' `ConfirmationPolicy`/`WAITING_FOR_CONFIRMATION` wired into Artemis' approval gate. For execution isolation on the 8GB box, run the OpenHands *local runtime* wrapped in Artemis' existing Windows restricted-token + Job Object sandbox (option c) — not the Docker runtime.**

Rationale / key trade-off:
- **Footprint forces it.** OpenHands' Docker runtime wants ~12GB and a WSL2 VM; that cannot coexist with Ollama on 8GB. The local runtime + existing restricted-token sandbox is the only path that runs alongside Ollama and reuses isolation Artemis already trusts for its Codex coder (one sandbox model for both coders).
- **The cost is isolation strength and Mac parity.** A restricted-token/Job-Object boundary is weaker than a container, and it is Windows-only (same limitation that made the ADR-031 Seatbelt interim macOS-only). Mitigate with the confirmation gate (§7) defaulting to confirm-risky.
- **Parity is recoverable cheaply** because the SDK's **workspace abstraction** lets the same agent code flip `LocalWorkspace` → `DockerWorkspace`/remote with minimal change. Spec the coding subsystem against the *workspace interface*, and make Docker/remote the Mac-prod target — develop local-sandboxed on Windows, run Docker-isolated on the Mac without rewriting the agent.
- **Two-rung sandbox maps cleanly:** Rung 1 = OpenHands `ConfirmationPolicy` (deferred to Artemis gate); Rung 2 = Artemis restricted-token + Job Object around the local runtime on Windows, swappable to the Docker/remote workspace on the Mac.

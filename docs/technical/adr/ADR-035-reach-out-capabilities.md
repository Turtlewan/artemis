# ADR-035 — Reach-out capabilities: fetch boundary, model-tiered aggregation, and the unified intent router

- **Status:** **Accepted** — owner + planning, 2026-07-01.
- **Date:** 2026-07-01
- **Deciders:** owner + planning
- **Design basis:** `docs/findings/enabler-wsl2-isolation-2026-07-01.md` · `docs/findings/enabler-model-tiering-architecture-2026-07-01.md` · `docs/findings/enabler-model-tiering-economics-2026-07-01.md` + a live host env-probe (2026-07-01).
- **Relates / builds on:**
  - `docs/v2/architecture.md` — **LOCKED substrate this ADR composes on, does not re-decide:** §10 WSL2 sandbox + egress allowlist + resource caps; §6 secrets in the **OS keychain** (Windows Credential Manager/DPAPI → macOS Keychain), referenced by-name, injected at call-time least-privilege, gated+audited; §5 quarantine staging + execution-grounded verification.
  - **ADR-009** (untrusted-content security layer + deep-research fetch/egress + **Dual-LLM quarantine**) — revived into v2 as the reader-tier posture.
  - **ADR-022** (pluggable `ModelPort`/roles) — this refines the role map for reach-out.
  - **ADR-026** (Codex primary build coder) — unchanged; Codex additionally gains a *runtime synthesizer* hat.
  - **ADR-030** (thin client) — intent routing moves **brain-side**.
  - **ADR-034** (unified Ask) — the router generalises its intent detection.
  - **ADR-012** (gated action staging) — the confirm-on-expensive gate.
  - **ADR-028** (spatial map) — capability display (CB-5b) is a separate track.
  - Capability-build slice CB-1…CB-5a (build-by-chat, proven live 2026-07-01).

## Context

Build-mode (CB-1…CB-5a) is proven live: the owner builds capabilities by chatting to the app. The owner's next intent: **capabilities that reach external internet sources and aggregate the results locally should be built *via the app*** (not hand-coded), and the app should guide secret entry. Most such capabilities pull from the open internet and aggregate in the owner's system.

Two constraints shape the design: **(1)** all requests arrive through **one input surface** — Telegram or the Ask Artemis overlay — so the system must *differentiate* intent at ingress; **(2)** the owner is **subscription-only** (no metered per-token API).

A 3-agent research pass (findings above) plus a live host env-probe validated the approach. `architecture.md` already **locks** the WSL2 sandbox, the OS-keychain secret store, and quarantine+grounded verification; **ADR-009** established the untrusted-web Dual-LLM posture in v1. This ADR **composes those** into the reach-out feature and adds only the genuinely new calls — it re-decides none of the locked substrate.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Enabler-first sequencing** | Network+secret capabilities are app-built, but only **after the substrate exists**, in order: **(i)** WSL2 isolation runner (behind the existing one-method `SandboxRunner` seam) → **(ii)** a secret-**capture UI** on top of the *already-locked* OS-keychain store (§6) → **(iii)** a key-entry gate in the build flow. The AST import-guard (`scan_for_unsafe_imports`) remains a **soft placeholder, not containment**, until (i) lands. |
| 2 | **Fetch boundary = Option B** | The sandbox is a **dumb, egress-allowlisted fetch pipe**: untrusted authored code runs in WSL2, may reach only its per-capability allowlisted domains, and returns **raw bytes to the host**. **All model reasoning runs host-side, outside the sandbox** — model credentials and orchestration never enter untrusted code. **Two fetch loci (reconciled):** (a) **public/open-web reads** (generic Q, public aggregation) use a **trusted host-side fetcher** (ADR-009: search API + clean-text fetch) under the egress allowlist — the code sandbox is not involved; (b) **authored capabilities that execute code and need network** (API spokes with secrets, custom fetch) run **inside the WSL2 egress-allowlisted sandbox**. Both: per-target allowlist, default-deny, logged. |
| 3 | **Two runtime patterns on one fetch foundation** | **Pattern A — generic internet question** ("look this up and answer"): one answering model + a web-search/fetch tool → inline answer. Lightweight; **no tier stack**. (New: the Ask/Spine path gains a web tool — today it has no web reach.) **Pattern B — aggregation capability:** Opus orchestrate → fetch → Haiku/Sonnet pull-extract (parallel) → Codex synthesize → owner store. Heavy; a **new ~60-line `AggregationPipeline`** component — **not** a change to `QuotaAwareRouter` or `Spine`. |
| 4 | **Dual-LLM quarantine on the reader tier** (adopt ADR-009) | Whatever reads raw untrusted web content is a **Quarantined reader: NO tools, schema/structured output only, spotlighted input.** That is the **pull/extract tier** (Haiku/Sonnet) in Pattern B and the read step in Pattern A. The **orchestrator (Opus) holds the plan/tools and never sees raw content**; the **synthesizer (Codex) operates on validated extracts, not raw pages.** Raw pages are held for the cycle and discarded (ADR-009 §6). |
| 5 | **Model/role map — subscription-only** | See table below. Pull leg on the **Claude Code CLI subscription** (org-access confirmed restored 2026-07-01; Haiku + Sonnet both reachable) + **Ollama** free-local fallback. The **metered Anthropic API is rejected (owner constraint).** |
| 6 | **Front-door intent router — brain-side** | One classifier at message-ingress, shared by **all transports (Telegram + Ask)**, classifies each message → {build-by-chat · generic-web-Q (A) · aggregate (B) · plain-Ask} and dispatches. This **moves CB-4's client-side intent heuristic brain-side** (keeps the client thin, ADR-030; gives Telegram identical behaviour). **Gate philosophy (ADR-012):** cheap/reversible intents run silently; expensive/irreversible ones (build, large aggregation) **confirm first** — the same gate build-mode already uses. |
| 7 | **Isolation runner — dev→prod** | WSL2 backend for dev (architecture.md §10), reusing the **same isolation script** on the Mac Mini via **Lima** (Apple Virtualization.framework Linux VM) — one `SandboxRunner` protocol, only the outer invocation differs (`wsl.exe` vs `limactl`). |

### Model / role map

| Role | Model | Plan | Notes |
|---|---|---|---|
| **Intent routing** (front door) | keyword pre-filter → **Haiku** | Claude | brain-side classifier |
| **Orchestrate** (privileged) | **Opus** | Claude | holds plan/tools; never sees raw content |
| **Pull / extract** (quarantined reader) | **Haiku → Sonnet** escalation | Claude | **no tools**; structured output only |
| **Synthesize** | **Codex → Opus** on-tap | ChatGPT / Claude | operates on extracts, not raw pages |
| **Build coder** (dev-time) | **Codex → Opus** fallback | ChatGPT / Claude | ADR-026, unchanged |

**Provider notes (subscription-only):**
- **Pull leg = Claude CLI subscription + Ollama fallback.** Org-access was flagged disabled mid-session earlier; **confirmed restored 2026-07-01** (`claude -p` exit 0; Haiku + Sonnet both answer). Metered Anthropic API **rejected** by the owner.
- **CLI clean-context gotcha:** `claude -p` invoked from the project inherits `CLAUDE.md` + startup hooks (observed: Haiku returned an APEX status summary instead of the asked answer). The provider **MUST** invoke the CLI with a clean, hook-free context (empty system prompt, no project settings) or pulls are slow and polluted.
- **Quota contention:** pull + orchestrate share one Claude pool with the build host → add a **concurrency semaphore** on the `claude_code` slot + a **"pull only when the builder is idle"** gate.
- **Codex wears two hats** (build coder + runtime synthesizer) on one ChatGPT plan — usually time-separated; the idle-gate covers overlap.

### Isolation — env probe (this host, 2026-07-01)

Unprivileged `unshare --net` ✅ (no root needed) · cgroups v2 ✅ · systemd ✅ (`systemd-run --scope` for caps) · default NAT networking ✅ · **`iptables` NOT installed** — the one gap. **Egress method:** DNS-sinkhole for the spike (self-authored code only) → **transparent proxy for production**. **Data path:** tmpfs copy in-sandbox, **text-only** result out.

## Consequences

- **Spec sequence** (each a separate spec, ≤3 files / ≤2 phases per the split rule):
  1. **WSL2 isolation spike** — install iptables/nftables; settle the egress method; prove netns + resource caps (~1–2 dev-days; PoC only).
  2. **`FetchSandbox` + isolation `SandboxRunner`** — the sandbox boundary contract.
  3. **Brain-side intent router + Pattern-A web tool** — unify Telegram + Ask; add web reach to the answer path.
  4. **`AggregationPipeline`** (Pattern B) — host-side Opus/Haiku-Sonnet/Codex tiering with the quarantine posture.
  5. **Secret-capture UI + build-flow key gate** — on the locked OS-keychain store.
- **Files (from code grounding):** new `src/artemis/model/aggregation.py`; `model/compose.py` (pipeline factory + role slots); `types.py` (`pipeline` field on `SkillDraft`/`Skill`); `capabilities/sandbox.py` (`FetchSandbox` + WSL2 runner behind `SandboxRunner`); `capabilities/forge.py` (guard aggregation caps behind `FetchSandbox`); a new brain-side router module wired into the transport/ask ingress; an Ask/Spine web-search tool.
- **ADR-009's untrusted layer is (re)instated for v2** — its local quarantined-reader becomes Haiku/Sonnet-on-subscription (Ollama = the local option); spotlighting + no-tools-on-reader carry over.
- **CB-5b (capability map display) is unaffected** — separate track; its 3 findings are filed and it is ready to spec independently.

## Alternatives considered

- **Metered Anthropic API for the pull leg** — *rejected* (owner: subscription-only).
- **Claude CLI with default project context** — *rejected* (inherits `CLAUDE.md`/hooks → slow + polluted output).
- **Option A — sandbox calls models itself** — *rejected* (model credentials + quota-failover logic inside untrusted code; undermines the sandbox trust model).
- **Heavy pipeline for generic questions** — *rejected* (overkill; Pattern A is a thin web tool).
- **Client-side intent router** — *rejected* (Telegram bypasses the client entirely).
- **Tool-holding reader over raw web** — *rejected* (ADR-009 injection rule: the reader that sees the poison must not reach a tool).

## Parked / next

- Run the WSL2 spike; install iptables/nftables; confirm DNS-sinkhole vs transparent-proxy.
- Secret-capture UX detail on the keychain store; **egress-allowlist governance at promote-time** (who approves a capability's new egress domains).
- Concurrency semaphore + build-idle gate implementation.
- **Partial-fetch policy** (default: synthesize on partial data with a coverage note, rather than abort).
- **Lima macOS backend** (HW-gated to the Mac Mini).
- Pattern-A search provider choice (Brave / Tavily per ADR-009) revalidated for v2.

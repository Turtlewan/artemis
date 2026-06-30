# Artemis v2 — Architecture

_Status: DESIGN (2026-06-30). Supersedes the entire v1 corpus. v1 is archived at git tag `archive/v1`; only the **name** and the **Tauri UI** (`client/`) carry forward._

---

## 1. Context & thesis

**Why v1 was scrapped.** v1 was built around a single load-bearing guarantee — *"no owner data ever in the cloud"* — which generated a heavy substrate (cryptographic privacy wall, mandatory local-model stack, sensitivity router, 34 ADRs / ~61 specs). A live email/OAuth bring-up session surfaced that this guarantee was not the owner's actual priority: every attempt to use a cloud/subscription model fought the local-first design at every layer (thinking-model output, Windows Codex launch, strict-vs-lenient schema rejection). The complexity served a constraint the owner did not want.

**v2 thesis.** A personal **agent harness** that:
1. runs across models from **multiple providers**,
2. **prioritises subscription models over metered APIs** (Codex/ChatGPT + Claude Code/Max driven headless), and
3. is a **framework for agents to build the capabilities the owner needs** — author, verify, store, reuse.

> _Plain-English:_ a small smart dispatcher. You say "I need it to do X"; it hands the job to an AI you already pay a flat fee for, has that AI build the tool, tests the tool before trusting it, files it away, and reuses it next time. The harness + the growing library of proven capabilities **are** the product.

**Kept from v1:** the name "Artemis" and the Tauri client (spatial travel-zoom map UI).

---

## 2. Locked decisions

| Decision | Choice | Status |
|---|---|---|
| Language / runtime | **Python** | LOCKED |
| Orchestration spine | **Thin own spine** over official Codex + Claude-Code SDKs; borrow LangGraph checkpoint/resume *patterns*, not the framework | LOCKED |
| Model layer | **LiteLLM** core + Router; `CustomLLM` adapters wrap subscription CLIs as providers | LOCKED |
| Routing policy | **Subscription-first**, cost/capability-aware, **graceful fallback on weekly-quota exhaustion** → other sub → metered API → local | LOCKED |
| Memory recall | **Retrieval-heavy** (remember a lot, retrieve smartly), behind a `MemoryPort` | LOCKED |
| Capabilities | **SKILL.md folders** + **MCP** invocation | LOCKED |
| Architecture style | Everything pluggable **behind thin interfaces** (model, memory, transport, scheduler, sandbox) | LOCKED |
| Privacy posture | Local is **just a fallback provider**, not the architecture; no privacy wall | LOCKED |

---

## 3. The 5-layer harness

1. **Model / provider layer** — LiteLLM unified interface; `CustomLLM` adapters wrap `codex exec` and `claude -p` as **first-class providers** (OAuth-subscription auth, no per-token bill). Router = subscription-first, cost/capability-aware, with fallback chains on quota/failure.
   > _The reasoning supply. Prefer the flat-fee AIs; fall back gracefully when the weekly cap is hit._
2. **Schema-normalization shim** — one canonical schema authored at **strictest** (OpenAI-strict) strictness; each adapter **down-converts** per backend (force `additionalProperties:false` + all-keys-required-nullable for strict targets; strip unsupported keywords; rewrite to a tool `input_schema` for Anthropic; pass-through for Ollama); **always validate client-side + re-ask**. This is the permanent fix for the v1 structured-output break.
   > _Strictness is the adapter's job, not an assumption baked into the schema._
3. **Thin plan/act/verify spine** — small orchestrator with **checkpoint / interrupt / resume** (borrowed LangGraph patterns). Can **run a task itself** OR **delegate a whole task to a subscription sub-agent** (Codex / Claude Code are full agents, not just models). Human-in-the-loop "agent inbox" gates for risky steps.
   > _The conductor. Sometimes it does the work; sometimes it hands the whole job to a subscription agent._
4. **Capability framework** — see §4.
5. **Tooling / safety substrate** — MCP for capabilities + external integrations; sandbox + egress allowlist for agent-generated code; **execution-grounded verification only**.

---

## 4. Tool / capability layer

**The stack (compose, not choose):** **tool script** (executable atom) → **SKILL.md folder** (container: when-to-use frontmatter + instructions + bundled scripts/resources, progressive disclosure) → **MCP** (uniform invocation surface to the agent loop and the UI). Rule: *everything is a Skill folder*; pure know-how is markdown only, deterministic work bundles a tool script; one local **capability MCP server** exposes the verified library.

**Self-extension loop:**
```
request → planner picks instructions-skill | code-tool
        → author in QUARANTINE staging
        → test-before-trust gate: (a) static + secret scan
                                  (b) sandbox run vs a concrete acceptance check (grounded, never self-judged)
                                  (c) owner one-tap confirm on first promotion
        → promote to trusted library + register with capability MCP server
        → index description embedding for retrieval/composition
        (edits re-run the gate)
```

**Filesystem layout** — the agent writes capabilities to a **data root**, never the harness source tree:
```
%LOCALAPPDATA%\Artemis\
  capabilities\ staging\  library\<skill>\{SKILL.md, tool.py, tests\, resources\}  index\
  mcp\servers.json   secrets\(refs only)   state\   logs\
```
Repo holds `src/` (spine) + `client/` (UI). Wiping `staging/` is always safe; self-extension never touches the spine.

**Secrets** — stored in the **OS keychain** (Windows Credential Manager / DPAPI; macOS Keychain later). Skills reference secrets **by name** (`secrets:[notion_token]`, `${SECRET:notion_token}`); the harness **injects at call time, least-privilege** (only the declared names), gated + audited, paired with the egress allowlist. Skills never contain raw secrets.

> _Recipe cards never write down the password; the harness slips in the one needed key at the moment of use._

---

## 5. Memory system

**Six layers + working memory**, all behind a single **`MemoryPort`** (swappable engine):

| Layer | Holds | In context | Anti-bloat |
|---|---|---|---|
| 0 · Constitution | persona, core rules | **always** | tiny, hand-curated |
| 1 · Rules | prescriptive prefs/policies | matched, deterministic | structured records, not prose |
| 2 · Semantic + KG | distilled facts + entities/relations | retrieved top-k | consolidate (ADD/UPDATE/DELETE/NOOP), decay, supersede |
| 3 · Episodic | timestamped events | recency+relevance | TTL + consolidation upward |
| 4 · RAG corpus | ingested documents | retrieved chunks only | content-hash dedup ingest |
| 5 · Capabilities | verified SKILL.md | name+desc until matched | test-before-trust |
| × · Working | turn buffer | live | compaction at budget |

**Retrieval-heavy pipeline (the quality lives here):**
```
permissive write but CONSOLIDATE (never blind-append)
  → RAPTOR summary tree over raw memories (gist + detail, one index)
  → hybrid retrieve (vector + keyword + graph) wide net
  → cross-encoder rerank (online; LLM rerank offline only)
  → MMR dedup
  → HARD token-budget cap (well under the context-rot ceiling)
  → inject; summarize the overflow
forgetting = demote to cold tier + decay rank (recency × salience × access); ARCHIVE, never delete
```

**Anti-rot checklist (= acceptance criteria):** update/supersede not append · dedup at write + MMR at read · hard token cap + summarize overflow · cross-encoder rerank · tiered demote/decay (archive ≠ delete) · temporal validity (latest-wins) · keep context under the rot ceiling (~4–10× below window) · **abstention path** (recall "unknown" > false recall) · continuous LongMemEval/LoCoMo degradation-slope eval.

**Engine — OPEN fork (spike to confirm):**
- **Graphiti (Zep)** — temporal **knowledge graph**; every edge **bi-temporal** (event time + validity time); contradictions **invalidate, not delete** ("Ben@Acme until June, Ben@Globex after" — both kept, queryable as-of any date). Best "what was true when" + multi-hop, ~300ms LLM-free queries; KG-only (pair with pgvector for episodic/RAG), graph-DB dependency.
- **Cognee** *(lean)* — single-process local stack (SQLite + LanceDB + Kuzu) spanning **KG + semantic + RAG ingestion**, has `forget`, provider-agnostic via LiteLLM/Ollama (aligns with our model layer). Softer temporal semantics → port a decay policy on top.
- Steal **decay/forgetting policy** from Redis Agent Memory Server (age/inactivity/budget) + MemoryOS (heat-based promotion). Build thin ourselves: Constitution, Rules, Capabilities.

> _Be the library, not the hoarder's garage: keep everything and **search every shelf** (retrieve widely — nothing relevant is missed), then hand over only the **highest-signal subset that fits the context budget** — because an overstuffed context degrades accuracy (context rot), and summary nodes let a few slots cover broad ground. Comprehensive = the store + the retrieval sweep; disciplined = what crosses into context._

---

## 6. Proactivity & scheduler

Makes Artemis act, not wait. Two trigger types feed one engine:
- **Time-based** (durable scheduler / cron) — "every morning at 7, build my digest".
- **Event-based** (watchers) — new matching email, approaching calendar event, file change, webhook.

A lightweight **always-on heartbeat loop** drains an **event queue** + checks the **persisted schedule** (survives reboot) → enqueues proactive tasks → a worker runs them through the spine.

Non-negotiables: **durable** (schedules/triggers survive restart) · **quota-budgeted** (a cheap local check gates whether to spend a subscription call — idle ≈ free) · **gated** (proactive **suggests/asks**; external-effect actions route through the human-in-the-loop gate).

> _A clock and tripwires wired to a quiet loop; it wakes the agent, but taps you before touching the outside world._

---

## 7. Transport layer

Core brain is **transport-agnostic**; surfaces are **adapters** (normalize input → core request, render core output → format):
- **Desktop (Tauri)** — rich local surface (travel-zoom map), local IPC/HTTP + session auth.
- **Telegram** — bot adapter for remote/mobile access **and proactive push** (agent messages you: digests, alerts). Bidirectional; free; mobile/voice/file.

Identity resolved per transport (Telegram = chat-ID allowlist; desktop = local session). Bot token = keychain secret.

> _Caveat:_ Telegram messages transit Telegram's servers (leave the box). Acceptable post-privacy-wall; the adapter design still supports a "desktop-only" tag for content that should never go over Telegram.

---

## 8. Backup & durability

The learned memory + capability library **are the moat** — back up by importance tier:
- **Capabilities (SKILL.md) → git.** Text; every promotion = a commit, full history, instant rollback.
- **Memory DBs (graph/vector/SQLite) → scheduled snapshots** (run by §6's scheduler; consistent dumps).
- **Off-box, encrypted, 3-2-1** — ≥1 encrypted copy off the machine (B2/S3/Drive or second device); backup key escrowed separately.
- **Secrets caveat** — keychain secrets aren't in the data-root backup; they need their own secure export, or a restored machine reaches memory but not integrations.
- **Restore drills** — periodic test restore; an untested backup is a hope.

> _Treat skills like source code (git), memory like a database (snapshots + off-site copy), and practice getting it back. Lose the laptop, keep the brain._

---

## 9. Rejected / out-of-scope

- **v1 privacy wall + mandatory local-model stack** — local is now *just a fallback provider*, not the architecture.
- **ToS-grey CLI proxies** (CLIProxyAPI et al.) — fragile; one shipped credential-stealing malware. Build on official SDK subprocess seams only.
- **Full self-rewriting agents** (Darwin-Gödel, ADAS) — heavyweight, research-stage.
- **Intrinsic self-reflection** as verification — proven fragile; verification must be execution-grounded.

---

## 10. Forks — de-risked (resolved 2026-06-30)

_Box probe: WSL2+Ubuntu v2 installed; Docker v29.4.1 (daemon on-demand); Python 3.12.10 + uv 0.11.17._

1. **Memory engine — RESOLVED (default + trigger): Cognee-first behind `MemoryPort`.** Cognee is embedded (Kuzu+LanceDB+SQLite), pure-Python, no server, LiteLLM-aligned → runs in-process here; Graphiti needs a graph-DB *server* (FalkorDB/Neo4j via Docker/WSL2) = added Windows friction. Build on Cognee; run the **bi-temporal-quality spike (Cognee vs Graphiti, LongMemEval/LoCoMo-style) in Slice 2**; swap to Graphiti only if the "what-was-true-when" gap is material.
2. **Windows sandbox — RESOLVED: WSL2 substrate.** Run self-built code in **WSL2 as a restricted process** — no-network-by-default + egress allowlist + CPU/mem/wall-time limits. Docker container = optional stronger tier on demand. Firecracker/gVisor microVMs deferred (multi-tenant hardening; not our single-owner threat model = buggy/injected self-built tool).
3. **Skill granularity — RESOLVED: flat + tags now, hierarchy later.** Flat global library; `SKILL.md` frontmatter tags (domain/keywords); retrieval = semantic-by-description + optional tag filter. **Composition** = explicit declared `uses: [skill]` deps invoked via the capability MCP server (gate re-verifies the chain). Hierarchical namespacing = later non-breaking change (YAGNI until the library outgrows flat).

---

## 11. Research appendix (grounded findings + sources)

- **Subscription CLIs as headless backends, ToS-sanctioned for personal use:** `codex exec --json --output-schema` ([openai](https://developers.openai.com/codex/noninteractive)); `claude -p --output-format json --json-schema` + Claude Agent SDK ([support.claude.com](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)). Binding constraint = **weekly quota cap**; only account-sharing/reselling barred.
- **LiteLLM `CustomLLM`** wraps a CLI subprocess as a provider; Router gives subscription-first fallback ([routing](https://docs.litellm.ai/docs/routing), [custom_llm_server](https://docs.litellm.ai/docs/providers/custom_llm_server)); precedent: [litellm-claude-code](https://github.com/cabinlab/litellm-claude-code).
- **Schema strictness:** OpenAI strict mode requires every key in `required` + bans `maxLength`/`maxItems`; Anthropic = tool `input_schema`; Ollama = lenient `format` ([OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)).
- **Capability building:** Voyager verify-then-store skill library ([arxiv 2305.16291](https://arxiv.org/abs/2305.16291)); Anthropic **Agent Skills** `SKILL.md` open standard ([anthropic](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)); **MCP** ~9.6k servers, dynamic tool discovery ([registry](https://registry.modelcontextprotocol.io/)); **GEPA** reflective evolution, 35× fewer rollouts ([arxiv 2507.19457](https://arxiv.org/abs/2507.19457)); test-before-trust, grounded-not-intrinsic.
- **Retrieval-heavy anti-rot:** **context rot** safe ceiling ~4–10× below window ([Chroma](https://research.trychroma.com/context-rot), [NoLiMa](https://arxiv.org/abs/2502.05167)); **RAPTOR** collapsed-tree +20% QuALITY ([arxiv 2401.18059](https://arxiv.org/abs/2401.18059)); cross-encoder rerank 50–500ms vs LLM 4–6s; **Mem0** ADD/UPDATE/DELETE/NOOP ([arxiv 2504.19413](https://arxiv.org/abs/2504.19413)); **Zep/Graphiti** bi-temporal invalidate-not-delete, LongMemEval +18% ([arxiv 2501.13956](https://arxiv.org/abs/2501.13956)).
- **Memory frameworks:** no single engine covers all 6 layers; Graphiti/Cognee best for KG+semantic; avoid Letta (runtime lock-in) / Mem0 (no real forgetting + paywalled KG) as the spine.
- **Eval:** **LongMemEval** ([arxiv 2410.10813](https://arxiv.org/abs/2410.10813)) + **LoCoMo** — score per-question-type, abstention, update-correctness, degradation slope. Defensible numbers ≈ LoCoMo 67% / LongMemEval +18% (ignore vendor 90%+ headlines).
- **Agent-framework landscape:** universal custom-model-client seam; LiteLLM = de-facto multi-provider shim; lean = thin own spine over official SDKs ([speakeasy](https://www.speakeasy.com/blog/ai-agent-framework-comparison)).

# Project: Artemis (v2)
_A multi-provider, subscription-first agent harness whose job is letting agents build the owner's capabilities. (v1 was a local-first RAG "second brain"; scrapped + rebuilt from scratch 2026-06-30.)_

> **v2 rebuild — branch `v2-rebuild`.** v1 code is preserved at git tag `archive/v1`; the full v1 planning/coding history is frozen at [`docs/archive/status-v1.md`](archive/status-v1.md).
> **Read first:** `docs/v2/architecture.md` (design) · `docs/v2/build-plan.md` (slice sequence) · `docs/handoff/2026-06-30.md` (latest handoff).
> Memory: `artemis-v2-harness-pivot`, `artemis-v2-build-cadence`.

stack: Python thin spine · own `QuotaAwareRouter` (codex → claude_code → anthropic_api → ollama; LiteLLM rejected) · Cognee memory behind `MemoryPort` (optional `memory` dep group) · capabilities = SKILL.md library + MCP · WSL2 sandbox (`SubprocessSandbox` = interim, no isolation) · Tauri client (kept v1 surface, wired in Slice 3)
token_profile: lean
autonomy_level: L5
specialists_default: [apex-security, apex-ai-systems]
stack_skills: [apex-python, apex-tauri]   # v2 Python harness + kept Tauri client; apex-swift dropped (v1 Swift app + audio sidecar scrapped)
coder_models: [codex]     # codex = gpt-5.5 (primary, per task via `codex exec`); opus = manual fallback. Dogfood: Opus plans/specs/reviews, Codex builds; host re-verifies full mypy --strict + pytest.
max_parallel_codex: 3

_Last updated by planning mode:_ 2026-06-30

## Current state — Slices 0–2 complete

All green on `v2-rebuild` (mypy --strict · 91 tests · ruff clean). HEAD `f2a1bea`. Build cadence = incremental: one spec → Codex builds → host-verify → commit → `done/` (memory `artemis-v2-build-cadence`).

- **Slice 0 — spine proves itself.** Scaffold + 5 typed ports + model layer + schema-normalization shim + minimal plan→act→verify loop + one capability through its full lifecycle (author → sandbox → promote to `SKILL.md` → reuse).
- **Slice 1 — model layer.** Own `QuotaAwareRouter` over the four-provider subscription-first chain (codex → claude_code → anthropic_api → ollama); per-backend schema down-conversion lives in each `RawProvider`. **LiteLLM rejected** (architecture.md §2).
- **Slice 2 — memory.** Engine = **Cognee** (confirmed by live LoCoMo spike, `docs/findings/cognee-vs-graphiti-spike-2026-06-30.md`). `CogneeMemory` behind `MemoryPort` (optional dep group) + retrieval-heavy pipeline (CHUNKS → rerank → MMR → token-budget → summarize-overflow) + embedding-cosine MMR (`EmbeddingPort`/`OllamaEmbedder`) + consolidation/latest-wins (`LLMConsolidator`: ADD/UPDATE/DELETE/NOOP + supersession) + `forget()`/decay over a durable SQLite ledger. Memory's internal LLM defaults to a small/local model.

**Next: Slice 3 — proactivity + transport** (durable scheduler + watchers + heartbeat; Telegram bot + wire the Tauri desktop UI). First slice that makes Artemis *act*, and the first to touch `client/`. Owner-chosen entry point: the **durable-scheduler** spec (Python, dev-box buildable). No Slice 3 spec written yet.

<!-- Do not remove or rename the CODING:START/END or PLANNING:START/END comment markers. They are used by automated writers to locate their blocks. -->

<!-- CODING:START -->
## In-Flight
| What | Mode | State | File | Stopped at | Uncommitted |
|------|------|-------|------|------------|-------------|

_(empty — Slice 2 committed; nothing in progress. One stray uncommitted file: `client/src-tauri/Cargo.toml` cosmetic no-op, unrelated to any spec.)_
<!-- CODING:END -->

<!-- PLANNING:START -->
## Pending Specs
| Spec | Summary |
|------|---------|

_(none ready — Slice 3 specs not yet written.)_

> ⚠️ The specs still sitting in `docs/changes/` (`M0-*`, `M2-*`, `M3-d`, `M5-a`, `CLIENT-*`, `BUILD-ORDER.md`) are **archived-stale v1** — do **not** build them. They survive the pivot only because the v1 cleanup is pending (see Open Questions). v2 specs live in `docs/changes/done/` (`v2-00`…`v2-12`).

## Open Questions
- **Slice 3 entry point** — owner chose to start with the durable-scheduler spec (Python, dev-box buildable). Spec not yet written; that is the next planning step.
- **Layering follow-up (review ⚠️):** `memory/embedder.py` imports `ProviderUnavailableError` from `artemis.model.errors`, transitively loading the model providers (anthropic). Relocate the failover-error taxonomy to a neutral module (e.g. `artemis/errors.py`) so memory doesn't drag in model providers.
- **`SubprocessSandbox` is interim** (timed host subprocess, no isolation). The WSL2-isolated runner (no-network + egress allowlist + resource caps) is **required before any *externally*-authored capability is trusted** — swaps in behind the `SandboxRunner` protocol. Security gate, not optional.
- **Pre-existing `capabilities/sandbox.py` ruff-format drift** (from Slice 0) — still unfixed; fold into the next capabilities-touching spec or a one-line `ruff format` cleanup.
- **Claude Code subscription org-access** for this Opus host was flagged org-disabled mid-session ("use an Anthropic API key / ask admin"). May block the next Opus session — set `ANTHROPIC_API_KEY` for Claude Code or re-enable org access. Does **not** affect Codex builds (separate ChatGPT subscription).
- **Stale v1 docs still in-tree** — `status.md` now archived (this cleanup). Still describing v1: root `PROJECT.md` / `ROADMAP.md` / `REQUIREMENTS.md` / `BACKLOG.md` / `CHANGELOG.md`, and the v1 specs in `docs/changes/`. Cleanup/regenerate-for-v2 is a follow-up.
<!-- PLANNING:END -->

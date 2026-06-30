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

**Slice 3 — proactivity + transport (in progress).** First slice that makes Artemis *act*; the first to touch `client/`.
- **`v2-13` durable scheduler — done.** SQLite-backed `Scheduler` (cron via croniter + one-shot) + heartbeat loop + fire-once catch-up after reboot; `dispatch` is an injected seam.
- **`v2-14` proactive worker — done.** `ProactiveWorker.run_job` (the scheduler's `dispatch`): job payload → `Task` → `Spine.run` → proactive `OutboundMessage` out a `TransportPort`. The time-based loop is proven end-to-end (scheduler→spine→transport) in tests.
- **`v2-15` runner + console transport — done (built by Codex).** `ConsoleTransport` (first real `TransportPort`) + `App`/`build_app` + an `artemis` console-script. **`uv run artemis` is now a live always-on heartbeat.** (Also cleared the old `sandbox.py` format drift, `8603623`.)
- **`v2-16` Telegram transport — done (built by Codex).** `TelegramTransport` (Bot API: send + allowlisted long-poll receive) + `telegram_from_env`; `uv run artemis` env-selects Telegram else console. Hermetically tested (`httpx.MockTransport`). **Not yet run live** (manual go-live — see Open Questions).
- **`v2-17` schedule-management CLI — done (built by Codex).** `artemis add/list/cancel/run` (argparse, all in `app.py`, no new deps). Live-smoked: real `uv run artemis add/list/cancel` round-trip works. mypy 73 files · 117 tests · ruff clean.
- **Next:** wire the Tauri desktop UI (first touch of `client/`) → event-based watchers (via `scheduler.emit`) → a real secret store (Telegram token is an env stopgap).

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
- **Telegram live go-live (manual, owner)** — adapter built + hermetically tested but never run against the real API. @BotFather → `TELEGRAM_BOT_TOKEN`; `/start` → capture chat ID → `TELEGRAM_CHAT_IDS` + `TELEGRAM_OWNER_CHAT_ID`; `uv run artemis` + a near-future job → confirm phone buzzes.
- **CLIENT REVIVAL (in progress, owner chose full scope 2026-06-30)** — make the fully-built v1 Tauri `client/` work against the v2 brain + bundle into one launchable `.exe`. Roadmap: `docs/v2/client-revival-roadmap.md` (CR-1…CR-6 = usable launchable app; CR-7+ = real spokes/voice/vault tail). Contract maps: `docs/findings/{client-brain-contract,v1-brain-api-inventory,client-ui-flows}-2026-06-30.md`.
  - **`CR-1` brain HTTP API skeleton — done.** FastAPI app on `127.0.0.1:8030` (`/healthz` + v1-exact `/app/status`) + `artemis serve` command.
  - **`CR-2` auth handshake — done.** Faithful port of v1 P-256 device pairing + API session (`archive/v1`, ref `docs/findings/cr-2-auth-port-reference.md`); adds `cryptography`. **No-lock** (owner decision 2026-06-30): unlock/lock are no-op 200, `vault_unlocked` always true, status requires a session. Real-signing handshake test + replay/counter rejection pass. mypy 80 · 122 tests.
  - **`CR-3` Ask — done.** `/app/ask` + `/app/ask/stream` + `/app/ask/voice` backed by the `QuotaAwareRouter` (a chat ask = one completion, not the Spine), SSE-framed to the client contract; engine tag (local/codex) from `model_id`; voice is a deferred stub. Session-gated. mypy 82 · 127 tests. The Ask popup now talks to the live v2 brain.
  - **`CR-4` layout persistence — done.** `GET/PUT /app/layout` (ported v1 atomic-JSON `LayoutStore`, LWW; `default_layout` reseeded to the client's 11 domains/clusters). Session-gated.
  - **`CR-5` typed-empty domain reads — done.** ~15 `/app/*` read + review/actions/suggestion endpoints returning typed-EMPTY payloads matched to the client's `screens/dtos.ts` (camelCase `tasksDueByDay`/`needsYou`, null finance advisories; mutations are 404/echo stubs). Every detail screen + glance card now renders. Session-gated. mypy 86 · 140 tests.
  - **The brain now fully satisfies the client's API contract** — pair → connect → map renders all 11 domains → detail screens show empty states → Ask works live.
  - **`CR-6` launchable app — done.** `npm run tauri build` → `artemis-client.exe` (MSVC builds cleanly; ~2m). `scripts/launch-artemis.ps1` + `Launch Artemis.cmd` (repo root) = **one double-click starts the brain + opens the client, no terminals** (verified end-to-end). Owner chose the on-machine launcher (needs local uv/Python), not a portable PyInstaller bundle.
  - **▶ CLIENT REVIVAL CR-1…CR-6 COMPLETE — the app launches and is usable.** Remaining = the **owner live-connect** (double-click → pair → use) + the **CR-7+ tail**: real spokes (Gmail/Calendar/Finance) replacing the empty reads, voice, true token-streaming, real vault, wiring proactivity into `serve`, and the portable PyInstaller bundle.
- **Deferred Slice-3 items** — event-based watchers (via `scheduler.emit`), a real secret store (Telegram token is an env stopgap). The `should_fire` quota-budget gate and per-job acceptance remain seams (defaults: always-fire, no acceptance).
- **Stale v1 dirs under `src/artemis/`** (`cli`, `voice`, `reactions`, `proactive`, `knowledge`, …) — the v2 scaffold left v1 directories in place; prune as part of the v1-cleanup item.
- **Layering follow-up (review ⚠️):** `memory/embedder.py` imports `ProviderUnavailableError` from `artemis.model.errors`, transitively loading the model providers (anthropic). Relocate the failover-error taxonomy to a neutral module (e.g. `artemis/errors.py`) so memory doesn't drag in model providers.
- **`SubprocessSandbox` is interim** (timed host subprocess, no isolation). The WSL2-isolated runner (no-network + egress allowlist + resource caps) is **required before any *externally*-authored capability is trusted** — swaps in behind the `SandboxRunner` protocol. Security gate, not optional.
- **Pre-existing `capabilities/sandbox.py` ruff-format drift** (from Slice 0) — still unfixed; fold into the next capabilities-touching spec or a one-line `ruff format` cleanup.
- **Claude Code subscription org-access** for this Opus host was flagged org-disabled mid-session ("use an Anthropic API key / ask admin"). May block the next Opus session — set `ANTHROPIC_API_KEY` for Claude Code or re-enable org access. Does **not** affect Codex builds (separate ChatGPT subscription).
- **Stale v1 docs still in-tree** — `status.md` now archived (this cleanup). Still describing v1: root `PROJECT.md` / `ROADMAP.md` / `REQUIREMENTS.md` / `BACKLOG.md` / `CHANGELOG.md`, and the v1 specs in `docs/changes/`. Cleanup/regenerate-for-v2 is a follow-up.
<!-- PLANNING:END -->

# Artemis v2 — Client Revival Roadmap

_Goal: make the fully-built v1 Tauri client (`client/`) work against the v2 brain, then bundle the whole thing into one launchable `.exe` (no terminals). Owner chose the full-revival scope 2026-06-30._

> Source maps (read these for detail): `docs/findings/client-brain-contract-2026-06-30.md` (what the client demands) · `docs/findings/v1-brain-api-inventory-2026-06-30.md` (what v1 provided, recoverable at tag `archive/v1`) · `docs/findings/client-ui-flows-2026-06-30.md` (the UI flows).

## The situation

The client is **done** (travel-zoom map, glance cards, detail overlays, Ask popup, P-256 auth — all with vitest coverage). It talks to the brain through a **Rust gateway** (session token never enters the webview, ADR-030) that calls **~20 `/app/*` HTTP endpoints on `127.0.0.1:8030`**. The v2 brain currently has **no HTTP API at all** — the v1 FastAPI brain was deleted in the rebuild (recoverable at `archive/v1`).

So "revival" = stand up a v2 brain HTTP API that satisfies the client's contract. The endpoints tier by how much new backing they need:

| Tier | Endpoints | v2 backing | Cost |
|---|---|---|---|
| **0 — connect** | `/app/pair`, `/session/begin+complete`, `/unlock/begin+complete`, `/status`, `/lock`, `/logout` | P-256 device registry + session (port from v1 archive); **dev-simplified unlock** | Medium |
| **1 — ask** | `/app/ask`, `/app/ask/stream` | **v2 `Spine` + `QuotaAwareRouter` already exist** — SSE-frame the output | Medium (high value) |
| **2 — layout** | `GET/PUT /app/layout` | trivial JSON/SQLite persistence | Small |
| **3 — review/actions/tasks** | `/app/review/*`, `/app/actions/*`, `/app/tasks/suggestion/*` | map to v2: review→capability-forge pending skills; actions→(no v2 GATE yet) stub; suggestions→scheduler | Medium |
| **4 — owner data** | `/app/{calendar,tasks,projects,email,finance}` + glance | needs real Gmail/Calendar/Finance integrations — **none exist in v2** | **Large (long tail)** |
| **5 — voice** | `/app/ask/voice` | voice sidecar — **doesn't exist in v2** | Large |
| **6 — bundle** | — | `tauri build` + a launcher that starts the brain as a background process and opens the UI | Medium |

## Build sequence (vertical slices, one spec each, v2 cadence)

Ordered so the client becomes progressively more alive — connect → talk → persist → render → bundle. Each slice is write→Codex/inline build→host-verify→commit.

- **CR-1 — Brain HTTP API skeleton.** Add `fastapi` + `uvicorn` (deps); `artemis/api/` app on `127.0.0.1:8030` with lifespan composing the v2 router/memory/scheduler; `/healthz` + a minimal `/app/status` (unpaired). `uv run artemis serve` starts it. _Verify: curl health + status._
- **CR-2 — Auth handshake.** Port the v1 P-256 device registry + session challenge-response (`/app/pair`, `/session/*`, `/status`, `/lock`, `/logout`) + `require_session` dep. **Unlock is dev-simplified** (handshake succeeds → in-memory `unlocked` flag; no real SQLCipher DEK custody — that's the HW/Hello tail). _Verify: the client's `pairing.test` flow against a live brain; pair→connect→unlock reaches "connected, unlocked"._ **← owner decision: confirm the dev-unlock simplification.**
- **CR-3 — Ask via Spine.** `/app/ask` + `/app/ask/stream` backed by `Spine` + `QuotaAwareRouter`, SSE-framed as the client expects (`{text}` / `{done, path?, escalated}`); `require_session` + (dev) unlocked. **The Ask popup now talks to the real v2 brain.** Voice (`/app/ask/voice`) returns a graceful "voice not yet available" until Tier 5. _Verify: client ask store streams a real answer._
- **CR-4 — Layout persistence.** `GET/PUT /app/layout` over SQLite (LWW). Cards stay where you drag them. _Verify: PUT then GET round-trips a `LayoutDTO`._
- **CR-5 — Typed-empty reads + glance.** `/app/{calendar,tasks,projects,email,finance}` + `/review/*` + `/actions/*` return well-typed **empty** payloads (matching `screens/dtos.ts`) so every detail screen + glance card renders without error (zeros / empty states). _Verify: each `app_*_read` returns a valid empty DTO; map shows no crashes._
- **CR-6 — Bundle into `.exe`.** A launcher that (a) starts the brain (`uvicorn`) as a background process if not already up, (b) opens the Tauri window; `tauri build` produces the installer/`.exe`. **The "one double-click, no terminals" deliverable.** _Verify: built `.exe` launches, connects, Ask works._
- **CR-7+ — The long tail (separate efforts, each large):** real owner-data spokes (Gmail/Calendar/Finance integrations) replacing the CR-5 stubs · voice sidecar · real recipe-review + a v2 action GATE · real encryption-at-rest vault (DPAPI/Hello on Windows, Secure Enclave on Mac).

## Milestone: "usable launchable app"

**CR-1 → CR-6 delivers a real, double-clickable Artemis:** it connects, the map renders and remembers your card layout, and **Ask works against the live v2 brain** (subscription-first router + memory). Domain cards show honest empty states until CR-7+ fills each spoke. This is the first end-to-end "launch one thing and use it" milestone — the owner's core ask — with the genuinely large integrations (email/calendar/finance/voice/vault) sequenced transparently after.

## Key decisions to confirm (as each slice lands)

1. **Dev-simplified unlock (CR-2)** — satisfy the client's lock/unlock UX with an in-memory unlocked flag, deferring real SQLCipher-DEK + Hello/DPAPI custody to the HW-gated tail. v2 data isn't the sensitive v1 vault yet, and the dev box drove the v2 pivot. _Recommend: yes, dev-simplified now._
2. **FastAPI + uvicorn deps (CR-1)** — mandatory for the desktop client; architecture §7 already anticipates "local IPC/HTTP + session auth." Not a violation of the thin-spine thesis (the client is a real surface).
3. **Port v1 auth vs. rebuild (CR-2)** — port the proven v1 P-256 handshake from `archive/v1` rather than redesign; it's exactly the contract the client signs against (ADR-025).
4. **Owner-data order (CR-7+)** — which spoke first (Gmail / Calendar / Finance) when we reach the long tail — defer until CR-6 ships.

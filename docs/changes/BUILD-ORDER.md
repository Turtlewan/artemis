# BUILD-ORDER — the "build specs" manifest (current)

**Trigger (coding mode):** when the owner says **"build specs"** (or "build it"), build the dev-buildable
`status: ready` specs below in the ordered waves, via apex-code (Codex `codex exec -p apex-coder`,
parallel per ADR-028/029). **Verify each wave's acceptance criteria before the next.** Mac/MSVC/Tauri-gated
specs are NOT in the active queue (see § Gated) — they wait for their host/dependency.

_Reconciled 2026-06-26: 15 built + 4 retired-Swift specs archived to `done/`; queue below is the true
dev-buildable set._

## Already built — do NOT rebuild (in `docs/changes/done/`)
M0 foundation/ports · M1 manifest/router-brain · M2-c dev-subset · M3-a/b/c · M4-a/b/c-1/c-2/d · M6 heartbeat/delivery ·
M7-a1/a2/a3/b/c · OBS-a/b · DR-a/c · GATE-a · M8 Gmail/Calendar/Productivity · FIN-a/b/c/d · sensitivity wall (ADR-029) ·
full Wave-R reactions (ADR-032) · Tauri client core/theme/world/card/screens/ask + CLIENT-a/b · CAL-* · X3/wake. (See `docs/status.md` In-Flight for SHAs.)
Old **Swift** client specs (CLIENT-c-artemiskit/d-app-shell/e-screens/f-mac-app) are **retired** (superseded by the Tauri rewrite) and parked in `done/`.

## ▶ Dev-buildable queue (build in this order)

### Group A — Agentic engine (ADR-031 Phases 1–4) — ✅ COMPLETE 2026-06-26 (baseline green @ `b09255c`)
All 9 specs built (Codex/Opus), host-verified (full mypy + pytest), Opus security-reviewed, committed, archived to `done/`.
Engine lives behind the optional `[dependency-groups] agentic` group (base sync stays lean). rung2 AppContainer network-deny
host-validated. 2 composition seams (spine approve→graduate · inbox deliver-count) wait on GATE-b — see `docs/handoff/2026-06-26.md`.
| Wave | Spec(s) | Status |
|------|---------|--------|
| A0 | `AGENT-types` | ✅ `4baaa6b` |
| A1 | `AGENT-checkpoint` · `AGENT-inbox` · `AGENT-authority` | ✅ `dc504ac` · `7806d67` · `d185662` |
| A2 | `AGENT-spine` (+`pydantic-ai`) | ✅ `6396427` |
| A3 | `AGENT-rung01` | ✅ `dea5016` |
| A4 | `AGENT-coder-router` → `AGENT-coder` (+`litellm`/`openhands-sdk`) | ✅ `865b10b` · `a97be1e` |
| A5 | `AGENT-rung2` (AppContainer sandbox) | ✅ `b09255c` |

### Group B — Voice (M5 dev twin) — independent of A
| Order | Spec | Notes |
|-------|------|-------|
| B1 | `M5-a-win-sidecar` | ⚠️ **CORE BUILT `4a574a7`** (wire-protocol twin + state machine + barge-in + fakes; full mypy+pytest green) + **dep-fix done** ([voice-dev] resolves). **TRANSPORT FORK RESOLVED 2026-06-26** (owner: bare TCP-loopback for the Windows twin; framing unchanged; Mac keeps AF_UNIX) → resolution spec **`m5-a-win-transport` (ready)**. Build that next → then archive M5-a-win-sidecar + m5-a-win-transport together. |
| B1.1 | `m5-a-win-transport` | **READY (Light)** — AF_UNIX-or-TCP-loopback transport seam in `IPCServer.start()` + `audio.port` rendezvous + un-skip the e2e socket test. Completes M5-a-win-sidecar. |
| B2 | `M5-b-stt-tts` | Moonshine STT + Kokoro/Piper TTS behind ports — UNBUILT (after the B1 transport decision) |
| B3 | `M5-c-speaker-id` | ECAPA-TDNN speaker-ID (voiceprint test Mac-gated) — UNBUILT |
| B4 | `M5-d-voice-loop-orchestrator` | orchestrator (tests vs the win-sidecar) — UNBUILT (consumes the B1 transport) |

### Group C — Quick wins (independent, any time)
| Spec | Notes |
|------|-------|
| `fix-finance-hooks-date-stability` | ✅ DONE `f0be86c` (greened the red baseline that was blocking all builds) |
| `distill-datagen-pipeline` | ✅ DONE `e73535c` (standalone `tools/distill/` teacher→JSONL pipeline; 10 tests green) |

**Concurrency:** A, B, C are mutually independent (disjoint files, no cross-prereqs) → may run concurrently;
owner priority is **A first**. Within A/B follow the wave order; C any time.

## Gated — NOT in the active queue (wait for host/dependency)
| Spec | Gate |
|------|------|
| `CLIENT-auth` | MSVC C++ Build Tools (Rust keystore FFI) |
| `GATE-b-action-review-surface` | Tauri client re-scope (Pending-actions tab) |
| `M2-a-key-broker` · `CLIENT-broker-pair-ipc` | Mac Secure Enclave (CLIENT-broker-pair-ipc deps M2-a) |
| `M2-c-broker-client-tier0-launchd` | Mac (partial dev-subset built; reconcile + Tier-0 tail) |
| `M2-d-security-gate` | Mac-phase **review gate** (not code) — run before the Mac sensitive-store build |
| `M0-b-launchd-services` · `M0-c-mlx-server` · `M0-e-isolation-backup` · `M0-f-env-injection` | Mac / launchd / mlx-server / deploy host |
| `M3-d-visual-document-understanding` | Mac / heavy vision deps |
| `M5-a-audio-sidecar` | native Swift (Mac) — the production twin of `M5-a-win-sidecar` |

Per-spec detail for the cluster lineage: `docs/findings/cluster-spec-roadmap.md`.

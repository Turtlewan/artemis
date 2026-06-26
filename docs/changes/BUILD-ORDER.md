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

### Group A — Agentic engine (ADR-031 Phases 1–4) — PRIORITY (owner: agentic first)
| Wave | Spec(s) | Notes |
|------|---------|-------|
| A0 | `AGENT-types` | shared types/Protocols barrel |
| A1 ∥ | `AGENT-checkpoint` · `AGENT-inbox` · `AGENT-authority` | file-disjoint, parallel |
| A2 | `AGENT-spine` | composes A1; adds `pydantic-ai` (`[agentic]` extra) |
| A3 | `AGENT-rung01` | read-only introspection + reversible file ops |
| A4 | `AGENT-coder-router` → `AGENT-coder` | LiteLLM router → embed `openhands-sdk` (`[agentic]` extra) |
| A5 | `AGENT-rung2` | no-network AppContainer sandbox + command exec |
_pyproject `[agentic]` extra is touched by spine/coder-router/coder — already dep-serialised across waves._

### Group B — Voice (M5 dev twin) — independent of A
| Order | Spec | Notes |
|-------|------|-------|
| B1 | `M5-a-win-sidecar` | Python sidecar (wake/VAD/STT/TTS), `[voice-dev]` extra |
| B2 | `M5-b-stt-tts` | Moonshine STT + Kokoro/Piper TTS behind ports |
| B3 | `M5-c-speaker-id` | ECAPA-TDNN speaker-ID (voiceprint test Mac-gated) |
| B4 | `M5-d-voice-loop-orchestrator` | orchestrator (tests vs the win-sidecar) |

### Group C — Quick wins (independent, any time)
| Spec | Notes |
|------|-------|
| `fix-finance-hooks-date-stability` | trivial test-date fix (the one red test) |
| `distill-datagen-pipeline` | offline `tools/distill/` teacher→JSONL pipeline (pre-Mac) |

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

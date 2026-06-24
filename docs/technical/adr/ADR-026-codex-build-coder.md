# ADR-026 — Codex as the build coder for Artemis core (supersedes the DeepSeek-on-Mini build binding)

- **Status:** Accepted
- **Date:** 2026-06-22
- **Deciders:** owner + planning
- **Relates:** **ADR-022** (adopted Codex on the ChatGPT subscription as the runtime reasoning engine — this ADR extends Codex to the *build* role) · **ADR-002** (deployment: Mac Mini = final host) · **ADR-001** (stack) · **ADR-023/025** (Tauri client — Windows-buildable) · `docs/bring-up/CODEX-BUILD-RUNBOOK.md` (the per-spec build procedure) · de-gating map `docs/findings/codex-degating/`.

## Context

The ~61-spec corpus was authored for **DeepSeek-V4-Flash to build on the Mac Mini** (`backends: coding=deepseek-v4-flash`; `coder_tier_policy: split`; status.md called ~56 specs "Mini-gated"). That binding pre-dates two developments:

1. **ADR-022 — build Windows-first.** The brain spine is pure Python; MLX is a swappable OpenAI-compatible endpoint. The validation slice (M0-a→M1-c, M4-a reduced, LanceDB, dev enablers) and the brain-Codex batch proved the core builds + tests on Windows/WSL2 today against fakes.
2. **Codex CLI as a working coder.** The brain-Codex batch (`uv-dependency-groups-migration` … `brain-sensitivity-routing`) is built by **Codex CLI (`gpt-5.5`)** driven per-spec from the runbook — *outside* `apex-code` orchestration, owner-supervised. It works: specs are self-contained execution scripts Codex reads and executes directly.

The owner's decision: **make Codex the coder for all Artemis core**, generalising the brain-batch exception into the standing build method, and cashing in the Windows-first unlock.

## Decision

| Aspect | Decision |
|--------|----------|
| **Coder** | **Codex CLI (`gpt-5.5`)** is the build coder for Artemis core, run with `--sandbox workspace-write`. Replaces DeepSeek-V4-Flash. |
| **Fallback** | No default fallback. DeepSeek-coding and Claude-coding remain available APEX modes but are **not** the Artemis-core path. (Revisit per-spec only if Codex can't meet a spec's AC — a stop-and-ask, not an auto-switch.) |
| **Build host** | **Windows/WSL2 now** (ADR-022 Windows-first). The **Mac Mini remains the final runtime host** and the host for genuinely hardware-gated build/verify tasks. |
| **Orchestration** | The **per-spec loop in `CODEX-BUILD-RUNBOOK.md`** (Codex self-drives its agentic loop; reads the spec, runs its commands, iterates to green). **Outside `apex-code`** wave orchestration. Specs' `## Wave plan` sections are **informational only** under Codex. |
| **Standing rules** | `AGENTS.md` (repo root) — Codex auto-loads it (surgical scope, tests-are-the-contract, never commit/push, stop-and-ask). |
| **Tier system** | **Retired.** Codex is effectively one model, so `coder_tier: flash/pro` frontmatter is **vestigial/ignored** (not stripped from specs — left inert). `coder_tier_policy: split` → retired. |
| **cross-model review** | **Default-satisfied.** Claude plans + reviews, Codex builds → every spec is cross-*family* by construction. `cross_model_review: true` becomes informational; the property holds corpus-wide. |
| **Commits** | **Owner-controlled** (per runbook). Codex builds + verifies only; never commits, never pushes. **Never push to main** (hard block). |

## Consequences

- **The "wait for the Mini" gate dissolves for Windows-buildable specs.** Most of the core (brain, memory, knowledge, Gmail/Calendar/Productivity logic, observability, recipe/teacher) is pure Python testable with fakes → **buildable now**. See the de-gating map (`docs/findings/codex-degating/`) for the per-spec NOW / PARTIAL / HW-GATED / BLOCKED-UPSTREAM split and the build order.
- **Genuinely hardware-rooted tail tasks still wait for the Mini:** Secure-Enclave broker (M2), MLX serve/probe (M0-c), the voice audio sidecar (M5, Swift+mic), and macOS `launchd`/`security`/`sysadminctl` runtime verification. Many appear as **PARTIAL** — the spec's core builds now, only a marked tail task is gated.
- **macOS-only CLI tools in *build* checks** (`plutil`, `chflags uchg`, `stat -f`) need WSL2 substitutes or skip-with-fake; flag at build time.
- **Quota:** Codex 5h/weekly caps (ADR-022). A large corpus consumes quota → sequence builds in waves rather than one firehose.
- **`stack_skills`:** `apex-python` is the primary build stack. `apex-swift` still applies to the genuinely-Swift HW-gated specs (M2-a broker, M5 sidecar); the **CLIENT layer moves to Tauri** (ADR-023/025), making it Windows-buildable after re-spec.
- **The runbook is promoted** from "brain-batch procedure" to the project's standing build method.

## Alternatives considered

- **Keep DeepSeek-V4-Flash on the Mini** — *rejected*: blocks build-now, defeats ADR-022 Windows-first, and leaves the corpus idle until hardware arrives.
- **Codex-first with DeepSeek auto-fallback** — *deferred*: available as a manual per-spec escape, but a standing auto-fallback adds a second toolchain to maintain for no current need (single-owner, supervised builds).
- **Drive Codex through `apex-code` wave orchestration** — *rejected for now*: Codex CLI is itself agentic and self-orchestrates per spec; layering apex-code's DeepSeek-shaped wave dispatch on top is redundant. The runbook's per-spec loop is the lighter fit.

## Build-time

The per-spec procedure in `CODEX-BUILD-RUNBOOK.md` is the method. The de-gating map sequences the first Windows build waves (NOW specs first, in dependency order; PARTIAL specs build their core now and defer gated tails to the Mini; HW-GATED + BLOCKED-UPSTREAM wait).

## Refinement 2026-06-24 — Codex now runs INSIDE apex-code (mechanic A)

**Reverses the original "Orchestration: outside apex-code" decision (Decision table) and the rejected alternative "Drive Codex through apex-code wave orchestration."**

The original rationale — "apex-code is DeepSeek-shaped wave dispatch, redundant on top of Codex's own agentic loop" — is now obsolete:
- **apex-code became Codex-native.** APEX **ADR-027** made Codex the primary coder dispatched as a `codex exec -p apex-coder` subprocess from an Opus build host (Opus = inline fallback on quota-out); **ADR-028** added parallel-Codex on git-worktrees within a wave; **ADR-029** added cross-spec parallel build with the file-disjointness invariant + a supervision gate. apex-code no longer carries DeepSeek-shaped dispatch.
- **The 2026-06-24 cluster build empirically showed the manual runbook flow *was* mechanic A** — Codex per-spec via `apex-coder`, host re-verify (`mypy --strict src tests`/ruff/pytest) + per-spec commit, parallel Codex on disjoint subtrees (`M7-a3 ∥ M4-c-2`, "recipes/ vs memory/ don't import each other"), serialized on shared files (`M4-d-2`/`OBS-a` both touch `brain.py`), timeout → recover-by-reverify. The human was hand-driving mechanic A; apex-code formalizes it and removes the manual orchestration burden.

**Refined decisions:**
- **Orchestration → apex-code mechanic A.** Replaces the standalone per-spec runbook.
- **`## Wave plan` sections become executable** (apex-code consumes them), not "informational only."
- **`CODEX-BUILD-RUNBOOK.md` retired.** Generic Codex mechanics (stdin-pipe, sandbox-artifact ownership, fallback-to-Opus, integrated re-verify) are owned by apex-code; the Artemis-specific gotchas it held (CAL specs large/slow → longer timeout/split; timeout → re-verify-not-redispatch; pre-flight every original-corpus spec against the live tree) move to `AGENTS.md`.
- **Fallback (OPEN — owner):** mechanic A defaults to Opus inline-fallback on Codex quota-out. ADR-026 chose no-auto-fallback (stop-and-ask). Kept `coder_models: [codex]` (stop-and-ask) pending the owner's call; `[codex, opus]` enables the Opus auto-fallback.
- **Unchanged:** tier system retired; cross-model review default-satisfied; commits owner-controlled; never push to main.

**Validation:** first real mechanic-A build = the next M3-a-independent wave (`CAL-c` → `M8-d-b` · `M4-d-2` · `OBS-a`), which doubles as the live proving run for APEX ADR-028/029 (the `brain.py`-touching specs must serialize while `CAL-c` runs parallel).

Relates: APEX ADR-027 (Codex-primary/Opus-fallback), ADR-028 (parallel Codex), ADR-029 (cross-spec parallel build).

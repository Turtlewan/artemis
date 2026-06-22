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

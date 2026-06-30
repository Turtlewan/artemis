# Artemis v2 — Build Plan

_Companion to [`architecture.md`](./architecture.md). The sequence, mechanics, and slice decomposition for building the v2 harness._

## Build mechanics (dogfooded)

- **Roles:** planning side (this assistant) writes specs + reviews; **Codex (`gpt-5.5`) builds** each task on the ChatGPT subscription — the harness builds itself with the subscription-first coder it's designed around, keeping the build off the scarce Opus pool.
- **Ports-first:** define the thin interfaces before features so engines/transports/memory are swappable (the whole "thin spine, borrow behind a port" ethos).
- **APEX loop per spec:** spec → Codex builds → host-verify (`uv run mypy` + `uv run pytest -q`) → review → commit → move spec to `done/`.
- **Vertical slices:** each slice is a runnable end-to-end thing, not a horizontal layer.

## Repo transition (one-time, before Slice 0 code)

1. **Tag `archive/v1`** at current HEAD — the entire v1 corpus stays recoverable forever.
2. **Scaffold fresh `src/artemis/`** for the v2 harness (v1 package removed, recoverable via the tag).
3. **Keep `client/` untouched** — the Tauri UI is the kept surface (re-bound to the harness in Slice 3).
4. Drop the uncommitted v1 email-override changes (superseded by the pivot).

> NEEDS-DECISION: v1 `src/artemis/` disposition after the tag — delete-and-replace (recoverable via `archive/v1`) vs. relocate to `legacy/`. Default below assumes delete-and-replace.

## De-risked forks (resolved 2026-06-30 — see architecture.md §10)

- **Sandbox:** WSL2 restricted process (no-network default + egress allowlist + resource caps); Docker tier on demand.
- **Memory engine:** Cognee-first behind `MemoryPort`; Cognee-vs-Graphiti bi-temporal quality spike inside Slice 2.
- **Skills:** flat global library + frontmatter tags; composition via declared `uses:` deps; hierarchy deferred.

## Slice sequence

| Slice | Delivers | Acceptance / verify |
|---|---|---|
| **0 · Spine proves itself** | scaffold + 5 ports; LiteLLM + Codex adapter + schema shim; minimal plan/act/verify loop; one capability through its full lifecycle | Ask for a capability → agent authors it → sandbox-verifies → promotes to `SKILL.md` → exposes via MCP → reuses it on a second task. `mypy` + `pytest` green. |
| **1 · Widen model layer** | Claude-Code adapter + API + local fallback; subscription-first quota-aware router | Force a primary-quota failure → router fails over to the next backend, same validated output. |
| **2 · Memory** | `MemoryPort` impl; Cognee-vs-Graphiti spike; retrieval-heavy pipeline (hybrid → rerank → MMR → budget); 6 layers | LongMemEval/LoCoMo-style degradation slope stays flat as the store grows; latest-wins on contradicting facts. |
| **3 · Proactivity + transport** | durable scheduler + watchers + heartbeat; Telegram bot + desktop (wire the Tauri UI) | A scheduled digest fires after a reboot and reaches you on Telegram; desktop map renders live capability nodes. |
| **4 · Durability + eval** | capabilities→git, DB snapshots, off-box encrypted 3-2-1, restore drill; eval harness | Wipe the data root, restore, agent keeps its brain + capabilities. |

## Slice 0 decomposition (the ready/next specs)

1. **`v2-00-scaffold-and-ports`** — uv project + tooling + clean `src/artemis/` + the 5 typed ports + import smoke test. _(ready — see `docs/changes/`)_
2. **`v2-01-model-layer-and-schema-shim`** — LiteLLM core + a `CustomLLM` adapter wrapping `codex exec` + the schema-normalization shim → validated structured output with a single-fallback path.
3. **`v2-02-minimal-spine`** — a plan→act→verify loop over `ModelPort` that runs one real task to completion.
4. **`v2-03-capability-lifecycle`** — one capability end-to-end: author → WSL2 sandbox verify against an acceptance check → promote to `SKILL.md` library → register with the capability MCP server → retrieve + reuse.

> NEEDS-DECISION (Slice 0 scope): does Slice 0's capability use a real MCP server, or an in-process registry with the MCP wrap deferred to Slice 1? Default: in-process registry in Slice 0, MCP wrap in Slice 1 (keeps Slice 0 a clean spine proof).

# Brief: the brain spine is Windows/WSL2-buildable now — validation-slice opportunity

**Date:** 2026-06-17
**Status:** Audited → GO (2026-06-17) — slice line-audit closed the open sub-question; owner to pick up (a DeepSeek coding session). See § Open sub-question.
**Origin:** APEX planning discussion, 2026-06-17. Owner confirmed the "build waits for the Mini" rule is an **inherited assumption**, not a deliberate constraint.

## The realisation

The whole corpus (~61 specs) is batch-handoff-ready but has **never been validated by execution** — only for internal consistency (interface fictions, async drift, `contracts.md` conformance, mypy-strict-ability). The sweeps prove the specs *agree with each other*; they cannot prove the design *works when built*. That is the largest unvalidated bet in the project, and it's gated on hardware (M5 Mini) that keeps slipping.

The blocker was assumed to be "Artemis = Mac app = can't build until the Mini." That conflates two different gates (the same conflation APEX itself untangled 2026-06-15):
- **Truly Mac-gated:** local model serving (M0-c mlx), launchd/infra (M0-b, M0-e, M2-c), Keychain (M0-f), the Apple clients (CLIENT-*), voice sidecar (M5-*).
- **NOT Mac-gated — pure Python:** the brain spine (M0-a, M0-d, M1-*, M3 retrieval logic, M4 memory schema, GATE staging). These merely *reference* MLX as a **swappable OpenAI-compatible endpoint**.

## Verification (live-checked, not assumed)

- **M1-b (router brain):** sole MLX reference is *"local 127.0.0.1 calls to mlx-openai-server"* — an OpenAI-compatible endpoint. Router logic is plain Python. Point the model port at any cloud OpenAI-compatible endpoint → it runs.
- **M0-a (foundation):** macOS hits are path assumptions (`~/artemis`, `$HOME`, plists) + *"deterministic on any Apple Silicon mac, no on-hardware empirical gate."* No hard runtime Mac dep in the Python skeleton; plist/sandbox concerns are fenced in M0-b/M0-e.
- **Grep map** (`docs/changes/`, case-insensitive `mlx|launchd|Keychain|SwiftUI|macOS|...`): heavy coupling only in M0-b (29), M0-c (34), M0-e (24), M0-f (37), M2-c (13), M5-a/b (11/16), CLIENT-c/d/e/f. Spine specs show only incidental endpoint/path references (M1-b 5, M0-a 6, M1-d 1, M4-b 4).

## Proposed validation slice (highest leverage, ~5 specs)

> **M0-a** (package layout) + **M0-d** (ports scaffolding) + **M1-a** (manifest/registry) + **M1-b** (router, model-port → cloud endpoint) + **M1-d** (time tool) — optionally **M1-c** (CLI) to invoke it.

End-to-end *"ask Artemis the time → router → tool → answer."* Validates the **highest-risk seams**: `contracts.md` cross-module boundaries, ADR-016 async dispatch, the manifest/router design — the assumptions threaded through the most downstream specs. (Slice 2 candidate: **M4-a** memory schema — pure SQLite/LanceDB + bitemporal — validates the storage seam.)

## Caveats (so this stays honest)

1. **De-risks the batch strategy; does not replace it.** ADR-002 (build-on-Mini for *production*) stands. This is a *dev/validation* build — verify the spine, then the eventual Mini handoff stands on tested ground.
2. **Cloud-model substitution is test-only.** The model port points at a cloud OpenAI-compatible endpoint *for the validation build only* — must NOT leak into specs as a permanent decision; local MLX (M0-c) remains the production target. Build-time config swap, nothing more.
3. **Build in WSL2, not native Windows.** Several specs assume Unix paths (`/opt/artemis`, `$HOME`). WSL2 gives a Unix env so the path assumptions just work, and is closer to the Mini target than native Windows.
4. **Needs a DeepSeek coding session** (build work). APEX's DeepSeek cloud coder is Windows-runnable now (`coding-session` gate, not `mac-gated`).

## How to execute (when owner picks up)

1. In `~/artemis`, switch to the DeepSeek backend (set `ANTHROPIC_BASE_URL` → `…/deepseek/anthropic`, restart) → coding mode.
2. Stand up WSL2 Python env (`uv`), build the slice specs in dependency order (M0-a → M0-d → M1-a → M1-b → M1-d → M1-c).
3. **Model-port config (test-only) — decided 2026-06-17:**
   - **LLM (`ModelPort`):** point `OpenAIModelPort` at DeepSeek's **native OpenAI-compatible endpoint** (`api.deepseek.com`, `deepseek-chat`/`-reasoner`) — NOT the Anthropic-protocol proxy that Claude Code coding-mode uses (different door, different key; Artemis speaks OpenAI protocol). [Catch A]
   - **Embeddings (`EmbeddingModel`):** keep the spec's own **`FakeEmbedder`** for the live run. DeepSeek serves completions only — no `/embeddings` route. [Catch B] The fake is fine: the tool set is 1–2 tools so embedding *quality* is irrelevant to tool selection; production embeddings come from the local MLX server, not a cloud LLM, so nothing is misrepresented. Only the LLM is "real" in the live run — that's the part worth validating.
4. Run the slice end-to-end; capture what the build *learned* (seam surprises, contract gaps) in a handoff — that is the execution signal the corpus has never had.

## Slice 2 (on-deck — sequenced behind slice 1)

**M4-a (bitemporal memory schema)** is the next slice — validates a *different* risk class (storage / data-model, not orchestration). **Sequenced, not bundled:** build slice 1 first, read its handoff, then pick up M4-a.

**🟡 M4-a pre-audit done 2026-06-17 — verdict YELLOW (buildable-with-caveats; NOT the clean GREEN of slice 1).** Correction to an earlier optimistic note: M4-a does **not** merely reuse M0-a+M0-d — its prerequisites also include **M2-b** (`ScopedConnection`/`KeyProvider`/`SecretKey` — the security wall) and **M2-c** (`sqlcipher_open` keyed open). Three frictions: (1) the `MemoryStore` adapter (Task 5) is built against M2-b/M2-c symbols; (2) **Task 1 is explicitly hardware-GATED** (the ADR-004 sqlite-vec-under-SQLCipher spike — runs on the Mini, cannot be validated pre-Mini); (3) SQLCipher native binding (APSW+sqlite3mc) is the predicted WSL2 friction.

**The saving grace (spec-designed):** a **plain-sqlite + sqlite-vec fallback** (no encryption, identical bitemporal SQL) — and the *valuable* part (bitemporal correctness: `as_of`, interval-closing, idempotent re-ingest, dimension-lock, cardinality keying) lives in `schema.py`+`repository.py`+golden tests (Tasks 2/4/6), which take a bare `conn` and touch **no** M2. So slice 2 splits:
- **Slice 2a (RECOMMENDED — reduced bitemporal core):** build Tasks 2/4/6 on the plain-sqlite+sqlite-vec fallback; stub/skip the M2-dependent store skeleton (Task 5) + the gated encryption spike (Task 1). High signal (proves the data-model design), low deps (no M2 wall, no Mini, no SQLCipher binding), WSL2-buildable.
- **Slice 2b (full M4-a):** needs M2-b+M2-c built first AND the Mini for Task 1. Bigger, partly hardware-gated — defer to the Mini.

**Slice 2 = 2a, sequenced after slice 1.** The encryption + M2-wall integration stays a Mini-side task.

## Open sub-question before committing — ✅ CLOSED 2026-06-17 → GO

Rigorously confirm the slice specs carry **no hidden** Mac/MLX/path dep beyond the swappable endpoint (this brief spot-checked M0-a + M1-b; M0-d / M1-a / M1-c / M1-d not yet line-audited). A 30-min read of those four closes it.

**Resolved — full line-audit of M0-d, M1-a, M1-c, M1-d done 2026-06-17. Verdict: GO (no hidden dep).**
- **No direct MLX/Mac engine call.** The only model/embedding reference is the *swappable OpenAI-compatible socket* — M1-b's adapters (`OpenAIModelPort`/`OpenAIEmbeddingModel`) are standard clients pointable at any compatible endpoint.
- **Fully fake-testable.** All four specs state "deterministic; no on-hardware gate; off-hardware testable with fakes" and ship their own stunt-doubles (`FakeEmbedder`/`FakeModelPort`/`FakeBrain`). M1-d's end-to-end test (`"what time is it" → real time tool`) runs entirely on fakes.
- **One — and only one — gated step:** M1-b Task 5 (the live-model run). That is exactly where the test-only cloud endpoint plugs in; everything else needs no model. The gate is endpoint-shaped, not Mac-shaped.
- **Two trivial frictions (not blockers):** (1) Files-to-Change tables write Mac-style absolute paths (`/Users/artemis-build/artemis/...`) — cosmetic; all *commands* are repo-relative, so the coder just creates files under the repo and ignores the prefix. (2) M1-a's export path uses M0-a's `/opt/artemis`-style data root — a one-time WSL2 `mkdir`/config override (and tests use `tmp_path` anyway). The recurring "configure an async test runner" note was already folded into M0-a via ADR-015.
- **Reversibility:** fully reversible, dev/validation only — does not touch ADR-002 (Mac = prod) or any spec decision. The single discipline to hold: the cloud-endpoint substitution stays a build-time config and is **never** written into a spec.

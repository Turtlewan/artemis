# ADR-039 — Capability invoke/reuse path: close the build→promote→reuse loop

- **Status:** **Accepted** — owner + planning, 2026-07-02.
- **Date:** 2026-07-02
- **Deciders:** owner + planning
- **Refines:** ADR-035 (reach-out capabilities) — the forge/store/sandbox substrate this reuses. **Adopts:** ADR-009 (untrusted-content Dual-LLM posture, via the reachout `WebTool` quarantine pattern), ADR-036 (hardened WSL2 sandbox — `FetchSandbox.run`'s execution model), the `cred-store` spec (`SecretStorePort` / `KeyringSecretStore`), and the R3 intent router (`ed3783e`, `src/artemis/intent.py` + `src/artemis/api/ask_routes.py`). Does not re-decide any of that locked substrate.
- **Design basis:** live code audit 2026-07-02 of `src/artemis/capabilities/{store,fetch_sandbox,forge}.py`, `src/artemis/types.py`, `src/artemis/intent.py`, `src/artemis/api/ask_routes.py`, and the shipped `cred-store` / `reachout-web-tool` / `build-gate` (5a/5b) specs.

## Context

The forge (`CapabilityForge.build`/`propose`/`build_proposed`) authors a capability, sandbox-verifies it, and `FileCapabilityStore.promote` installs it into the library. `FetchSandbox.run(capability_dir, entrypoint, argv, egress_domains, timeout_s)` can execute a promoted capability inside the hardened WSL2 isolate — but nothing calls it. There is no trigger: `store.retrieve()` exists (lexical shortlist), but no code path turns an owner's natural-language ask into "run capability X with these args and tell me the result." Every build dead-ends in the library. This ADR fixes the missing last mile: **build → promote → reuse**.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Trigger: natural-language via the intent router** | The owner asks in plain English through an existing transport (Telegram, `/app/ask`). No new UI surface, no explicit "run capability" command — the same inbound-message path that already reaches `IntentRouter` is where invoke selection happens. |
| 2 | **Selection = match-first, ahead of the classifier** | Before `IntentRouter.classify` runs, try to match a promoted capability: `store.retrieve(request, k)` shortlists candidates by lexical score, then a small model call picks one (or none) and extracts typed args. A confident match short-circuits straight to invoke; no match falls through to the existing `build`/`web_q`/`aggregate`/`plain_ask` classifier unchanged. This is a **pre-classifier stage**, not a fifth `Route` literal value returned by `classify()` — `classify()` itself is untouched. |
| 3 | **Match-first LLM call MUST use a dedicated `claude_code` Haiku port** | Never the shared codex-primary `QuotaAwareRouter` (`build_model_router`). Forcing `model="haiku"` onto that router reaches Codex as an unknown model, fails non-failover-eligibly, and silently degrades every call to a no-op — this exact bug shipped and was fixed in `ed3783e` for the R3 intent classifier (`ask_routes._intent()` now builds `IntentRouter(ModelClient(ClaudeCodeProvider(), model_default="haiku"))` explicitly). The invoke selector mirrors that exact construction, not the shared router. |
| 4 | **Inputs = structured, declared in SKILL.md frontmatter** | Each capability declares a typed `inputs` schema (a list of `{name, type: string\|number\|boolean, description, required}` — see spec #1) at build time; the forge authors it (spec #2); the selector extracts typed args against it (spec #3) instead of freeform text. Capabilities with no `inputs` declared (every capability built before this ADR) are treated as **parameterless** — invoked with empty argv, unchanged from today. No migration required. |
| 5 | **Safety default (a): missing-key run-guard** | Before running, cross-check the capability's `secrets: list[str]` against the keychain cred-store (`SecretStorePort.list_names()`/`get()`). Any declared secret not present → block the run and deep-link to the keys panel, mirroring the 5b build-gate consent pattern (plan-card egress + missing-secrets cross-check, `docs/changes/done/` step 5a/5b). The capability does not run with partial credentials. |
| 6 | **Safety default (b): confirm-before-run** | Show the owner: capability name, `egress_domains`, `secrets` it will use, and the extracted typed inputs — then Run/Cancel. No auto-run. Aligns with the locked "agency = ask, never auto" decision and ADR-012's confirm-on-expensive-action posture. |
| 7 | **Credential injection: env vars into the WSL2 isolate, never logged** | Secret VALUES read from the keychain (`SecretStorePort.get(name)`) are injected as environment variables into the WSL2 isolate process that runs the capability (`FetchSandbox`/`run_isolated`'s command environment) — never passed as argv (which can leak via process listings/logs), never logged at any level. The host-side `SecretStorePort` itself is never handed into the sandbox; only resolved values for that one run are. |
| 8 | **Result = untrusted → dual-LLM quarantine before reply** | `FetchSandbox.run`'s `FetchResult.output` is raw, capability-produced text — untrusted by the same logic as fetched web content (`fetch_sandbox.py`'s own docstring already flags this). Reuse the reachout `WebTool` quarantine shape (ADR-009, ADR-037 decisions 2–4): a no-tools reader validates/extracts, a synthesizer composes the reply — never feed raw capability output straight into a reply-generating model call. |

**Calling convention (pinned in spec #1):** a capability with a non-empty `inputs` schema receives its extracted args as **one JSON object string as the sole `argv` element** passed to `FetchSandbox.run` — landing at `sys.argv[1]` inside the child process (`python3 <entrypoint> <argv...>`, where `sys.argv[0]` is the entrypoint itself). A parameterless capability gets an empty `argv`, identical to today.

## Consequences

**Five specs, four build waves (file-disjoint per ADR-029 rules):**

| # | Spec | Prereq | Wave | Files (approx.) |
|---|------|--------|------|------------------|
| 1 | `invoke-inputs-schema` | none | **Wave 1** | `types.py`, `skill_md.py`, `store.py` |
| 4 | `invoke-sandbox-secrets-guard` | none | **Wave 1** (parallel with #1 — disjoint: `fetch_sandbox.py` / secrets wiring, no overlap with #1's files) | `fetch_sandbox.py` or a new secrets-injection module, cred-store call sites |
| 2 | `invoke-forge-inputs` | #1 | **Wave 2** | `forge.py` (`AUTHOR_SYSTEM`, `SKILL_DRAFT_SCHEMA`) |
| 3 | `invoke-route-selector` | #1 | **Wave 2** (parallel with #2 — disjoint: new selector module, `intent.py` untouched or additive only) | new `invoke_selector.py`-shaped module |
| 5 | `invoke-wiring-quarantine` | #2, #3, #4 | **Wave 3** | `api/ask_routes.py`, Telegram transport wiring, a quarantine module (adapted from `reachout/web_tool.py`'s reader/synth shape) |

Only spec #1 is drafted now (`docs/drafts/invoke-inputs-schema.md`, status: draft). Specs #2–#5 are scoped here for sequencing only; each gets its own spec doc when its prerequisites are done and it comes up for build.

**What this reuses, unchanged:**
- `FileCapabilityStore.retrieve(query, k, tags)` — the existing lexical shortlist (`store.py`); spec #3 calls it as-is, no new retrieval method.
- `FetchSandbox.run(capability_dir, entrypoint, argv, egress_domains, timeout_s)` — the existing execution primitive (`fetch_sandbox.py`); untouched signature. Spec #1 only pins how `argv` is built from typed args; it does not add a call site.
- `SecretStorePort` (`ports/secrets.py`) / `KeyringSecretStore` (`secrets_store.py`) — the existing keychain-backed cred-store (`cred-store` spec, shipped); spec #4 reads it for the missing-key guard and value resolution, never re-implements storage.
- The 5a/5b build-gate consent UI pattern (plan-card egress + missing-secrets cross-check + credential pending item) — spec #5's confirm-before-run screen is the same shape applied to invoke instead of build.
- The reachout `WebTool` dual-LLM quarantine (`web_tool.py`'s `_read`/`_synthesize`, ADR-009/ADR-037) — spec #5 adapts this shape for capability output instead of fetched web pages; it is **not** a shared module today (ADR-037 deferred extraction until a second consumer needs it) — spec #5 is that second consumer, so extracting a shared quarantine helper becomes an option at that point, not before.
- The intent router's dedicated-Haiku-port pattern (`ask_routes._intent()`, `ed3783e`) — spec #3's match-first LLM call is built the identical way: `IntentRouter`-shaped or a sibling `ModelClient(ClaudeCodeProvider(), model_default="haiku")`, never the shared `QuotaAwareRouter`.

**What is explicitly NOT built by this ADR:**
- No new `Route` literal value in `intent.py` for "invoke" — match-first is a pre-classifier stage (decision 2), keeping `classify()`'s contract stable for every existing caller.
- No migration of existing library capabilities — they simply have `inputs == []` and stay invokable as parameterless (decision 4).
- No shared quarantine module extraction ahead of need (mirrors ADR-037's own deferral) — spec #5 decides whether to extract from `web_tool.py` or write a smaller sibling, at build time.

## Alternatives considered

- **`inputs` as a fifth `Route` literal returned by `IntentRouter.classify`** — *rejected*. Would force every classify call (including ones with no promoted capabilities yet) through a heavier schema and couples capability-store state into the classifier's prompt. Match-first as a separate pre-step keeps `classify()`'s existing contract and tests untouched.
- **Freeform (untyped) args extracted from the request text** — *rejected* (locked decision). A typed schema declared at build time makes extraction a structured-output call against a known shape instead of a second unconstrained generation step, and lets the missing-key guard and confirm screen show concrete field values instead of an opaque string.
- **Auto-run on high-confidence match (skip confirm)** — *rejected*. Contradicts the locked "agency = ask, never auto" posture and ADR-012's confirm-on-expensive-action rule; every invoke shows the confirm screen regardless of match confidence.
- **Reuse the shared `QuotaAwareRouter` for the match-first pick, passing `model="haiku"` as an override** — *rejected*, this is the exact anti-pattern that broke the R3 classifier (`ed3783e`); decision 3 hard-pins a dedicated `claude_code` Haiku port instead.

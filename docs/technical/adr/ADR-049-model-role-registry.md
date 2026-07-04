# ADR-049 — Model-role registry: roles in code, models in config

- **Status:** **Accepted** — owner decision, 2026-07-04 (session 11, agent-loop model discussion).
- **Date:** 2026-07-04
- **Deciders:** owner
- **Refines:** ADR-047 (#3 fast-driver — "haiku-class" becomes a role binding, not a hardcoded
  model), the subscription-first doctrine (architecture.md §2), memory `ask-path-true-agent-loop`.
- **Driver:** the owner wants runtime models swappable from the client as the market moves
  (cheaper GPT tiers, local models good enough for haiku/sonnet-tier work) with observed cost
  per role — and the loop arc is about to multiply model call sites.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Roles in code, models in config** | Runtime code requests a ROLE (`loop_driver`, `extractor`, `phraser`, `judge`, `reader`, `synth`, `memory`, `forge_author` — the build-by-chat capability author + its self-correction retries; owner clarification 2026-07-04) — never a provider/model literal. A registry (config in the data dir) maps role → (provider, model). No new call site may hardcode a model name; existing dedicated-port sites migrate as touched. |
| 2 | **Owner-editable from the client** | Session-gated GET/PUT registry endpoint + a client settings panel (KeysPanel pattern). Changes take effect without restart (resolution at call time). |
| 3 | **Safety posture rides the ROLE, not the model** | Role bindings carry invariant constraints a swap cannot drop: `reader` is always no-tools; `extractor`/`judge` run temperature 0; `judge` must not resolve to the same binding as `loop_driver` (evaluator independence). The registry validates on write. |
| 4 | **Per-role metering** | Every role-resolved call records model, tokens, latency (and cost when a metered price exists) — the observability gap flagged 2026-07-04 closes here. Comparison across bindings ("haiku vs gpt-mini as extractor") is read from data, not guessed. |
| 5 | **Providers are interchangeable per role** | claude_code (Claude tiers), codex CLI `-m` (GPT tiers under the ChatGPT sub), ollama (local/internal). Subscription-first unchanged; metered API remains the explicit last-resort rung. |
| 6 | **Build-time (APEX) roles are config, not client-toggleable** | The construction crew is assigned in `docs/status.md` + per-session `/model`, outside the app. Owner assignment 2026-07-04: **reason=opus · orchestrate=sonnet (AFK hosts) · draft specs=opus · code=codex gpt-5.5** — revisited as models improve. |

## Consequences
- New spec precedes the agent-loop arc: `model-role-registry` (brain: registry + resolution +
  metering + endpoint) then a client settings panel spec. Loop specs consume roles only.
- The QuotaAwareRouter remains the `synth` role's binding (a role may bind to a chain, not just
  a single model).
- Defaults ship as today's de-facto assignments (haiku ports, codex-first synth) — zero behavior
  change until the owner toggles.

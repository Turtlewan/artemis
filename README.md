# Artemis

A multi-provider, subscription-first **agent harness** whose job is to let agents build the owner's
capabilities — you talk to Artemis, and it builds itself the tools to answer you.

> **v2 rebuild.** v1 (a local-first RAG "second brain") was scrapped and rebuilt from scratch on
> 2026-06-30; the v1 tree is preserved at git tag `archive/v1`. Active work lives on the
> `v2-rebuild` branch. Current state: `docs/status.md`.

## What it does

The core loop is **build-by-chat**: type a request in the desktop client's Ask popup (e.g. *"build me
a tool that shows today's calendar"*) and Artemis

1. **proposes** a capability (a coder model authors a `SKILL.md` + `tool.py`, declaring its inputs,
   network egress, and any secrets/OAuth scopes),
2. shows you a **plan gate** (what it will build + what it can reach),
3. **builds** it and **verifies** it in a WSL2-isolated sandbox (network-egress allowlisted, resource-capped),
4. **promotes** it into the capability library, and
5. **reuses** it — a later question is match-selected to the right capability, confirmed, run in the
   sandbox with any credentials injected, and answered.

Once built, capabilities are also driven proactively (a durable scheduler) and answered against a
local-first data store (external services are pull-only, read-only sources; the owner's system is the
source of truth).

## Architecture (thin spine, swappable ports)

- **Spine** — a small `plan → act → verify` loop over typed ports (model, sandbox, transport, memory, secrets).
- **Model layer** — an own `QuotaAwareRouter` over a subscription-first provider chain
  (`codex → claude_code → anthropic_api → ollama`; LiteLLM was rejected). Runtime code requests
  **roles**, not model names — an owner-toggleable registry binds each role to a provider/model
  (ADR-049), with safety posture (no-tools, temperature) riding the role.
- **Memory** — Cognee behind a `MemoryPort` (optional `memory` dependency group), with retrieval,
  consolidation, and decay over a durable ledger.
- **Capabilities** — a `SKILL.md` library plus MCP; authored, sandbox-verified, and promoted at runtime.
- **Sandbox** — a WSL2-isolated runner (egress IP-allowlist + resource caps) for anything externally
  authored or network-touching; untrusted output passes a dual-LLM quarantine.
- **Client** — a Tauri desktop app (a pannable spatial command-map) that pairs to the brain over a
  local HTTP + device-key session.

## Running it

Requires Python + [uv](https://docs.astral.sh/uv/); the sandbox and client need WSL2 and a Rust/Tauri
toolchain respectively.

```bash
uv sync
uv run artemis serve      # brain: FastAPI on 127.0.0.1:8030
uv run artemis            # always-on heartbeat (scheduler + proactive transport)
uv run artemis add|list|cancel|run   # scheduled-job CLI
```

Desktop app (Windows): double-click **`Launch Artemis.cmd`** (or run `scripts/launch-artemis.ps1`) —
it starts the brain and opens the client.

## Repository layout

- `src/artemis/` — the brain: `spine/`, `model/`, `memory/`, `agent/`, `capabilities/`, `oauth/`,
  `data/`, `reachout/`, `scheduler/`, `transport/`, `proactivity/`, `api/`, `ports/`.
- `client/` — the Tauri desktop client (`src/` TypeScript UI, `src-tauri/` Rust gateway).
- `evals/` — frozen eval corpora + offline scoring harnesses (not part of the default test suite).
- `docs/` — `status.md` (current state), `v2/architecture.md`, `v2/build-plan.md`,
  `technical/architecture/overview.md`, plus ADRs, specs, and handoffs.

## Development

```bash
uv run ruff format . && uv run ruff check .   # format + lint
uv run mypy                                   # type-check
uv run pytest -q                              # test suite (hermetic)
```

Client checks run from `client/`: `npm run typecheck`, `npm run lint`, `npm run test`, and
`cargo test` in `client/src-tauri`.

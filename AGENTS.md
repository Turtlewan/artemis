# AGENTS.md — Artemis v2 (Codex build instructions)

Standing instructions for the **Codex CLI** when building Artemis specs. Auto-loaded by Codex each
session. Builds run inside apex-code mechanic A (`codex exec -p apex-coder` subprocess, dispatched
per spec by the host session).

## What this repo is
Artemis **v2** — a multi-provider, subscription-first agent harness: a Python "brain"
(`src/artemis/`, FastAPI on 127.0.0.1:8030) + a Tauri desktop client (`client/`). Capabilities are
SKILL.md-packaged tools run in a WSL2 isolate. Specs in `docs/changes/` are self-contained
execution scripts. (v1 — the RAG second brain — is archived at tag `archive/v1`; ignore any
doc that mentions `openhands`, an `agentic` dependency group, or `/Users/artemis-build/` paths.)

## How to build a spec
When asked to implement `docs/changes/<name>.md`:
1. **Read the whole spec first**, including header banners (review rulings are folded into tasks).
   Implement `## Exact changes` precisely — signatures, file contents, edit locations.
2. **Surgical scope:** only create/modify files listed in the spec's `## Files to change` (or the
   dispatch prompt's scope line). `git diff --stat` must show only those files.
3. **Run the spec's `## Commands to run`** — the spec's commands are authoritative — and make
   every `## Acceptance criteria` item pass.
4. **Tests are the contract:** if a check fails, fix the *code* and re-run until green.
   NEVER weaken, skip, or delete a test to make it pass.
5. **Stop and ask** only if a spec's acceptance criteria cannot be met as written — that is a
   planning question. Note it precisely; do not improvise around the spec.

## Verify commands (brain default — the spec may extend these)
```
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q
```
- **Plain `uv sync`. There is NO `agentic` dependency group in v2** — `uv sync --group agentic`
  errors. Dev tools (mypy/pytest/ruff) are in `[dependency-groups]` dev; no extras flags needed.
- `uv run mypy` is strict over `files = ["src", "evals", "tests"]` (~169 files). Full
  `uv run pytest -q` runs ~600 tests in <1 min (`live`-marked tests are deselected by default).
- Client-half specs carry their own commands (tsc / eslint / vitest / cargo) — use exactly what
  the spec lists; do not invent npm script names.

## Sandbox environment quirks (do these FIRST, they hit every run)
- Default user cache/temp paths are permission-blocked in the Codex sandbox. Immediately redirect
  to workspace-local scratch: `UV_CACHE_DIR`, `TEMP`/`TMP`, and `TLDEXTRACT_CACHE`. Remove the
  scratch dirs when done (if deletion is policy-blocked, say so in the final report).
- **In-sandbox pytest may skip environment-dependent tests** (e.g. 13 skipped vs the host's 6).
  Do not chase the extra skips — the host re-runs the full recipe outside the sandbox as the
  arbiter. Report your counts honestly.
- **Never create `.venv` or `node_modules` inside the sandbox** — dependency installs are done by
  the host as the normal user (Windows sandbox-SID file-ownership rule). If a spec needs a new
  package, stop and report it instead of installing.

## Hard rules
- **Never `git commit`, never `git push`.** Build + verify only; leave work dirty for host review.
- **Sandbox:** builds run `--sandbox workspace-write`; stay repo-confined.
- **Baseline:** the host dispatches on a green baseline. If your first full verify is red in a way
  the dispatch prompt did not pre-authorize you to fix, stop and report — never build on red.
- **A dirty working tree is NORMAL** (concurrent host/docs work; this file forbids committing).
  Leave out-of-scope modified/untracked files strictly untouched; note them in the report.

## Project layout (v2)
- `src/artemis/api/` — FastAPI app + routes (auth handshake, ask, capabilities, oauth, secrets)
- `src/artemis/data/` — local data spine (ADR-046/048): `store` (generic record store),
  `ingest` (quarantine-at-ingest), `read` (local read + phrasing), `curate` (owner CRUD),
  `fetcher` (scheduled sync runner)
- `src/artemis/capabilities/` — forge (build-by-chat), store, select, WSL2 sandboxes
  (`sandbox_wsl2`, `fetch_sandbox`)
- `src/artemis/model/` — providers (codex / claude_code / anthropic / ollama), `ModelClient`,
  `QuotaAwareRouter` (subscription-first; per-provider schema down-conversion)
- `src/artemis/oauth/` — Google OAuth broker (loopback+PKCE, keychain-backed)
- `src/artemis/scheduler/` — durable scheduler + ledger; `src/artemis/reachout/` — web fetch/tool
- `src/artemis/memory/`, `src/artemis/ports/`, `src/artemis/expiry.py`, `src/artemis/types.py`
- `capabilities/builtin/` — git-tracked builtin capabilities (e.g. `calendar-sync`); the REST of
  `capabilities/` is runtime storage (gitignored, ruff-excluded — never lint or edit it)
- `client/` — Tauri desktop app (TS webview + Rust gateway in `client/src-tauri/`)
- `poc/` — spike PoCs (in lint scope but not production; don't touch unless spec'd)

## Conventions
- Python 3.12, fully typed — strict mypy must pass (pydantic.mypy plugin on). No untyped defs.
- Pydantic v2 at all IO boundaries; frozen models for value objects.
- Async I/O throughout (FastAPI + httpx; tests `asyncio_mode=auto`) — never block the event loop.
- `ruff` owns style (line-length 100) — let it; don't hand-format.
- Client DTO rule: every brain JSON field the client consumes needs a matching field in the Rust
  gateway structs (`client/src-tauri/.../gateway.rs`) — serde silently drops undeclared fields.
- Security invariants you must never relax in passing: raw external `payload` never reaches an
  LLM (only `sanitized_text`); quarantine readers are no-tools; secrets/OAuth tokens go to the
  isolate env only (never argv, never logs); guest-side decodes fail closed.

## Tests
- `tests/` mirrors `src/` (`tests/data/`, `tests/api/`, `tests/capabilities/`, …), `test_*.py`,
  `asyncio_mode=auto`. Hermetic by default: fake model ports (see `tests/data/test_read.py`),
  `httpx.MockTransport`, in-memory stores. `live`-marked tests need real services and are
  excluded by default — never required for a spec unless it says so.

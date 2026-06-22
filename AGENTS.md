# AGENTS.md — Artemis (Codex build instructions)

Standing instructions for the **Codex CLI** when building Artemis specs. Auto-loaded by Codex
each session. Companion to `docs/bring-up/CODEX-BUILD-RUNBOOK.md` (the full per-batch runbook).

## What this repo is
Artemis — a local-first personal assistant with a RAG second brain. The brain spine is pure
Python (`src/artemis/`), tested with `uv` + pytest + mypy + ruff. Specs in `docs/changes/` are
self-contained execution scripts.

## How to build a spec
When asked to implement `docs/changes/<name>.md`:
1. **Read the whole spec first.** Implement `## Exact changes` precisely — signatures, file
   contents, edit locations.
2. **Surgical scope:** only create/modify files listed in the spec's `## Files to change`.
   Touch nothing else. `git diff --stat` must show only those files.
3. **Run the spec's `## Commands to run`** and make every `## Acceptance criteria` item pass.
4. **Tests are the contract:** if a check fails, fix the *code* and re-run until green.
   NEVER weaken, skip, or delete a test to make it pass.
5. **Stop and ask** if a spec's acceptance criteria cannot be met as written — that is a planning
   question. Note it; do not improvise around the spec.

## Building a queue of specs
On **"build specs"** (or "build the queue" / "build docs/changes"): work through every spec in
`docs/changes/` (not `done/`):
1. **Dependency order** — honour each spec's `## Prerequisites`; if order is unclear, ask once then proceed.
2. **One spec fully at a time** — implement → run the verify recipe → green — before starting the next.
3. **STOP on the first failure** — if verify won't go green or a criterion can't be met, stop, leave the tree as-is, and report which spec + why. Never continue onto a red tree.
4. **After a spec passes, move it to `docs/changes/done/`** (a file move, not a commit).
5. **Never commit** (hard rule) — leave all built work dirty for owner review at the end.
6. **End with a summary** — specs passed, specs blocked, final verify status.

## Verify commands (run after each spec)
```
uv sync
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest -q
```
Green on all + correct `git diff --stat` = spec done.

## Hard rules
- **Never `git commit` and never `git push`.** Commits are owner-controlled. Pushing to `main` is
  a permanent hard block. Build + verify only; leave the working tree dirty for owner review.
- **Sandbox:** building needs `--sandbox workspace-write`. (Artemis's *runtime* use of Codex is
  read-only — that is a different mode, not for building.)
- **Baseline before building:** run the **full** verify recipe once first — **including `uv sync`** (it installs the `artemis` project + dev group); never run the `--frozen` check-only commands against an un-synced venv, since a missing project install reads as a **false red** (`ModuleNotFoundError: artemis`). If the baseline is genuinely **red**, stop and report — never build on a broken base. **Do NOT stop merely because the working tree has uncommitted changes** — that is the owner's normal state by design (this file forbids committing, so the tree is *expected* to be dirty). Note what is already modified, then proceed.

## Setup
`uv sync` installs the `artemis` project **and** the `dev` dependency-group (mypy/pytest/ruff) — it is
the first line of the verify recipe, so a normal verify run prepares the env. Dev tools live in
`[dependency-groups]`, **not** extras — do **not** use `--all-extras`.

## Project layout (src/artemis/) — ports & adapters (hexagonal)
Implement against ports; put concrete tech in adapters. A new integration = a new adapter implementing
an existing port — never leak tech (DB/HTTP/model SDK) into a port.
- `ports/`     interfaces only: `memory`, `retrieval`, `model`, `routing`, `voice`, `types`
- `adapters/`  concrete impls of ports (e.g. `model_adapters.py`)
- `memory/`    memory subsystem: `schema.py` (Pydantic models), `repository.py` (persistence)
- `knowledge/` RAG "second brain": `vector_store.py` (lancedb / sqlite-vec)
- `registry/`  capability/tool registry (`registry.py`, `index.py`)
- `tools/`     agent tools (e.g. `time_tool.py`)
- top level:   `api.py` (FastAPI), `brain.py`, `router.py`, `gateway.py`, `cli.py`/`main.py`
               (entrypoints), `config.py` (pydantic-settings), `manifest.py`, `heartbeat.py`, `paths.py`

## Conventions
- Python 3.12, fully typed — `mypy --strict` must pass (pydantic.mypy plugin on). No `Any` escapes, no untyped defs.
- Pydantic v2 for all models / IO boundaries; `pydantic-settings` for config — no scattered `os.getenv`.
- Async I/O throughout (FastAPI + httpx; tests `asyncio_mode=auto`) — never block the event loop.
- `ruff` owns style (line-length 100, import-order, naming, pyupgrade) — let it; don't hand-format.

## Tests
- Fast unit loop:  `uv run --frozen pytest -q -m "not integration"`
- Full (incl. integration, needs external deps):  `uv run --frozen pytest -q` (this is the verify-recipe default)
- Tests live in `tests/` as `test_*.py`, `asyncio_mode=auto`.

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
- Start from the last green state (121 tests). If the tree is dirty before you start, stop and say so.

## Dev-tools note
Until `uv-dependency-groups-migration` (spec 1) lands, bare `uv sync` may not install
ruff/mypy/pytest. Run `uv sync --all-extras` once before starting; after spec 1, bare `uv sync`
installs them.

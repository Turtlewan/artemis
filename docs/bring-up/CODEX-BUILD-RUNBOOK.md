# Codex Build Runbook — brain-Codex batch

_How to build the 5-spec brain-Codex batch using the **Codex CLI** (OpenAI, ChatGPT subscription)
as the coder, instead of Claude/DeepSeek. The specs in `docs/changes/` are self-contained execution
scripts, so Codex can read and execute them directly._

_Created 2026-06-22. Coder = Codex (`gpt-5.5`). Outside the APEX `apex-code` auto-orchestration —
you supervise each spec._

## Prerequisites

- **`codex` CLI installed** (verified working at `codex-cli 0.141.0`).
- **`codex login`** — authenticate against your ChatGPT subscription. (Heads-up: a 5-spec batch
  consumes Codex quota against the 5-hour / weekly caps — see ADR-022 § engine conditions.)
- **`uv` installed**, and run from the **same environment where `uv run pytest` already works** for
  this repo (WSL2, per the validation slice — confirm before starting).
- Start from the **last green state** (121 tests passing). `git status` clean.
- **Dev tools:** until spec 1 lands, bare `uv sync` may not install ruff/mypy/pytest. Run
  `uv sync --all-extras` **once** before starting; after spec 1 (the PEP 735 migration) bare
  `uv sync` installs them.

## Standing rules — `AGENTS.md` (repo root)
Codex auto-loads `AGENTS.md` from the repo root into every session. It holds the build rules
(surgical scope, tests-are-the-contract, never commit/push, stop-and-ask, verify commands) so the
driving prompt stays short. Added 2026-06-22. Edit it, not each prompt, to change standing behaviour.

## Important — sandbox mode

Building needs **write + command-exec**, which is the *opposite* of how Artemis *uses* Codex at
runtime (read-only). For building, run Codex with:

```
--sandbox workspace-write
```

Never use `--sandbox read-only` here (that's the runtime adapter's mode — it can't edit files).

## Build order (linear — each must be green before the next)

| # | Spec | Depends on |
|---|------|-----------|
| 1 | `uv-dependency-groups-migration` | — (do first) |
| 2 | `tooling-cleanup` | spec 1 |
| 3 | `codex-model-adapter` | — |
| 4 | `composite-model-routing` | spec 3 |
| 5 | `brain-sensitivity-routing` | spec 4 |

## Per-spec procedure

For each spec, in order:

### 1. Point Codex at the spec
Interactive (recommended — you watch it iterate on test failures):
```
codex --sandbox workspace-write -m gpt-5.5
```
…then give it this prompt (swap `<SPEC>` for the filename):
```
Implement the spec at docs/changes/<SPEC>.md exactly as written.
Rules:
- Only create/modify the files listed in its "## Files to change" section. Touch nothing else.
- Follow "## Exact changes" precisely — signatures, file contents, edit locations.
- Then run the commands in "## Commands to run" and make every item in
  "## Acceptance criteria" pass.
- If a check fails, fix the code and re-run until green. Do NOT weaken or delete tests to pass.
- Do NOT run `git push` and do NOT commit. Stop when green and show me `git diff --stat`.
```

Or one-shot (scriptable):
```
codex exec --sandbox workspace-write -m gpt-5.5 --skip-git-repo-check --color never \
  "Implement docs/changes/<SPEC>.md exactly; only the files it lists; run its Commands to run; make its Acceptance criteria pass; fix until green; no commit, no push."
```

### 2. Verify (independently confirm green)
```
uv sync
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest -q
```
All green + `git diff --stat` shows **only** the files the spec listed → spec is done.

### 3. Commit (you control commits — Codex must not)
Per the project's per-spec commit discipline:
```
git add <the spec's files by name>          # never git add -A
git commit -m "feat: <spec title>"          # or fix:/chore:
```
End commit messages with the project's Co-Authored-By trailer. **Never push to main** (hard block —
push to a branch + PR if you push at all). Then move the spec to `docs/changes/done/`.

### 4. Advance to the next spec.

## Autonomous one-shot mode (alternative to per-spec)
The per-spec procedure above is the supervised default. To build the whole batch in one go (Codex
walks all 5 in dependency order, verifying each before the next), launch interactively so you can
watch, then give it the batch prompt. `AGENTS.md` supplies the rules; commits stay owner-controlled.

```
codex --sandbox workspace-write -m gpt-5.5
```
Prompt:
```
Build these 5 specs in this exact order, each fully green before starting the next:
1. docs/changes/uv-dependency-groups-migration.md
2. docs/changes/tooling-cleanup.md
3. docs/changes/codex-model-adapter.md
4. docs/changes/composite-model-routing.md
5. docs/changes/brain-sensitivity-routing.md

For each spec: implement only the files it lists, run its Commands to run, make every
Acceptance criterion pass, and fix the code (never the tests) until green. Follow AGENTS.md.
Do NOT commit and do NOT push at any point. After all 5 are green, show me the full
`git diff --stat` and a per-spec summary. If any spec's acceptance criteria can't be met
as written, stop and tell me which one and why — don't skip ahead.
```
Trade-off vs supervised: no human gate between specs, so you review the full diff + commit per-spec
at the end instead of between each. A spec that can't meet its AC surfaces as a stop-and-report.

## Scope & safety rules

- **Surgical:** every spec names its exact files; hold Codex to them (`git diff --stat` is the check).
- **Tests are the contract:** if Codex can't make a test pass, it fixes the *code*, never the test.
- **No push, no force, no main-branch surprises** — you commit; Codex builds + verifies only.
- **Stop-and-ask** if a spec's acceptance criteria can't be met as written — that's a planning
  question (note it, don't let Codex improvise around the spec).

## Bonus — cross-model review is satisfied for spec 5

`brain-sensitivity-routing` is `cross_model_review: true` (wants a second model *family* to check it).
Its spec was planned + reviewed on the **Claude** family (apex-security + apex-python). Building it on
**Codex/GPT** gives exactly that cross-family diversity — Claude designed/reviewed, GPT implements. The
intent of the flag is met by this split.

## After the batch

You'll have: the Codex runtime adapter + composite cloud/local routing + the local-model sensitivity
gate — all built and tested green. Next is **running it** (Ollama local models + config wiring →
`uv run python -m artemis.cli`); see the Phase-2 steps. The `codex login` you did here also unlocks
Artemis's live cloud-reasoning path later.

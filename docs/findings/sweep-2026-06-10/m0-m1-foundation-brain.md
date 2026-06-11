# Sweep findings — M0 foundation + M1 thin brain (2026-06-10)

**Scope:** M0-a..f, M1-a..d. Cross-checked against ADR-001, ADR-002, BRING-UP-RUNBOOK, SECRETS-INVENTORY.
**Counts:** BLOCK 11 · UPGRADE 6 · FLAG 14 · RESEARCH 5

---

## BLOCK

### B1 — `.gitignore` does not ignore the secret-bearing slot env files
**M0-a Task 1** (`.gitignore`: "ignore `.venv/`, `__pycache__/`, `*.db`, `*.sqlite*`, `.env`, local data roots") vs **M0-f Assumptions** ("The repo `.gitignore` (VERIFIED) ignores the secret-bearing slot files via `.env` + `.env.*` while keeping the examples tracked via `!.env.*.example`").
The pattern `.env` does NOT match `config/.env.dev` (filename is `.env.dev`). M0-a as written never adds `.env.*` or `!.env.*.example` — nothing exists yet, so M0-f's "VERIFIED" is verified against nothing. As specced, `config/.env.<slot>` (Brave/Tavily/Google secrets, ntfy topic secret) is committable. **Fix:** amend M0-a Task 1 to the exact patterns `.env`, `.env.*`, `!.env.*.example`; add an acceptance check (`git check-ignore config/.env.dev` exits 0).

### B2 — `ModelPort` has no streaming return type; M1-b requires one
**M0-d Task 4** defines `ModelPort.complete(...) -> ModelResponse` (a frozen dataclass) even when `stream=True`. **M1-b Task 2** (`respond_stream`: "call `model.complete(role=..., stream=True)` and yield each text segment as it arrives") and **M1-b Task 4** ("FakeModelPort returns an async iterator of segments when `stream=True`") require `complete` to return an iterator of segments — which violates the M0-d protocol and cannot pass `mypy --strict` with the structural `_check: ModelPort = FakeModelPort()` assertions. **Fix:** amend M0-d `ModelPort` with an explicit streaming method, e.g. `def complete_stream(self, role, messages, *, response_schema=None) -> AsyncIterator[str]: ...` (or an overload on `stream:`), and update M1-b Tasks 2–4 to call it.

### B3 — Router needs the top cosine score; M1-a exposes no score and M1-b may not touch `registry.py`
**M1-a Task 3:** `retrieve_tools(query, k) -> list[str]` returns fq ids only — no scores. **M1-b Task 1** needs "the top cosine score" to threshold the route and says "extend the registry call OR re-search the index — prefer reusing M1-a's `InMemoryToolIndex.search`". But (a) `registry.py` is NOT in M1-b's Files to Change (surgical scope lock blocks "extend the registry call"), and (b) the registry's index + embedder are internal — the spec never says `ToolRegistry` exposes them. A literal executor has no compliant path. **Fix:** amend M1-a Task 3 to add `retrieve_tools_scored(self, query: str, k: int = 3) -> list[tuple[str, float]]` (or expose `self.index`/`self.embedder` as read accessors), then make M1-b Task 1 call that method by name.

### B4 — `{MLX_PORT}` placeholder in `roles.toml` has no substitution mechanism
**M0-c Task 3:** "set every `adapter = "openai"` role's `endpoint` to `http://127.0.0.1:{MLX_PORT}/v1` (keep `{MLX_PORT}` as a render placeholder so render_plists/Settings substitute per slot; if Settings needs a concrete value, resolve via the slot's `mlx_port`)". `render_plists.py` (M0-b Task 5) renders *plists*, never `roles.toml`; M0-a Task 3's `Settings` validator does a plain `tomllib.load` with no interpolation step specced. Result: `base_url_for_role("responder", s)` returns the literal string `http://127.0.0.1:{MLX_PORT}/v1` — M0-c Task 7's test ("ends with `/v1`") still passes, M0-a's acceptance print shows a non-URL, and M1-b's live adapter calls an invalid URL. **Fix:** spec the interpolation exactly — e.g. M0-a's roles validator replaces the token `{MLX_PORT}` with `str(self.mlx_port)` after `tomllib.load` — and add a test asserting no `{` remains in any endpoint.

### B5 — `pipeline.sh` integration stage fails: pytest exits 5 when no tests are collected
**M0-b Task 6:** "`uv run pytest -q -m integration` (integration; passes vacuously in M0 — no integration tests yet)". pytest exits with code **5** ("no tests collected") when `-m integration` matches nothing; under `set -euo pipefail` the pipeline aborts on its very first run. **Fix:** spec the stage as `uv run pytest -q -m integration; rc=$?; [ "$rc" -eq 0 ] || [ "$rc" -eq 5 ] || exit "$rc"`, and register the `integration` marker in `pyproject.toml` (`[tool.pytest.ini_options] markers`) so `--strict-markers` doesn't fail later.

### B6 — Backup retention cannot delete `uchg`-immutable snapshot dirs
**M0-e Task 4:** snapshots are made immutable (`chflags uchg`) AND "apply retention (keep last N, default 7)". Deleting an immutable directory fails on macOS; the script errors at the first retention cycle (day 8). The spec never says to clear the flag before pruning. **Fix:** spec retention as `chflags -R nouchg <dir>` then `rm -rf <dir>` for pruned snapshots only; add a test that creates N+1 fake snapshots, runs retention, and asserts the oldest is removed.

### B7 — `compose_brain` "no network at construction" contradicts registration-time embedding; CLI acceptance fails off-hardware
**M1-c Task 1 done-when:** "`compose_brain(get_settings())` returns a `Brain` without contacting any network". But `compose_brain` registers M1-d's time-tool manifest, and **M1-a Task 3** `register()` *embeds each tool description via the EmbeddingModel* — with the real `OpenAIEmbeddingModel` that is an HTTP call to a server that doesn't exist off-hardware. Likewise **M1-c Acceptance 3** (`printf 'what time is it\n/quit\n' | uv run python -m artemis.cli` → "exit 0 either way"): `router.route` embeds the request *before* Brain's try/except (M1-b Task 2 wraps only tool dispatch), so a dead embedder raises out of `respond` and the CLI exits non-zero. **Fix options (pick one in the spec):** make registry embedding lazy (embed on first `retrieve_tools`), or make `compose_brain`/the CLI catch connection failures and degrade to the escalate stub, or downgrade the CLI smoke to a GATED on-hardware check.

### B8 — `inject_env.py` Settings circularity + the "Settings fails LOUD" layer doesn't exist
**M0-f Task 1/main:** "Resolve the slot `Settings`" to derive the env-file path; **M0-f Assumption:** "M0-a's pydantic `Settings` raises a validation error at construction [when a required secret is missing]". Two problems: (a) **M0-a Task 3's `Settings` declares no secret fields at all** (slot, data_root, ports, roles only) — no spec ever adds `BRAVE_API_KEY` etc. as Settings fields, so the loud-failure layer M0-f's `--allow-missing` design "relies on" does not exist anywhere in the corpus; (b) if a later spec DOES add them as required fields, `inject_env.py`'s own `get_settings()` call fails *before* injection (the secrets aren't in the env file yet) — a hard bootstrap circle. **Fix:** decide and spec it: either resolve the env path without full Settings (a slot→path function that doesn't validate secrets), and add a separate spec/task that adds the six vars to `Settings` as required fields consumed by daemons only — or drop the "Settings fails LOUD" assumption and spec daemon-side validation explicitly.

### B9 — Three contradictory candidates for the slot `.env` path; `{ENV_FILE}` never defined
**M0-f Assumptions** say the env file is `config/.env.<slot>` (matching RUNBOOK Step 4 and M0-a Task 7), but the same assumption offers the example resolver "`paths.slot_root(settings) / ".env"`" (= `/opt/artemis/<slot>/.env` — a different file), and **M0-f Security** says the file sits "in the owner-private slot dir behind FileVault" (a third location; `config/` is in the build agent's repo, not the data root). Meanwhile **M0-b Task 5** lists `{ENV_FILE}` among render_plists' resolutions but never states the expression, and **M0-a Task 4's `paths.py` has no `env_file()` function** to reuse. The "use the SAME resolver" instruction points at a resolver that is nowhere defined. **Fix:** define it once — add `env_file(s: Settings) -> Path` to M0-a `paths.py` returning the chosen canonical location, make M0-b Task 5 use it for `{ENV_FILE}`, and make M0-f reference that function by name. Note the security trade-off when choosing: `config/.env.<slot>` lives inside `/Users/artemis-build/artemis` (the sandboxed build agent owns the parent dir and can delete/replace the file even at `0600`); the data-root location keeps secrets out of the build tree but contradicts the runbook. Resolve explicitly.

### B10 — Single shared working tree for all slots contradicts ADR-002; `--rollback` flips every slot
**M0-b Tasks 2/7:** all slots' plists template `WorkingDirectory {REPO_DIR}` (the one checkout at `/Users/artemis-build/artemis`), and rollback = "`git checkout artemis-prod-prev`, re-render, re-bootstrap". **ADR-002** locks "three roles/slots on one box (**separate logins/dirs**/ports/data)". With one working tree: promoting or rolling back PROD checks out a different commit under dev/uat's running daemons too (their next restart silently runs PROD's rolled-back code), and `git checkout` over a dirty dev tree can fail or destroy in-progress work. **Fix:** spec per-slot checkouts (e.g. `git worktree add /opt/artemis-app/<slot> <ref>` or per-slot clone dirs) as the plists' `WorkingDirectory`, with deploy.sh promoting by updating the target slot's worktree only.

### B11 — Client-side "apply Outlines" in an HTTP adapter is not implementable
**M1-b Task 3:** "`complete(...)` calls the OpenAI-compatible `/v1/chat/completions`; when `response_schema` is provided, apply **Outlines** constrained decoding" + Commands `uv add outlines`. Outlines constrains decoding at the *logits* level — it can only run inside the inference server, not in an HTTP client. M0-c's own assumption states the server side correctly ("OpenAI `response_format` JSON-schema + Outlines for structured output" — i.e. mlx-openai-server uses Outlines internally). A literal executor cannot bridge this. **Fix:** respec Task 3 as: map `response_schema` → the request body field `response_format={"type":"json_schema","json_schema":{"name":...,"schema":response_schema,"strict":true}}`; drop `uv add outlines` from M1-b (the dependency belongs to the server install, M0-c); keep the "no retry loop" contract.

---

## UPGRADE

### U1 — Don't launch daemons via `uv run`; use the venv binaries directly
**M0-b Task 2** (`ProgramArguments` = `{UV_BIN} run uvicorn ...`). Under a LaunchDaemon with `UserName`, `HOME`/cache env is minimal; `uv run` resolves/syncs the environment on every start (cache dir lookups, potential network). More robust + faster crash-restart: `{REPO_DIR}/.venv/bin/uvicorn artemis.main:app --host 127.0.0.1 --port {BRAIN_PORT}` (same for `mlx-openai-server` in M0-c Task 3). If `uv run` is kept, the plists must set `EnvironmentVariables` `HOME` (and `UV_CACHE_DIR`) explicitly.

### U2 — Use FastAPI lifespan, not `@app.on_event("startup")`
**M1-c Task 4** offers "`@app.on_event("startup")` or a lifespan". `on_event` has been deprecated since FastAPI 0.93 and emits warnings (or is removed) on 2026 FastAPI versions. Spec the lifespan form exactly (`@asynccontextmanager async def lifespan(app): app.state.gateway = ...; yield`) so the literal executor doesn't pick the deprecated branch.

### U3 — `Scope = Literal[...] | str` collapses to `str`
**M0-d Task 1.** A union of a `Literal` with `str` is just `str` to mypy — the literal adds zero type safety and may draw a ruff/mypy redundancy warning. Spec it as `Scope = str` with the validation rule documented (and enforced at runtime by `paths.scope_dir`'s `ValueError`), or a `NewType("Scope", str)` for at least nominal discipline.

### U4 — Install `mlx-openai-server` isolated from the brain venv
**M0-c Task 1** (`uv add "mlx-openai-server==1.8.1"`). Pulling the inference server (mlx, mlx-lm, outlines, large transitive pins) into the brain's project venv couples two unrelated dependency trees — a server-side pin conflict would block brain dependency upgrades. Within-stack improvement: `uv tool install "mlx-openai-server==1.8.1"` (own isolated venv, stable bin path for the plist) or a second uv project under `deploy/mlx/`. The plist's `{MLX_LAUNCH_CMD}` then points at the tool binary.

### U5 — Two of M1-b's three thresholds do the work of three
**M1-b Task 1 / Assumptions:** decision rule "≥0.6 → deterministic; ≥0.35 → local; <0.15 → escalate; otherwise → local" makes the 0.15–0.35 band identical to the 0.35–0.6 band — `route_local_threshold` is dead. Either drop it (two thresholds: deterministic ≥0.6, escalate <0.15, else local) or give the middle band distinct behaviour. As written a senior engineer would call the third threshold speculative config.

### U6 — Restore-in-place procedure is referenced but never specced
**M0-b Task 7** rollback says "restore the pre-promote backup"; **M0-e** ships only `restore_test.sh` (restore *to scratch*); RUNBOOK Step 12 says "follow M0-e's restore procedure to restore in place" — which doesn't exist. Add the in-place restore mode (`restore.sh --slot <s> --snapshot <ts>` stopping the slot daemons, copying snapshots back, clearing `uchg` on copies, integrity-checking) to M0-e or a follow-up spec, and have deploy.sh `--rollback` call it by name.

---

## FLAG

### F1 — Rendered plist filename convention unspecified
**M0-b Task 5** says render to `deploy/launchd/rendered/{slot}/` but never names the output files; **Task 8**, **M0-e Task 7**, and **RUNBOOK Steps 6d/8a/8c** all assume `com.artemis.<slot>.<svc>.plist`. A literal executor may write `com.artemis.brain.plist` (template name minus `.template`), breaking every downstream command. Spec the output name exactly: `com.artemis.{slot}.{service}.plist`.

### F2 — "extend render_plists.py OR a direct render" — pick one
**M0-e Task 5** leaves the backup plist render path as an either/or; RUNBOOK Step 8a expects `render_plists.py --slot dev` to emit the backup (and broker) plists in one pass. Spec: extend `render_plists.py` to include `com.artemis.backup.plist.template`, and add the file to M0-e's Modify list properly (it currently lives in a parenthetical note).

### F3 — M0-c internal naming drift: "mlx.toml" / "resident flags"
**M0-c Specialist Context → Performance** says "Encoded as `resident` flags in mlx.toml"; the actual artifact is `config/mlx-models.yaml` with `on_demand` keys (Task 2). Harmless to humans, but a literal executor cross-reading sections may create a second file. Align the wording.

### F4 — M0-c Task 4 pulls 2 models; the YAML and the runbook list 4
`mlx-models.yaml` (Task 2) declares 4 models; gated Task 4 downloads only responder + embedder; RUNBOOK Step 8b pulls all 4 (incl. reranker + Qwen3.6-27B, ~18GB). If mlx-openai-server validates `model_path` existence at startup, the daemon crash-loops with 2 of 4 present. Either Task 4 pulls all four, or the spec states the server tolerates absent `on_demand` paths until first load (→ R1).

### F5 — `model_dir: "${ARTEMIS_MODEL_DIR}"` env expansion is unconfirmed; the mlx plist sets no env
**M0-c Task 2** puts a shell-style env reference inside YAML; nothing establishes mlx-openai-server expands `${...}`, and the M0-b mlx plist template's `EnvironmentVariables` carries only `ARTEMIS_ENV_FILE` (brain plist; the mlx template doesn't specify any). Either render the concrete path into the YAML per slot, or spec `EnvironmentVariables ARTEMIS_MODEL_DIR` in the mlx plist AND confirm expansion (→ R1).

### F6 — M0-d `__init__` re-export list must name `RouteDecision` + `ModelResponse`
**M0-d Task 6** says re-export "every type + every Protocol", but `RouteDecision`/`ModelResponse` live in `routing.py`/`model.py`, not `types.py` — a literal executor exporting "types.py types + the 13 Protocols" misses them, and **M1-b Assumptions** import `RouteDecision`/`ModelResponse` from `artemis.ports`. Enumerate the full `__all__` in the task.

### F7 — `deploy.sh` first run: `git diff artemis-prod-prev..HEAD` fails when the tag doesn't exist
**M0-b Task 7** step (1) diffs against `<prev-prod-tag>` to detect risky files, but the tag is only created in step (5) — on the first-ever deploy the diff fails under `set -e`. Spec the fallback: if the tag is absent, treat the change set as risky (or diff against the empty tree).

### F8 — `Capability` enum is defined and never used
**M1-a Task 1** defines `Capability(StrEnum)` OWNER/GUEST, but `Permissions` uses plain bool fields. Dead code at birth; drop it or use it as the `Permissions` key type.

### F9 — Two scope vocabularies with no mapping
**M0-d** `Scope` values: `owner-private`, `general`, `guest-<id>` (storage partition). **M1-a** `DataScope`: `owner-private`, `guest-visible`, `shared` (module classification). `shared`/`guest-visible` vs `general` are never mapped, and M1-d's time tool ships `DataScope.SHARED`. Fine in M1 (nothing enforces it), but the mapping must be written down before M2 enforcement; add one line to M1-a stating the intended correspondence.

### F10 — M1-c Task 3 describes both the pyproject script entry and the `python -m` form
The PREFER clause is present, but a literal executor reading the first half may still edit `pyproject.toml` (and the Acceptance + Commands use `python -m`). Delete the `[project.scripts]` sentence; keep only the `python -m artemis.cli` + `if __name__ == "__main__":` instruction.

### F11 — M1-b Task 5 conditional dependency gating is executor-hostile
"Add `outlines` + the OpenAI client dep via `uv add` ... IF the off-hardware suite can run without importing them; otherwise add them in Task 3 behind a lazy import" — a literal model can't evaluate this. Decide now (and per B11, `outlines` drops out entirely; the HTTP client — `httpx`, already a FastAPI/TestClient transitive — or `openai` should be added unconditionally in Task 3 with lazy import inside the adapter).

### F12 — "not byte-identical to a naive cp" is not a reliable proof VACUUM INTO ran
**M0-e Task 6.** A vacuumed copy of a tiny fresh DB can legitimately be byte-identical to the source, and the parenthetical "compare via opening + integrity_check" doesn't establish non-identity either. Replace with a deterministic check: create the source with a deleted row / free pages, assert the snapshot's file size < source, or assert `PRAGMA freelist_count` == 0 in the snapshot.

### F13 — "text contains a parseable ISO timestamp" needs a concrete assertion
**M1-d Task 4** (and M1-b Task 4's "contains the fixed time"): spec the runnable form, e.g. `re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r.text)` then `datetime.fromisoformat(match)`. As written, executors invent inconsistent checks against the `f"{return_model}"` repr rendering.

### F14 — SECRETS-INVENTORY P2 (ntfy secret mechanism) is resolved by M0-f but still parked
M0-f locks S11 to the slot `.env` (generated + preserved), which answers inventory **Parked P2** ("slot `.env` vs separate Keychain slot") — but only P1/P5 were marked resolved. Mark P2 resolved → M0-f to keep the parked table truthful.

### F15 — `backup.sh --slot test` uses a slot name outside the dev/uat/prod set
**M0-e Tasks 4/6 + Acceptance** invoke `--slot test`. Bash doesn't care, but everywhere else `slot` is `Literal["dev","uat","prod"]` (M0-a Task 3); if backup.sh ever validates the slot against the known set (a natural hardening), the test breaks. Spec either that backup.sh accepts arbitrary slot strings, or use `--slot dev` with a tmp data-root in the test.

---

## RESEARCH

### R1 — Pin-verify mlx-openai-server 1.8.1 facts before M0-c executes
The spec pins several CLI/config facts that must be confirmed against the real 1.8.1 release (the executor cannot adapt): (a) `--config <yaml>` multi-model launch flag and the YAML schema key names (`model_dir`, `models[].model_id/model_path/on_demand/on_demand_idle_timeout`, `tool_call_parser`); (b) `--version` flag exists (Task 1 prints it); (c) importable module name (`mlx_openai_server` — Task 1's done-check hedges "or the confirmed module name"); (d) whether `--host/--port` CLI flags override YAML `host/port`; (e) env-var expansion inside the YAML (F5); (f) startup behaviour when an `on_demand` model path is absent (F4); (g) the weight-pull mechanism (RUNBOOK Parked P5).

### R2 — mlx-openai-server `response_format: json_schema` support shape (pre-M1-b)
B11's fix routes constrained decoding through the OpenAI `response_format` field. Confirm 1.8.1's exact accepted shape (`{"type":"json_schema","json_schema":{...,"strict":true}}` vs `{"type":"json_object"}+schema`) and that it applies Outlines server-side for the qwen3 parser, so M1-b Task 3 can spec the literal request body.

### R3 — Claude Code OS-sandbox config schema (RUNBOOK Parked P2, M0-e Task 2)
Already parked; restating because M0-e ships a JSON whose filename/schema is invented. Before the on-hardware gate, capture the installed Claude Code version's actual sandbox/permissions schema (settings.json `permissions`+`sandbox` keys as of mid-2026) so Task 7 is an apply, not a redesign.

### R4 — `security find-generic-password` ACL behaviour in the M0-f context
Items created by the `security` CLI are normally readable by `security` without a GUI prompt, but confirm on macOS 26: (a) no per-item prompt when `inject_env.py` shells out from an SSH (non-GUI) owner session with the login keychain unlocked; (b) behaviour when the session is SSH-only and the keychain is locked (`security unlock-keychain` step may need adding to RUNBOOK Step 5).

### R5 — Embedder dimension source for `OpenAIEmbeddingModel.dimension`
**M1-b Task 3** says "read once from the first embedding or a config constant" — an either/or the executor must not choose freely, and M0-d's `EmbeddingModel.dimension` docstring says the dimension is "locked in store metadata". Decide: add `embedding_dimension: int` to Settings/roles.toml (Qwen3-Embedding-0.6B = 1024) or spec the lazy first-call probe explicitly, and record which one M3/M4's LanceDB schema will trust.

---

## Cross-checks that PASSED (for the record)

- Port plan (brain 8030–32 / mlx 8040–42 / ntfy 8050–52 / audio 8060–62) consistent across M0-a Task 7, M0-b Task 8, M0-c, RUNBOOK Step 4.
- Repo path `/Users/artemis-build/artemis` and data root `/opt/artemis` consistent across all six M0 specs and the runbook.
- M0-f Keychain item map exactly matches SECRETS-INVENTORY S1/S2/S4/S5/S6/S7 service/account names; required/optional split matches the runbook's "S1/S2/S4/S5 minimum".
- Tiered-secrets invariant held: S3 (HIGH) nowhere in any M0/M1 spec's env handling; no secret values in plists (only `ARTEMIS_ENV_FILE` path); M0-f never logs values and discards `security` stderr; ntfy topic secret preserve-not-rotate is consistent between M0-f and the runbook.
- M0-d's 13 Protocol names match M1-a/M1-b/M1-c import expectations (modulo F6); `MemoryStore` carries `person_id`+`as_of` per ADR-004; `AsOf` decision recorded.
- M1-c's `artemis.tools.time_tool.manifest` contract matches M1-d's module path + factory name exactly.
- M1-a/M1-b/M1-d fake-embedder and FakeModelPort test patterns are mutually consistent (modulo B2's streaming shape).
- launchd modern API (`bootstrap`/`bootout`), `plutil -lint`, `stat -f '%Lp'`, `chflags uchg`, `sysadminctl` usage all correct for macOS.
- Simplicity posture is generally good: Protocol-not-ABC, no LangGraph, asyncio-not-APScheduler heartbeat, stdlib-only cosine index are all appropriately minimal. The only over-engineering candidates found are U5 (third router threshold) and F8 (unused `Capability` enum).

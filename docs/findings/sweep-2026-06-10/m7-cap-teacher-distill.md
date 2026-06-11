# Sweep findings — M7 teacher/recipe loop + CAP distillation pipeline (2026-06-10)

Scope: M7-a1, M7-a2, M7-a3, M7-b, M7-c, distill-datagen-pipeline. Cross-checked against M8-d-c2, CLIENT-b, OBS-b, M0-d, M1-b, ADR-003.

Severity counts: **BLOCK 5 · UPGRADE 6 · FLAG 12 · RESEARCH 3**

---

## BLOCK

### B1 — `_resolve_teacher_is_cloud` depends on a ModelPort capability that does not exist
**File:** `docs/changes/M7-a2-escalation-distill-replay-brainseam.md` — Task 1 + Assumption 4.
Task 1 requires `def _resolve_teacher_is_cloud(model: ModelPort) -> bool` described only as "a small capability the `ModelPort`/config exposes". M0-d (`M0-d-ports-scaffolding.md`) defines `ModelPort` with no such method/attribute, and no spec amends the port. This is the **load-bearing privacy guard** (`CloudEgressForbiddenError`) — DeepSeek cannot invent the seam. Fix: either (a) add an explicit optional capability to the spec (e.g. a `ResolvesAdapter` Protocol with `def is_cloud(self, role: str) -> bool` that adapters/`SpyModelPort` satisfy, checked via `isinstance`/`getattr` with a stated default), or (b) pass an explicit `teacher_is_cloud: bool` (from config/composition) into `escalate_and_distill`. Must be exact in the spec.

### B2 — "enqueue an EscalationRequest": no queue exists anywhere
**File:** `docs/changes/M7-a2-escalation-distill-replay-brainseam.md` — Task 4 (Brain seam), Files to Change.
Task 4(c) says "return a typed `ESCALATION_QUEUED` BrainResponse **and enqueue an `EscalationRequest`**". No queue type, persistence, file, or consumer is defined in M7-a2 or any other spec (grep across `docs/changes/` finds no EscalationQueue; OBS-a/OBS-b record escalation *telemetry events*, which is a different artifact). The "owner-gated / Curiosity-driven" consumer is never named. A literal executor will invent storage or silently drop the request. Fix: either define a minimal persisted queue (file + dataclass + `list/pop` API) with its consumer named, or delete the enqueue clause and state that the escalation is recorded only via the OBS-a telemetry tap (which M7-c's gap scan already consumes) — the latter is simpler and probably the intended design.

### B3 — Nobody wires `Promoter.note_occurrence` into the Brain escalate path
**Files:** `docs/changes/M7-b-promotion-policy-review-surface.md` — Assumption 3 ("`note_occurrence(task_class_key)` is called from the Brain escalate path (M7-a2)") vs `docs/changes/M7-a2-...md` — Task 4, which never mentions `note_occurrence` (and cannot — M7-a2 builds before M7-b exists). M7-b's Files to Change does not modify `brain.py`. Result: the N≥2 recurrence promotion **never fires** for teacher-escalation recipes — the core M7-b mechanism is dead code for its primary input. (M8-d-c2 wires it only for capture-pattern keys.) Fix: add a task to M7-b (or a follow-up wiring spec) that adds an optional `Promoter` ctor param to `Brain` and calls `note_occurrence(key)` in the escalate branch when a CANDIDATE exists for the key, with a test.

### B4 — Multi-version recipe semantics undefined; M7-a3's superseded rule is unimplementable against M7-a1's name-keyed API
**Files:** `docs/changes/M7-a1-recipe-format-store-signing.md` — Task 2 (`RecipeStore`) · `docs/changes/M7-a3-dedupe-retire.md` — Task 1 (superseded rule), Task 3 (test).
- M7-a1 persists `{name}@{version}.skill.md` (multiple versions of one name can coexist on disk) but `set_status(name, status)` and the index id (`ids=[recipe.name]`) are **name-keyed** — there is no way to retire a *specific version*. `list()` behavior over multiple versions of one name (all? latest-per-name?) is unspecified.
- M7-a3's superseded rule ("higher `version` retires the lower" for the same `task_class_key`) presupposes version-targeted retire. If the duplicate versions share a name, `set_status(name, RETIRED)` loads the **latest** version — retiring the wrong one (or both, depending on `list` semantics). The Task 3 acceptance test ("version 0.2.0 retires 0.1.0") doesn't say whether the two share a name, so the executor may write a test that passes on the easy case (distinct names) while the common real case (re-distilled same-name recipe) misbehaves.
- "Load latest (or given) version" in `get` has no defined ordering; lexicographic comparison breaks at `0.10.0` vs `0.9.0` (also poisons M7-a3's tiebreaker "lower version string").
Fix in M7-a1: define `list()` = latest-version-per-name (or all, explicitly), define version ordering as parsed numeric tuple `tuple(int(x) for x in v.split("."))`, and either give `set_status` a `version=` param or state that superseded-version cleanup = **deleting/archiving the lower-version file**, then restate M7-a3's superseded rule against that exact API.

### B5 — distill-datagen writes datasets to `tools/distill/datasets/`, contradicting Resolved seam P3
**File:** `docs/changes/distill-datagen-pipeline.md` — Task 5 (`PipelineConfig.output_dir = Path("datasets/distill")`), Commands to Run ("From tools/distill/"), Acceptance ("`uv run distill --dry-run ... --output-dir datasets/distill`").
P3 resolves the dataset home as **repo-root** `datasets/distill/`, Git-tracked. But every command is run from `tools/distill/` with a *relative* default, so output lands at `tools/distill/datasets/distill/` — a different, untracked location. A literal executor will follow the commands exactly and "pass" while violating P3. Fix: resolve the default against the repo root (e.g. `Path(__file__).resolve().parents[3] / "datasets" / "distill"`, or require `--output-dir` absolute in the documented commands), and add the P3 `.gitignore` check (`!datasets/`) as an explicit task — it currently has no owner.

---

## UPGRADE

### U1 — `set_status`/`list` skip signature verification; `set_status` re-signs (launders) a tampered on-disk recipe
**File:** `docs/changes/M7-a1-recipe-format-store-signing.md` — Task 2.
Only `get` is specified to verify. `set_status` = "load, mutate status, re-write (re-sign...)" — if "load" doesn't verify, a file tampered on disk gets **re-signed with a fresh valid HMAC** the moment status flips (e.g. M7-b `_auto_promote` → ENABLED via `set_status`), defeating verify-on-load. `Promoter._auto_promote` also reads via `store.list(status=CANDIDATE)` (unverified). Amend: `set_status` MUST load via `self.get(name)` (verified), and `list` verifies each loaded recipe (skip-or-raise on mismatch — state which). One sentence each; closes the only real hole in the signing chain. (Positive: `Promoter.promote` already verifies via `get`, and M8-d-c2's third-author `RecipeStore.write` is fully supported — write signs any caller's recipe.)

### U2 — claude-cli adapter should reuse the already-verified `--output-format json` interface
**File:** `docs/changes/M7-a2-...md` — Task 7 vs `docs/changes/distill-datagen-pipeline.md` — Resolved seam P1.
P1 *verified on 2026-06-09*: `claude -p "<prompt>" --output-format json` → completion in `.result`, `.is_error` flags failure. M7-a2 Task 7 instead says "parse stdout as JSON" with no `--output-format` flag — raw `claude -p` stdout is plain text, so the literal implementation parses the wrong thing or only works by luck when the model emits bare JSON. Amend Task 7 to the P1-verified invocation: `--output-format json`, take `.result`, treat `.is_error`/non-zero exit as failure; when `response_schema` is set, JSON-parse `.result` (then the existing retry-once/repair path). Also note the ~44k fixed per-call overhead from P1 in M7-a2's Performance section (teacher calls are 2 per escalation).

### U3 — Judge prompt: put reasoning before score; consider per-criterion subscores (mid-2026 judge practice)
**File:** `docs/changes/distill-datagen-pipeline.md` — Task 4.
The judge JSON is `{"score": <float>, "reasoning": "<one sentence>"}` — score first means the rationale is post-hoc and the score uncalibrated. Current practice for single-call judge filters: (a) emit reasoning **before** score in the JSON key order/prompt instruction; (b) score the three named criteria separately (`{"cot_completeness": x, "plausibility": y, "relevance": z, "reasoning": "...", "score": min/mean}`) — cheap, same single call, measurably better filtering; (c) state that `threshold=0.6` is provisional and recalibrated after the pilot by inspecting the score distribution. Also: `judge_threshold` lives in both `JudgeAdapter(threshold=)` and `PipelineConfig.judge_threshold` — name one source of truth (pipeline passes its config value into the adapter) or `passed` vs the pipeline's drop rule can disagree.

### U4 — Batched generation needs explicit diversity scaffolding, not just `{start}`
**File:** `docs/changes/distill-datagen-pipeline.md` — Planning refinement + Task 2.
Independent `claude -p` calls have no memory; asking each call for "k DISTINCT instances (indices starting at {start})" reliably produces *within-call* variety but heavy *cross-call* mode collapse (same few meeting-scheduling tropes). SimHash only removes near-identical text, not semantic homogeneity — the dataset will be diverse-looking but narrow. Standard fix (self-instruct style): give each `Category` a `seed_topics: tuple[str, ...]` (15–30 entries: domains, personas, constraints, difficulty bands) and have the pipeline sample a different seed subset into each call's prompt, deterministic by `seed`. Small spec change (one field + one render step), large dataset-quality effect.

### U5 — eTLD+1 in the grounding gate needs a public-suffix source
**File:** `docs/changes/M7-c-curiosity-loop.md` — Task 2 (`grounding_gate`).
"Distinct registrable domain (eTLD+1)" cannot be computed from the stdlib — it requires the Public Suffix List. No dependency is listed; a literal executor will write a last-two-labels heuristic that is wrong for `*.co.uk`/`*.com.au` (two `.co.uk` publishers would count as one domain, or worse, two subdomains pass as independent on multi-label suffixes). Amend: add `tldextract` to deps (offline snapshot mode, no network fetch at import) and say "use `tldextract.extract(url).registered_domain`", or explicitly accept and document a stated heuristic.

### U6 — Windows subprocess + timeout realities for the teacher adapter
**File:** `docs/changes/distill-datagen-pipeline.md` — Task 3.
(a) On Windows, the npm-installed `claude` is a `claude.cmd`/`.ps1` shim; `subprocess.run(["claude", ...])` does **not** resolve `.cmd` without `shell=True` → `FileNotFoundError` even though `claude` works in the terminal where P1 was verified. Amend: resolve the executable via `shutil.which("claude")` at adapter init (raise a clear error if None) and pass the resolved path. (b) `timeout_s=180` was sized for one trace; a batch of 10 full-CoT traces in one response can exceed it. Raise the default (e.g. 600) or scale by `batch_size`.

---

## FLAG

### F1 — `replay_verify`/`apply_recipe`: inputs derivation and prompt construction unspecified; `expected` param unused
**File:** `docs/changes/M7-a2-...md` — Tasks 2–3.
- SCRIPT path: `sandbox.run(recipe.script, inputs, ...)` — but the only available original input is `EscalationRequest.request_text` (a string), while the recipe declares structured `inputs_schema`. How `req` becomes the `inputs: Mapping` is never stated (pass `{"request_text": req.request_text}`? constrained-decode extraction? who conforms it to `inputs_schema`?).
- INSTRUCTIONS path: "one `model.complete(role='responder', response_schema=recipe.outputs_schema)`" — the message content (presumably `recipe.instructions` + the inputs rendered somehow) is unspecified.
- `replay_verify(recipe, original_inputs, expected, model, ...)` takes `expected: TeacherOutcome` but the default schema-conformance comparator never reads it — a literal executor gets a confusing dead parameter. Either state "expected is reserved for richer comparators; unused by the default" or drop it.
Spell out the exact input mapping + prompt template; this is the kind of gap DeepSeek cannot fill.

### F2 — Source of `is_cloud_safe` when the Brain builds an `EscalationRequest` is unspecified
**File:** `docs/changes/M7-a2-...md` — Task 4. The Brain enqueues an `EscalationRequest` whose `is_cloud_safe` field must be set — from what? `RouteDecision` (M1-b) carries no sensitivity flag; no classifier is named. The cloud-egress guard (Assumption 4) is only as good as this bit. State the rule (e.g. "default `False` — fail-closed — until the M2 scope/sensitivity classifier provides it; wired at composition").

### F3 — M7-a3 near-dupe rule has no specified access to vectors
**File:** `docs/changes/M7-a3-dedupe-retire.md` — Task 1. `dedupe_retire(store)` must compute pairwise cosine over embedded descriptions, but the M0-d `VectorStore` port exposes only `search`, and M7-a1 never declares `RecipeStore.embedder`/`.index` as public attributes. State the mechanism: e.g. "RecipeStore exposes `embedder` and `index` as public attributes (amend M7-a1)" or "re-embed each ENABLED description via `store.embedder` and compare pairwise". Also "identical **canonical** instructions" (exact-dupe rule) is undefined — exact string? whitespace-collapsed? Pin it.

### F4 — Near-dupe retire key `provenance["verified_at"]` is absent on third-author recipes
**Files:** `docs/changes/M7-a3-...md` — Task 1 vs `docs/changes/M8-d-c2-capture-integration.md` — Task 5. M8-d-c2 writes capture recipes with `provenance={"origin": "capture_graduation", "capture_key": ...}` — no `verified_at`. M7-c staged recipes may likewise lack it. The near-dupe rule "retire the one with the older `provenance['verified_at']`" KeyErrors or behaves arbitrarily. Specify the missing-key rule (e.g. "missing `verified_at` sorts oldest" + tiebreaker applies).

### F5 — M7-b: `Promoter.threshold` and `.recurrence` must be declared public
**Files:** `docs/changes/M7-b-...md` — Task 2 vs `docs/changes/M8-d-c2-...md` — Task 5, which reads `self.promoter.threshold` and calls `self.promoter.recurrence.note(...)` directly. M7-b only describes ctor params. One line in M7-b Task 2: "store ctor args as public attributes `store`, `recurrence`, `threshold` (M8-d-c2 consumes them)". Otherwise a DeepSeek build may name-mangle (`self._recurrence`) and break the downstream spec.

### F6 — `RecipeAlreadyRetiredError` missing from M7-b re-exports
**File:** `docs/changes/M7-b-...md` — Task 4. The error is defined in Task 2 but not in the Task 4 re-export list; CLIENT-b Task 4 imports it to map → HTTP 409. Add it to `__all__`.

### F7 — M7-c grounding-gate done-when contradicts its own test
**File:** `docs/changes/M7-c-curiosity-loop.md` — Task 2 done-when ("False if ... **or any source unreachable**") vs Task 6 ("3 sources where 1 is unreachable but ≥2 distinct-domain reachable remain → **True**"). The gate definition (≥2 reachable suffices) is correct; the Task 2 done-when wording is the bug. Rewrite as "...or fewer than 2 distinct-domain sources reachable".

### F8 — M7-c Task 4 step 6 (distill→StagedItem) is underspecified
**File:** `docs/changes/M7-c-curiosity-loop.md` — Task 4.
- The recipe-vs-chunk decision ("a recurring procedural gap → recipe; a factual gap → RAG chunk") has no operational rule — presumably `gap.kind` mapping (`escalation-cluster`/`recurring-topic` → recipe; `low-confidence`/`staleness` → chunk?) — state it.
- "a recipe via `escalate_and_distill`-style distill writing a CANDIDATE recipe" conflicts with "do NOT write to the live store": `escalate_and_distill` signs+writes via `store.write` (Task 2 step 6 of M7-a2). Does M7-c call it with a *separate staging RecipeStore*? Re-implement the two teacher calls and put the recipe dict in `StagedItem.payload`? And what `EscalationRequest` (request_text? is_cloud_safe?) is constructed for a gap? Each must be exact.
- How `commit_staged` reconstructs a `Recipe` from `payload: dict[str, object]` (presumably `Recipe.model_validate(payload)`) — say so.

### F9 — M7-c smaller ambiguities
**File:** `docs/changes/M7-c-curiosity-loop.md`. (a) `TokenLedger.remaining_this_cycle` — what bounds a "cycle"? (one `curiosity_tick` invocation? a ledger `begin_cycle()` reset?) Unstated. (b) `GroundingError` is defined but the gate returns `bool` — when is it raised? Dead symbol; cut or specify. (c) Task 5 "a `HookSpec`-shaped factory **(or a plain async callable)**" — a literal executor must not be given an either/or; pick one. (d) Files-to-Change lists `heartbeat.py` modify "ONLY if needed" — conditional scope; decide now.

### F10 — distill-datagen acceptance commands are not Windows-PowerShell-runnable
**File:** `docs/changes/distill-datagen-pipeline.md` — Acceptance Task 1 (`cd tools/distill && uv sync`) + the bash-fenced Commands block. The build machine's shell is Windows PowerShell 5.1, where `&&` is a parser error. Either mark the commands "run in Git-Bash/cmd" or rewrite (`cd tools/distill; uv sync` / separate lines).

### F11 — distill-datagen: refinement text contradicts the call-count rule; P2 doc edits have no task
**File:** `docs/changes/distill-datagen-pipeline.md`. (a) § Planning refinement says a short batch is fine because "the next call covers the remaining target", but Task 5 step 1 issues a *fixed* `ceil(count_per_category / batch_size)` calls — shortfalls are never covered; raw counts will land systematically under target. Pick one: fixed calls (and reword the refinement) or generate-until-target with a max-calls bound. (b) Resolved seam P2 says "Add `DEEPSEEK_API_KEY` to `docs/bring-up/SECRETS-INVENTORY.md` and a `.env` example" — neither file appears in Files to Change, and no task loads `.env` (JudgeAdapter reads raw env vars). Assign the doc edit + state whether dotenv loading is in scope (recommend: no dotenv; document `$env:DEEPSEEK_API_KEY` usage).

### F12 — M7-a1 `retrieve_recipes` status filtering vs the `VectorStore` port
**File:** `docs/changes/M7-a1-...md` — Task 2. Status filtering must happen either inside `index.search` (does the M0-d `VectorStore.search` signature take metadata filters? scope only, per M1-a) or post-search in `retrieve_recipes` — in which case `search(k)` then filter can return fewer than `k` ENABLED names. State the mechanism (recommend: over-fetch `search(k*4)` then filter to `k`, or filter on the index's own metadata before scoring).

---

## RESEARCH

### R1 — The 6 category generation prompts are materially undefined (and voice_drafting hides a privacy decision)
**File:** `docs/changes/distill-datagen-pipeline.md` — Task 2.
What's actually missing: only the `scheduling_calendar` skeleton exists; "Adapt wording per category" delegates the highest-leverage design work in the whole pipeline to DeepSeek, which will produce six near-identical thin prompts. Each category needs: a real system prompt (teacher persona, CoT depth, answer style), instance-diversity scaffolding (see U4 seed lists), a difficulty mix, and per-category output constraints. **Specific unresolved fork:** `voice_drafting` ("drafting in the owner's voice") cannot be learned from purely synthetic data — the teacher doesn't know the owner's voice, yet the spec's cloud-safety rule forbids owner data. Either (a) the owner hand-clears a few style exemplars into the prompt (an ADR-003-shaped, owner-gated egress decision that must be made consciously), or (b) the category is renamed to generic register/tone drafting. Research + owner decision before the pilot run.

### R2 — `research_tool_use` traces have no tool-call structure
**File:** `docs/changes/distill-datagen-pipeline.md` — Tasks 2/6. The `<task>/<reasoning>/<answer>` format and the `{"messages":[user, assistant]}` output carry no tool-call turns, so "multi-hop research & tool-use reasoning" trains *narration about* tool use, not the student's actual tool-calling format (which M1-a/M1-b routing depends on). Research: what trace shape (simulated tool-call/observation turns in the assistant message vs multi-message tool roles) matches how the student (Qwen3-class via mlx) will be prompted for tools at runtime — then encode it in the category template before generating 150+ of these.

### R3 — Align the assistant-message format with the student's reasoning channel before the v1 run
**File:** `docs/changes/distill-datagen-pipeline.md` — Task 6 (`reasoning + "\n\n" + answer` as flat assistant content). Reasoning-distillation practice (and Qwen3-class students, the project's local model family) uses a delimited thinking channel (`<think>…</think>` + final answer) that the chat template treats specially during `mlx_lm.lora` fine-tuning; flat concatenation teaches the model to always emit CoT into the user-visible answer. This is cheap to fix now (one formatting decision in `output.py`) and expensive after a 10k-trace v1 run. Research the exact target template together with the Mac-side training spec and pin the format in the manifest (`generation_params["assistant_format"]`).

---

## Cross-spec consistency notes (verified, no action)
- `BrainResponse.path` is a plain `str` in M1-b, so M7-a2's `path="recipe"` is compatible.
- M8-d-c2's third-author use of `RecipeStore.write(CANDIDATE)` is fully supported by the M7-a1 interface (write signs + upserts regardless of caller); its `note_occurrence`/`PENDING`-gating walkthrough matches M7-b exactly (modulo F5).
- OBS-b's `SqliteTelemetrySource` matches M7-c's `TelemetrySource` Protocol method-for-method, including the `scan_gaps` end-to-end shape test.
- CLIENT-b's Review endpoints match `ReviewSurface`/`RecipeReview` field-for-field (modulo F6).
- The owner-gate chain is sound end-to-end: only `READ_ONLY`/`NO_DATA` ever auto-enable; `TOUCHES_DATA`/`TAKES_ACTION` reach ENABLED solely via owner `approve`/`promote` (signature-verified, retired-blocked); Curiosity results are staged-never-committed without `commit_staged`; teacher distill prompts are instance-free with a runnable Spy assertion. ADR-003's method/data split is faithfully encoded (modulo B1's missing seam and F2's unset sensitivity bit).

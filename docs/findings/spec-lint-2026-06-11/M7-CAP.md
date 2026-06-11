# Spec-lint — M7 Capability cluster (recipes / curiosity / distill-datagen)

Pass: **FINAL pre-handoff**, 2026-06-11. Executor: DeepSeek V4-Flash (literal; gap-fills wrongly; silently skips later phases).
Reference contract consulted: `docs/technical/contracts.md` Seam 1 (`ModelPort`/`ModelResponse`).

---

## M7-a1-recipe-format-store-signing.md

**Verdict: WARN-only**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| a1:51 | WARN | env pre-conditions | `recipes_dir` = "`<per-scope encrypted volume root>/recipes`" — the volume-root accessor is named in prose only (no `Settings` attribute named). Flash will invent an attribute. | Name the exact `Settings`/`paths` accessor, e.g. `paths.encrypted_volume_root(s, scope)`. |
| a1:44 | WARN | code detail | `provenance: dict[str, str] = {}` and `inputs_schema: dict = {}` as mutable Pydantic defaults — Flash may copy the literal; in Pydantic v2 this is actually safe, but ruff (B006-style) / reviewers may flag. | Confirm Pydantic-v2 default is intended (it is safe); leave as-is or use `Field(default_factory=dict)`. |
| a1:46 | WARN | code detail | "Inline/flatten `$defs`/`$ref` (enums)" — no snippet showing the flattening; Flash may emit `model_json_schema()` raw with `$ref` left in. | Inline a 3-line expected-shape example of the flattened schema (enum as `{"enum":[...]}`). |
| a1:54 | WARN | acceptance | numeric-tuple version ordering tested, but no test for malformed version string (`"1.x.0"`) → `int()` raises. | Add one line: out-of-spec versions rejected at `Recipe` validation or documented as caller-guaranteed. |

Notes: file paths all explicit; every task has a runnable done-when; signatures exact. Solid spec.

---

## M7-a2-escalation-distill-replay-brainseam.md

**Verdict: BLOCK**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| a2:48–49 vs 45 | **BLOCK** | code detail / cross-ref | Contradictory signature: Task 2 declares module-level `async def escalate_and_distill(req, model, store, *, sandbox=None)` (no `self`), but step 1 (line 49) and Assumption (line 20) read `self.teacher_origin`. Flash cannot resolve where `teacher_origin` lives — Task 1 offers "enclosing context **or** a thin `DistillService` dataclass **if preferred**" (line 45), an open choice. Flash will pick one arbitrarily and the Brain wiring (Task 4) + tests (Task 6) will reference the other. | Pick ONE shape and pin it: define `@dataclass class DistillService: model, store, teacher_origin: Literal["local","cloud"], sandbox=None` with `async def escalate_and_distill(self, req)`. Update Task 2 signature, Task 4 call-site, Task 6 to match. |
| a2:50–51, 59 | **BLOCK** | code detail / cross-ref | `model.complete(role=..., messages=[{"role":"user","content":...}], max_tokens=..., response_schema=...)` passes raw dicts as `messages`, but Seam 1 (contracts.md:34-40) types `messages: Sequence[Message]` — a `Message` model, not dicts. `mypy --strict` (the gate) will fail, or Flash invents a `Message` shape that diverges. The `Message` type is never inlined in this spec. | Inline the `Message` shape (`Message(role=..., content=...)`) and show one constructed call, e.g. `messages=[Message(role="user", content=solve_prompt)]`. |
| a2:50,58,59 | WARN | code detail | "`<solve framing of req.request_text>`" / "`<INSTANCE-FREE distill template…>`" are placeholders, not literal prompt strings. Flash will improvise prompts; the instance-free guarantee (the load-bearing privacy line) then rests on improvised text. | Inline the exact distill template string (with `{task_class_key}`/`{action_class}` slots) so the instance-free property is mechanical, not improvised. |
| a2:58 | WARN | code detail | `replay_verify(recipe, original_inputs, expected, model, *, sandbox=None)` — `original_inputs`/`expected` provenance undefined: step 5 (line 53) calls `replay_verify(recipe, req, outcome, ...)` passing `req` (an `EscalationRequest`) and `outcome` (a `TeacherOutcome`), but the signature names them `original_inputs`/`expected`. Type mismatch + unclear what "inputs" the SCRIPT path feeds to `sandbox.run`. | Align param names/types to the call-site (`req: EscalationRequest`, `expected: TeacherOutcome`); state explicitly which field becomes `sandbox.run` inputs. |
| a2:74 | WARN | code detail | `TeacherMalformedResponseError` raised by Task 7 but never declared in Files-to-Change exports/`__all__` (Task 5 omits it). | Add `TeacherMalformedResponseError` to the claude_cli module + Task 5 `__all__`. |
| a2:46 | WARN | acceptance | done-when references `self.teacher_origin` resolution but no runnable assertion ties to the chosen shape (blocked on the BLOCK above). | Resolves once the DistillService shape is pinned. |

---

## M7-a3-dedupe-retire.md

**Verdict: WARN-only**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| a3:36 | WARN | code detail | near-dupe needs "cosine over embedded descriptions" but `RecipeIndex`/`VectorStore` exposes `search(query)`-by-vector, not pairwise cosine between two stored recipes. How Flash obtains the two vectors to compare is unspecified (re-embed? read index?). | State the mechanism: re-embed each description via `store._embedder` (or expose a helper) and compute cosine, or query the index per recipe and read scores. |
| a3:36 | WARN | code detail | "missing `verified_at` sorts oldest — treated as `""`" then "tiebreaker below applies" — interaction of empty-string sort + tiebreaker is slightly ambiguous when one has `""` and other has a real timestamp. | Confirm: real timestamp always beats `""` (newer survives); only equal/both-empty hit the tuple tiebreaker. One clarifying clause. |
| a3:46 | WARN | atomicity | superseded test writes `foo@0.2.0` and `foo@0.1.0` (same name) but near-dupe rule keys on `action_class`+cosine across *different* names — test fixtures must avoid the two rules colliding. Not wrong, but Flash may build fixtures that trip both rules. | Note in Task 3 that superseded fixtures use a distinct `task_class_key`/description from the near-dupe fixtures. |

Notes: three rules each have a concrete done-when; deterministic tiebreaker specified; `set_status(version=...)` correctly references the M7-a1 param. No BLOCK.

---

## M7-b-promotion-policy-review-surface.md

**Verdict: WARN-only**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| a2-dep | WARN | cross-ref | Consumes `task_class_key` from M7-a2 whose own shape is currently BLOCKED (DistillService ambiguity). Cascades: `note_occurrence` keying depends on a2 resolving. | Resolve M7-a2 BLOCK first; no change needed here once a2 is pinned. |
| b:64 | WARN | code detail | Task 5 Brain wiring: "the condition is: `bool(self._store.list(status=CANDIDATE))` filtered to `task_class_key == key`, **or** `store.list` result filtered inline — **whichever matches** M7-a1's `list` signature" — offers Flash a choice and asks it to match a signature it must go re-read. `list(*, status=...)` returns `list[Recipe]` (a1:55); the filter is a one-liner. | Pin it: `any(r.task_class_key == key for r in self._store.list(status=RecipeStatus.CANDIDATE))`. Remove the "whichever matches" fork. |
| b:54 | WARN | pseudocode | `explain` body is an inline ternary-soup f-string sketch ("e.g."). Flash may reproduce the sketch verbatim incl. the `==NO_DATA` shorthand (undefined local). | Provide the literal function body or a clean if/elif over `recipe.action_class`. |
| b:45 | WARN | cross-ref | "M8-d-c2 reads `self.promoter.threshold` and calls `self.promoter.recurrence.note(...)`" — forward dep on an unbuilt spec; harmless (just mandates public attrs) but Flash needn't act on it. | Keep the public-attr requirement; drop the M8-d-c2 rationale inline (it's a why). |

Notes: classifier is a pure function with an exact membership test; signature-gated `promote` + `RecipeAlreadyRetiredError` well-specified; acceptance criteria runnable. Two-phase split is self-flagged and justified. No BLOCK.

---

## M7-c-curiosity-loop.md

**Verdict: BLOCK**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| c:56,83 | **BLOCK** | code detail | Grounding gate requires "distinct registrable domain (**eTLD+1**) — NOT the raw `domain` string" and tests assert `news.x.com`/`sport.x.com` collapse. But NO eTLD+1 mechanism is specified: `tldextract` is not in any dep list (no pyproject/deps for the curiosity module given), and a naive `split(".")[-2:]` fails on `.co.uk`. Flash will gap-fill with the naive split and the `.co.uk`-class test (if written) fails — or it adds an unpinned import. | Specify the mechanism: either add `tldextract` to deps and call `tldextract.extract(url).registered_domain`, or inline a documented PSL-free heuristic with its known limitation and matching test domains (avoid multi-part eTLDs in fixtures). |
| c:74 | WARN | code detail | `commit_staged` for a `chunk` raises `NotImplementedError` "until the M3 ingest hook is specced" — acceptable, but Task 6 owner-gated-commit test only covers the `recipe` path; the chunk-raises path is untested. | Add a one-line test: `commit_staged` on a chunk item raises `NotImplementedError`. |
| c:64,71 | WARN | code detail | Task 4 step 6 distill "via `escalate_and_distill`-style distill writing a CANDIDATE recipe" — but `CuriosityLoop` ctor (line 64) takes `model`/`recipe_store` but NOT a `DistillService`/teacher_origin; how it invokes distill without the M7-a2 service is unspecified. Flash will improvise a teacher call (uncapped, possibly cloud). | State exactly how the recipe StagedItem is built (payload = distilled recipe fields) and that NO teacher call happens at stage time — distill-to-recipe occurs only via the staged payload, or inject the DistillService explicitly. |
| c:60 | WARN | env pre-condition | `TokenLedger` rolling-7-day window over "recorded usage" — persistence format of the ledger JSON (list of `(ts, tokens)`?) not specified; `remaining_this_week` semantics depend on it. | Specify the on-disk ledger shape (e.g. `list[{at: iso, tokens: int}]`). |
| c:78 | WARN | code detail | Task 5 "`HookSpec`-shaped factory (**or** a plain async callable)" — choice offered; `HookSpec` type origin (M1-d) not inlined. | Pick the plain async callable; drop the `HookSpec` reference unless its shape is inlined. |
| c:68 | WARN | scope | Two-phase split self-flagged (trigger+scan / research+gate+stage+caps); 4 files + 1 test. Justified as one end-to-end cycle, but it is genuinely large for one Flash build. | Acceptable; reviewer may opt for the offered c1/c2 split if a build wave stalls. |

---

## distill-datagen-pipeline.md

**Verdict: WARN-only** (PowerShell host clean — no `&&`, no bash-isms, no bare `claude` subprocess hazard)

PowerShell 5.1 host check: `&&` correctly avoided (F10 notes call it out at lines 313/320/324); commands use `;`/separate lines; `claude` is invoked via `shutil.which`-resolved `self._exe` + list-form `subprocess.run` (no `shell=True`), which handles `.cmd`/`.ps1` shims (U6, lines 144–154). **No BLOCK on the Windows-host rule.**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| dd:227 | WARN | code detail | `output_dir = Path(__file__).resolve().parents[3] / "datasets" / "distill"` — `parents[3]` is brittle: from `tools/distill/distill/pipeline.py`, parents = [distill, tools/distill, tools, repo-root] → `parents[3]` = repo-root. Correct ONLY if the package layout is exactly `tools/distill/distill/`. If Flash nests differently the default silently points elsewhere. | Keep but add an assertion/comment pinning the expected file depth; the absolute `--output-dir` override (used in acceptance) mitigates. |
| dd:252 | WARN | code detail | `_simhash_similar`: "Hamming distance / 64 <= 1 - threshold" with `dedup_threshold=0.85` → drop if Hamming/64 ≤ 0.15 → ≤9 bits differ. Plausibly correct but the inequality direction is easy to invert; no unit assertion on a known pair. | Add a Task-7 micro-assert: two identical strings → similar True; two unrelated → False (beyond the "near-identical" test 4). |
| dd:334 | WARN | command | Dry-run smoke (line 334) passes `--output-dir datasets/distill` (relative) while acceptance line 321 mandates an ABSOLUTE path "regardless of cwd". The Commands block contradicts the acceptance criterion. | Make line 334's `--output-dir` absolute (or `$PWD\datasets\distill`) to match the B5 acceptance requirement. |
| dd:38 | WARN | scope | Shortfall behaviour ("fewer than k parseable → not retried; final counts land under target; intentional") is well-documented — no defect. | none. |
| dd:210 | WARN | code detail | Judge parse-fail path "retry once via tenacity then score=0.0" — `JudgeAdapter` shows no tenacity decorator in the sketch (only TeacherAdapter line 169 specifies one). | State the tenacity decorator on `JudgeAdapter.score` (or the internal HTTP call) explicitly. |
| dd:62,200 | WARN | acceptance | `FakeJudge(pass_rate=0.5)` "by hash" — deterministic mapping from content-hash to pass/fail not specified; Task 7 test 2 relies on `pass_rate=0.0`/`1.0` (fine) but `0.5` determinism is unpinned. | Specify: `passed = (int(sha256(trace),16) % 100) / 100 < pass_rate`. |

---

## Area verdict

**M7-CAP cluster: BLOCK** — 2 specs (M7-a2, M7-c) carry true BLOCKs that would make Flash build the wrong thing; M7-b cascades off a2. a1/a3/distill-datagen are WARN-only and handoff-ready after minor tightening.

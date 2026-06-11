# Spec-Lint Pass — Gmail + Productivity (M8) — 2026-06-11

Final pre-handoff lint. Executor: DeepSeek V4-Flash (literal; fills gaps with plausible-but-wrong code; silently skips later phases). Classification: **BLOCK** = stop handoff; **WARN** = soft flag.

---

## M8-a-google-auth-foundation.md — WARN-only

Verdict: WARN-only (0 BLOCK, 3 WARN). Strong spec — exact signatures, runnable per-task done-criteria, all files named, the cross-ADR refs all inline the consumed shapes (StoredToken, OAuth params, error types).

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| M8-a:9,11 | WARN | task atomicity / size | Task 1 bundles three logical things (deps + console script + scope registry). Defensible as one file-group but technically multi-phase. | Acceptable as flagged atomic exception; no change required, leave as-is. |
| M8-a:48 | WARN | commands need env vars | `uv run pip-audit` gate may emit non-zero on an unrelated transitive CVE unrelated to the 3 new deps; "no known vulnerabilities in the added deps" is narrower than what the bare command checks. | Note that pip-audit failure must be triaged to the 3 added deps only; pre-existing CVEs do not block. |
| M8-a:165 | WARN | criteria human-judgment | Acceptance line correctly explains why the shell `artemis-google-auth status` cannot be the runnable check and points to the pytest seam — good, but the GATED line 167 ("no token appears in any log") is human-inspection. | Acceptable (GATED/on-hardware); leave. |

---

## M8-b1-gmail-connector.md — WARN-only

Verdict: WARN-only (0 BLOCK, 3 WARN). Large but genuinely atomic; every port method signature is exact, the History-API cursor contract (3-tuple) is spelled out, the two untrusted boundaries are explicit, all consumed M3-a/M4-b/DR-a shapes are inlined in Assumptions.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| M8-b1:75 | WARN | code detail | `extract_body_text` says "strip text/html" without naming a method; Flash may pull in an HTML lib or write a fragile regex. | Name the approach: "use stdlib `html.parser`/regex tag-strip; no new dep" (consistent with no-new-deps prereq). |
| M8-b1:82 | WARN | env precondition | `backfill()` uses `relativedelta` (`after = today - relativedelta(months=...)`) but `dateutil` is not in the no-new-deps list (line 34 says no new deps). | Either add `python-dateutil` to deps explicitly or replace with stdlib month arithmetic; pin which. |
| M8-b1:9,16 | WARN | spec size | 9 files + inlined snippets is large; flagged atomic exception per precedent. | No change; flagged correctly. |

---

## M8-b2-gmail-urgency-hook.md — WARN-only

Verdict: WARN-only (0 BLOCK, 2 WARN). The async-bridge/pre-flight pattern, the 3-tuple return (hook, pre_flight, register_template), and the Seam-7 payload sanitisation are all specified precisely with exact signatures and the M6-c `pre_tick_steps` seam inlined.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| M8-b2:149 | WARN | code detail | The implementation block at line 137-149 shows `return hook, _pre_flight` (2-tuple) but the canonical contract at line 125-128 and done-criteria line 154 require the **3-tuple** `(hook, _pre_flight, register_template)`. The two return snippets in the same task disagree. | In the line 138-149 code block, change the final `return hook, _pre_flight` to `return hook, _pre_flight, lambda registry: registry.register("gmail.gmail_urgency_check", renderer.render)` so the single canonical return matches line 154. |
| M8-b2:23,92 | WARN | cross-reference | Relies on M6-c `pre_tick_steps` seam being already amended; spec asserts "amendment is already made" but Flash cannot verify. Signature is inlined though, so buildable. | Acceptable; leave (consumed signature is inlined at line 23). |

---

## M8-d-a-tasks-projects-areas.md — WARN-only

Verdict: WARN-only (0 BLOCK, 4 WARN). Schema DDL, all repository method signatures, recurrence grammar, and the 30-tool table are all exact and runnable. Eager-GOAL `entity_repo` shape is inlined.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| M8-d-a:110 | WARN | cross-reference | `create_project` calls `entity_repo.resolve_or_create_entity(name=, entity_type=EntityType.GOAL, entity_id=)` and uses `EntityType.GOAL` / `EntityRef`, imported from M4-d. The method signature is inlined but `EntityType`/`EntityRef`/`EntityRepository` import path is not named; Flash may guess wrong module. | Name the import path once (e.g. `from artemis.memory.entities import EntityRepository, EntityType, EntityRef`) or state "type-only Protocol, accept duck-typed `entity_repo`". |
| M8-d-a:79,110 | WARN | task atomicity | The `project_goal_entity_id` column is described in Task 1 DDL (line 79) AND re-stated as "Add … to the projects DDL in Task 1" inside Task 2 (line 110) — duplicated instruction across two tasks; harmless but Flash may add the column twice. | Drop the redundant "Add … to the projects DDL in Task 1" clause at line 110 (it is already in Task 1). |
| M8-d-a:22 | WARN | scope/size split | Self-flags a possible post-approval split into a1/a2 (two phases, 8 files). | Acceptable flagged exception; leave. |
| M8-d-a:96 | WARN | acceptance count | done-when says "creates all 7 tables"; the table list is meta/areas/projects/tasks/task_subtasks/task_recurrence/suggestions = 7. Consistent. Test line 275 says "6+ indexes" — vague lower bound. | Make the index count exact (count them: areas1+projects2+tasks4+subtasks1+suggestions1 = 9) or keep "≥6" as deliberate floor. |

---

## M8-d-b-time-blocking-seam.md — BLOCK

Verdict: BLOCK (1 BLOCK, 3 WARN). One stale-name BLOCK that the F7 fix banner claims to have fixed but did not fully apply.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| M8-d-b:36 | **BLOCK** | cross-reference / code detail | The amendment banner (line 15) says "F7 fix: Assumption text uses CalPrefs (not CalendarPrefs)", and line 30 was fixed — but line 36 still reads `CalendarPrefs.focus_block_duration_minutes`. CalPrefs is canonical (line 30/132). Flash will read `CalendarPrefs` as a real symbol and emit an import that does not exist → build break or a guessed alias. | Change `CalendarPrefs.focus_block_duration_minutes` → `CalPrefs.focus_block_duration_minutes` at line 36. |
| M8-d-b:268,295 | WARN | acceptance / cross-spec | Tool-count assertion is 31 (30+1). Correct **only if** M8-d-c2 has not yet run. Since build order is a→b→c1→c2 and these are separate sessions, 31 is right at b-time. But M8-d-c2 line 286 retroactively says base is 31→32. No conflict at b-execution time. | No change; cross-checked consistent. (Listed for traceability.) |
| M8-d-b:199,398 | WARN | code detail | `cancel_event` AUTO justification cites "classifier rule 4" (line 199 comment) vs "classifier rule 2" (line 398 Security). Inconsistent rule number; does not change generated code (the call is the same), but a reviewer-confusing discrepancy. | Pick one rule number (CAL-b's actual self-only-cancel rule) in both places. |
| M8-d-b:155,270 | WARN | cross-reference | `make_calendar_manifest(tools, schedule_task_fn)` signature change is additive to CAL-b's manifest factory; the CAL-b factory's existing param name (`tools: CalendarTools`) is assumed but not verified-inlined. | Acceptable — assumption states "verify before executing"; leave. |

---

## M8-d-c1-hooks.md — BLOCK

Verdict: BLOCK (1 BLOCK, 1 WARN). A self-contradicting acceptance criterion on tool count.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| M8-d-c1:291 | **BLOCK** | acceptance criteria | Acceptance line says "tools list remains **30**" but the entire spec (line 153, 202, B1 banner line 14) establishes the base is **31** after M8-d-b, and this spec adds no tools → must assert 31. Flash will write a test asserting `len(tools) == 30`, which fails against the real 31-tool manifest → red build it cannot self-resolve. | Change "tools list remains 30" → "tools list remains 31" at line 291 (matches line 153/202). |
| M8-d-c1:292 | WARN | acceptance criteria | The smoke check prints `len(productivity_manifest.__code__.co_varnames)` and only "verify exits 0" — it asserts nothing about the value, so it cannot catch a signature regression. Weak check. | Either assert the expected varname count or replace with a real import+construct assertion. |

---

## M8-d-c2-capture-integration.md — BLOCK

Verdict: BLOCK (2 BLOCK, 2 WARN). The prior-sweep concern (twice-defined CaptureService + "Wait — simpler approach" narration) is **RESOLVED** — verified single canonical `@dataclass CaptureService` at Task 4 (line 141-149); Task 2 (line 94) explicitly says "Do not add a second definition here"; no self-revision narration remains. However a new BLOCK exists: the `productivity_manifest` signature is given in two mutually-contradictory parameter orders.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| M8-d-c2:295-301 vs 313 | **BLOCK** | code detail / cross-reference | Task 7 shows the signature TWO ways with different param ORDER and SET. The code block (295-301) is `productivity_manifest(store, registry, capture_service, ingest_pipeline, memory_queue)` — it DROPS `schedule_fn` and `write_tools` (added by M8-d-b) and omits `settings`. The B1 prose (line 313) says the cumulative signature is `(store, schedule_fn, write_tools, registry, capture_service, ingest_pipeline, memory_queue)`. Flash will emit the code block verbatim, dropping `schedule_fn`/`write_tools` → breaks M8-d-b's `task.schedule` wiring (init_schedule_fn never called) and contradicts the call sites in tests (line 375 uses `(store, schedule_fn, write_tools, registry, capture_svc, ingest, queue)`). | Replace the Task 7 code block (295-301) with the full cumulative signature from line 313, including `settings`: `def productivity_manifest(store, schedule_fn, write_tools, registry, capture_service, ingest_pipeline, memory_queue, settings) -> ModuleManifest:`. Make it the single canonical signature; the test call line 375 must match it. |
| M8-d-c2:284,286 | **BLOCK** | code detail / acceptance | Task 6 line 284 says adding `project.complete` makes "total becomes 31"; line 286 B1 fix says the correct total is **32**; the done-criteria (line 317), tests (line 375), and acceptance (line 480) all say 32. The inline "31" at line 284 is a leftover that directly contradicts the same task's own count. Flash reading line 284 literally may target 31 and write a failing assertion / wrong manifest comment. | At line 284 change "total becomes 31" → "total becomes 32" (consistent with B1 line 286 and all downstream counts). |
| M8-d-c2:309 | WARN | code detail | "Add `settings: Settings` as a parameter … OR thread it through a module-level reference (match the project convention) — check how M8-d-a passes settings." This offers Flash a choice + a "go read M8-d-a" instruction; Flash picks arbitrarily and may mismatch the test's call signature. | Decide it: add `settings: Settings` as the explicit final param (as folded into the BLOCK fix above); remove the "OR thread it / check how" optionality. |
| M8-d-c2:329,362 | WARN | code detail | `FakePromoter` is described in prose (line 329) and also constructed with `ReviewSurface(FakeRecipeStore(), FakePromoter(...))` at line 362 — but line 332 (F12) warns NEVER to pass fresh `FakeRecipeStore()`/`FakeRecurrenceStore()`. Line 362 violates its own F12 rule by calling `ReviewSurface(FakeRecipeStore(), ...)` with a fresh store. | At line 362 use the shared fixtures: `ReviewSurface(shared_recipe_store, FakePromoter(shared_recipe_store, shared_recurrence_store))` (or the same promoter fixture) — never a fresh `FakeRecipeStore()`. |

---

## Area verdict

**Gmail (M8-a/b1/b2): clean — handoff-ready (WARN-only).** Productivity (M8-d a/b/c1/c2): **3 of 4 specs BLOCK** on copy-paste-grade count/signature/name contradictions introduced by the cumulative-signature amendments — all are one-line fixes, but each would make Flash build a failing or wrong manifest. Fix the 4 BLOCK lines (M8-d-b:36, M8-d-c1:291, M8-d-c2:295-301, M8-d-c2:284) before handoff; the c2 twice-defined-CaptureService prior concern is confirmed resolved.

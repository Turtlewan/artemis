# Sweep findings — M8-d Productivity module (2026-06-10)

Specs reviewed in full: `M8-d-a-tasks-projects-areas.md`, `M8-d-b-time-blocking-seam.md`,
`M8-d-c1-hooks.md`, `M8-d-c2-capture-integration.md`. Cross-checked against:
`CAL-a-read-findtime-prefs-sync.md`, `CAL-b-write-gating-activitylog.md`,
`M6-a-scheduler-tickloop-hookcontract.md`, `M6-b-hit-handling-batched-llm-urgency-briefing.md`,
`M7-a1-recipe-format-store-signing.md`, `M7-b-promotion-policy-review-surface.md`,
`M3-a-ingestion-pipeline.md`, `M4-b-write-path-audn-extraction.md`,
`DR-a-untrusted-content-security.md`, `M0-a-foundation-layout.md`,
`docs/technical/modules/productivity.md`.

**Counts: BLOCK 7 · UPGRADE 10 · FLAG 18 · RESEARCH 5**

---

## BLOCK

### B1. `productivity_manifest` signature + tool-count collision across M8-d-b / c1 / c2
- M8-d-b (Tasks 3–4): changes signature to `productivity_manifest(store, schedule_fn)` then `(store, schedule_fn, write_tools)`; asserts **31** tools (`task.schedule`).
- M8-d-c1 (Task 2): changes signature "from `(store)`" to `(store, registry)`; Task 3 asserts **`len(tools) == 30`** ("tools list is NOT modified by this spec").
- M8-d-c2 (Task 7): final signature `(store, registry, capture_service, ingest_pipeline, memory_queue)` — **omits `schedule_fn` and `write_tools` entirely** — and asserts **31** tools (`project.complete`), which is wrong if M8-d-b is built (should be 32).
- No build order is pinned that makes these consistent (c1/c2 prereqs don't include b; b's prereqs don't include c1/c2). DeepSeek executing these literally in any order produces a manifest whose signature breaks the previously-built spec's tests. Fix: state one cumulative signature per spec ("if M8-d-b already applied, signature is X"), or better, switch all wiring to keyword-only optional params and make all tool-count assertions relative (`base + N`), and pin the build order a → b → c1 → c2 in each spec's Prerequisites.

### B2. M8-d-b link-clear is impossible under M8-d-a's `update_task` None-sentinel semantics
M8-d-a Task 2 specifies update methods as "only non-None kwargs written" (stated for `update_area`; `update_task(id, *, ... scheduled_block=None, calendar_event_id=None)` uses the same None-default pattern). M8-d-b Task 3b calls `store.update_task(args.id, calendar_event_id=None, scheduled_block=None)` to CLEAR the link — under M8-d-a semantics this is a no-op, the link can never be cleared, and M8-d-b Task 6 / Acceptance ("`get_task(...)["calendar_event_id"] is None` after `task_complete`") fails with no resolution a literal executor can derive. Fix: add an explicit `clear_task_schedule_link(task_id)` repository method in M8-d-a (or a sentinel object pattern), and have M8-d-b call it.

### B3. Recurrence idempotency guard breaks on re-completion (M8-d-a Task 2 + Task 7)
`complete_task(id)` unconditionally sets `status='done'`, `completed_at=now` and calls `spawn_next_recurrence` if a recurrence row exists. The Task 7 test requires a second `complete_task` on the same task to NOT double-spawn. But the second call **overwrites `completed_at` with a fresh now**, so the guard "existing todo task with `created_at > completed_at`" no longer matches the first spawn (its `created_at` < the new `completed_at`) → second spawn → the spec's own test fails. Also, with second-resolution ISO timestamps, the first spawn's `created_at` can equal `completed_at`, and strict `>` fails even on the first retry. Fix: make `complete_task` an early-return no-op (`return None`) when `status` is already `done`/`cancelled`, and change the guard comparison to `>=`.

### B4. Fixed-mode recurrence "compute from now" contradicts the locked design (§F)
productivity.md §F (LOCKED): fixed-schedule = "next instance due on the calendar **regardless of when the last was done**". M8-d-a Task 2 says fixed-mode computes the next occurrence "from `now` (NOT from `completed_at`)" — but `now` at spawn time IS the completion moment, so for `"every <N> <unit>"` rules the fixed mode degenerates into completion-based (complete 3 days late → next due drifts 3 days). Weekday/`monthly on N` rules are fine (they snap to calendar boundaries); the `"every N days|weeks|months"` rules must advance from the previous `due_at` (repeatedly, until > now), not from now. Spec must state this per rule-type.

### B5. M8-d-c2 `_build_capture_recipe` uses a `Recipe.provenance` field that does not exist (M7-a1)
M7-a1 defines `Recipe` frontmatter fields as `name, description, version, recipe_class, action_class, task_class_key, inputs/outputs schema, script?, signature` (+ `instructions`, `status`). There is no `provenance` field anywhere in M7-a1/M7-a2 (grep across all specs: no Recipe provenance). `Recipe(..., provenance={"origin": ...})` raises a Pydantic `ValidationError` at the graduation threshold → graduation is dead on arrival. Fix: drop the field, encode origin in `description`, or amend M7-a1 to add an optional `provenance: dict` (round-trip + signing implications — must be decided in planning, not by DeepSeek).

### B6. M8-d-c2 knowledge push writes a temp file outside M3-a `FileConnector` allowed roots
M3-a Task (connectors): `FileConnector` "reject[s] paths outside an allowed roots set passed at construction — no traversal". `_push_knowledge` writes the project summary to `tempfile.NamedTemporaryFile` (system temp dir) and ingests `Source(kind="file", uri=tmp_path, ...)`. The composition-root `FileConnector` will be rooted at the data dirs, not `/tmp` → `ValueError` on every push, silently swallowed by `_push_knowledge`'s try/except → the knowledge-push feature never works and never surfaces an error. The Acceptance test passes only because `FakeIngestPipeline` doesn't enforce roots — the bug ships invisible. Fix: write the temp file under a path inside the allowed roots (e.g. `scope_dir/.../ingest-staging/`), or add a `kind="text"`/in-memory ingest seam to M3-a.

### B7. M8-d-c2 graduation guard can demote an owner-ENABLED recipe (security-adjacent)
The "create CANDIDATE only once" guard checks `recipe_store.list(status=CANDIDATE)` only. After the promoter moves the recipe to `PENDING` (or the owner approves to `ENABLED`), the next `accept_with_graduation` over the same key finds **no CANDIDATE**, re-runs `_build_capture_recipe`, and `RecipeStore.write` **upserts by name** (M7-a1) — resetting a PENDING or owner-approved **ENABLED** recipe back to `CANDIDATE`, then re-promoting to `PENDING`. That silently revokes an owner approval — exactly the boundary the spec's own Security §3 declares load-bearing. The Task 8 idempotency test ("still exactly one CANDIDATE entry") even passes under the broken behaviour. Fix: existence check must be by `task_class_key`/name across **all** statuses; never write if any recipe for the key exists.

---

## UPGRADE

### U1. `datetime.utcnow()` is deprecated — and inconsistently used across the four specs
M8-d-a Task 2 (`now_iso() = datetime.utcnow().isoformat() + "Z"`) and M8-d-b Task 1 step 2 use `datetime.utcnow()` — deprecated since Python 3.12 (DeprecationWarning; slated for removal) and a lint target under ruff's DTZ rules. M8-d-c1 already uses `datetime.now(timezone.utc)` correctly. Standardise on `datetime.now(timezone.utc)` everywhere; define one `now_iso()` helper and reference it from M8-d-b/c2 (note: with an aware datetime, `isoformat()` yields `+00:00`, so the `+ "Z"` suffix logic must be adjusted once, in one place).

### U2. `suggestion_list` is misclassified as a WRITE tool (M8-d-a Task 4/5)
`suggestion.list` is a pure SELECT but sits in the Write table with `action_risk=WRITE` (making the read/write split 13/17, not 12/18). Move it to READ — risk metadata feeds future brain gating; misclassification is cheap to fix now.

### U3. Simplify the graduation flow: create the CANDIDATE on first accept (M8-d-c2 Tasks 4–5)
The current dance (raw `promoter.recurrence.note()` + `count()`, threshold check, conditional CANDIDATE write, then `note_occurrence` to trigger promotion) reaches into Promoter internals, double-increments the counter at the threshold crossing (raw `note` + `note_occurrence`'s internal `note`), and needs B7's guard fix anyway. Simpler and fully within M7-b's public contract: write the CANDIDATE on the **first** accept for a key (if no recipe exists for the key), then call only `promoter.note_occurrence(key)` on every accept — M7-b's promoter already counts and promotes (gated → PENDING) at threshold. Removes ~20 lines and all internals access.

### U4. `schedule_task` should bound the block to the estimate, not the slot (M8-d-b Task 1 steps 5–7)
The primitive books `slot.start_dt → slot.end_dt`. CAL-a does not specify whether `FreeSlot` is trimmed to the requested duration or is the whole free gap; if the latter, a 45-minute task books a 4-hour focus block. Robust either way: `end = start + duration_minutes` (capped at `slot.end_dt`). One line, removes the dependency on an unverified CAL-a behaviour.

### U5. Cut the three redundant assign tools (M8-d-a)
`task.assign_to_project`, `task.assign_to_area`, `project.assign_to_area` duplicate what `task.update(project_id=...)` / `project.update(area_id=...)` already do (same auto WRITE risk, same repo columns). productivity.md §D lists them, but they add 3 tools + 3 repo methods + tests for zero new capability — and every extra tool dilutes RAG-for-tools retrieval. Recommend cutting (30 → 27) with a one-line note in productivity.md; if the locked doc must stand, keep but note the duplication.

### U6. `project.complete` (M8-d-c2 Task 6) is a new tool beyond the locked §D surface
productivity.md §D has no `project.complete`; `project.update(status="done")` already exists. Adding a tool mid-spec compounds the B1 count collision. Prefer: trigger `_push_knowledge` inside `project_update` when `status` transitions to `"done"` (and keep `project_archive` semantics separate, see U9). If a dedicated tool is genuinely wanted, amend productivity.md first.

### U7. Don't smuggle `commitment_shape` through the `notes` field (M8-d-c2 Tasks 2/4)
`notes = f"shape:{shape}|source:{source}"` turns a human-visible field into a machine encoding — and M8-d-a's `accept_suggestion` copies suggestion data into the created task, so tasks surface "shape:will_send|source:email" as their notes. M8-d-a's schema is built in the same milestone: add a `commitment_shape TEXT` column to `suggestions` in M8-d-a Task 1 instead (one column, no parsing, no notes pollution).

### U8. Inject a `cancel_fn` callable, not the whole `CalendarWriteTools` (M8-d-b Task 3)
`task_schedule` needs exactly one calendar capability beyond `schedule_fn`: cancel-by-id. Passing the entire `CalendarWriteTools` into productivity's module-level singletons couples the modules broadly. Mirror the `schedule_fn` pattern: `init_cancel_fn(Callable[[CancelEventArgs], WriteResult])` bound at the composition root. Also simplifies B1's signature reconciliation.

### U9. `project_archive` should not push a "Project completed" summary (M8-d-c2 Task 6 item 3)
Archiving can mean abandoned/superseded; pushing "Project completed: {title}" into knowledge + a "completed milestone" memory fact poisons recall with false facts. Trigger the push only on the done-transition (see U6); on archive, either skip or use neutral "Project archived" text.

### U10. Move `FakeCommitmentDetector` out of `capture.py` (M8-d-c2 Task 1)
The spec defines a test-only fake inside the production module while warning "do NOT import in prod". Define it in `tests/test_productivity_capture.py` like every other Fake* in this corpus (FakeRecipeStore, FakeIngestPipeline, etc. are all test-file fixtures).

---

## FLAG

### F1. M8-d-c2 contains unresolved self-revision a literal executor will mis-execute
Task 4 includes "**Wait** — simpler approach: …" superseding steps 1–2 it just gave; Task 5 contains **two** "revised flow" code blocks where the first is explicitly invalidated by the second; Task 2's `notes` format is retroactively changed by Task 4's note; `CaptureService` is defined twice (Task 2 without `recipe_store`/`promoter`, Task 4 with). The CLAUDE.md spec-authoring rule says a spec is an execution script — DeepSeek may implement the first (superseded) version of each. The spec needs a clean rewrite with exactly one canonical flow per task before it is `status: ready`.

### F2. "# all 28 ToolSpecs" comment vs 30 (M8-d-a Task 5)
The manifest snippet comment says 28; the text and acceptance say 30. Trivial but a literal executor copies comments verbatim; fix to 30.

### F3. 30 ToolSpec descriptions are unspecified (M8-d-a Task 5)
Task 5 gives exact tool **names** but no per-tool `description` strings and no example `ToolSpec(...)` construction (M8-d-b Task 2 shows the shape, but that spec comes later). Descriptions matter doubly here — M1-a RAG-for-tools embeds them for retrieval. Provide a name→description table (or a stated generation rule, e.g. derive from the repository docstrings given in Task 2).

### F4. `due_at` format and comparison semantics are unspecified (M8-d-a Task 2)
`today_tasks()` = `due_at <= today`, `overdue_tasks()` = `due_at < today` — but `due_at` is free TEXT and the tests mix date-only (`"2026-07-01"`) values. With ISO **datetime** values, string comparison against a date string misbehaves: `"2026-06-10T08:00:00Z" <= "2026-06-10"` is **false**, so a task due today at 08:00 appears in neither `today` nor `overdue`. Pin: due_at is date-only (`YYYY-MM-DD`), or compare with `date(due_at) <= date('now')` SQL, and define whether "today" means start-of-day or end-of-day.

### F5. `"every N months"` and `"monthly on 31"` edge cases unspecified (M8-d-a Task 2)
The rule grammar includes `months` but stdlib `timedelta` has no month arithmetic; the spec mandates "stdlib datetime only" with no algorithm. `"monthly on 31"` (or 29/30) in a short month will raise `ValueError` in a naive `date.replace(day=N)` implementation. Specify: month addition = increment month with day clamped to the target month's last day.

### F6. Recurrence/today computations run in UTC, ignoring `CalPrefs.timezone`
"Next Monday", `_today_iso()`, and `today_tasks()` all use UTC. For the owner (SGT, UTC+8) the day/week boundary is off by 8 hours: at Mon 06:00 SGT (Sun 22:00 UTC), "next monday" and the morning-plan dedup date compute for the wrong day. Decide: either declare v1 = UTC-everywhere (document the skew) or thread the owner timezone (CalPrefs or a Settings field) into `now_iso`/`_today_iso`/recurrence. (No DST in SGT, so this is a fixed offset issue — but the spec should say so.)

### F7. `CalendarPrefs` vs `CalPrefs` naming (M8-d-b Assumptions vs Task 1)
CAL-a defines `CalPrefs`; CAL-b Task 3 calls the constructor param type `CalendarPrefs`; M8-d-b's Assumption (line 21) says "`CalendarPrefs` … importable from `artemis.modules.calendar`" while Task 1 imports `CalPrefs` from `…calendar.preferences`. The Task 1 import is correct; fix the Assumption text (and flag the CAL-b naming to the CAL reviewer).

### F8. Calendar manifest factory shape is hedged (M8-d-b Task 2)
"In `make_calendar_manifest` (or its equivalent factory)" — "or its equivalent" forces exploration, DeepSeek's weakest area. Worse, CAL-a defines the factory `make_calendar_manifest(tools: CalendarTools)` but CAL-b's acceptance imports a module-level constant `CALENDAR_MANIFEST` — the CAL specs themselves disagree about whether the manifest is a factory product or a constant. M8-d-b must pin the exact symbol it modifies (and the CAL contradiction needs resolving upstream).

### F9. `cancel_event` AUTO-classification citation is inconsistent (M8-d-b Task 3 vs Security §3)
Task 3 comment says "classifier rule 4 → AUTO"; Security §3 says "AUTO per classifier rule 2". CAL-b's rule 2 covers only `block_focus_time`/`set_reminders`; `cancel_event` goes AUTO via the **attendee check** (and is baseline `ActionRisk.HIGH_STAKES` in CAL-b). Also: `CancelEventArgs` carries no attendees — `CalendarWriteTools.cancel_event` must resolve them (presumably from the event cache); behaviour when the old focus-block is missing from the cache (stale/cancelled externally) is unspecified — the re-schedule path should tolerate a cancel failure of the old event rather than aborting the new booking.

### F10. Subtasks exist in schema + repository but no tool can create one (M8-d-a)
`add_subtask`/`complete_subtask`/`list_subtasks`/`delete_subtask` are repo methods with no corresponding tools (productivity.md §D omits them too), so the brain can never create or tick a checklist item — `task_subtasks` is write-orphaned at the tool surface. Either add subtask tools or state explicitly that subtasks are deferred surface (and consider cutting the repo methods until then — dead code per the corpus's own simplicity rules).

### F11. c1's payload comment promises an M6-b capability that doesn't exist
hooks.py inline doc: "M6-b fetches details by ID if richer content is needed" — M6-b's `HitHandler` has no `ProductivityStore` access and no fetch-by-ID mechanism; it only renders payloads via one batched call. Consequence: the flagship morning plan can only ever say "3 tasks today, 1 overdue" — no task names. Acceptable for v1 (and the injection boundary is sound), but delete the misleading comment or actually spec the M6-b enrichment seam; the owner should know the briefing will be counts-only.

### F12. c2 test fixtures construct disconnected store instances (M8-d-c2 Task 8)
The `CaptureService` fixture passes `recipe_store=FakeRecipeStore()` and `promoter=FakePromoter(FakeRecipeStore(), FakeRecurrenceStore())` — **two different** FakeRecipeStore instances, and the graduation assertions later construct `ReviewSurface(FakeRecipeStore(), FakePromoter(...))` with yet more fresh instances. As literally written the promoter never sees the candidate the service wrote and ReviewSurface inspects an empty store — the graduation tests cannot pass. Spec must state: one shared `FakeRecipeStore` and one shared `FakeRecurrenceStore` across service, promoter, and review surface.

### F13. `CaptureService` defined twice (M8-d-c2 Tasks 2 and 4)
Two `@dataclass class CaptureService` blocks with different fields. State once (Task 2) with all six fields, or mark Task 4's as "replace the Task 2 definition".

### F14. c2 split-note vs Files-to-Change disagreement on `hooks.py`
The HTML split comment says "hooks.py (modify, thin call-site addition)" but the Files-to-Change table (correctly, per Assumption 2) does not list hooks.py. Remove the stale mention.

### F15. `ToolRegistry` construction in c1's Tier-1 test omits the embedder
M6-a's tests build `ToolRegistry(FakeEmbedder())`; c1 Task 3 says "Build a `ToolRegistry`" with no args. Pin the constructor call.

### F16. `suggest_from_text` sync/async whiplash (M8-d-c2 Task 2)
The signature is given as `def suggest_from_text(...)`, then a mid-step NOTE says "`suggest_from_text` is therefore `async def`". Give the final `async def` signature up front; also state how the sync trusted path and callers handle the coroutine (who awaits it — relevant given no caller is wired, see R1).

### F17. `Source.scope` expects a `Scope` type, c2 passes a raw string
M3-a: `Source { kind, uri, scope: Scope }`. c2: `Source(kind="file", uri=tmp_path, scope="owner-private")`. If `Scope` is a NewType/enum rather than a plain str alias, mypy --strict rejects this. Use the `OWNER_PRIVATE` constant from `artemis.identity.scope` (consistent with every other spec).

### F18. `weekly_review` as an interval hook fires its check on every process restart
M6-a initialises interval hooks "due on the first tick", and `next_due` is in-memory — every launchd restart re-runs the weekly check immediately. Delivery is suppressed only if M6-c's dedup (`dedup_key` + `_week_iso()`) is durable across restarts. The hook design is fine **iff** that holds — state the dependency explicitly in c1 (see R-class verification below).

---

## RESEARCH

### R1. Nothing calls `CaptureService.suggest_from_text` — the capture path has no trigger
c2 builds detection but wires no caller: M8-b1/b2 (gmail) never reference it, no productivity hook invokes it (correct — capture is reactive per §E), and no brain/composition spec schedules it ("the brain schedules it" appears only in c2's Performance prose). As specced, capture never fires. Planning must decide the entry point(s) — e.g. a gmail-hook call-site, a brain post-turn hook for chat — and spec the wiring, or explicitly park capture-triggering as a later spec.

### R2. Verify `MemoryWriteQueue.enqueue` signature against M4-b
c2 assumes `enqueue(text: str, turn_id: str)`. M4-b shows `process_turn(text, turn_id=..., role=...)` and only `enqueue(...)` elided; a required `role` param (or a different arg shape) would break the call. Verify before build (one-line check in M4-b's write_path.py task).

### R3. Confirm CAL-a `FreeSlot` is trimmed to the requested duration
Determines whether U4 is a nicety or a correctness fix (whole-gap focus blocks). Check CAL-a `FindTimeEngine.find_slots` behaviour / tests.

### R4. `jsonschema` package availability (M8-d-c2 Task 1)
The done-when asserts `jsonschema.validate(...)` in tests, but the spec declares "no new PyPI deps". Confirm `jsonschema` is already a transitive/dev dependency in the locked `pyproject`; otherwise the test import fails — switch to a hand-rolled shape assert or add the dev dep explicitly.

### R5. Verify M7-b `RecurrenceStore`/`Promoter` public surface used by c2
c2 reaches `promoter.recurrence.note/count` and `promoter.threshold`. M7-b's constructor `(store, recurrence, threshold=2)` makes them plausibly accessible, but `RecurrenceStore`'s exact method names (`note`/`count`/`reset`) and whether attribute access is intended-public are unverified. Moot if U3 (note_occurrence-only flow) is adopted.

---

## Security check (rubric item 4) — verdict: sound, with B7 as the exception

The quarantine gating for email-derived suggestions is well-specified and consistent across specs: `untrusted=True` requires a `QuarantinedReader` (ValueError otherwise); only `Extract.summary` reaches the detection model; `raw_context` is always `None`; suggestions are inert (`status='pending'`) until owner `accept_suggestion`; the c1 hook payloads are counts+UUIDs only (structural injection boundary, tested); the capture recipe is hardcoded `TOUCHES_DATA` → gated → PENDING-only. The one hole is **B7** (re-graduation can clobber an owner-ENABLED recipe). Minor residual: M8-d-a's `suggestion.create` brain tool accepts `source="email"` without quarantine, but it is brain/owner-initiated and the row is inert — acceptable.

## Over-engineering check (rubric item 5)

Largest cut candidates: U5 (3 redundant assign tools), F10 (orphaned subtask repo surface), U6 (`project.complete` tool), U3 (graduation flow complexity). The 30-tool surface is otherwise locked by productivity.md §D and each tool is thin; the hooks set (3) is the locked minimum; M8-d-b is appropriately lean. The module is large but mostly by mandate, not gold-plating.

# Module design — Productivity (Tasks + Projects + Areas)

_Per-module design doc (third spoke-module design, after `calendar.md` + `gmail.md`). The complete
intended surface for the Productivity module. **All decisions LOCKED 2026-06-09** (elicitation
complete). Source-of-truth for the M8-d spec(s)._

> Posture (ADR-011): **owned — Artemis IS the source of truth** (not a mirror). The structural
> inversion of Gmail/Calendar: **no external sync, no conflict resolution, no untrusted layer** (you
> author this content — it is trusted), **self-only writes are autonomous** (editing your own task list
> affects nobody → no Review gating), and **no external integration at all** (no Google Tasks — owner
> decision 2026-06-09). The only cross-module effect is the Calendar time-blocking seam (§C), which
> creates self-only calendar focus-blocks (auto, ADR-011).

## Scope (LOCKED 2026-06-09)
- **In:** **Tasks** + **Projects** + **Areas** (life-domain shelves above Projects).
- **Deferred (clean follow-on, rail reserved):** **Habits + Goals** — the Calendar time-blocking
  mechanism built here is the same rail `calendar.md` §C reserved for projecting Habits/Goals onto
  open slots, so they slot in later without rework.

## Plugs into the contract
- **Module** = a `ModuleManifest` (M1-a): typed `tools` (§D) + `proactive_hooks` (§E) +
  `data_scope = OWNER_PRIVATE` → hooks are **Tier-1** (queued while locked).
- **Owned store** (M0-a `relational/`, M2 wall): SQLCipher, owner-private. Artemis is authoritative —
  no read-cache, no sync cursor (it owns the data).
- **Calendar seam** (§C): a new `calendar.schedule_task(...)` time-block primitive.
- **Capture** (§G): suggestion-inbox → learned, owner-approved **automation recipes** (M7 loop).
- **Knowledge push** (M3-a): completed-project/task summaries → searchable knowledge (trusted source).
- **Memory** (M4-b): standing facts (recurring task patterns, working preferences) via A.U.D.N.
- **Heartbeat** (M6): the proactive planning hooks (§E).
- **Brain composes**: the module ships typed primitives; "remind me to call mom tomorrow" is the brain
  parsing NL into `task.create(title="call mom", due=<tomorrow>)`.

## A. Tasks — the model
Fields: `title`, `notes`, `status` (`todo | doing | done | cancelled`), `priority`
(`none | low | medium | high`), `tags`, `project_id` (nullable), `area_id` (nullable — a task may
attach directly to an Area without a Project), `subtasks`/checklist, `estimate_minutes`,
`created_at`/`completed_at`, plus recurrence (§ Recurrence) and the time-blocking links (§C).

**The load-bearing distinction — due ≠ scheduled:**
- `due_at` = the **deadline** ("report due Friday").
- `scheduled_block` = when you'll **do** it (the Calendar focus-block this task is planned into).
- `calendar_event_id` = the link to the real Calendar focus-block (§C level 2).

## B. Projects + Areas — the model
- **Project**: `title`, `status` (`active | on_hold | done`), optional `target_date`, `notes`,
  `area_id` (nullable), a set of Tasks. Flat (no sub-projects in v1).
- **Area** (LOCKED in for v1): an **ongoing responsibility with no finish line** (Health, Work,
  Finances, Home). `title`, `notes`, never "completes". Projects + standing tasks file under an Area
  (`project.area_id` / `task.area_id`). The top-level life-domain shelf — enables "show me everything
  Health-related" + the per-area weekly review.

## C. Calendar integration — full time-blocking, all 3 levels (LOCKED 2026-06-09)
1. **Deadline awareness (read):** task `due_at`s surface in Calendar's daily briefing + agenda.
2. **Time-blocking (the star):** `schedule_task(task_id, window?)` → uses Calendar's `find_time` to
   pick an open slot → creates an **auto focus-block** event (self-only → auto, ADR-011) → writes
   `task.calendar_event_id` + `task.scheduled_block`; the event links back to the task. **New seam
   into the Calendar module:** a `calendar.schedule_task` / block-for-task primitive (reconcile against
   `calendar.md` §B `block_focus_time` + CAL-b at spec time).
3. **Completion loop (capability, not a proactive hook):** `task.complete(task_id)` can be invoked when
   a focus-block ends. NOTE: the owner opted OUT of the proactive completion-check *hook* (§E) — the
   capability exists (mark done on request / from the block), but Artemis does not auto-nag "did you
   finish?".

## D. Tools — all `read`/`write`, **auto** (owned data, no external effect, no gating)
**Read:** `task.list(filter)`, `task.get(id)`, `task.search(query)`, `task.today()`/`task.upcoming()`,
`task.overdue()`, `project.list()`, `project.get(id)`, `project.tasks(id)`, `area.list()`,
`area.get(id)`, `area.contents(id)`.
**Write (auto — self-only):** `task.create/update/complete/cancel`, `task.schedule(id, window?)`
(→ §C level 2), `task.set_recurrence(...)`, `task.assign_to_project/area(...)`,
`project.create/update/archive`, `project.assign_to_area(...)`, `area.create/update/archive`.

## E. Proactive hooks — M6 Heartbeat, Tier-1 (LOCKED set 2026-06-09)
- **Morning plan** (daily cron) — "here's your day + open tasks; want me to time-block them?" (the
  flagship; the on-demand entry to the §C time-blocking capability).
- **Overdue nudge** (interval) — surfaces tasks past `due_at`.
- **Weekly review** (weekly cron) — projects/tasks/**areas** status digest.
- **NOT built (owner opted out 2026-06-09):** gap-fill suggestion + completion-check hooks. The
  time-blocking capability remains (via Morning plan + on request); Artemis just won't interrupt about
  free gaps or chase task completion.

## F. Recurrence — both modes (LOCKED 2026-06-09)
- **Fixed-schedule:** "every Monday", "1st of the month" — next instance due on the calendar regardless
  of when the last was done (rent, standing commitments).
- **Completion-based:** "N days/weeks after I last completed it" — next `due_at` computed from
  `completed_at` (water plants, replace filter).
- The `recurrence` representation carries a `mode` (`fixed | after_completion`) + the rule; on
  `task.complete` of a recurring task, the next instance is spawned per its mode.

## G. Capture — suggestion-inbox → written automation recipes (LOCKED 2026-06-09)
**You guide it at the start; the automation rules get written.** Two stages:
1. **Suggestion inbox (v1 default):** Artemis detects commitments anywhere it has awareness (chat,
   email, calendar) — "I'll send the report Friday" — and drops a **suggested task** into a tray the
   owner confirms/corrects with one tap. Captures from EVERY source, including **untrusted** email,
   without a misread/injection ever landing a phantom task on the real list (a suggestion is inert
   until the owner approves). Email-sourced suggestions carry their content through `artemis.untrusted`
   before any LLM-generative handling (mirrors gmail.md).
2. **Learned automation (the graduation):** as the owner repeatedly approves the *same kind* of
   capture, that recurring pattern is distilled into a **written, inspectable automation recipe** (M7-a2
   distill / M7-c curiosity → the recipe is a plain-language SKILL.md-shaped rule, NOT a black box).
   The owner approves it once on the **recipe Review screen** (M7-b), after which that capture happens
   automatically. This is the ADR-012 recurrence→recipe bridge applied to capture: **the automation
   rules are written (as recipes), guided by the owner.**

## H. Knowledge + memory integration
Push completed-project summaries → knowledge ("what did I ship last quarter"). Extract standing facts →
memory (working-hours patterns, recurring tasks, typical estimates) → feed back into `find_time` +
auto-scheduling. Source is trusted (owner-authored) → no `artemis.untrusted` layer (EXCEPT
email-sourced capture suggestions, per §G).

## I. Data
All owned SQLCipher under the owner-private scope (M2 wall): `areas`, `projects`, `tasks`, a
`task_subtasks`/checklist table, a recurrence representation (mode + rule), and a `suggestions` table
(the capture inbox: pending suggested tasks awaiting owner confirm). Artemis is authoritative; no
read-cache, no sync cursor, no external store. Schema detail → the M8-d spec(s) + `data-model.md`.

## Decisions (LOCKED 2026-06-09)
- Scope = **Tasks + Projects + Areas**; Habits/Goals deferred.
- Calendar integration = **full 3-level time-blocking** (capability); gap-fill + completion-check
  *hooks* opted out.
- Capture = **suggestion-inbox you guide → written automation recipes** (M7 loop / ADR-012 bridge).
- **No Google Tasks / no external integration** (owner decision) — purely Artemis-owned.
- Recurrence = **both fixed + completion-based**.
- **Areas in v1** (life-domain shelves above Projects).
- Hooks = **Morning plan + Overdue nudge + Weekly review** only.

## Spec decomposition (tentative — finalize at drafting)
- **M8-d-a** — Tasks + Projects + Areas core: owned SQLCipher schema (areas/projects/tasks/subtasks/
  recurrence/suggestions) + CRUD read/write tools + recurrence engine + `ModuleManifest`. No external
  deps beyond M1-a/M0-a/M2. Independent, buildable first.
- **M8-d-b** — Calendar time-blocking seam: `task.schedule` + the new `calendar.schedule_task` primitive
  + the Task↔Event link. Prereq: M8-d-a + CAL-b (write tools).
- **M8-d-c** — proactive hooks (morning plan / overdue / weekly review) + memory/knowledge integration
  + the suggestion-inbox capture path (+ the capture-recipe graduation wiring to M7). Prereq: M8-d-a +
  M6 + M3-a/M4-b + the M7 recipe loop.

## Deferred / future
- **Habits + Goals** (reuse the time-blocking rail).
- Sub-projects; gap-fill + completion-check proactive hooks; methodology opinionation.
- Google Tasks export — **explicitly not planned** (owner decision 2026-06-09).

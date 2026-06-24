# Cluster decisions — TASKS / PRODUCTIVITY (open-decision inventory)

_Decision-resolution pass for the Tasks + Projects + Areas + time-blocking + capture cluster.
Source-of-truth: `docs/technical/modules/productivity.md` (LOCKED 2026-06-09) + the four ready specs
`docs/changes/M8-d-{a,b,c1,c2}` + owner-rules `6-productivity.md` / `1-proactivity.md` /
`2-scheduling.md` / `7-cross-module-reactions.md` + status.md._

**What this pass found:** the module is heavily locked. The *engine* (schema, recurrence, time-block
seam, hooks, capture, graduation) is fully specced and frozen. The genuinely-open decisions are almost
all **owner-rule values not yet captured** or **gaps the owner-rules workbook explicitly surfaced** that
the frozen specs don't yet satisfy. Most force a re-spec/amendment at Mini-build time, not a rewrite.

Order = importance (owner-facing behaviour + blocks-a-spec first).

---

## 1. Hook schedule mismatch: WAKE-triggered digest vs the specced cron/interval hooks (BLOCKS M8-d-c1 re-spec)

**Context.** M8-d-c1 is frozen with three hooks on clock/interval triggers: morning-plan `cron="0 8 * * *"`,
overdue-nudge `interval_seconds=3600` (hourly), weekly-review `interval_seconds=604800`. But the owner's
captured proactivity rules (`1-proactivity.md`, RESOLVED 2026-06-19) want something materially different:
the morning plan + briefing **MERGED into one WAKE-triggered Morning digest** (fires on "good morning" /
first interaction, not 08:00); overdue nudge **~once daily folded into the digest** (not hourly); and the
weekly review **SPLIT** into a **Weekend review (Saturday wake, day-gated)** + a **Week-ahead review
(Sunday ~19:00 clock)**. M6 has no event/intent trigger class today (design gap #6). This is the single
biggest open item: the locked spec and the locked owner-rules disagree.

**Options.**
- **A — Re-spec M8-d-c1 + add the M6 wake/intent trigger now.** Honours owner intent fully; cost: new M6
  trigger type (event=wake + per-day-of-week gating) + a "good morning" intent + first-interaction
  detection, then rebuild the three productivity hooks around it. Largest scope.
- **B — Ship the frozen cron hooks as v1, defer the wake-trigger to a fast-follow.** Lowest build cost;
  owner gets an 08:00 ping instead of a wake ping until the follow-up lands. Diverges from captured intent.
- **C — Hybrid: keep overdue-nudge on interval, but build the wake trigger only for the merged Morning
  digest + Weekend/Week-ahead split.** Targets the highest-value divergence (the digest) while leaving the
  cheap deterministic nudge alone.

**Recommended default: A (re-spec + build the wake trigger).** The owner-rules workbook flagged this as a
real requirement three times and split the reviews deliberately; shipping 08:00 cron would build the wrong
thing. The trigger is also reused by other modules (Saturday-gated reviews, calendar). Resolve before
M8-d-c1 is built.

**UI implication: y** — the Morning digest is a primary surface on the client command-map; wake-trigger
changes when/how it appears.

---

## 2. Overdue-nudge cadence: hourly (specced) vs ~once-daily (owner)

**Context.** `1-proactivity.md` explicitly flags "hourly overdue nudge too frequent for gentle" and asks
for ~1–2×/day, folded into the Morning digest + optional midday check. The frozen M8-d-c1 hook is
`interval_seconds=3600`. Smaller than #1 but a distinct knob (cadence value, independent of the trigger
type).

**Options.**
- **A — Once daily, folded into the Morning digest.** Matches "gentle nudges"; simplest mental model.
- **B — Twice daily (digest + one mid-afternoon check).** Owner's stated upper bound; catches same-day
  slippage.
- **C — Keep hourly but dedup so it only *notifies* once/day.** Engine stays as specced; the dedup_value
  already nearly does this (`f"{_today_iso()}-{len(overdue)}"` re-fires when the count changes).

**Recommended default: B (twice daily).** Owner said "once or twice"; a midday check is cheap and the
deterministic template hook (`needs_llm=False`) is near-zero cost. Pick the cadence value at the same time
as #1 since both touch the same hook file.

**UI implication: n** (notification cadence only; no new screen).

---

## 3. `preferred_focus_window` — morning-bias slot pick vs earliest-free (gap on M8-d-b + CAL-a)

**Context.** `2-scheduling.md` RESOLVED (2026-06-19): time-block slot pick should **prefer mornings
(~09:00–12:00) for deep-work blocks, falling back to earliest**. But M8-d-b's `schedule_task` is frozen to
pick `slots[0]` (earliest free slot), and `CalPrefs` has no `preferred_focus_window` field. The owner-rules
INDEX lists this as spec gap #8. Function decision (slot-pick policy), not just a value.

**Options.**
- **A — Add `preferred_focus_window` to CalPrefs + bias `schedule_task` to prefer in-window slots.**
  Honours intent; cost: one CalPrefs field + a slot-ranking tweak in the primitive (prefer earliest slot
  *within* the window; else earliest overall). Touches the frozen M8-d-b primitive.
- **B — Leave earliest-first; owner overrides per-task via the `window` arg.** Zero spec change; pushes the
  burden onto the owner every time.
- **C — Make morning-bias a global toggle (on by default) rather than a window field.** Simpler config;
  loses the explicit 09:00–12:00 band the owner gave.

**Recommended default: A.** The owner gave a concrete window and a clear fallback rule; biasing slot pick
is a small, well-scoped amendment to M8-d-b + CAL-a. Also feeds the calendar free-gap focus-protect hook
(defend morning gaps first).

**UI implication: n** (back-end scheduling; the resulting block shows on the calendar either way).

---

## 4. `working_days` field — weekends off (gap on CAL-a, affects every time-block)

**Context.** Owner confirmed **Mon–Fri, weekends off** (`2-scheduling.md`). But `find_time` / `CalPrefs`
key off working *hours*, not *days* — so today `schedule_task` would happily place a focus block on
Saturday. Owner-rules INDEX spec gap #1. This is a productivity-facing correctness bug for time-blocking
(the cluster consumes `find_time`), even though the field lives in the Calendar module.

**Options.**
- **A — Add `working_days: list[int]` to CalPrefs; `find_time` excludes non-working days.** Correct; small
  field + filter. Default `[Mon..Fri]`.
- **B — Approximate via a recurring "weekend = busy" overlay event.** No schema change but hacky, leaks
  into the event cache, and fights the time-blocking logic.

**Recommended default: A.** It's a one-field schema add with an obvious default; without it every
auto-scheduled task can land on a weekend, directly contradicting captured owner intent. Flag to the
Calendar/Integration cluster as the owning module, but it gates correct task time-blocking.

**UI implication: n.**

---

## 5. Habits + Goals sub-domains — build now, or stay deferred?

**Context.** `productivity.md` defers **Habits + Goals**, with the time-blocking rail "reserved" so they
slot in later without rework. status.md Parked list still carries them. Separately, the **GOAL entity** is
already created eagerly per-project (M8-d-a Decision D3 → `project_goal_entity_id`), and cross-module
reactions C3c/C7 reference a "Goal-progress loop" gated on Goals existing. So a *thin* Goal surface is
half-present (the entity) but there's no Goal **module** (no goal CRUD, no goal review, no Habits at all).

**Options.**
- **A — Stay deferred (status quo).** Lowest scope; the rail is reserved; Goal entity already supports the
  entity-link reactions. Habits/Goals as full sub-domains wait for a later milestone.
- **B — Build a thin Goals surface now** (Goal CRUD + surface-in-week-ahead, no Habits): unblocks C3c/C7
  Goal-progress reactions and gives the eagerly-created GOAL entity a real home. Habits still deferred.
- **C — Build both Habits + Goals now** using the reserved time-blocking rail (Habits project onto open
  slots like tasks). Fullest scope; matches the "rail reserved for exactly this" design note.

**Recommended default: A (stay deferred), with a flag** that the Goal *entity* already exists so C3c/C7
reactions can link to it on-demand without a Goals module. Per the owner's prefers-end-state-scope memory,
surface B/C as the explicit upgrade if the owner wants the Goal-progress loop live at v1 — but nothing in
the captured rules demands Habits yet, and the rail is genuinely reserved, so deferral carries no rework
cost. **Ask the owner which.**

**UI implication: y if B/C** — Goals/Habits would each be a cluster on the command-map; defer = no new
surface.

---

## 6. Email→task capture TRIGGER — engine built, nothing calls it (defer wiring to Integration cluster)

**Context.** M8-d-c2 builds the full capture engine: `CaptureService.suggest_from_text(source="email",
untrusted=True)` routes raw mail through DR-a quarantine → inert suggestion → graduation. But **nothing in
the specs calls it on incoming mail** — there is no proactive capture hook (§E is reactive-only by design),
and the Gmail spoke doesn't invoke `suggest_from_text`. Cross-module reaction **A4** ("email contains a
commitment → capture a suggestion") is marked ✅-in-specs but the actual trigger wiring is unbuilt. The
*productivity-side* contract is complete and frozen; the open question is purely **who fires the trigger
and when** (per-incoming-mail? batched? on the Gmail urgency-scan tick?).

**Options (noted, not resolved here — this is cross-spoke).**
- A — Gmail spoke calls `suggest_from_text` per relevant incoming mail (during its existing scan).
- B — A new reaction-layer dispatcher (ADR-021) fans email events to the capture service.
- C — A dedicated capture pre_tick_step on the heartbeat.

**Recommendation: DEFER to the Integration / cross-spoke agent.** The productivity engine needs no change;
this is reaction-wiring under ADR-021 (A4). Flagged here so the cluster inventory is complete; the trade-off
belongs to whoever owns cross-module reaction dispatch.

**UI implication: n** (the suggestion inbox UX is #7; the trigger is back-end).

---

## 7. Suggestion-inbox acceptance UX — one-tap confirm/correct surface (function decision forcing a UI choice)

**Context.** `productivity.md` §G describes the suggestion inbox as a tray the owner "confirms/corrects
with one tap." The data layer is built (`suggestions` table, `suggestion.list/accept/reject` tools,
`accept_with_graduation`). But the **acceptance interaction model** is undefined: accept-as-is vs
accept-with-edits (project/area/due override — the tools support `project_id`/`area_id`/`due_at` on accept),
batch-accept, and what correction signal feeds graduation. Function decision: does correcting a suggestion
(changing its project/shape) count toward the graduation pattern key, or only a clean accept?

**Options.**
- **A — One-tap accept + optional inline edit (project/area/due); any accept (edited or not) counts toward
  graduation.** Simplest; matches the §G "confirm/correct with one tap" wording.
- **B — Accept vs Accept-and-edit are distinct; only clean accepts count toward graduation.** More precise
  graduation signal (only un-corrected patterns auto-graduate), but more taps and a subtler model.
- **C — Batch review (accept-all / reject-all for a source) in addition to per-item.** Faster at volume;
  risks bulk-accepting a misread.

**Recommended default: A.** The captured intent is explicitly "one tap"; counting all accepts toward
graduation is the simplest faithful reading and the spec's `capture_pattern_key` already collapses on
source+shape (edits to project/area don't change the shape). Note for the UI cluster: this needs a
dedicated inbox surface with inline project/area/due editing.

**UI implication: y** — the suggestion inbox is a client surface; this decides its interaction affordances.

---

## 8. Areas vs Projects taxonomy edges — orphan tasks, archived-area children, area auto-tagging

**Context.** Model is locked (Area = ongoing responsibility, never completes; Project = finite; task may
attach to Area directly OR via Project). But a few behavioural edges are unspecified: (a) **archive_area
does NOT cascade** (specced — projects/tasks keep their `area_id`), so an archived area can still own active
tasks — is that surfaced anywhere or silently orphaned? (b) **area auto-tagging**: owner-rules INDEX gap #5
wants a `needs_review` state + confidence floor on "Productivity areas" auto-tagging (precision-first), but
the frozen M8-d-a has no auto-area-assignment at all (areas are set explicitly). (c) a task with neither
project nor area — fully valid, but does it surface in any review?

**Options.**
- **A — Accept the locked behaviour as-is; areas are manual-only, no auto-tag, archived areas keep
  children visible via `area_contents`.** Zero change; defers the auto-tag gap.
- **B — Add area auto-tagging with a `needs_review`/confidence floor** (per INDEX gap #5) so Artemis can
  suggest an area for a new task/project. New capability; matches the cross-cutting precision-first tagging
  rule the owner set.
- **C — Just add the safety surfacing** (weekly review flags active tasks under archived areas + fully
  un-filed tasks) without auto-tagging.

**Recommended default: A for v1, with B flagged as the cross-cutting tagging gap.** Auto-area-tagging is
part of the broader `needs_review`/confidence-floor decision (memory, email, ingestion, finance all share
it) — resolve it once at the cross-cutting layer rather than productivity-locally. The locked manual model
is coherent and shippable now.

**UI implication: y if B** (a "suggested area · needs review" affordance); n for A.

---

## 9. Runtime-config layer vs code-constant transcription (cross-cutting, affects all productivity knobs)

**Context.** owner-rules INDEX "Deferred architecture question": do the captured values (recurrence grammar,
priority vocab, upcoming-window, commitment-shape vocab, hook cadences, focus window) become a real
**externalized owner-editable runtime-config layer** (`policy.json`-style, edit without code) or stay as
**code constants the coder transcribes**? `1-proactivity.md` already hints the proactivity rules are
"designed as an owner-editable `policy.json`." This is cluster-wide but lands hard on productivity because
it has the most owner-tunable knobs.

**Options.**
- **A — Code constants transcribed at build (status quo default).** Simplest; re-tuning = a code edit +
  redeploy on the Mini.
- **B — Externalized runtime-config layer** (owner edits JSON/UI, no redeploy). Matches the long-term
  vision; cost is a config-loading layer + validation across modules.
- **C — Hybrid: high-churn knobs (hook cadences, focus window, quiet hours) externalized; structural ones
  (recurrence grammar, enums) stay constants.** Targets the values most likely to be re-tuned against live
  behaviour.

**Recommended default: C (hybrid).** The owner-rules explicitly mark cadence/window/quiet-hours as
"tune on-Mini against real volume" (high-churn) while recurrence grammar and enums are structural. A
config layer for the churny ones avoids redeploy-to-retune; the rest stay as constants. This is a
cross-cutting decision — flag to whoever owns the config/runtime layer, but productivity is the heaviest
consumer.

**UI implication: y if B/C** (an owner settings surface on the client); n for A.

---

## Already resolved / locked (excluded from the open list — appendix)

These were checked and are **not** open:

- **Scope = Tasks + Projects + Areas** — LOCKED 2026-06-09. (Habits/Goals deferral is itself revisited in #5.)
- **Time-blocking = full 3-level capability; gap-fill + completion-check hooks opted OUT** — LOCKED.
  (D3 free-gap reaction also DROPPED in `7-cross-module-reactions.md`, consistent with the opt-out.)
- **Recurrence = both fixed + completion-based**, with drift policy (calendar rules snap to boundary;
  interval rules advance from `due_at`), month-overflow clamp, fixed grammar — LOCKED (M8-d-a, owner-rules §6).
- **No Google Tasks / no external integration** — owner decision LOCKED 2026-06-09.
- **Capture = suggestion-inbox → written automation recipes**, graduation threshold N≥2, TOUCHES_DATA →
  gated → never auto-enabled — LOCKED + specced (M8-d-c2); status.md marks it RESOLVED + built.
- **Email-capture quarantine-first** (`raw_context=None`, suggestions inert until accept) — FROZEN
  invariant (owner-rules §6 🔒).
- **Hook LLM payloads = counts + IDs only** (injection boundary) — FROZEN invariant; v1 briefing is
  counts-only (M6-b has no store access).
- **GOAL entity created eagerly per project** (Decision D3, contracts.md Seam 6) — LOCKED; M4 is the entity
  backbone (ADR-013), PLACE/GOAL created on-demand by owning spokes.
- **Task↔Calendar link integrity** (write-after-success, auto-cancel old block on re-schedule, clear link
  on complete, Google event NOT auto-deleted) — LOCKED (M8-d-b + `7-cross-module-reactions.md` C1/C4).
- **Tools all auto (self-only writes, no gating)**; module = OWNER_PRIVATE / Tier-1 — LOCKED (ADR-011).
- **Priority vocab** (`none/low/medium/high`), **upcoming window** (7d), **commitment-shape vocab**,
  **search cap** (50) — captured defaults accepted (owner-rules §6); values can still be over-typed but no
  decision is pending.
- **Cross-module reaction TRIAGE** (which C-cluster reactions to keep) — DONE 2026-06-20; runtime model
  LOCKED → ADR-021 (hybrid learned-first). The remaining open item is only the email-capture *trigger
  wiring* (#6), which is cross-spoke.

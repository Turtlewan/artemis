# Owner Rules — 2. Scheduling Preferences

_Feeds: CAL-a (`CalPrefs` + find_time) · M8-d-b (time-blocking). Calendar hook *timings* live in
`1-proactivity.md` §Hook schedule; this file is your scheduling *preferences*._

Status: ⬜ not started

## On the Mini
These become `CalPrefs` (one config object, `CAL-a/preferences.py`) + the time-blocking primitive defaults.

## Tunable rules
| Rule | Default | Lands in | Your value |
|------|---------|----------|------------|
| ⭐ Timezone | `UTC` (some code defaults SGT) | `CalPrefs.timezone` | **`Asia/Singapore` (SGT, UTC+8)** — standardize ALL specs to this; resolves the UTC/SGT mismatch |
| ⭐ Working hours start/end | `09:00 / 18:00` | `CalPrefs.working_hours_start/end` | **`09:00 / 18:00`, Mon–Fri** (confirmed) |
| ⭐ No-meeting-before / -after | `09:00 / 18:00` | `CalPrefs.no_meeting_before/after` | **`09:00 / 18:00`** (no meetings outside work hours) |
| ⭐ Inter-meeting buffer | `15 min` | `CalPrefs.buffer_minutes` | |
| ⭐ Focus-block duration | `90 min` | `CalPrefs.focus_block_duration_minutes` (also M8-d-b) | |
| Default write calendar | `primary` | `CalPrefs.default_write_calendar` | |
| Default reminder lead | `10 min` | `CalPrefs.default_reminder_minutes` | |
| Sync window (past / future) | `12 / 12 months` (perf knob) | `CalPrefs.sync_window_months_past/future` | |
| Time-block default search window (when unset) | `now → now+7d` | M8-d-b primitive default | |
| Time-block slot pick policy | earliest free slot | M8-d-b primitive | **Prefer MORNING for focus/deep-work blocks** (~09:00–12:00); fall back to earliest if no morning slot. |
| Preferred focus window (NEW pref) | — (not modelled) | CalPrefs add `preferred_focus_window` | **09:00–12:00** (mornings) |

## Notes / open
- **⚠️ Weekend = off (Mon–Fri only), but `CalPrefs` has no "working days" field today.** `find_time`
  and the free-gap hook key off working *hours*, not *days*, so they'd happily suggest Saturday
  slots. Capturing "weekends off" means adding a `working_days` knob — a small spec gap to confirm. →
- Secondary knobs left at default unless changed: buffer `15m`, focus-block `90m`, reminder lead
  `10m`. Say the word to retune any.
- `owner_email` is derived from the `primary` calendar on first sync — not captured here.
- ✅ **Slot pref RESOLVED: mornings for deep work** (owner 2026-06-19). Spec gap: CalPrefs/M8-d-b
  don't model a time-of-day block preference — add `preferred_focus_window` (~09:00–12:00) and bias
  the free-gap focus-protect hook to defend morning gaps first.

## 🔒 Frozen invariants (not owner-tunable)
- `find_time` algorithm (available band = `max(working_start, no_meeting_before) → min(working_end,
  no_meeting_after)`, ≤10 slots earliest-first) — *inputs* are your prefs above; the logic is fixed.
- Attendee gate, tentative-projection mechanics → see `3`/security; not scheduling prefs.

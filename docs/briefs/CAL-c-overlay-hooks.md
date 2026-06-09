# Brief: CAL-c — proposal/hold overlay (+ Google tentative projection lifecycle) + proactive hooks

- **For:** AFK Deep Details drafting · **autonomy_level:** L2 · **token_profile:** balanced
- **review_domains:** security, ai-systems  _(security: the projected-hold lifecycle must not leak holds to others or desync; Tier-1 hook gating while locked; ai-systems: the hooks that compose LLM briefings/nudges — but the untrusted quarantine itself is CAL-d, so flag any hook that renders external text before CAL-d lands)_
- **Read first:** `docs/briefs/CAL-shared.md` · `docs/technical/modules/calendar.md` §C,§D · M1-a · M6-a (Heartbeat/HookSpec) · M8-a · M2
- **Build order:** after CAL-b (modifies the manifest; uses CAL-a sync/cache + CAL-b write-through).

## Intent
The Artemis-native **proposal/hold overlay** (§C) with **Google tentative projection** (shared decision
3) and the **proactive hooks** (§D) the M6 Heartbeat runs. This is the "active calendar manager" layer.

## Scope / files (proposed — drafter finalises)
- `src/artemis/modules/calendar/overlay.py` — overlay SQLCipher store + `propose_*` / `hold_tentative` / `list_proposals` / `approve_proposal` / `reject_proposal` + the Google-tentative projection lifecycle (marker, proposal_id↔google_event_id map, approve=promote, reject=delete)
- `hooks.py` — the §D `HookSpec`s (daily briefing, upcoming-event reminder, change-detection→drives CAL-a `sync()`, conflict alert, free-gap focus-protect→emits a proposal, unanswered-invite nudge, prep nudge)
- `manifest.py` (**modify** — add proposal tools + `proactive_hooks`)
- `tests/test_calendar_overlay_hooks.py`

## Resolved decisions (from CAL-shared — bind)
- Holds projected to Google as `status:"tentative"` + native overlay row; marker `extendedProperties.private.artemis_overlay=<proposal_id>`; CAL-a sync already recognizes the marker (own-projection).
- approve → promote (tentative→confirmed update, or create real event) + clear hold; reject → delete projected event + mark rejected. Projected holds are self-only → auto write-through.
- Hooks are **Tier-1** (queued while vault locked, ADR-006). change-detection drives sync cadence (calls CAL-a `sync()`).
- ⚠️ **`check_ref` signature:** M1-a declares `Callable[[], bool]`; calendar.md says `HookResult`. **Bind to the real M6-a Heartbeat hook contract**; park `[NEEDS CLARIFICATION]` if they conflict.
- **Intentions projection** (render Habits/Goals onto open slots) needs the Productivity module, which is **not built** → ship the hook/seam as a documented stub that no-ops until Productivity exists; do NOT block CAL-c on it.

## Tasks (concern layers)
1. Overlay store + `propose_*`/`hold_tentative`/`list/approve/reject` with the projection lifecycle (marker write, id map, approve-promote, reject-delete).
2. The §D `HookSpec`s (check_ref bound to M6-a; deterministic checks; Tier-1; dedup keys; urgency).
3. Wire change-detection hook → CAL-a `sync()`; free-gap hook → emits a proposal.
4. Manifest modify (proposal tools + hooks).
5. Tests (fakes): projection lifecycle (hold→tentative-on-Google→approve-promotes / reject-deletes); marker round-trips with CAL-a sync (no double-count); hooks fire deterministically; locked → queued (Tier-1); intentions-stub no-ops.
6. (GATED on-hardware) real hold projection + approve/reject against Google; real change-detection via syncToken.

## Acceptance shape
mypy --strict + ruff clean; pytest proves the hold projection lifecycle + marker reconciliation with sync + deterministic hook firing + Tier-1 queueing; gated on-hardware = real projection + change detection.

## Out of scope / deferred
Read/write tools (CAL-a/b); knowledge/memory push + untrusted quarantine (CAL-d); learned proposal auto-escalation; email negotiation. Intentions projection beyond a no-op stub (awaits Productivity).

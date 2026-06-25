# Cluster Decisions — LOG (the locked answers)

_Personal-productivity cluster: Gmail · Calendar · Tasks · Finance · Integration · UI.
Decision-resolution pass before any spec/build (owner: "answer every decision up front").
Open forks live in `docs/findings/cluster-decisions/{area}.md`; this file records the **answers**.
Status: **LOCKED** = owner-decided · **PROPOSED** = recommended default, accepted unless vetoed · **PENDING** = not yet walked._

**Owner patterns noted:** (1) external-effect writes are **held until owner approval** (clean external systems). (2) "Build everything fully" = the **named cluster done properly**, NOT adjacent extras — scope-disciplined (deferred Habits/Goals).

---

## Cross-cutting (resolved once)
- **X1 — `working_days`** — LOCKED: Mon–Fri (no weekend auto-scheduling).
- **X2 — `preferred_focus_window`** — LOCKED: morning bias, earliest-fallback.
- **X3 — runtime-config layer** — LOCKED: **A** — build a thin owner-editable config layer for all tunable values (VIP list, keywords, schedules, thresholds…); structural constants stay in code; the client settings UI reads/writes it later. (No rebuild to tune behaviour.)

## Gmail — COMPLETE
D1 A (OR-in admit) · D2 A (bank exclude) · D3 A (hybrid VIP, admit) · D4 A (send deferred) · D5 A (read-only) · D6 A (default tunables) · D7 A (no floor on Gmail labels).

## Calendar — COMPLETE
C3 location+optional buffer (Maps deferred) · C4 defer other-people scheduling · **C5 B (tentative HOLD in Artemis until approved)** · C6 free-gap propose-only 1/day morning · C7 recurring-edit THIS_EVENT+elicit · C8 single SGT.

## Tasks — COMPLETE
- **T1** LOCKED: wake-triggered rhythm ("good morning" → Morning digest w/ fixed-time fallback; Sat-wake Weekend review; Sun-19:00 Week-ahead) — re-specs M8-d-c1 + adds an M6 wake trigger.
- **T2** LOCKED: overdue folds into digest (~1–2/day, gentle).
- **T5** LOCKED: **C — defer both Habits + Goals** (Goal entity stays for linking; no modules). Cluster stays tight.
- **T8** LOCKED: taxonomy defaults (archived-area tasks → "no area"; area auto-tag carries needs_review floor).
- T7 → UI (suggestion-accept UX).

## Finance — IN PROGRESS
- **F-D1** LOCKED: schema designed for end-state, awareness slice used in v1 (one schema, no migration).
- **F-D3** LOCKED: fixed SG seed categories + owner add/rename; flat.
- **F-D4** LOCKED: bank sender-allowlist + receipt classifier; quarantine-first.
- **F-D5** LOCKED: generic column-mapped CSV importer + manual entry.
- **F-D6/7/8** LOCKED: tight reconciliation defaults; type = model+rules, ambiguous→ask; recurring at 2 occurrences.
- **F-D11** LOCKED: account table (FK).
- **F-a — v1 capability scope** — LOCKED: baseline (auto-track + categorize + on-demand Q&A) **+ unusual-spend flagging + bill reminders & "handling"** (active bill lifecycle: open→paid status, reconciliation, task linkage → Integration). **Net-worth view DEFERRED** (not selected). Category budgets/envelopes deferred (locked). The "handling" verb = bill→task + payment→mark-paid reactions (route to Integration).
- **F-b — bank-data stance** — LOCKED: **A** — manual + email/receipt extraction + CSV only; **no bank link, ever**. Gaps filled by import/manual.

## Integration / reactions — IN PROGRESS
- **I-1 — Email→Task** — LOCKED: dispatcher-detects-commitment in a signal email → inert task **suggestion** (existing `CaptureService`, M8-d-c2); owner accepts. (Matches approval pattern.)
- **I-2 — Email→Calendar** — LOCKED: dispatcher-detects-event (flight/meeting) → **held tentative event** (per C5=B, NOT written to Google until approved) via a new `calendar.create_from_extract`.
- **I-3 — Fraud confirm threshold** — LOCKED: ~S$500 + ±7d window as a tunable config knob (X3), re-tune on Mac.
- **I-6 — Per-reaction tiering** — LOCKED: extend learned-first to all gate-passing reactions; ratify the list once.
- **I-7 — Link-integrity reconciler** — LOCKED: auto-repair deterministic half-links, flag fuzzy; nightly sweep.
- **I-8 — Stateful reaction state home** — LOCKED: spoke owns domain state; dispatcher keeps a thin idempotency ledger.
- **I-10 — GATE posture (auto-creations)** — LOCKED: internal/reversible (task suggestion, memory fact, held tentative) act automatically with an **undoable notice**; external-effect (invites, payments) **hold for approval**. (Owner pattern.)
- **I-11 — Gift-signal + clip channel** — LOCKED: ship gift-signal memory category + email-to-self clip now; defer the iOS Share Extension.
- **I-12 — Migrate legacy pushes** — LOCKED: migrate only where observability/links/graduation add value; leave dumb notifiers.
- _(I-9 config layer = X3.)_
- **I-4/5 — v1 reaction scope** — LOCKED: **ALL reactions** (full A–E set surviving triage) + **de-park the Trip entity** + **de-park the Maps connector** (travel-time). Pulls in the full 5-capability dependency set. The triage's own reclassifications stand (E8 = hub view, D3 dropped — these were never reactions). Maps real API key is owner-present (Mac), faked on dev.

## UI — IN PROGRESS
- **Glance cards** — LOCKED: Gmail="N need you" (signal, not unread) · Calendar="N events today" + pending/conflict accent · Tasks="N due today" (overdue accent) · Finance=MTD-spend headline + bill-due badge (spend excludes transfers).
- **Map placement** — LOCKED: inner ring near core — Gmail→Comms, Calendar+Tasks→Planning, Finance→Self.
- **Detail actions split** — LOCKED: self-only acts inline; external-effect stages to Review.
- **Finance/S$500** — LOCKED: finance v1 = instant local edits, no action-gate; confirm only on dup-merge; S$500 is the fraud-*alert* threshold only (notification, not a UI gate).
- **Gated actions** — LOCKED: Review card = authoritative pending count + top-bar indicator; approvals in Review (no ntfy-button actions).
- **Sensitivity held-back** — LOCKED: per-item "held back / include & redo" chip row under the Ask answer; accent; audited (ADR-029).
- **Capture inboxes** — LOCKED: on their originating card's detail + glance badge (separate from Review).
- **ntfy** — LOCKED: read-only echo; tap→Home; deep-link fast-follow.
- **Ask pop-up** — LOCKED: answers + acts (inline writes; gated→Review); spans all four.
- **Lock-state** — LOCKED: glance counts mask while Vault locked; map shape stays visible.
- **Fonts** — LOCKED: deferred (Space Grotesk + Inter).
- **Expanded-card detail views** — LOCKED:
  - **Gmail:** urgency "needs you" list (sender·subject·why-flagged) + browsable signal mail + search; tap→spotlighted reader; open-in-Gmail (no send v1); inline accept task-suggestion / approve held event.
  - **Calendar:** **Month + Week toggle** + a **selected-day panel** (pick a day → its events AND tasks-due). Held-tentatives distinct; RSVP strip; approve-held→Google, self-edit inline, invites→Review, morning find-time. *(Tasks-due-on-day = a Tasks↔Calendar view link.)*
  - **Tasks:** tasks-only — Due/Overdue/Upcoming + capture inbox; check/reschedule/time-block(morning)/accept-suggestion/quick-add.
  - **Finance:** **compact / no-cards awareness page** (confirmed 2026-06-24 via `docs/research/mockups/finance-page.html` — supersedes the earlier "weekly spend dashboard = bar + pie chart"): a **week-to-date daily-spend list** (weekday+date · S$amount; today marked with an accent divider below it; upcoming days "—") + Week/MTD figures · a **leader-line category donut** (slices connected out to name/% labels; total in centre) · transactions · Bills strip (inline mark-paid) · unusual-spend flag · duplicate-merge · confirm-type. Posture unchanged: **awareness-only, instant local edits, no action-gate, no bank link, S$500 = alert-only.**
  - **Projects (NEW separate card):** detail designed in its own pass (its own module).

## Structural / architecture changes from this pass (ripple into existing specs)
- **Productivity spoke splits** — **Tasks module + Projects module** (separate cards in the Planning cluster). Currently bundled in M8-d (Tasks+Projects+Areas). → re-architect M8-d-a; 30 auto-tools split across two modules.
- **Areas DROPPED** — no life-domain layer. Two levels: Projects→Tasks; standalone tasks float. → remove `areas` table + `area_id` from M8-d-a schema/tools; T8 "archived-area" decision is moot.
- **M8-b2 (Gmail urgency)** — amend per D1 (OR-in topic+VIP admit), D2 (bank-sender exclude), D3 (hybrid VIP, force-admit).
- **M8-d-c1 (hooks)** — re-spec to the wake-triggered digest rhythm (T1) + new M6 wake trigger.
- **CalPrefs** — add `working_days` (X1), `preferred_focus_window` (X2); C5 hold-tentative-until-approved overlay change.
- **New builds queued** — the sensitivity gate (ADR-029, 6 specs) · the full reaction layer + dispatcher + Trip entity + Maps connector (ADR-021, all reactions) · the Finance spoke (FIN-*, no prior specs) · the Projects module · the 7 UI Tauri specs (ADR-028) incl. the per-domain detail views above · a thin runtime-config layer (X3).

---
**✅ DECISION PASS COMPLETE — 2026-06-23.** All six areas (Gmail · Calendar · Tasks · Finance · Integration · UI) resolved. This record is the input to spec-writing.

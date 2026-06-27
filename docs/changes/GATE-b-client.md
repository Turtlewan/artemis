---
status: ready
weight: light
cross_model_review: false
coder_effort: medium
---

# GATE-b-client — pending-actions review surface (Tauri)

## Intent
The Tauri client surface for the one-off pending-action approval flow (ADR-012 §4): a "Pending
actions" section on the existing Review screen where the owner approves/rejects staged
external-effect actions. This is the **Tauri re-scope of GATE-b's client half** — the original
GATE-b Swift/ArtemisKit Tasks 4–8 (`WireModels`/`ApiClient`/`ReviewScreen.swift`) are superseded by
this spec; GATE-b now ships only the brain endpoints. Mirrors the already-built **recipe-review**
surface exactly (gateway transport fn → `app_*` command → `ReviewDetail.tsx` section).

## Prerequisites
- **GATE-b (brain)** — the `/app/actions/pending|approve|reject` endpoints + `app.state.action_staging`
  (GATE-b Tasks 1–3). Build/serve those first; this spec consumes them over the wire.
- **CLIENT-core / CLIENT-screens** — built: `gateway.rs` (`request_json`, Bearer-from-Rust per
  ADR-030), `app_review_*` recipe-review fns (the template), `client/src/screens/ReviewDetail.tsx`
  (the surface to extend), `dtos.ts`, `client/src/api/gateway.ts`.

## Key decisions
- **Mirror the recipe-review wiring verbatim** — same transport shape, same command-registration,
  same `ReviewDetail` section pattern. No new mechanism; actions are review's structural twin.
- **`args` is never sent to the client** (the brain already excludes it from `PendingActionResponse`)
  — the surface renders `summary`/`tool`/`module`/`expires_at` only.
- **Optimistic UI with restore-on-error** — approve/reject removes the row immediately; a 404
  (gone) / 409 (already settled) / 423 (vault locked) restores it and surfaces a recoverable message;
  423 also routes through the existing `connection`/locked handling (re-lock), never a silent fail.
- **No new capability grant needed** — app-defined `#[tauri::command]`s are invokable like the
  existing `app_review_*` (only core/global-shortcut are in `capabilities/default.json`); confirm at
  build, grant window-`"main"` only if the recipe-review commands turn out to be granted.

## Gotchas / edge cases
- **`approve` is the highest-privilege action in the app** (it executes an external-effect tool).
  The gate is brain-side (`require_unlocked` → 423 if the vault idle-locks mid-dispatch); the client
  must surface 423 as a re-lock, not an error toast.
- **Accessibility (apex-accessibility), carry from the Swift spec:** Approve/Reject controls carry the
  action **summary** in their accessible name (not bare "Approve"/"Reject" — disambiguates rows,
  WCAG 1.3.1); the "expires soon" indicator is **text + icon, never colour alone** (WCAG 1.4.1);
  Approve and Reject stay **individually focusable** (don't merge the row into one a11y element,
  WCAG 2.1.1); touch targets **≥44px** (WCAG 2.5.8); a proper empty state ("No pending actions").
- **Field/status mapping:** `status` is lowercase (`pending|approved|rejected|expired`),
  `action_class` is always `"takes-action"`, timestamps are ISO-8601 — match the brain
  `PendingActionResponse` exactly (a snake_case/camelCase or date-format mismatch fails the decode).

## Tasks
1. Transport + DTO + commands — files: `client/src-tauri/src/gateway.rs`, `client/src-tauri/src/lib.rs`,
   `client/src/api/gateway.ts`, `client/src/screens/dtos.ts` — mirror the `app_review_*` trio:
   in `gateway.rs` add a `PendingAction` response struct (id/module/tool/summary/action_class/status/
   created_at/expires_at/result — **no `args`**) + internal transport fns `actions_pending`
   (GET `actions/pending`), `actions_approve` (POST `actions/approve` `{id}`), `actions_reject`
   (POST `actions/reject` `{id}`) + their `app_actions_*` `#[tauri::command]` wrappers; register the
   three in `lib.rs invoke_handler!`; add `actionsPending()/approveAction(id)/rejectAction(id)` to
   `gateway.ts`; add the `PendingAction` TS type to `dtos.ts`. — done when: `cargo check` + `tsc
   --noEmit` exit 0; the three commands are in `invoke_handler!`; a `gateway.rs` round-trip test
   (mock transport) verifies the three paths/bearer/JSON-body and the `args`-absent decode.
2. "Pending actions" section in `ReviewDetail.tsx` — files: `client/src/screens/ReviewDetail.tsx`,
   `client/src/screens/ReviewDetail.test.tsx` — add a "Pending actions" section **above** the recipe
   section: reader = `gateway.actionsPending`; a `PendingActionRow` (summary, `module.tool` caption,
   text+icon "expires soon" when `<1h`, Approve + Reject buttons with summary-bearing accessible
   names, ≥44px); optimistic remove + restore-on-(404|409|423); 423 → existing locked handling; empty
   state. Honour the a11y checklist above. — done when: `tsc --noEmit` + `npx vitest run` pass;
   `ReviewDetail.test.tsx` covers: list renders without `args`; approve optimistic→stays-removed on
   200; approve restores + message on 409; reject restores on 404; 423 on either restores + triggers
   the locked path; the recipe-review section still renders (regression).

## Files to touch
- `client/src-tauri/src/gateway.rs` — modify (PendingAction struct + 3 transport fns + 3 commands)
- `client/src-tauri/src/lib.rs` — modify (register `app_actions_*` in `invoke_handler!`)
- `client/src/api/gateway.ts` — modify (3 invoke wrappers)
- `client/src/screens/dtos.ts` — modify (`PendingAction` type)
- `client/src/screens/ReviewDetail.tsx` — modify ("Pending actions" section + `PendingActionRow`)
- `client/src/screens/ReviewDetail.test.tsx` — modify (the cases above)

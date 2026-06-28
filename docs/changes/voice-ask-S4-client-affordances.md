---
spec: voice-ask-S4-client-affordances
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: voice-ask-S4 — overlay voice affordances (mic button + speak/mute toggle + speaking indicator + restore streaming display)

**Identity:** Tauri/React overlay affordances for ADR-034: restore `askStore.send` to consume the streaming `askStream` channel (regressed to non-streaming `ask()`), add a session-scoped speak/mute toggle (speaks-by-default, remembers last state) threaded as `speak` on the request, a mic push-to-talk button, and a speaking indicator. → why: docs/technical/adr/ADR-034-unified-voice-text-ask.md §B (new seam 5, §D mute) + design-brief §1c/§3.

<!-- Split note: 2 source + 2 test files. Atomic exception (precedent: CLIENT-ask shipped the overlay as one cohesive unit) — the store change and the affordances that drive it are mutually dependent. -->

## Assumptions
- The streaming transport already exists end-to-end: Rust `app_ask_stream` + TS `askStream` generator (client/src/api/gateway.ts) are live; ONLY `askStore.send` (askStore.ts:142) still calls non-streaming `ask`. S4 rewires the store; it does not build new transport. → impact: Stop.
- `AskPopup` renders the dialog; `AskWindow` mounts it as the floating window. Tests use vitest + RTL with mocked `@tauri-apps/api/core` `invoke`/`Channel` and a mocked connection store. → impact: Caution.
- S1 adds `speak` to the brain `AskRequest`; the TS `AskRequest` DTO + the Rust `AskRequest` gain `speak: boolean`/`speak: bool`. The mic button triggers brain-side PTT via a NEW `app_ask_voice` command — that Rust command is S2/S3 integration, OUT of S4's vitest surface; S4 calls it behind an injectable `onVoiceTrigger` seam (mocked in tests). → impact: Caution (cross-spec dependency, noted below).
- Mute is session-scoped, not auth-scoped (ADR-034 defaults); persisted in-memory for the session, remembering the last toggle state. → impact: Low.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/ask/askStore.ts | modify | `send` consumes `askStream` (Text→append streaming buffer, VaultLocked→re-unlock, Done→finalize+engine tag); add `muted`/`speaking` state + `toggleMute`; pass `speak: !muted` on the request |
| client/src/ask/AskPopup.tsx | modify | mic button (push-to-talk, `aria-label`), speak/mute toggle (`aria-pressed`), speaking indicator (`aria-live="polite"`); restore streamed-text rendering from the store buffer |
| client/src/ask/askStore.test.ts | modify | streaming Text/Text/Done builds one assistant message + engine tag; `speak` reflects mute; toggle remembers state |
| client/src/ask/AskPopup.test.tsx | modify | mic button calls `onVoiceTrigger`; mute toggle flips `aria-pressed` + persists; speaking indicator shows while `speaking` |

## Exact changes
**client/src/ask/askStore.ts**:
- Replace the `const response = await ask(...)` block in `send` with: `for await (const ev of askStream({ text: trimmed, speak: !snapshot.muted })) { ... }` — `ev.type==="text"`→append to `streaming` + the assistant message (debounced polite region on sentence boundary); `"vault_locked"`→re-unlock + failedLocked (unchanged); `"done"`→finalize + `deriveEngine(ev.path, ev.escalated)`.
- Add to `AskSnapshot`: `muted: boolean` (default `false` = speaks), `speaking: boolean`. Add `toggleMute()` (flips + persists last state) and a `setSpeaking(b)` used by the voice path.

**client/src/ask/AskPopup.tsx**:
- Mic button → `onVoiceTrigger` prop (wired to `invoke("app_ask_voice", { speak: !muted })` in app composition; mocked in tests). `aria-label="Hold to talk"`.
- Toggle button → `askStore.toggleMute`, `aria-pressed={muted}`, labelled "Speak answers" / "Muted".
- Speaking indicator → `aria-live="polite"` region shown when `speaking`; reduced-motion safe; tokens only (no hex).

**client/src/api/dto.ts** (1-liner): `AskRequest` gains `speak?: boolean`. (Rust `AskRequest.speak: bool` + `app_ask_voice` command land with S2/S3 integration.)

## Acceptance criteria
- [ ] `cd client && npx tsc --noEmit` → exit 0.
- [ ] `cd client && npx vitest run` → a Text/Text/Done channel sequence builds ONE assistant message whose text is the concatenated stream and whose engine tag comes from the `Done` payload; `send` posts `speak: true` when not muted and `speak: false` after `toggleMute`; the toggle remembers its last state across opens; the mic button invokes `onVoiceTrigger`; `getByRole('button',{pressed})` reflects mute; the speaking indicator is in the a11y tree while `speaking`; a `vault_locked` event still raises re-unlock and does not finalize.
- [ ] `cd client && npx eslint . --max-warnings 0` → exit 0.
- [ ] `grep -E "#[0-9a-fA-F]{3,6}" client/src/ask/` → no literal hex (tokens only).

## Commands to run
```
cd client && npx tsc --noEmit
cd client && npx vitest run
cd client && npx eslint . --max-warnings 0
```

# voice-ask-wiring

## Intent
The unified voice+text Ask (ADR-034) was built as SEAMS ONLY across voice-ask-S1..S4 — the pieces exist but nothing constructs them or installs the real sinks, so voice Ask does not run end-to-end. This spec is the composition/wiring: construct `frontend`+`stt`+`tts` in the brain lifespan, install the REAL `app.state.speak_sink` (replacing S1's no-op drain), add a brain `/app/ask/voice` route that drives `overlay_voice_turn`, and add the `app_ask_voice` Tauri command + client wiring so the mic button reaches it. The text Ask path is already fully live and is not touched.

## Key decisions
- **Co-locate construction in `main.py` lifespan**, mirroring the existing heartbeat block: build `SidecarAudioFrontend` + `ParakeetWhisperSTT` + `KokoroTTS` (lazy — they do not contact the sidecar/models until used), install `app.state.speak_sink = compose_speak_sink(frontend, tts, is_owner_unlocked=key_provider.is_owner_unlocked)` and `app.state.voice_capture = PushToTalkCapture(frontend, stt)`. Wrap in `try/except` that logs and continues (like the heartbeat) so a box with no sidecar/mic still boots.
- **Vault recheck is the security fold (MUST):** `compose_speak_sink` / `speak_overlay_answer` gain an `is_owner_unlocked: Callable[[], bool]` and re-check it before playing each spoken sentence (and the tail), matching the per-chunk fail-closed recheck the display branch in `/app/ask/stream` already does. The S1 speak-sink site comment flagging this is at `src/artemis/api_app.py:876-879`.
- **Speak task is retained, not fire-and-forget:** both the existing `/app/ask/stream` speak branch (`api_app.py:881`) and the new voice route keep a reference to the speak task and log failures via a done-callback (folds the LOW-priority S1 flag).
- **Voice request DTOs are separate** (`VoiceAskRequest { speak }` on both brain + Rust sides) so the live text-Ask `AskRequest` is left untouched.
- **Shape-aware speakable rule is already built** in `gateway.py` (`classify_shape` / `subject_phrase` / `to_speakable`, the "it's on screen" pointer) and reached via `handle_ask_unified` — fold, do not re-spec.
- **On-box real-audio bring-up is owner-run** (gated tail) — a manual acceptance step, not a code task.

## Gotchas / edge cases
- `compose_speak_sink` currently has signature `(frontend, tts)` (voice_loop.py:285) and its returned sink is what S1's route picks up via `getattr(app.state, "speak_sink", _drain_speak)`. Changing the signature requires updating `tests/test_overlay_voice_output.py:80` which calls `compose_speak_sink(sidecar, tts)`.
- The Rust `AskRequest` (gateway.rs:64-67) has only `text` — it does NOT carry `speak`. Do not bolt `speak` onto it; add a distinct `VoiceAskRequest`.
- `PushToTalkCapture.capture_transcript()` re-issues `startListening` each call, so one stored instance is reusable across turns.
- The instant-ack beep at the start of `speak_overlay_answer` carries no owner content; the recheck gate goes before each owner *sentence*, not before the ack.
- S4 wired the mic button to `onVoiceTrigger?.({ speak: !muted })` (AskPopup.tsx:353) but `<AskPopup>` in `App.tsx:151` is rendered WITHOUT an `onVoiceTrigger` prop — so the mic is currently a no-op. App.tsx must pass it.

## Assumptions
- The brain process runs co-located with the mic/speaker (audio is on the brain host, per ADR-034) — voice capture and playback both happen brain-side; the client only triggers and renders display text.
- `key_provider.is_owner_unlocked` is a stable bound method usable as the recheck callable (used the same way at api_app.py:887).
- Reusing the `/app/ask/stream` SSE display pattern (fail-closed recheck + `[DONE]`) verbatim for `/app/ask/voice` is acceptable; only the input (captured transcript vs body text) differs.
- **Simplicity check:** this is the minimum wiring for end-to-end voice — construct-and-install in the one lifespan that already builds app.state, one new brain route reusing the existing SSE shape, one new Tauri command mirroring `app_ask_stream`, and one prop pass-through. No new abstraction, no config flag, no change to the text path.

## Tasks
1. **Add the per-chunk vault recheck to the speak path** — `src/artemis/voice/voice_loop.py`: add `is_owner_unlocked: Callable[[], bool]` param to `speak_overlay_answer` and `compose_speak_sink`; in `speak_overlay_answer` return early (stop speaking) if `not is_owner_unlocked()` before each `_play_sentence` call and before the tail. done when: `uv run pytest -q tests/test_overlay_voice_output.py` passes including a new test where `is_owner_unlocked` flips True→False mid-iteration and the FakeTTS records zero sentence plays after the flip; `uv run mypy src tests/test_overlay_voice_output.py` exits 0.
2. **Construct voice components and install the real sink** — `src/artemis/main.py`: in `lifespan`, build `frontend`/`stt`/`tts`, set `app.state.speak_sink = compose_speak_sink(frontend, tts, is_owner_unlocked=key_provider.is_owner_unlocked)` and `app.state.voice_capture = PushToTalkCapture(frontend, stt)`, wrapped in a `try/except` that logs and continues. done when: a TestClient startup test asserts `app.state.speak_sink` is not `_drain_speak` and `app.state.voice_capture` is a `PushToTalkCapture`; with sidecar/mic construction forced to raise, startup still succeeds (no exception out of lifespan). `uv run pytest -q` green.
3. **Add the brain voice route + retain the speak task** — `src/artemis/api_app.py`: add `VoiceAskRequest { speak: bool = True }` and `POST /app/ask/voice` that resolves scope from `principal`, calls `overlay_voice_turn(gateway, app.state.voice_capture, scope=scope, speak=body.speak)`, SSE-streams `display_iter` with the same fail-closed recheck + `[DONE]`, and tees `speak_iter` to `app.state.speak_sink` as a RETAINED task with a failure-logging done-callback; apply the same retain+log to the existing `/app/ask/stream` speak branch (api_app.py:881). done when: `uv run pytest -q tests/test_api_app.py` passes including a new test that POSTs `/app/ask/voice`, asserts the FakeGateway received the captured transcript with `speak=True`, the SSE body streams the display frames + `[DONE]`, a vault-lock mid-stream yields `{"error":"vault_locked"}`, and the recorded `speak_sink` received `speak_iter`.
4. **Add the Tauri voice command** — `client/src-tauri/src/gateway.rs`: add `VoiceAskRequest { speak: bool }`, an `ask_voice(state, speak, channel)` helper that POSTs `/app/ask/voice` and parses SSE frames into the channel (reuse `parse_stream_frame`, mirror `ask_stream`), and the `#[tauri::command] app_ask_voice(state, speak, channel: Channel<StreamEvent>)` wrapper. done when: `cargo test` (in client/src-tauri) passes including a unit test asserting `app_ask_voice` POSTs to `/app/ask/voice` with the `speak` flag and emits parsed `StreamEvent`s on the channel.
5. **Register the command** — `client/src-tauri/src/lib.rs`: add `gateway::app_ask_voice` to the `generate_handler!` list. done when: `cargo build` (in client/src-tauri) compiles with the command registered.
6. **Add the TS voice transport** — `client/src/api/gateway.ts`: add `askVoice(speak: boolean)` as an async generator mirroring `askStream` but invoking `"app_ask_voice"` with `{ speak, channel }`. done when: vitest asserts `askVoice(true)` calls `invoke("app_ask_voice", { speak: true, channel })` and yields the channel's `StreamEvent`s.
7. **Wire the mic button** — `client/src/App.tsx`: pass an `onVoiceTrigger` prop to `<AskPopup>` that drives `askVoice` (feeding the same display render path the Ask popup uses). done when: vitest renders `App`, asserts `<AskPopup>` receives a defined `onVoiceTrigger`, and triggering it calls `askVoice` with the muted-derived `speak` flag.
8. **(Owner-run, gated tail — NOT a code task)** On-box real-audio bring-up: with the sidecar + mic/speaker live on the brain host, hold the mic button, speak a short question, and hear the spoken answer on the brain-host speaker; lock the vault mid-answer and confirm speech stops immediately. done when: the owner confirms spoken output + mid-answer cutoff on real hardware.

## Files to touch
- `C:\Users\User\artemis\src\artemis\voice\voice_loop.py` — add `is_owner_unlocked` param + per-sentence recheck to `speak_overlay_answer` / `compose_speak_sink`.
- `C:\Users\User\artemis\src\artemis\main.py` — construct `frontend`/`stt`/`tts`; install `app.state.speak_sink` (real) + `app.state.voice_capture`; guarded try/except.
- `C:\Users\User\artemis\src\artemis\api_app.py` — `VoiceAskRequest` + `POST /app/ask/voice`; retain+log the speak task on both voice and `/app/ask/stream`.
- `C:\Users\User\artemis\client\src-tauri\src\gateway.rs` — `VoiceAskRequest`, `ask_voice` helper, `app_ask_voice` command.
- `C:\Users\User\artemis\client\src-tauri\src\lib.rs` — register `app_ask_voice` in `generate_handler!`.
- `C:\Users\User\artemis\client\src\api\gateway.ts` — `askVoice` generator.
- `C:\Users\User\artemis\client\src\App.tsx` — pass `onVoiceTrigger` to `<AskPopup>`.

## Commands to run
- `uv run mypy src tests` → exit 0
- `uv run pytest -q` → green (full suite)
- `cd client/src-tauri && cargo test` → green
- `cd client/src-tauri && cargo build` → compiles
- `cd client && npm test` → green

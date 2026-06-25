<!-- amended 2026-06-11 per m5-m6-voice-heartbeat.md BLOCKs B6, FLAG F12 -->
<!-- amended 2026-06-25 Windows dev re-scope — see docs/research/2026-06-25-voice-windows-dev/README.md -->
---
spec: m5-d-voice-loop-orchestrator
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M5-d — Voice-loop orchestrator (custom thin pipeline: wake→capture→VAD-endpoint→STT→Brain.respond→sentence-stream→TTS→sidecar) behind the `AudioFrontend` port + instant-ack + barge-in + latency-budget instrumentation

> **Amendment 2026-06-25 (Windows dev re-scope):** The voice-loop orchestrator is **fully dev-buildable and testable on Windows** — it is already brain-side Python with no Mac dependencies. See `docs/research/2026-06-25-voice-windows-dev/README.md`.
> - **IPC client builds and tests against `M5-a-win-sidecar`:** the `SidecarAudioFrontend` socket client speaks the same frozen wire protocol (1-byte kind + 4-byte length + body; events + `0x02`/`0x03` PCM frames; 16 kHz/mono/Int16) whether the far end is the Swift sidecar (Mac production) or the Windows Python sidecar — no changes to Task 1.
> - **FakeSidecar test coverage is unchanged:** the off-hardware suite already validates the full cascade; running against the real Windows sidecar is an additional integration path at Task 5/6 (the existing GATED tasks remain Mac production gates; Windows integration is a separate bring-up step documented in `M5-a-win-sidecar`).
> - **No cascade or gate logic changes:** `VoiceLoop`, latency instrumentation, barge-in, instant-ack, and the `NeedsPhoneUnlock` path are platform-neutral — they run identically on Windows against the dev sidecar.

**Identity:** Implements the Python `AudioFrontend` port as the thin custom voice loop: a `SidecarAudioFrontend` IPC client to the M5-a audio sidecar (consume mic PCM + wake/VAD/barge-in events, send playback PCM) and a `VoiceLoop` orchestrator that drives wake→capture→endpoint→STT (M5-b)→speaker-ID + scope (M5-c Gateway voice path)→Brain.respond (M1)→split the responder token stream into sentences→Kokoro TTS per sentence (M5-b)→stream PCM to the sidecar, with an instant ack masking TTFT, barge-in cancellation of the in-flight TTS, and per-stage latency-budget instrumentation.
→ why: see docs/technical/architecture/brain.md § "Voice (cascaded, streaming every stage)" (the full cascade + instant-ack + barge-in + 750–800ms budget; AudioFrontend port; multi-room satellites later) · docs/drafts/m5/M5-a-audio-sidecar.md (the sidecar IPC contract this client consumes) · docs/drafts/m5/M5-b-stt-tts.md (STT/TTS adapters) · docs/drafts/m5/M5-c-speaker-id.md (the Gateway `handle_voice` path) · docs/drafts/m1/M1-b-router-brain.md (`Brain.respond`).

<!-- Split rule: this spec touches >3 files because the voice loop is ONE orchestration unit whose pieces must agree across three seams: the sidecar IPC client (new, implements the M5-a contract), the VoiceLoop orchestrator (new, the AudioFrontend port impl + the cascade), and the latency instrumentation (new, small) — plus the composition wiring (modify M2/M5-c's compose). They share the audio PCM format + the sidecar event vocabulary + the Gateway voice path; splitting would let the loop drive a sidecar contract no client implements, or instrument a loop that doesn't exist. Justified atomic exception, flagged per rules. The orchestration/scope-routing/event-handling is fully off-hardware-testable with a FAKE sidecar + fake STT/TTS/SpeakerID; real end-to-end audio + the latency budget are GATED on-hardware. -->

## Assumptions
- M5-a (the audio sidecar + its frozen IPC contract at `docs/technical/protocol/audio-ipc.md`: multiplexed 1-byte kind + 4-byte length + body; events `wakeDetected`/`speechStart`/`speechEnd`/`bargein`/`playbackStarted`/`playbackFinished`/`error`/`status`; commands `startListening`/`stopListening`/`play`/`stopPlayback`/`getStatus`; `0x02` mic PCM in / `0x03` speaker PCM out; 16 kHz/mono/Int16), M5-b (`ParakeetWhisperSTT`/`KokoroTTS` + `warmup_all` + `PCM_FORMAT`), M5-c (the Gateway `handle_voice(audio, transcript)` voice path + `SpeakerID`), M1-b (`Brain.respond`), M1-c/M2-b/M5-c (`compose_brain`/`Gateway`) are complete. → impact: Stop (M5-d consumes all of these exact contracts; the AudioFrontend port is M0-d's `capture()`/`play()`).
- M0-d `AudioFrontend` port = `def capture(self) -> Iterator[bytes]: ...`; `def play(self, audio: Iterator[bytes]) -> None: ...`. M5-d's `SidecarAudioFrontend` structurally satisfies it (capture = the mic PCM stream from the sidecar; play = send PCM `0x03` frames to the sidecar). The `VoiceLoop` uses the frontend; "multi-room satellites are just more AudioFrontends" (brain.md) — M5 ships ONE local frontend; the loop is written so a second frontend instance is a later addition (no Wyoming exposure now). → impact: Caution (the port stays the seam; M5 is single-frontend).
- **Instant ack masks TTFT** (brain.md): the moment STT yields a transcript (before Brain.respond returns), the loop plays a short pre-synthesised/cached ack (e.g. a brief tone or "mm-hm"/"one sec") so the user hears a response within ~the STT latency, while the brain + first TTS sentence are still in flight. → impact: Caution. DRAFTED DEFAULT: a pre-rendered short non-speech earcon PCM cached at startup (cheapest, language-neutral, always fast). A spoken filler (synth once + cached) is a config swap. The ack MUST be barge-in-interruptible. Confirmed at on-hardware bring-up (Task 6).
- **Sentence streaming**: as `Brain.respond` streams responder tokens, the loop splits the token stream into sentences (on sentence-final punctuation / a max-chars flush) and calls `tts.synthesize(sentence)` per sentence, streaming each sentence's PCM to the sidecar as it's produced — so audio starts at the first sentence, not the full reply. → impact: Stop (the brain.md "sentence-by-sentence as the LLM streams" latency lever; the splitter lives here). DECISION (CROSS-MILESTONE DEP): M5-d consumes `Brain.respond_stream(text, scope) -> AsyncIterator[str]` (yields text segments) added to M1-b — the responder adapter already supports `stream=True`; the tool path yields its rendered answer as one segment. This is brain.md "stream every stage" and back-fills M1-b. The loop splits the segment stream into sentences and pipelines `tts.synthesize` per sentence.
- **Barge-in**: when the sidecar emits a `bargein` event during playback, the loop (1) cancels the in-flight TTS synthesis + the responder stream, (2) stops sending `0x03` PCM, (3) re-arms capture for the user's new utterance (the sidecar already flushed playback <200ms per M5-a). → impact: Stop (the loop's half of the barge-in contract; M5-a does the audio flush, M5-d cancels the upstream generation).
- **Latency-budget instrumentation**: the loop timestamps each cascade stage (end-of-speech/endpoint → STT-done → speaker-ID-done → brain-first-token → first-TTS-PCM → first-audio-out) and logs the deltas + the end-to-end `endpoint→first-audio` figure against the ~750–800ms budget. → impact: Low (instrumentation is logging/metrics only; it doesn't change behaviour but is a deliverable).
- The loop is **fully testable off-hardware** with a FakeSidecar (an in-process object emitting a scripted event/PCM sequence + recording the PCM/commands sent to it) + `FakeSTT`/`FakeTTS`/`FakeSpeakerID` + a FakeBrain. Real microphone→speaker end-to-end + the real latency budget are GATED on-hardware. → impact: Caution.

Simplicity check: considered using a voice framework (Pipecat / HA-Wyoming) to orchestrate the cascade — rejected by brain.md (custom thin pipeline, NO framework; Wyoming exposure is deferred). Considered making the loop a big monolithic coroutine — kept it as a small `VoiceLoop` over the `AudioFrontend` port + injected STT/TTS/SpeakerID/Brain so each stage is swappable + testable (ports everywhere). Considered skipping the instant-ack for M5 — rejected; brain.md makes instant-ack the primary TTFT mask + it's cheap (one cached earcon). The minimum is a thin event-driven loop wiring the existing port adapters with one cached ack + a sentence splitter + barge-in cancellation + stage timers.

## Prerequisites
- Specs that must be complete first: **M5-a** (sidecar + IPC contract), **M5-b** (STT/TTS adapters + PCM_FORMAT + warmup), **M5-c** (Gateway `handle_voice` + SpeakerID), **M1-b** (`Brain.respond`; + the `Brain.respond_stream` back-fill — CROSS-MILESTONE DEPENDENCY, added to M1-b), **M1-c/M2-b/M5-c** (`compose_brain`/`Gateway`), **M0-d** (`AudioFrontend` port), **M0-a** (paths/config — the sidecar socket path is resolved from `ARTEMIS_DATA_ROOT` + `ARTEMIS_SLOT` via `paths`: `<slot>/run/audio.sock`; do NOT hardcode `/opt/artemis` — F12 fix; Task 1 uses `paths` to resolve the socket path the M0-a way).
- Environment setup required: none beyond M0/M1/M2/M5-a/b/c. Off-hardware testable with a FakeSidecar + fakes (no audio hardware, no models); **the real sidecar round-trip + microphone-to-speaker end-to-end + the latency budget are GATED on-hardware (Tasks 5–6).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/voice/sidecar_client.py | create | `SidecarAudioFrontend` implementing the `AudioFrontend` port over the M5-a Unix-socket IPC (events + mic PCM in / playback PCM out) + `FakeSidecar` |
| /Users/artemis-build/artemis/src/artemis/voice/voice_loop.py | create | `VoiceLoop` orchestrator: the wake→…→TTS cascade + instant-ack + sentence splitter + barge-in cancel + stage timers |
| /Users/artemis-build/artemis/src/artemis/voice/latency.py | create | `StageTimer`/`LatencyBudget` instrumentation (timestamps + endpoint→first-audio against the 750–800ms budget) |
| /Users/artemis-build/artemis/src/artemis/gateway.py | modify | (small) add the streaming voice entry `handle_voice_stream(audio, transcript) -> AsyncIterator[str]` consuming `Brain.respond_stream` (M1-b back-fill) and reusing the M5-c `Brain.pre_route` Tier gate; keep `handle_voice`/`handle_text` intact |
| /Users/artemis-build/artemis/tests/test_voice_loop.py | create | cascade + instant-ack + sentence-stream + barge-in + scope-routing + latency-timer tests against the FakeSidecar + fakes |

## Tasks
- [ ] Task 1: Implement the sidecar IPC client (AudioFrontend port) — files: `/Users/artemis-build/artemis/src/artemis/voice/sidecar_client.py` — `class SidecarAudioFrontend` structurally satisfying `artemis.ports.AudioFrontend`, constructed with the socket path (from `paths`: `<slot>/run/audio.sock`). Implements the M5-a multiplexed framing (1-byte kind + 4-byte big-endian length + body): 
  - an async event/PCM reader that demuxes incoming frames into (a) JSON events (`wakeDetected`/`speechStart`/`speechEnd`/`bargein`/`playbackStarted`/`playbackFinished`/`error`/`status`) delivered to a subscriber callback/async queue, and (b) `0x02` mic PCM delivered to the capture stream.
  - `def capture(self) -> Iterator[bytes]`: yields mic PCM frames (the port method; an async variant `async def capture_async` for the loop).
  - `def play(self, audio: Iterator[bytes]) -> None`: send a `play(sampleRate, channels)` command then stream the PCM as `0x03` frames; an async `play_async(audio: AsyncIterator[bytes], cancel: Event)` that stops sending on cancel (barge-in).
  - `def send_command(cmd)` for `startListening`/`stopListening`/`stopPlayback`/`getStatus`.
  - parse `error(code,message)` → typed `SidecarError`. Never block on the socket in a way that drops mic frames (buffered reader).
  - `class FakeSidecar` (TEST): emits a scripted sequence of events + mic PCM, and RECORDS every command + every `0x03` PCM chunk sent to it (so the loop's playback + barge-in behaviour is assertable without real audio).
  — done when: `uv run mypy --strict src` passes; against a fake in-process socket server speaking the M5-a contract, the client demuxes a `wakeDetected` event + a mic PCM frame and round-trips a `play` + PCM; a static `_f: AudioFrontend = SidecarAudioFrontend(...)` conformance assertion type-checks.

- [ ] Task 2: Implement the latency instrumentation — files: `/Users/artemis-build/artemis/src/artemis/voice/latency.py` — `class StageTimer`: `mark(stage: str)` records a monotonic timestamp per named stage; `delta(a, b) -> float`; `endpoint_to_first_audio() -> float`. `class LatencyBudget`: holds the target (`first_audio_budget_ms = 800`, config) and `def check(timer) -> bool` (true if endpoint→first-audio ≤ budget) + `def log(timer)` emitting the per-stage deltas + the end-to-end figure + a WARN if over budget. Stages: `endpoint`, `stt_done`, `speaker_id_done`, `brain_first_token`, `first_tts_pcm`, `first_audio_out`. Pure timing/logging; no audio. — done when: `uv run mypy --strict src` passes; a unit test marking fake timestamps computes the correct deltas and `check` flags over/under budget.

- [ ] Task 3: Implement the VoiceLoop orchestrator — files: `/Users/artemis-build/artemis/src/artemis/voice/voice_loop.py` — `class VoiceLoop` constructed with `(frontend: AudioFrontend, stt: STT, tts: TTS, gateway: Gateway, settings, ack_pcm: bytes, budget: LatencyBudget)`. The cascade (an async loop):
  1. wait for a `wakeDetected` event from the frontend → `startListening`.
  2. accumulate mic PCM until a `speechEnd(reason="endpoint")` event → `mark("endpoint")`; assemble the captured utterance PCM.
  3. STT: `transcript = stt.transcribe(utterance_pcm)` → `mark("stt_done")`.
  4. **instant ack**: immediately `frontend.play_async(iter([ack_pcm]))` (barge-in-interruptible) so the user hears the ack while the brain runs.
  5. speaker-ID + scope + Tier nuance: call `gateway.handle_voice_stream(utterance_pcm, transcript)` (the streaming variant added in Task 4). `mark("speaker_id_done")` after identity resolves (at the first yield or on exception). If `handle_voice_stream` raises `NeedsPhoneUnlock` (locked owner + Tier-1 request, M5-c/B6 fix) → synth + play `gateway.NEEDS_UNLOCK_PROMPT` (the fixed spoken phrase, NOT "NEEDS_PHONE_UNLOCK" verbatim — F6 fix) and end the turn (do NOT serve sensitive data). Do NOT call both `handle_voice` and `handle_voice_stream` for the same utterance — use only the streaming path here.
  6. as response text segments stream in: `mark("brain_first_token")` on the first; split into sentences (sentence-final punctuation OR a max-char flush); per sentence `tts.synthesize(sentence)` → stream the PCM to `frontend.play_async`. `mark("first_tts_pcm")` / `mark("first_audio_out")` on the first chunk produced/sent.
  7. **barge-in**: a `bargein` event at any point during 4–6 → set the cancel `Event` (stops `play_async` + the TTS/brain stream generators), `stopPlayback`, re-arm capture for the new utterance.
  8. on `playbackFinished` with no barge-in → back to idle (await next wake).
  9. `budget.log(timer)` at turn end.
  Degrade-don't-crash: STT/TTS/brain errors → synth a short "sorry, try again" + log; never raise out of the loop. — done when: `uv run mypy --strict src` passes; the loop is an async, cancellable coroutine.

- [ ] Task 4: Wire the voice composition + the streaming brain/gateway seam — files: `/Users/artemis-build/artemis/src/artemis/gateway.py` (modify), `/Users/artemis-build/artemis/src/artemis/voice/voice_loop.py` (the composition helper) — add `def compose_voice_loop(settings) -> VoiceLoop`: build the `SidecarAudioFrontend` (socket path from `paths` — `<slot>/run/audio.sock`; NOT a hardcoded `/opt/artemis` literal — F12 fix), `ParakeetWhisperSTT`/`KokoroTTS` (M5-b) + `warmup_all`, the `Gateway` from M5-c's `compose_brain` (with the real `SpeakerID`/`KeyProvider`), load the cached `ack_pcm` (the drafted default: a pre-rendered bundled earcon file loaded at startup; a synth-once spoken filler is the config swap), a `LatencyBudget` from config, and return the `VoiceLoop`. In `gateway.py` add the streaming voice entry with the EXACT contract (B6 fix): `async def handle_voice_stream(self, audio: bytes, transcript: str) -> AsyncIterator[str]`. This method runs the full M5-c identity + Tier gate (same `pre_route`/`tier_for`/`is_owner_unlocked` logic as `handle_voice`). If the gate determines NEEDS_PHONE_UNLOCK (locked owner + Tier-1 request), it **raises `NeedsPhoneUnlock` (a typed exception defined in `gateway.py`)** instead of yielding text — the loop in Task 3 catches `NeedsPhoneUnlock`, synthesises a fixed spoken phrase (e.g. `"That needs your phone unlock first."` — a constant `NEEDS_UNLOCK_PROMPT` in `gateway.py`; NOT the sentinel string "NEEDS_PHONE_UNLOCK" which would be TTS'd verbatim), and ends the turn. Otherwise `handle_voice_stream` runs the M1-b `Brain.respond_stream` and yields text segments. Keep `handle_voice`/`handle_text` from M5-c/M2-b intact. — done when: `uv run mypy --strict src` passes; `compose_voice_loop(get_settings())` returns a `VoiceLoop` without contacting the sidecar or loading models at construction (lazy; warmup is explicit); `handle_voice_stream` is typed as an async generator returning `AsyncIterator[str]` and `NeedsPhoneUnlock` is a concrete importable exception class.

- [ ] Task 5: Write the voice-loop tests — files: `/Users/artemis-build/artemis/tests/test_voice_loop.py` — typed pytest, all off-hardware with `FakeSidecar` + `FakeSTT`/`FakeTTS`/`FakeSpeakerID`/`FakeBrain`/`FakeKeyProvider`:
  - port conformance: `_f: AudioFrontend = SidecarAudioFrontend(...)` type-checks.
  - happy cascade: FakeSidecar scripts `wakeDetected → mic PCM → speechEnd(endpoint)`; FakeSTT returns "what time is it"; FakeSpeakerID returns OWNER; FakeBrain streams "It is noon."; assert the FakeSidecar RECORDED: a `startListening`, the ack PCM played, then TTS PCM for the sentence, and the loop ended idle.
  - instant-ack ordering: the ack PCM is sent to the FakeSidecar BEFORE the brain's TTS PCM (assert recorded order) — proves the ack masks TTFT.
  - sentence streaming: FakeBrain streams "First sentence. Second sentence."; assert FakeTTS was called once per sentence in order (the splitter works) and PCM for sentence one was sent before sentence two was synthesised.
  - barge-in: FakeSidecar emits `bargein` mid-playback; assert the loop set the cancel (no further `0x03` PCM sent after the event), sent `stopPlayback`, and re-armed `startListening`.
  - voice scope nuance (delegates to M5-c, B6 fix): configure a `FakeGateway` whose `handle_voice_stream` raises `NeedsPhoneUnlock` for OWNER+Tier-1+locked → the loop plays `NEEDS_UNLOCK_PROMPT` (assert the FakeSidecar recorded the prompt PCM, NOT the string "NEEDS_PHONE_UNLOCK") and serves NO sensitive answer (no `brain.respond` call); OWNER + Tier-0 + locked → `handle_voice_stream` yields normally, proceeds; UNKNOWN → guest scope used (FakeBrain asserts the guest scope).
  - latency timers: after a turn, `StageTimer` has all stages marked and `LatencyBudget.check` returns a bool (with injected fake clock, assert under/over budget both detectable).
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_voice_loop.py` passes.

- [ ] Task 6 (GATED — on-hardware): Real end-to-end voice turn + latency budget — files: (no repo files; runs `compose_voice_loop` against the REAL M5-a sidecar + real M5-b models + real M5-c ECAPA on the Mini) — on the Mac Mini, with the audio sidecar LaunchAgent running + the responder + voice models warm: say "Hey Jarvis, what time is it" → confirm the full cascade fires (wake→capture→endpoint→STT→speaker-ID→brain→TTS→playback), the instant ack is heard before the answer, the answer streams sentence-by-sentence, and barge-in (speak during the answer) cancels playback + the upstream generation. Measure + log `endpoint→first-audio` against the ~750–800ms budget. Build-time empirical (full audio stack + ANE + models + latency). — done when: on the Mini, a real spoken turn completes end-to-end with instant-ack + barge-in working and the endpoint→first-audio latency recorded (target ~750–800ms) in `docs/handoff/`.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/voice/sidecar_client.py, /Users/artemis-build/artemis/src/artemis/voice/voice_loop.py, /Users/artemis-build/artemis/src/artemis/voice/latency.py, /Users/artemis-build/artemis/tests/test_voice_loop.py |
| Modify | /Users/artemis-build/artemis/src/artemis/gateway.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_voice_loop.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (FakeSidecar + fakes) |
| (GATED, on-Mini) run `compose_voice_loop` against the real sidecar + models | Live end-to-end voice turn |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/voice/sidecar_client.py, src/artemis/voice/voice_loop.py, src/artemis/voice/latency.py, src/artemis/gateway.py, tests/test_voice_loop.py |
| `git commit` | "feat: M5-d voice-loop orchestrator (AudioFrontend port) — cascade + instant-ack + barge-in + latency instrumentation" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (socket path, budget, model dir) |
| `ARTEMIS_DATA_ROOT` | Locate `<slot>/run/audio.sock` |
| `ARTEMIS_SLOT` | Which slot's sidecar socket |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Sidecar IPC is a local Unix socket; brain/model calls are M1-b/M5-b's concern (loopback) |

## Specialist Context
### Security
The loop treats the STT transcript as **untrusted data, not instructions** (agent self-defense — voice is an injection vector). It NEVER serves Tier-1 owner data on voice-ID alone: it delegates the voice-ID≠key boundary to M5-c's Gateway (`handle_voice` → `NEEDS_PHONE_UNLOCK` for a locked-owner Tier-1) and must play that prompt rather than the sensitive answer. Captured utterance PCM + transcripts are owner-sensitive → never written to disk/logs (log timings + events only). The sidecar socket carries no key material (ADR-005 keeps the DEK on the broker socket). [FLAG apex-security: confirm the loop cannot be driven to serve sensitive data without an unlocked session — the only sensitive path is via `gateway.handle_voice`, which already gates it; ensure no direct `brain.respond` bypass for the voice path.]

### Performance
This is THE latency-critical path (brain.md 750–800ms endpoint→first-audio). Levers wired here: instant-ack (cached earcon, played the moment STT returns, masking TTFT); sentence-streaming TTS (first sentence's audio before the full reply); warm STT/TTS/responder (M5-b/M0-c pre-warm); barge-in upstream cancellation (stops wasted generation). The `LatencyBudget` instrumentation makes the budget observable + flags regressions. The sidecar IPC reader must not drop mic frames.

### Accessibility
(none rendered — but the voice loop IS a primary accessibility surface; the instant-ack + barge-in directly serve responsiveness/interruptibility.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/voice/sidecar_client.py, src/artemis/voice/voice_loop.py, src/artemis/voice/latency.py | Type + docstring all exports; document the cascade order, the instant-ack/barge-in contract, the voice-ID≠key delegation to the Gateway, and the latency stages |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_voice_loop.py` → verify: exit 0 (incl. `AudioFrontend` structural conformance).
- [ ] Run `uv run pytest -q tests/test_voice_loop.py` → verify: happy cascade records startListening→ack→TTS PCM; the ack is sent BEFORE the brain's TTS PCM; per-sentence TTS calls in order; `bargein` cancels playback + re-arms capture; OWNER+Tier-1+locked → `NeedsPhoneUnlock` raised → loop plays `NEEDS_UNLOCK_PROMPT` spoken phrase (NOT the literal "NEEDS_PHONE_UNLOCK") and no sensitive answer served; UNKNOWN routes to guest scope; the latency timer marks all stages.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Real spoken turn "Hey Jarvis, what time is it" → verify: full cascade fires, instant-ack heard before the answer, sentence-by-sentence playback, barge-in cancels mid-answer, endpoint→first-audio latency recorded (~750–800ms target) — in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

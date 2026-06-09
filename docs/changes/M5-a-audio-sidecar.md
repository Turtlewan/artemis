---
spec: m5-a-audio-sidecar
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M5-a — Swift audio sidecar (VoiceProcessingIO capture+playback through one engine, openWakeWord trigger, Silero VAD + barge-in, brain↔sidecar IPC contract)

**Identity:** Builds the hardened Swift `ArtemisAudio` LaunchAgent — the single owner of ALL audio I/O via Apple `AVAudioEngine` + `VoiceProcessingIO` (AEC): captures post-AEC mic frames, renders TTS PCM through the SAME engine (echo-cancel requirement), runs the openWakeWord ("Hey Jarvis") trigger and Silero VAD on post-AEC audio, kills playback on barge-in (<200ms flush), and exposes a local Unix-socket IPC (length-prefixed JSON + raw PCM) that streams audio events/frames to the Python brain and accepts PCM to play.
→ why: see docs/technical/architecture/brain.md § "Voice (cascaded, streaming every stage)" (VoiceProcessingIO AEC, TTS through the same engine, Silero barge-in <200ms, AudioFrontend port) · docs/technical/adr/ADR-002-deployment-method.md (the audio sidecar LaunchAgent).

<!-- Split rule: this spec creates ONE atomic component (the audio sidecar) in ONE logical phase. It exceeds 3 files because the sidecar is a new SwiftPM package that must compile and run as a unit: the AVAudioEngine/VoiceProcessingIO graph, the openWakeWord runner, the Silero VAD runner, the barge-in controller, and the IPC server are mutually dependent and cannot be sub-split without leaving a non-building package or an audio graph with no consumer. This deliberately mirrors the M2-a ArtemisBroker SwiftPM package structure (same Sources/Tests/Package.swift layout, same Unix-socket length-prefixed-JSON IPC pattern, same "ship the verification side + a fake/mock for tests" discipline). Justified atomic exception, flagged per rules. The Python AudioFrontend client that consumes this IPC is M5-d. -->

## Assumptions
- The sidecar is a **Swift** component (`AVAudioEngine` `voiceProcessing` / `AUVoiceIO`, `kAudioUnitSubType_VoiceProcessingIO`, AVAudioSession-equivalent macOS audio APIs are Apple-only; Python cannot drive the AEC audio unit). Built as a SwiftPM executable package at `/Users/artemis-build/artemis/swift/ArtemisAudio/`, mirroring `/Users/artemis-build/artemis/swift/ArtemisBroker/`. → impact: Stop (language + AEC API access is non-negotiable per brain.md; a pure-Python AEC pipeline was rejected — the Swift sidecar owns audio).
- The sidecar runs as a **LaunchAgent in the owner-runtime user's login/audio session** (audio I/O requires the GUI/audio session, NOT a LaunchDaemon — same constraint as the broker). The launchd plist already exists from **M0-b** (`com.artemis.audio.plist.template`) pointing at `{AUDIO_SIDECAR_BIN}`; M5-a produces that binary. → impact: Stop (if run headless as a daemon, the audio unit fails to start).
- **TTS playback MUST render through the same `AVAudioEngine` instance** that owns the `VoiceProcessingIO` input node, so the AEC reference signal cancels the assistant's own voice from the mic. A separate playback path (e.g. `AVAudioPlayer`) breaks echo-cancel. → impact: Stop (this is the core brain.md AEC requirement; the engine graph wires capture + playback into one engine).
- **openWakeWord** ("Hey Jarvis", the built-in model) runs on the post-AEC capture stream inside the sidecar. The model is an ONNX model run via an embeddable runtime; the EXACT Swift inference path is a build-time choice. → impact: Caution. DRAFTED DEFAULT: openWakeWord ("Hey Jarvis") behind a `WakeWordDetector` protocol + `FakeWakeWord` for off-hardware tests; concrete on-device runtime (ONNX Runtime Swift/C via SwiftPM primary, CoreML `MLModel` fallback) loaded + confirmed in GATED Task 9. On-hardware item, not an owner fork.
- **Silero VAD** runs on the post-AEC capture stream to detect speech onset/offset for endpointing and barge-in. Same runtime question as the wake word. → impact: Caution. DRAFTED DEFAULT: Silero VAD behind a `VoiceActivityDetector` protocol + `FakeVAD`; concrete runner (same ONNX-primary/CoreML-fallback) loaded in GATED Task 9; playback-state-aware barge-in threshold testable off-hardware against the fake.
- **Barge-in**: while TTS is playing, if the VAD reports speech onset (above a playback-state-aware threshold), the sidecar MUST flush the playback buffers and stop the player node within <200ms, and emit a `bargein` event to the brain so it can cancel the in-flight TTS stream. → impact: Stop (brain.md hard latency requirement; the flush-and-stop path is the load-bearing logic).
- The brain (Python) is the IPC **client**, built in **M5-d**. M5-a ships only the sidecar **server** + a Swift test harness (fakes for wake/VAD/audio-unit) that exercises the IPC framing, the state machine, and the barge-in flush logic. → impact: Caution (the wire protocol frozen here is the contract M5-d consumes; both must match).
- The IPC carries TWO data kinds over ONE Unix-domain socket: (1) **control/event messages** as length-prefixed JSON (the M2-a framing pattern: 4-byte big-endian length + UTF-8 JSON body), and (2) **raw PCM frames** as length-prefixed binary blobs tagged by a 1-byte channel discriminator before the length. PCM format is fixed: 16 kHz, mono, 16-bit signed little-endian (the STT/VAD/wake working format). → impact: Caution. DRAFTED DEFAULT: a single multiplexed Unix-domain socket (1-byte kind tag + 4-byte big-endian length + body) — one LaunchAgent endpoint, mirrors the broker. Split sockets are the documented fallback if on-hardware bring-up shows framing contention; only the framing module changes.
- The sidecar is **stateful**: a small state machine `idle → wake-detected → capturing → (endpoint) → awaiting-response → playing → (barge-in|done) → idle`. The brain drives transitions via IPC (e.g. "play this PCM", "stop") and the sidecar reports events (wake, speech-start, speech-end/endpoint, barge-in). → impact: Caution (the state machine is the orchestration contract; M5-d's voice loop is its peer).

Simplicity check: considered a pure-Python audio pipeline (sounddevice + a Python AEC/WebRTC-APM) — rejected by brain.md/the voice research: Apple `VoiceProcessingIO` is the validated AEC blueprint and "TTS must render through the same engine as capture", which a Python pipeline cannot satisfy cleanly. Considered embedding wake/VAD in Python and streaming raw mic to it — rejected: the AEC reference + low-latency barge-in flush must live next to the audio unit (a network/IPC hop before VAD would blow the <200ms barge-in budget). The minimal form is a tiny Swift sidecar owning the engine, with wake/VAD/barge-in co-located, mirroring the existing M2-a SwiftPM package — smallest auditable audio-owning unit.

## Prerequisites
- Specs that must be complete first: **M0-a** (the `/Users/artemis-build/artemis` repo root + the per-slot data-dir layout, esp. `<slot>/run/` where the sidecar socket lands, mirroring the broker socket), **M0-b** (the `com.artemis.audio.plist.template` LaunchAgent already pointing at `{AUDIO_SIDECAR_BIN}` — M5-a fills that binary; M5-a does NOT modify the plist). Soft: **M2-a** (the `swift/ArtemisBroker` package this one mirrors for layout/IPC conventions).
- Environment setup required: Swift 6 toolchain (Xcode CLT) on the Mac Mini. The IPC framing, the state machine, the barge-in flush logic, and the wake/VAD protocol wiring are unit-testable on any Apple Silicon mac with the toolchain using fakes; **real microphone capture, real VoiceProcessingIO/AEC, real openWakeWord + Silero inference, real playback, and the <200ms barge-in latency are GATED on-hardware (see Tasks 8–9).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/swift/ArtemisAudio/Package.swift | create | SwiftPM executable package `artemis-audio` + a test target (mirrors ArtemisBroker/Package.swift) |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/AudioEngine.swift | create | `AVAudioEngine` + `VoiceProcessingIO` graph: post-AEC capture tap + TTS playback node on the SAME engine |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/WakeWord.swift | create | `WakeWordDetector` protocol + the openWakeWord runner + `FakeWakeWord` |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/VAD.swift | create | `VoiceActivityDetector` protocol + Silero runner + `FakeVAD` + playback-state-aware barge-in threshold |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/BargeIn.swift | create | barge-in controller: on speech-onset-during-playback, flush+stop playback <200ms, emit `bargein` |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/StateMachine.swift | create | the `idle→wake→capturing→endpoint→playing→…` state machine driving events/transitions |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/Protocol.swift | create | the wire message types (Codable) + PCM framing — the brain↔sidecar contract |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/IPCServer.swift | create | Unix-domain-socket server; peer-cred check; multiplexed JSON+PCM framing; dispatch |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/main.swift | create | entry point: parse args (`serve`), read socket path/format from env, wire components |
| /Users/artemis-build/artemis/swift/ArtemisAudio/Tests/ArtemisAudioTests/AudioTests.swift | create | unit/integration tests using FakeWakeWord/FakeVAD + an in-process socket pair |
| /Users/artemis-build/artemis/docs/technical/protocol/audio-ipc.md | create | the frozen IPC message + PCM-framing contract (consumed by M5-d's Python client) |

## Tasks
- [ ] Task 1: Scaffold the SwiftPM package — files: `/Users/artemis-build/artemis/swift/ArtemisAudio/Package.swift` — mirror `swift/ArtemisBroker/Package.swift`: `swift-tools-version: 6.0`; one executable target `artemis-audio` (path `Sources/ArtemisAudio`) + one test target `ArtemisAudioTests`; macOS platform matching the broker package's (document if the SDK ceiling differs); strict concurrency enabled. Dependencies: `Foundation`, `AVFoundation`, `AudioToolbox` (system); declare the wake/VAD inference runtime dependency as a TODO comment to be added at the GATED task (kept out of the off-hardware build so the package compiles + unit-tests without the model runtime). — done when: `swift build` (in `swift/ArtemisAudio/`) succeeds with an empty `main.swift` stub.

- [ ] Task 2: Define the wire protocol + PCM framing — files: `/Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/Protocol.swift` — `Codable` control/event message types, framed per the M2-a pattern but multiplexed: each frame = 1-byte `kind` (`0x01` = JSON control, `0x02` = PCM-from-mic, `0x03` = PCM-to-speaker) + 4-byte big-endian length + body.
  - Events sidecar→brain (JSON): `wakeDetected`, `speechStart`, `speechEnd(reason: "endpoint"|"maxDuration")`, `bargein`, `playbackStarted`, `playbackFinished`, `error(code, message)`, `status(state)`.
  - Commands brain→sidecar (JSON): `startListening` (arm capture after wake or on demand), `stopListening`, `play(sampleRate, channels)` (announces an incoming `0x03` PCM stream to render), `stopPlayback`, `getStatus`.
  - PCM frames: `0x02` carries 16 kHz/mono/16-bit-LE mic audio sidecar→brain during capture; `0x03` carries the same format brain→sidecar for playback. Define the fixed `AudioFormat` constant (16000 Hz, 1 ch, Int16 LE) and document it as the frozen working format.
  — done when: `swift build` passes; a round-trip encode/decode unit test frames+parses each message + a PCM blob without loss (Task 8 test list).

- [ ] Task 3: Implement the AVAudioEngine + VoiceProcessingIO graph — files: `/Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/AudioEngine.swift` — `final class AudioEngine` (actor-isolated or `@unchecked Sendable` with documented locking):
  - one `AVAudioEngine`; enable voice processing on the input node (`try inputNode.setVoiceProcessingEnabled(true)` — the macOS AEC path) so capture is post-AEC.
  - install a tap on the (post-AEC) input node converting to the fixed 16 kHz/mono/Int16 format, delivering frames to an injected `onMicFrame: (Data) -> Void` callback (the wake/VAD/IPC consumers subscribe).
  - a player node (`AVAudioPlayerNode`) attached to the SAME engine for TTS playback: `func play(pcm: AsyncStream<Data>)` schedules buffers; `func flushPlayback()` stops the player node + clears scheduled buffers immediately (the barge-in primitive).
  - `func start() throws` / `func stop()`; surface `CFError`/`NSError` as a thrown typed `AudioError`.
  - Document: capture + playback share this ONE engine so AEC cancels self-voice; no separate playback path is permitted.
  — done when: `swift build` passes; the engine class compiles; a unit test (with the real audio unit NOT started — engine constructed but `start()` skipped off-hardware behind an `ARTEMIS_AUDIO_HW=1` guard) exercises the `flushPlayback` buffer-clear logic against a stubbed player. The real `setVoiceProcessingEnabled`/AEC start is GATED (Task 9).

- [ ] Task 4: Implement the wake-word runner + protocol + fake — files: `/Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/WakeWord.swift` — `protocol WakeWordDetector { func feed(_ pcm: Data) -> Bool }` (returns true on a wake event for the just-fed frame window). `struct FakeWakeWord: WakeWordDetector` (TEST) — returns true once after an injected number of frames / on an injected flag; mark "TEST HARNESS — stands in for the openWakeWord ONNX/CoreML runner loaded on-hardware." `final class OpenWakeWord: WakeWordDetector` — load the "Hey Jarvis" model + run inference on a sliding window of post-AEC frames; the concrete inference runtime is added at the GATED task (Task 9) behind this same protocol (compile-guard the runtime import so the off-hardware build excludes it; the off-hardware build uses only `FakeWakeWord`). — done when: `swift build` passes (off-hardware, FakeWakeWord only); a test shows `FakeWakeWord` fires exactly once on its trigger condition.

- [ ] Task 5: Implement the VAD runner + protocol + fake + barge-in threshold — files: `/Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/VAD.swift` — `protocol VoiceActivityDetector { func feed(_ pcm: Data) -> VADEvent }` where `enum VADEvent { case none, speechStart, speechEnd }`. `struct FakeVAD: VoiceActivityDetector` (TEST) — emits a scripted sequence of events. `final class SileroVAD: VoiceActivityDetector` — Silero on the post-AEC stream (concrete runtime at Task 9, compile-guarded, same protocol). Add `struct BargeInThreshold` — a playback-state-aware gate: `func shouldBargeIn(vad: VADEvent, isPlaying: Bool) -> Bool` returns true ONLY when `isPlaying && vad == .speechStart` AND a configurable energy/confidence margin is met (the margin is a constant in M5-a; tuning is a build-time spike per brain.md "barge-in tuning"). — done when: `swift build` passes; tests show `shouldBargeIn` returns true only during playback on speech-start and false while idle.

- [ ] Task 6: Implement the barge-in controller + the state machine — files: `/Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/BargeIn.swift`, `/Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/StateMachine.swift` —
  - StateMachine.swift: `enum AudioState { case idle, capturing, awaitingResponse, playing }` + `actor AudioStateMachine` with transitions driven by events (wake → capturing; endpoint/speechEnd → awaitingResponse; play command → playing; bargein/stopPlayback/playbackFinished → idle or capturing). Pure logic, no audio calls — it decides transitions and which IPC events to emit. Document the legal transition table.
  - BargeIn.swift: `struct BargeInController` wiring `BargeInThreshold` + the `AudioEngine.flushPlayback` primitive + the state machine: on a `shouldBargeIn` true while `state == .playing`, (1) call `flushPlayback()` synchronously, (2) transition the state, (3) emit a `bargein` IPC event — measured to complete the flush in <200ms (the latency itself is GATED Task 9; the *ordering/logic* is tested off-hardware with a stub engine recording that `flushPlayback` was called before the `bargein` emit). — done when: `swift build` passes; a test feeds a `.speechStart` while `state == .playing` and asserts `flushPlayback` was invoked AND a `bargein` event was emitted AND the state left `.playing`; feeding `.speechStart` while idle does nothing.

- [ ] Task 7: Implement the IPC server + entry point — files: `/Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/IPCServer.swift`, `/Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/main.swift` —
  - IPCServer.swift: Unix-domain-socket server bound to `<dataRoot>/<slot>/run/audio.sock` (dir `0700`, socket `0600`), mirroring the broker IPCServer. BEFORE dispatch, enforce a peer-credential check (`getpeereid`/`LOCAL_PEERPID`): connecting uid MUST equal the sidecar's own uid (rejects other accounts) — mirror the broker's peer-uid gate; a code-signing check is OUT of scope for the audio socket in M5 (no DEK crosses it; document the difference + leave a flagged TODO). Demux frames by the 1-byte kind (Task 2): route `0x01` JSON commands to a handler, `0x03` PCM to the engine's playback, and stream `0x02` mic PCM + `0x01` events back to the connected brain. Never block the audio thread on the socket (buffer/queue). 
  - main.swift: parse argv `serve`; read `ARTEMIS_DATA_ROOT`/`ARTEMIS_SLOT` (resolve the socket path the M0-a way), construct `AudioEngine` + `OpenWakeWord` (or `FakeWakeWord` when `ARTEMIS_AUDIO_HW` unset) + `SileroVAD`/`FakeVAD` + the state machine + `BargeInController` + `IPCServer`, and run the loop wiring mic frames → wake/VAD → state machine → IPC events, and IPC `play` → engine playback. — done when: `swift build` passes; `swift run artemis-audio serve` (off-hardware, fakes) starts, creates the socket with `0600`, accepts a connection, and a scripted FakeWakeWord→FakeVAD sequence emits `wakeDetected`→`speechStart`→`speechEnd` events over the socket (Task 8).

- [ ] Task 8: Write the sidecar test suite — files: `/Users/artemis-build/artemis/swift/ArtemisAudio/Tests/ArtemisAudioTests/AudioTests.swift` — XCTest/swift-testing covering, all off-hardware with fakes: Protocol frame round-trip (each JSON message + a PCM blob, incl. the 1-byte kind + 4-byte length); state-machine legal/illegal transitions; `BargeInThreshold.shouldBargeIn` truth table; barge-in ordering (flush-before-emit, leaves `.playing`); end-to-end over an in-process socket pair — a scripted FakeWakeWord+FakeVAD drives `wakeDetected→speechStart→speechEnd`, the brain side sends `play`, then a FakeVAD `speechStart` triggers `bargein` and the stub engine records `flushPlayback`. The real-audio tests are guarded by `ARTEMIS_AUDIO_HW=1` (skipped off-hardware). — done when: `swift test` passes off-hardware (HW-guarded tests reported skipped).

- [ ] Task 9 (GATED — on-hardware): Real AEC + wake + VAD + barge-in latency on the Mini — files: (no new files; loads the concrete wake/VAD runtimes added here behind their protocols + runs the `ARTEMIS_AUDIO_HW=1` paths) — on the Mac Mini only: (a) add + wire the chosen openWakeWord + Silero inference runtime (the Assumptions drafted-default: ONNX Runtime primary / CoreML fallback) behind `WakeWordDetector`/`VoiceActivityDetector`; (b) start the real `AVAudioEngine` with `setVoiceProcessingEnabled(true)`, confirm mic capture is post-AEC and that playing TTS PCM through the same engine does NOT re-trigger the wake word / VAD from the assistant's own voice (AEC works); (c) say "Hey Jarvis" → confirm a `wakeDetected` event; (d) during playback, speak → confirm playback flushes + a `bargein` event within **<200ms** (measure end-of-speech-onset → playback-silence). Build-time empirical (mic, ANE/AEC, latency). — done when: on the Mini, AEC suppresses self-voice, "Hey Jarvis" fires the wake event, and barge-in flushes playback in <200ms — measured + recorded in `docs/handoff/`.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/swift/ArtemisAudio/Package.swift, /Users/artemis-build/artemis/swift/ArtemisAudio/Sources/ArtemisAudio/*.swift, /Users/artemis-build/artemis/swift/ArtemisAudio/Tests/ArtemisAudioTests/AudioTests.swift, /Users/artemis-build/artemis/docs/technical/protocol/audio-ipc.md |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `swift build` (in swift/ArtemisAudio) | Compile the sidecar |
| `swift test` (in swift/ArtemisAudio) | Run the sidecar test suite (HW-guarded tests skipped off-hardware) |
| `swift run artemis-audio serve` (off-hardware, fakes) | Smoke the IPC + state machine with FakeWakeWord/FakeVAD |
| `ARTEMIS_AUDIO_HW=1 swift test` (GATED, on-Mini) | Real audio/AEC/wake/VAD/barge-in |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | swift/ArtemisAudio/**, docs/technical/protocol/audio-ipc.md |
| `git commit` | "feat: M5-a audio sidecar — VoiceProcessingIO AEC engine, openWakeWord, Silero VAD + barge-in, brain↔sidecar IPC" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_DATA_ROOT` | Root of the per-slot data tree (run/ holds audio.sock) |
| `ARTEMIS_SLOT` | Which slot the sidecar serves |
| `ARTEMIS_AUDIO_HW` | Gate the real-audio paths (set only on the Mini) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No outbound; IPC is a local Unix domain socket only |
| (GATED, on-Mini) wake/VAD model fetch | Download the openWakeWord + Silero model files for the on-hardware runtime |

## Specialist Context
### Security
The audio socket carries voice PCM + control only — NO DEK, NO owner data keys cross it (those stay on the broker socket, ADR-005). It still enforces a peer-uid check (rejects the build-agent user + other accounts), mirroring the broker; the code-signing check is deliberately omitted here (no key material) — documented + flagged. Mic audio is owner-sensitive content: the sidecar must never write captured PCM to disk or a log (log only events + frame counts). [FLAG apex-security: voice is an injection vector — transcribed speech is untrusted data; the brain (M5-d) treats STT output as data, not instructions. The sidecar itself runs no model-driven logic, so its blast radius is small.]

### Performance
Barge-in <200ms is the hard budget (brain.md): wake/VAD/flush are co-located with the audio unit so no IPC hop sits inside the barge-in path. The mic-frame callback must be non-blocking (the socket write is queued off the audio thread). The fixed 16 kHz/mono/Int16 format avoids per-frame resampling cost downstream.

### Accessibility
(none — headless audio agent; the voice interaction *is* an accessibility surface, but no rendered UI here.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | all Sources/ArtemisAudio/*.swift | Doc-comment every public type/func; flag `FakeWakeWord`/`FakeVAD` as test-only; document the one-engine AEC requirement |
| Protocol | docs/technical/protocol/audio-ipc.md | Write the frozen multiplexed (1-byte kind + 4-byte length + body) message + PCM-framing contract (the M5-d client implements it) |

## Acceptance Criteria
- [ ] Run `swift build` in `swift/ArtemisAudio` → verify: exit 0.
- [ ] Run `swift test` in `swift/ArtemisAudio` → verify: all off-hardware tests pass (HW-guarded tests reported skipped).
- [ ] Run `swift run artemis-audio serve` against a temp `ARTEMIS_DATA_ROOT` (fakes) → verify: an `audio.sock` exists under `<root>/<slot>/run/` with perms `0600`; a connected client receives a scripted `wakeDetected`→`speechStart`→`speechEnd` event sequence.
- [ ] Run the barge-in unit test → verify: a `.speechStart` during `.playing` invokes `flushPlayback` BEFORE emitting `bargein` and leaves `.playing`; a `.speechStart` while idle does nothing.
- [ ] Run the peer-uid rejection test → verify: a connection from a simulated non-owner uid is refused before dispatch.
- [ ] (GATED, on Mini) `ARTEMIS_AUDIO_HW=1` real run → verify: AEC suppresses self-voice (playing TTS does not self-trigger wake/VAD), "Hey Jarvis" fires `wakeDetected`, barge-in flushes playback in <200ms — recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

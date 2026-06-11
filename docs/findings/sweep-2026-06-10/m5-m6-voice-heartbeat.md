# Sweep 2026-06-10 — M5 voice pipeline + M6 heartbeat/proactivity

Reviewer scope: M5-a/b/c/d, M6-a/b/c, ADR-006. Rubric: BLOCK / UPGRADE / FLAG / RESEARCH.
All file references are to `docs/changes/` specs unless noted.

---

## BLOCK

### B1 — M6-c `attach_to_heartbeat` / `pre_tick_steps` amendment is incoherent with M6-a's Heartbeat
**File:** `M6-c-ntfy-delivery-policy-tier1-queue.md` Task 4 + Task 5; vs `M6-a-scheduler-tickloop-hookcontract.md` Task 3.
M6-a defines `tick()` as a **synchronous** method and `run_forever` as "each iteration run `tick()` then `await asyncio.sleep(...)`" — there is **no seam** for substituting the loop body. M6-c Task 4 says the runner "is an `async def _tick_runner()` coroutine that `attach_to_heartbeat` **patches onto the Heartbeat** so `run_forever`'s loop body calls `await _tick_runner()` instead of `tick()` directly." Two failure modes for a literal executor: (a) monkeypatch `heartbeat.tick = _tick_runner` → M6-a's `run_forever` calls `tick()` without `await` → a coroutine is created and never awaited (drain + pre-steps silently never run); (b) modify `heartbeat.py` to add the seam → `heartbeat.py` is **not in M6-c's Files to Change** (scope-lock violation; coding mode will treat it as a blocked action). The amendment also leaves the drain-vs-tick **ordering** ambiguous: Task 4 lists "(1) await pre_tick_steps … before `heartbeat.tick()`; (2) calls `queue.drain(...)`" while the Assumptions say "poll `is_owner_unlocked()` at the start of each tick" and the no-steps fallback says "(drain + tick)". **Fix:** amend M6-a Task 3 to give `Heartbeat` an explicit `tick_runner: Callable[[], Awaitable[None]] | None` seam (or a `pre_tick`/`post_tick` hook) that `run_forever` awaits, and state the canonical order (pre_tick_steps → drain-if-unlocked → tick), or add `heartbeat.py` to M6-c's Files to Change with the exact modification.

### B2 — M6-b↔M6-c `deliver` sink type mismatch fails `mypy --strict`; drain's "confirmed delivery" count is unreachable
**File:** `M6-b-hit-handling-batched-llm-urgency-briefing.md` Task 2 ("constructed with `(model, templates, deliver: Callable[[list[OutboundMessage]], None]`") vs `M6-c-ntfy-delivery-policy-tier1-queue.md` Task 3 ("`def __call__(self, messages) -> int` — returns the count SUCCESSFULLY published … this IS the M6-b `deliver` sink").
Under `mypy --strict` (both specs' acceptance gate), a callable returning `int` is **not assignable** to `Callable[[list[OutboundMessage]], None]` (return types are covariant; `int` is not a subtype of `None`). The build fails its own type gate. Worse, M6-c Task 4 drain says "route through `hit_handler.handle(...)` whose delivery (`NtfyDelivery.__call__`) returns a 2xx count — remove the entry ONLY on CONFIRMED delivery (B5)" — but `handle()` calls `self.deliver(messages)` internally and **discards its return**; `handle()` returns `list[OutboundMessage]`. The drain has no plumbed path to the 2xx count as specified. **Fix:** type the M6-b seam `Callable[[list[OutboundMessage]], int]` (or `object`) AND give the drain an explicit confirmation path — e.g. drain builds the messages via a HitHandler constructed with a capturing sink, then calls `NtfyDelivery.__call__` itself and compares counts; or `handle()` returns `(messages, delivered_count)`.

### B3 — M6-b digest dedup (`dedup_key="digest"`, `dedup_value=today`) silently drops every low-urgency hit after the day's first digest
**File:** `M6-b-...md` Task 2 step 5; interacts with `M6-c-...md` Task 2/3 dedup.
The heartbeat ticks every ~60s. The first tick of the day with any low-urgency hit emits the digest message; M6-c posts it and `dedup.mark("digest", <today>)`. Every later tick that day, new low-urgency hits are folded into a digest with the **same** `(key, value)` → `dedup.seen()` → "log deduped + skip". The individual messages were already removed in step 5, so those hits are **lost, by construction, with no log of the per-hit dedup tuples**. This contradicts the intent of batch-low→digest (bundle, don't drop). **Fix options (pick one in a spec amendment):** (a) digest `dedup_value = f"{date}-{tick-seq}"` and rely on per-hit dedup *before* folding (move the per-hit `dedup.seen` check into the fold so already-sent low hits don't re-digest); (b) hold low-urgency messages in M6-c's `held.json` and flush as one digest at a scheduled time (the more honest "daily digest"); (c) make the digest a daily cron hook. As written the behaviour is silent data loss.

### B4 — M6-c `flush_held()` has no caller — quiet-hours-held messages are never delivered
**File:** `M6-c-...md` Task 3 (defines `flush_held`), Task 4/5 (`attach_to_heartbeat`, `compose_proactive`).
Held messages are "delivered when `flush_held()` is next called outside quiet hours" — but neither `attach_to_heartbeat`'s `_tick_runner` nor `compose_proactive` nor any task wires a `flush_held()` call. Task 6's test calls it manually; the composed system never does. A literal executor builds a hold queue that fills and never drains (until entries hit `held_ttl_hours` and are *dropped*). **Fix:** add `ntfy.flush_held()` to the per-tick runner (e.g. step 0 of `_tick_runner`), and add a Task 6 assertion that a held message is delivered by a *tick* occurring outside quiet hours (not by a manual call).

### B5 — Security: `held.json` persists full `OutboundMessage` bodies — a drained Tier-1 message held during quiet hours puts sensitive content in plaintext on disk
**File:** `M6-c-...md` Task 3 + Assumptions ("They hold ONLY Tier-0-safe metadata … so no encryption") + Specialist Context §Security invariant (1).
The no-encryption rationale covers `dedup.json`/`tier1_queue.json` (identities only) but `held.json` stores whole messages, **title + body included**. Sequence that breaks the invariant: owner unlocks late evening → `drain()` runs a Tier-1 `check_ref` (allowed, unlocked) → resulting message has `urgency=normal` ⇒ `deferrable` → quiet hours (22:00–07:00) ⇒ `suppresses → "hold"` → the **sensitive body sits in plaintext JSON** in `held.json` overnight, exactly the at-rest exposure ADR-005/006 exists to prevent. The spec's own security section claims "no sensitive payload ever lands here — Tier-1 checks don't run while locked", which is true for the *queue* but not for the *hold list*. **Fix:** either (a) never hold Tier-1-sourced messages (deliver immediately or re-queue the hook identity instead of the rendered message), or (b) encrypt `held.json` under the Tier-0 key and accept the scope creep explicitly in ADR-006, or (c) hold only Tier-0 (`msg.tier == 0`) messages and treat Tier-1 + quiet-hours as immediate-with-low-priority. Also note the secondary interaction: a held drained message yields delivered-count 0 → drain increments `retry_count` → re-runs the hook next tick AND the held copy later flushes ⇒ **duplicate delivery + spurious dead-lettering** (see U6).

### B6 — M5-d streaming voice path has no channel for the `NEEDS_PHONE_UNLOCK` signal
**File:** `M5-d-voice-loop-orchestrator.md` Task 3 step 5 + Task 4; vs `M5-c-speaker-id.md` Task 3.
M5-c's `handle_voice` returns a typed `BrainResponse(text="NEEDS_PHONE_UNLOCK", path="needs-unlock", ...)`. M5-d's loop, however, is told to use `handle_voice_stream(audio, transcript) -> AsyncIterator[str]` — a bare string stream with **no defined representation** for the needs-unlock case (or for guest routing metadata). Task 3 step 5 conflates the two: "call `gateway.handle_voice(...)` — BUT to stream, use the streaming voice path … If the gateway returns `NEEDS_PHONE_UNLOCK` …". A literal executor cannot decide: does `handle_voice_stream` yield the sentinel as its only segment? Raise a typed exception? Should the loop call `handle_voice` first and `handle_voice_stream` second (two identify + two pre_route passes)? **Fix:** define `handle_voice_stream`'s contract exactly — recommended: it performs identify + Tier gate itself and either (a) raises a typed `NeedsPhoneUnlock` exception the loop catches, or (b) returns a small union `VoiceStreamResult = NeedsUnlock | AsyncIterator[str]`. Also specify what the loop *speaks* (see F6 — the sentinel string would be TTS'd verbatim).

---

## UPGRADE

### U1 — M6-b batched LLM call: use `response_schema` structured output instead of newline-split-and-zip
**File:** `M6-b-...md` Task 2 step 3. The `ModelPort.complete` signature *already carries* `response_schema=None` (M0-d). Line-splitting a free-text response and zipping by order is the fragile pattern (a model emitting a blank line, a wrapped line, or a preamble breaks alignment; the spec needs a whole fallback branch + mismatch logging for it). Within-stack fix: request `{"items": [{"index": int, "line": str}, ...]}` via `response_schema` (mlx-openai-server supports OpenAI-style JSON-schema/structured output as of 2026) and keep the template fallback only for schema-parse failure. Smaller spec, fewer failure modes.

### U2 — M5-d/M5-c: synchronous STT/TTS/SpeakerID calls inside the async loop will starve event handling — barge-in cannot interrupt an in-flight sync `synthesize` iteration
**File:** `M5-d-...md` Task 3 (steps 3, 5, 6), `M5-b-...md` (sync `transcribe`/`synthesize` ports), `M5-c-...md` Task 3 (sync `identify` inside async `handle_voice`).
The loop is "an async, cancellable coroutine", but `stt.transcribe()` (hundreds of ms of MLX inference), `tts.synthesize()` (a *sync* `Iterator[bytes]` consumed per chunk), and ECAPA `identify()` (PyTorch) are all synchronous. While any of them executes, the asyncio loop cannot read the sidecar socket — so a `bargein` event sits unprocessed until the current sentence finishes synthesising. Off-hardware tests pass (fakes are instant); on hardware the <200ms-flush story holds at the sidecar but the *upstream cancellation* (M5-d's half of the contract) is delayed by up to a full sentence of synth. **Fix:** spec amendment requiring `await asyncio.to_thread(stt.transcribe, ...)` / driving the TTS iterator in a worker thread feeding an `asyncio.Queue` (cancel = stop consuming + drop the thread's output), and the same for `identify`. Name it in Task 3 explicitly — a literal executor will not add threading on its own.

### U3 — M5-c: SpeechBrain (full PyTorch) is a heavy dependency for one embedding model — consider ECAPA via ONNX (sherpa-onnx / WeSpeaker ONNX export)
**File:** `M5-c-...md` Assumptions + Task 1. Everything else in the brain is MLX; SpeechBrain drags in torch + torchaudio (~2+ GB, slow cold import) for a single 22M-param embedding model run once per utterance. As of mid-2026 the within-stack lighter options: `sherpa-onnx` ships ready-made speaker-embedding models (3D-Speaker / WeSpeaker / NeMo ECAPA-class) on CPU via ONNX Runtime with a tiny footprint, or export ECAPA to ONNX once and run with `onnxruntime` directly (the repo will already carry ONNX Runtime expertise from M5-a's wake/VAD path). The `_load_ecapa` seam means this is a one-line drafted-default change now vs a heavyweight dep forever. Keep SpeechBrain as the fallback if the gated task finds quality issues.

### U4 — M5-b: the Kokoro MLX drafted default package name is almost certainly `mlx-audio`, not `kokoro-mlx`
**File:** `M5-b-...md` Assumptions, Task 6, Permissions (`uv add kokoro-mlx`). The maintained MLX implementation of Kokoro-82M ships inside the `mlx-audio` package (Blaizzy/mlx-audio — TTS/STS for Apple Silicon, Kokoro + CSM + others); a standalone `kokoro-mlx` PyPI name is speculative. The gated task does say "confirm name", but the Permissions table pre-authorises `uv add kokoro-mlx` — a literal executor on the Mini will run that and fail or, worse, install a squatter package (supply-chain risk for a pre-authorised network action). Same nit for `parakeet-mlx` (real, exists) — fine. **Fix:** change the drafted default + Permissions row to `mlx-audio`, keep the confirm-at-gate language.

### U5 — M5-a: no pre-roll/ring buffer — the first ~0.3–0.5s of post-wake and barge-in utterances are lost
**File:** `M5-a-audio-sidecar.md` Tasks 3/6/7; `M5-d-...md` Task 3 step 7. After `wakeDetected`, mic PCM only flows once capture is armed (and M5-d even waits a socket round-trip to send `startListening` — see F1); after `bargein`, the speech that *triggered* the barge-in began before the flush. Without a small ring buffer (e.g. 1s of post-AEC audio) prepended when capture opens, both utterance types arrive truncated at STT and transcribe wrong. This is a standard wake-word-pipeline pattern and cheap to add in the sidecar (`AudioEngine` keeps a rolling buffer; `startListening` drains it first). **Fix:** add the ring buffer to M5-a Task 3 and state that the capture stream begins with buffered pre-roll from speech onset / wake-phrase end.

### U6 — M6-c drain: one `hit_handler.handle()` per queued hook ⇒ N model calls; batch the drained hits into one `TickResult`
**File:** `M6-c-...md` Task 4. "For each pending queued hook: … RUN `check_ref()` NOW; if it hits, route through `hit_handler.handle(...)`" — N drained `needs_llm` hooks = N batched-LLM calls, violating the spirit (and the M6-b test contract) of "ONE batched LLM call per tick". **Fix:** drain collects all hits from all due queued hooks first, then makes ONE `handle(TickResult(hits=...))` call; per-hook retry bookkeeping keyed off which messages confirmed. (Also resolves half of B2's plumbing if `handle` is called once.)

### U7 — M6-b digest `tier=min(tiers)` should be `max` (most restrictive) — or drop the field from the digest
**File:** `M6-b-...md` Task 2 step 5. `min` labels a digest containing any Tier-1-sourced (post-drain) message as Tier-0. Nothing in M6-c gates on `msg.tier` *today*, but the field exists precisely so delivery policy can; the day it does, the label is wrong in the unsafe direction. One-character fix.

---

## FLAG

### F1 — Who arms capture after wake: M5-a's state machine auto-transitions `wake → capturing`, but M5-d sends `startListening` and its test asserts the command was recorded
**File:** `M5-a-...md` Task 6 ("transitions driven by events (wake → capturing; …)") + Task 8 (the scripted e2e emits `wakeDetected→speechStart→speechEnd` with no brain command); vs `M5-d-...md` Task 3 step 1 + Task 5 ("assert the FakeSidecar RECORDED: a `startListening`"). Both can be built, but the *contract* (who owns the transition; is `startListening` required, idempotent, or a no-op while already capturing?) must be written into `docs/technical/protocol/audio-ipc.md` explicitly or the two implementations will disagree on edge cases (e.g. wake fires while the brain is busy). State it: sidecar auto-captures on wake; `startListening` is an idempotent re-arm used after barge-in.

### F2 — M5-a Task 6: transition target "idle **or** capturing" is unresolved; the legal transition table is demanded but not given
**File:** `M5-a-...md` Task 6. "bargein/stopPlayback/playbackFinished → idle or capturing" — a literal executor must pick. For barge-in the *correct* target is `capturing` (the user is mid-utterance, per M5-d step 7); for `playbackFinished` it's `idle`; for `stopPlayback` unstated. Write the actual table into the spec (it's ~8 rows), don't delegate "Document the legal transition table" to the executor.

### F3 — M5-a acceptance: the peer-uid rejection test is not runnable as specified
**File:** `M5-a-...md` Acceptance Criteria bullet 5, Task 7. A unit test cannot present a foreign uid on a Unix socket without a second user account/root. The check is only testable if the peer-credential lookup is behind an injectable seam (e.g. `protocol PeerCredentialChecker` with a fake returning an arbitrary uid) — no such seam is in the file list or task text. Add the seam to Task 7 or mark the criterion GATED like the broker presumably did (mirror whatever M2-a did here — cross-check that spec).

### F4 — M5-c voiceprint store location: `scope_dir(...)` ellipsis + self-contradicting assumption
**File:** `M5-c-...md` Task 1 ("stores … under `scope_dir(...)/voiceprints/`") vs Assumptions ("under `scope_dir("owner-private")/voiceprints/<person_id>.npy` … DECISION: voiceprints in a SEPARATE small store readable WITHOUT the owner DEK"). If the owner-private scope dir implies DEK-encrypted residency conventions, placing the Tier-0-keyed store there contradicts the decision; either way the literal `scope_dir(...)` is unexecutable. Name the exact path (suggest `<slot>/proactive/voiceprints/` next to M6-c's Tier-0-class stores, or a dedicated `<slot>/identity/`).

### F5 — M5-d: the earcon `ack_pcm` asset does not exist and no task creates it
**File:** `M5-d-...md` Task 4 ("load the cached `ack_pcm` (… a pre-rendered bundled earcon file loaded at startup)"). No file path, no asset in the Files to Change, no generation step. A literal executor stalls or invents a path. Fix: add e.g. `src/artemis/voice/assets/ack.pcm` to Files to Change with a task that generates it deterministically (a stdlib-synthesised 150ms sine-blip written as 16kHz/mono/Int16 — no model needed), or specify `ack_pcm=b""`-tolerant behaviour for off-hardware.

### F6 — M5-d will TTS the literal sentinel "NEEDS_PHONE_UNLOCK"
**File:** `M5-d-...md` Task 3 step 5 ("synth + play that prompt"); `M5-c-...md` Task 3 (`BrainResponse(text="NEEDS_PHONE_UNLOCK", ...)`). The "prompt" the loop holds *is* the sentinel string; a literal executor synthesises "NEEDS PHONE UNLOCK" as speech. Specify the sentinel→spoken-phrase mapping (e.g. "That needs your phone unlock first.") and where it lives (a constant in voice_loop.py).

### F7 — M5-d latency stage `speaker_id_done` is unobservable from the loop
**File:** `M5-d-...md` Task 2 (stage list) + Task 3 step 5. Identity resolution happens inside `gateway.handle_voice_stream`; the loop cannot `mark("speaker_id_done")` at the documented point. Either the gateway must expose the timing (e.g. an optional `on_stage: Callable[[str], None]` it calls), or drop the stage / mark it at gateway-call-return. As written the Task 5 test "all stages marked" forces the executor to invent something.

### F8 — M5-b/M5-d: the Whisper multilingual route is dead code in the live voice loop
**File:** `M5-b-...md` Task 1 (routing on the `language` kwarg) vs `M5-d-...md` Task 3 step 3 (`stt.transcribe(utterance_pcm)` — no language hint, nothing in the pipeline produces one). At runtime `language is None` ⇒ always Parakeet; non-English speech produces garbage *without raising*, so the error-fallback never fires either. The Assumptions acknowledge confidence-based fallback as "build-time refinement" — fine, but the specs should say plainly that v1 voice is English-only-in-practice, or wire the briefest signal (e.g. Parakeet returning empty/low-confidence ⇒ one Whisper retry) into M5-b Task 1 so the fallback is reachable.

### F9 — M6-c: nothing generates `ntfy_topic_secret`; the gated smoke command uses the guessable topic the spec itself banned
**File:** `M6-c-...md` Assumptions ("topic_secret … generated at slot-init and stored in the slot's non-public Settings — … (BLOCK fix)") + Permissions/Commands (`curl -d "test" http://127.0.0.1:{NTFY_PORT}/artemis-dev-owner`). No M6-c task (nor any cited M0 task) generates the secret or adds the `Settings.ntfy_topic_secret` field — only the on-hardware bullet "confirm whether M0-a/M0-b provide it, else M6-c introduces them" with no introducing task. And the pre-authorised smoke curl publishes to `artemis-dev-owner` — the exact guessable-topic shape the BLOCK fix replaced. Add a Task (or M0 amendment) that generates + persists the secret, and fix the smoke command to use the secret topic. (Severity kept at FLAG because ntfy binds 127.0.0.1 + Tailscale, so exposure is bounded — but the spec is internally inconsistent.)

### F10 — M6-a: "a `Hit` … flagged queued" — `Hit` has no such field
**File:** `M6-a-...md` Task 3 tick step (tier gate). The queued sentinel Hit is described as "flagged queued" but the `Hit` dataclass (Task 2) has no flag field; the guard note ("a queue-token ONLY — never a hit signal") covers the semantics, but a literal executor may add an ad-hoc field or misuse `result`. Either add `queued: bool = False` to `Hit` or strike "flagged queued" from the text. Trivial wording fix.

### F11 — M6-c policy: per-module floor lookup from `OutboundMessage` is unspecified
**File:** `M6-c-...md` Task 1 (`module_min_urgency: dict[str, ...]`) vs `OutboundMessage.source` = "fq `module.hook_name`, or `digest`". The module key must be derived (`source.split(".")[0]`? what about `"digest"`?). One sentence fixes it; without it `suppresses` implementations will diverge from the Task 6 test (`{"finance":"high"}` vs a message whose source is `finance.budget_alert`).

### F12 — M5-d prerequisite hardcodes `/opt/artemis` as the data root; every other M5/M6 spec resolves it from `ARTEMIS_DATA_ROOT`
**File:** `M5-d-...md` Prerequisites ("the data root resolves to `/opt/artemis`; the sidecar socket is `/opt/artemis/<slot>/run/audio.sock`") vs `M5-a-...md` Task 7/Permissions (env-resolved). If M0-a's canonical root differs, M5-d's prose plants a wrong constant in the executor's head; Task 1 correctly says "socket path (from `paths`)", so just delete the literal `/opt/artemis` mention or verify it against M0-a.

### F13 — M6-c drain × quiet-hours: an unconfirmed-because-held delivery increments `retry_count` ⇒ duplicate delivery + spurious dead-letter
**File:** `M6-c-...md` Task 3 + Task 4 (interaction; see also B5). A drained hit whose message is held (or deduped!) yields 0 confirmed publishes → entry retried next tick → hook re-runs → second copy held/deduped → after `max_attempts` the hook lands in `tier1_dead.json` even though nothing was wrong, while the held copy may still flush later. Define "confirmed" to include held-and-persisted and deduped-as-already-delivered, or drop the per-message confirmation in favour of "check_ref ran without raising".

### F14 — Headless-unverifiable audio criteria are properly gated, but the off-hardware Swift criteria still require a Mac
**File:** `M5-a-...md` Acceptance Criteria / Prerequisites. The spec is disciplined about `ARTEMIS_AUDIO_HW=1` gating (good). Note for sequencing only: "off-hardware" for M5-a still means *an Apple-Silicon Mac with Xcode CLT* (`swift build`/`swift test`, `setVoiceProcessingEnabled` symbol resolution) — with no Mac Mini purchased yet (per project memory), no M5-a acceptance criterion is runnable anywhere today. Worth stating in the bring-up runbook so nobody schedules M5-a before hardware exists.

---

## RESEARCH

### R1 — openWakeWord is a three-stage ONNX pipeline, not one model
**File:** `M5-a-...md` Task 4 / Task 9. openWakeWord inference = melspectrogram model → embedding (Google speech-embedding) model → wake classifier, three ONNX graphs with a specific feature-buffering dance between them. The spec's `final class OpenWakeWord` + "load the 'Hey Jarvis' model" reads as one model. Before the gated task, research the Swift port effort honestly (ONNX Runtime C API × 3 models + the 80-dim mel buffering) vs alternatives *within the locked stack*: ONNX pipeline as drafted, a CoreML conversion of all three stages, or an Apple-native fallback (`SFSpeechRecognizer` keyword spot is NOT suitable; CoreML-converted openWakeWord is). Budget risk: this is the largest unknown in M5-a Task 9.

### R2 — VoiceProcessingIO side effects on macOS
**File:** `M5-a-...md` Tasks 3/9. Known behaviours to confirm on the Mini during Task 9: enabling voice processing (a) ducks/attenuates *other apps'* output system-wide while the engine runs, (b) constrains the input HW format (the tap must convert from the VPIO rate, often 24/48kHz), (c) on some macOS releases requires enabling VP on input before `engine.start()` and behaves differently if the default device changes mid-session, (d) interacts with `AVAudioPlayerNode` scheduling latency (the AEC reference path). None of these block the design; all can surprise the gated bring-up — pre-list them in the Task 9 checklist.

### R3 — Parakeet confidence/language signal for the auto-fallback (ties to F8)
**File:** `M5-b-...md` Assumptions/Task 5. Confirm what `parakeet-mlx` actually exposes (token logprobs? none?) to drive the "Parakeet output looks non-English/low-confidence ⇒ Whisper retry" refinement, and whether mlx-whisper's `detect_language` on a 1–2s prefix is cheap enough (~tens of ms) to run per utterance as the router instead.

### R4 — Speaker-ID anti-spoofing posture (recorded/cloned voice)
**File:** `M5-c-...md` Assumptions (noted "not v1"). Voice-ID gates *routing* only (Tier-1 still needs the phone unlock), which bounds the damage — but a replayed owner clip still elevates a stranger from guest to owner-Tier-0 (calendar, reminders, briefing content). Worth a one-page research note before M5-c ships defaults: cosine threshold vs replay, and whether owner-Tier-0 should exclude anything embarrassing-if-replayed. Feeds the parked "anti-spoof/liveness" item.

### R5 — ECAPA cosine threshold default
**File:** `M5-c-...md` Assumptions (0.25 placeholder). ECAPA verification operating points vary by enrolment length and channel; 0.25 is in the plausible band for same-device enrolment but the gated tuning should sweep with both the owner and ≥2 non-owners and record FAR/FRR in the handoff, not a single accept/reject anecdote (the current Task 6 done-when is one owner + one stranger).

---

## Cross-spec contract verification summary (requested checks)

- **M5-a ↔ M5-d IPC vocabulary:** event names (`wakeDetected`, `speechStart`, `speechEnd(reason)`, `bargein`, `playbackStarted`, `playbackFinished`, `error`, `status`), command names (`startListening`, `stopListening`, `play(sampleRate, channels)`, `stopPlayback`, `getStatus`), framing (1-byte kind 0x01/0x02/0x03 + 4-byte BE length), and PCM format (16kHz/mono/Int16 LE) **match exactly**. ✅ (Behavioural ambiguity at F1/F2/U5.)
- **M5-b/c/d port signatures vs M0-d:** consistent as cited (`transcribe`, `synthesize`, `identify`, `capture`/`play`). ✅
- **M6-a ↔ M6-b ↔ M6-c types:** `Hit`/`TickResult`/`HookResult`/`DeliverySpec`/`OutboundMessage` field lists match across the three specs ✅; the `deliver` callable's return type does NOT (B2) ❌; the `on_hits`/`tier1_sink` seam names match ✅.
- **M6-c `pre_tick_steps` amendment coherence:** ❌ — incoherent with M6-a's sync `tick()`/`run_forever` and M6-c's own file-scope (B1); ordering ambiguity (drain vs tick) unresolved.
- **Voice-Tier gating (security):** the voice-ID≠key encoding in M5-c is sound and well-tested (locked-owner Tier-1 → NEEDS_PHONE_UNLOCK; guest wall regression). Residual gaps: pre_route-vs-actual-route divergence is mitigated only by the locked store failing closed (worth one test), and the streaming path's gate is undefined (B6).
- **ntfy topic secrecy:** the secret-topic scheme is specified but ungenerated + contradicted by the spec's own smoke command (F9).
- **Over-engineering:** none material — the specs consistently choose the thin custom option (no APScheduler, no croniter, no Pipecat, JSON stores). The one place to *simplify* is M6-b's line-zip fallback machinery, which structured output makes unnecessary (U1).

**Counts: BLOCK 6 · UPGRADE 7 · FLAG 14 · RESEARCH 5**

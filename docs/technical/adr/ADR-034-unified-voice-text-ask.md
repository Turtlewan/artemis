# ADR-034 — Unified voice + text "Ask Artemis" overlay (one generation, teed into display + speak)

**Status:** Accepted 2026-06-28
**Deciders:** owner + planning
**Design basis:** `docs/findings/unified-voice-ask-design-brief.md`
**Relates:** ADR-028 (overlay folds into the locked travel-zoom map) · ADR-030 (thin client — token-in-Rust, network-free webview) · ADR-031 (agentic runtime — reuse the GATE/sensitivity posture) · ADR-029 (sensitivity ingestion gate) · the M5-a/b/c/d voice-stack specs · CLIENT-ask + client-live-overlay (the Tauri `ask` window). Reuses the M5-c Tier gate and the ADR-029/031 sensitivity posture as applicable.

## Context

Today there are **two separate answer paths**: a **text path** (overlay query → `/app/ask/stream` SSE → rich on-screen text) and a **voice path** (M5-d wake→capture→STT→`handle_voice_stream`→sentence-split→TTS→sidecar playback). They share `Brain.respond_stream` but never the same turn.

The owner has locked an end-state: the "Ask Artemis" overlay becomes a **unified voice + text surface** — it accepts **both spoken and typed input** and answers in **streamed on-screen text AND spoken aloud**. The spoken answer is a **speakable rendering** (gist/pointer), not a verbatim read of the screen.

The reuse surface already exists (M5-a sidecar + frozen IPC wire; M5-b STT/TTS ports; M5-c speaker-ID + Tier gate; M5-d voice-loop orchestrator with sentence-splitter, instant-ack, barge-in, latency budget; the Tauri `ask` always-on-top window with ⌥Space, token-in-Rust, EngineTag rendering, and the `/app/ask/stream` SSE route). The genuinely new idea is the **display↔speakable split** and the **stream tee** that lets one brain generation drive both surfaces. This ADR records the owner decisions; it does not write the specs.

## Decision

### A — End-state: one unified Ask surface

The overlay is a single voice+text surface. Input may be **typed or spoken**; output is **always** streamed rich text on-screen **and** (subject to the mute toggle, D) a spoken rendering. There is no separate "voice mode" UI — voice is an input/output modality of the same overlay.

### B — Architecture: one generation, teed into two branches

One `Brain.respond_stream` generation per Ask turn, **teed** into two consumers:

- **(a) Display branch** — rich text (markdown / lists / fenced code / citations / `local`/`codex`/`review` engine tags) → existing `/app/ask/stream` SSE → Tauri overlay, **UNCHANGED**.
- **(b) Speak branch** — a **brain-side speakable projection** of the same stream → existing **M5-d sentence splitter → M5-b TTS → M5-a sidecar `0x03` playback** cascade, reused verbatim (same instant-ack, same barge-in).

**New seams ONLY:**
1. a **stream tee** forking the single generation into the two iterators;
2. a new Gateway entry **`handle_ask_unified(query, *, scope_or_identity, speak) -> (AsyncIterator[DisplaySeg], AsyncIterator[SpeakSeg])`** that runs the M5-c Tier gate + `Brain.respond_stream` **once** and tees;
3. a brain-side **`speakable.py`** deterministic renderer on the speak branch;
4. a **push-to-talk trigger** that routes a captured+STT'd utterance into an *overlay* turn (reusing M5-d's capture+STT front half);
5. overlay **mic button + speak-toggle UI** (plus speaking/stop indicators).

Everything else is **reuse** of the already-built M5-a/b/c/d stack + the Tauri ask window. When `speak=False` the speak branch is simply not consumed (zero TTS cost). The display branch must be restored to the **streaming** `/app/ask/stream` path (client-live-overlay regressed it to non-streaming).

Voice **INPUT** reuses M5-d `SidecarAudioFrontend.capture()` → endpoint → `STT.transcribe`; the only new bit is a trigger targeting the overlay turn instead of the headless voice-loop turn. Voice **OUTPUT** reuses M5-d's back half (sentence-split → TTS → sidecar) with instant-ack and barge-in.

### C — Speakable rendering = brain-side, deterministic, SHAPE-AWARE (the key owner rule)

The speakable renderer **classifies the answer shape** and speaks accordingly:

- **SHORT / one-sentence answer** → speak it **near-verbatim**, stripped of markdown / citations / footnotes / engine tags (and code).
- **LIST / structured / long answer** → speak only a **brief pointer statement** that references the request ("I've put your top tasks on screen", "Your results are on screen") and **NEVER read the list / content aloud**.

The **screen always shows the full rich answer** regardless. The renderer is a pure function behind a clean **`to_speakable(seg) -> str` seam**, computed **brain-side** (TTS is brain-side; the client stays thin per ADR-030 — the client only ever renders display). It is **deterministic and unit-testable on the Windows dev box today**, adds **zero latency and zero token cost**, and reuses the existing single token-stream + M5-d sentence splitter untouched. The seam is kept clean so a future **marked-segment convention** (the model brackets non-speakable spans) can layer on later for cases where blunt stripping is too coarse — it only changes how the renderer decides what to drop.

**Rejected: a two-field model output** (`display` + `speak`). Emitting two fields fights token-streaming — both the overlay's first-token latency and the voice loop's 750–800 ms endpoint→first-audio budget depend on streaming a single sequence; two fields double generation or desync, and cost extra tokens on every Ask.

### D — When to speak, and privacy

**Always speak SOMETHING** (shape-aware per C — either the short answer or the pointer statement). Include a **mute toggle** so the owner can suppress spoken output for room-audio privacy (spoken answers are audible to anyone present).

### E — Defaults adopted (recorded as decided)

- **Barge-in:** reused from M5-d (speaking over the spoken answer cancels TTS + the brain stream and starts a new turn).
- **Duplex:** **half-duplex on the Windows dev box** (mic muted while Artemis speaks) / **full-duplex on the Mac** (mic live for barge-in; couples to sidecar AEC).
- **Split locus:** the display↔speak split is computed **brain-side** (per C).
- **Identity for spoken overlay input = SESSION-SCOPED.** The overlay is already an unlocked, authenticated session; spoken input through it inherits **full session scope**. Voice is an **input method, not auth** — this deliberately **sidesteps the M5-c voice-ID≠key Tier gate**, which exists only to govern the **headless, session-less wake-word loop**. The headless loop continues to use SpeakerID-derived identity + the M5-c gate unchanged; `handle_ask_unified` accepts either via its `scope_or_identity` parameter.
- **Input topology:** **co-located brain-host mic reuse NOW** (the voice loop + sidecar run on the brain host; in co-located dev the overlay and the brain are the same machine). The **client-device-mic + STT-over-HTTP remote path is DEFERRED** to a later spec.

### F — Platform reality (what is testable where)

**Windows-dev testable NOW** (a real end-to-end voice round-trip is achievable per the M5 Windows re-scope): the `speakable.py` renderer (full unit coverage), the stream tee + `handle_ask_unified` typing/behaviour (with the existing M5-d FakeBrain/FakeTTS/FakeSidecar), the overlay affordances (vitest + RTL with mocked Channel/events), and a live wake/PTT→STT→brain→speakable→TTS→playback path via `M5-a-win-sidecar` + Moonshine/faster-whisper + Kokoro-FastAPI/Piper.

**Mac-production-gated:** the Swift MLX sidecar, Parakeet + Kokoro-MLX, ANE residency, the tuned **750–800 ms** endpoint→first-audio budget (Windows numbers are indicative), the ECAPA speaker-ID threshold (M5-c Task 6), and the **remote-mic leg** (client-device mic → brain STT — only meaningful once the brain runs headless on the Mini and the client is a separate device).

## Consequences

- **No second answer engine.** One `Brain.respond_stream` generation feeds both surfaces via the tee; the existing text and voice paths converge on `handle_ask_unified` rather than being replaced.
- **The client stays thin (ADR-030).** All speakable computation is brain-side; the webview remains network-free and renders display only.
- **The overlay folds into the locked travel-zoom map (ADR-028).** The mic button, speak/mute toggle, and speaking/stop indicators are affordances on the existing floating Ask surface, not a new shell.
- **Deterministic-strip v1 is intentionally blunt.** It strips, it does not rephrase; edge cases (raw URLs, dense tables) may mis-speak. The `to_speakable()` seam is the upgrade path to the marked-segment convention (option c) without re-architecture.
- **Spec breakdown — 1 ADR (this) + 4 build specs + 1 deferred spec.** The specs are **not** authored here:
  - **Spec 1 (brain)** — `speakable.py` shape-aware renderer + stream tee + `handle_ask_unified` + restore `/app/ask/stream` streaming. Windows-dev testable with fakes.
  - **Spec 2 (brain/voice)** — push-to-talk input into an overlay turn (reuse M5-d capture + STT; route transcript into the unified entry). Dev-box live integration; Mac-gated for the MLX path.
  - **Spec 3 (brain/voice)** — voice output for the overlay turn (wire the speak branch → splitter → TTS → sidecar with the `speak` flag + instant-ack/barge-in reuse). Dev-box Windows-sidecar integration; Mac-gated playback.
  - **Spec 4 (client)** — overlay voice affordances (mic button, speaking indicator, speak on/off mute toggle, stop/barge control, streaming display restore). vitest/RTL testable now.
  - **(Deferred) Spec 5** — remote client-mic capture + STT-over-HTTP brain endpoint. Only if/when the remote topology is pursued.

## Alternatives considered

- **Two-field model output (`display` + `speak`)** — *rejected* (decision C): breaks the single-stream model that both the overlay TTFT and the 750–800 ms voice budget depend on; doubles generation / desyncs; extra tokens per Ask.
- **Marked-segment convention now (model brackets non-speakable spans)** — *deferred, not rejected*: smarter than a blunt strip and still single-stream, but depends on the model reliably emitting markers and needs prompt work + an eval. Kept as the layer-on upgrade behind the `to_speakable()` seam.
- **Client-side display↔speak split** — *rejected*: TTS is brain-side and the client must stay thin (ADR-030); a client-side split would force spoken text into the webview and thicken the client.
- **Speak the full answer always (read lists/content aloud)** — *rejected* (decision C): long/structured answers are unbearable as speech; the screen carries the full content, the voice carries a pointer.
- **Client-device-mic + STT-over-HTTP for input now** — *deferred*: genuinely new (client audio capture + an STT-over-HTTP seam), not needed for co-located dev; in scope only if the remote end-state is pursued (Spec 5).

## Parked / next

- **Spec series authoring** — the 4 build specs + 1 deferred spec above. Authored separately; not part of this ADR.
- **Marked-segment convention (option c)** — prompt + eval work for the smarter speakable rendering; layered behind `to_speakable()` when blunt stripping proves too coarse.
- **Remote topology leg** — client-device mic → brain STT; meaningful once the brain runs headless on the Mini and the client is a separate device.
- **Mac-gated tuning** — the 750–800 ms budget, ECAPA threshold, full-duplex AEC — validated on the Mac; the dev box validates the seams behind the Windows voice twin.

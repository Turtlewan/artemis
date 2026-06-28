# Design Brief — Unified voice + text "Ask Artemis" overlay

_Status: DESIGN BRIEF (not a spec, not code). Drafted 2026-06-28. Owner has locked the end-state:
the Ask overlay accepts **both spoken and typed input** and answers in **streamed text on-screen
AND spoken aloud**, where the spoken answer is a **speakable rendering** (gist/prose), not a
verbatim read of the screen._

> Litmus for this doc: it grounds the bridge in what already exists (M5-a/b/c/d voice stack +
> CLIENT-ask + client-live-overlay) and REUSES it. It does not redesign the voice loop or the
> overlay. The one genuinely new idea is the **display↔speakable split** and the **stream tee**
> that lets a single brain answer drive both surfaces.

---

## 0. What already exists (the reuse surface)

| Piece | Where | Contract we reuse |
|-------|-------|-------------------|
| Audio sidecar + IPC | M5-a (+ `M5-a-win-sidecar`, `m5-a-win-transport`) | multiplexed `1-byte kind + 4-byte len + body`; events `wakeDetected/speechStart/speechEnd/bargein/playbackStarted/playbackFinished`; `0x02` mic PCM in / `0x03` speaker PCM out; **16 kHz/mono/Int16**. Mac = Swift sidecar; Windows-dev = Python sidecar, **same frozen wire**. |
| STT / TTS ports | M5-b | `STT.transcribe(audio, *, language) -> str`; `TTS.synthesize(text) -> Iterator[bytes]` (per-sentence, 16 kHz PCM). Mac = Parakeet+Whisper / Kokoro-MLX; Windows-dev = Moonshine/faster-whisper / Kokoro-FastAPI or Piper. |
| Speaker-ID + Tier gate | M5-c | `handle_voice` resolves **voice-ID identity** + Tier gate; voice-ID≠key → Tier-1-while-locked returns `NEEDS_PHONE_UNLOCK`. Voiceprints Tier-0-keyed (readable while locked, for routing). |
| Voice loop orchestrator | M5-d | `SidecarAudioFrontend` (AudioFrontend port), `VoiceLoop` cascade wake→capture→endpoint→STT→`gateway.handle_voice_stream`→sentence-split→TTS→sidecar; instant-ack, barge-in, 750–800 ms endpoint→first-audio budget. |
| Gateway streaming entries | M5-d / M5-c / CLIENT-b | `handle_voice_stream(audio, transcript) -> AsyncIterator[str]` (voice, identity from SpeakerID); `handle_text_stream_scoped(text, scope) -> AsyncIterator[str]` (text, scope from session). |
| Ask overlay (client) | CLIENT-ask + client-live-overlay | Separate always-on-top Tauri **`ask`** window, ⌥Space global shortcut, text-only. Token lives in **Rust** (ADR-030); webview is network-free and calls the Rust `ask` command → `POST /app/ask` (`require_unlocked`). EngineTag `local/codex/review`. (Live-overlay currently uses **non-streaming** `/app/ask`; `/app/ask/stream` SSE exists and is the streaming path to restore.) |

**Two topology facts that shape everything below:**
1. The **voice loop + sidecar run on the BRAIN host** (Mac Mini in production; the Windows dev box
   when co-located). The mic and speaker the voice loop drives are **local to the brain**.
2. The **Ask overlay runs on the CLIENT device** and is a thin HTTP/SSE client of the brain
   (ADR-030; token-in-Rust). In co-located dev these are the **same machine**; in the end-state
   remote case they are **not**.

---

## 1. Architecture of the bridge

### 1a. The core insight — one answer, two renderings, one tee

Today there are two *separate* answer paths: the **text path** streams display text to the overlay
(SSE), and the **voice path** streams spoken text to TTS. The unified Ask needs **one brain
generation** forked into **two consumers**:

```
                    ┌─────────────────────────── BRAIN HOST ───────────────────────────┐
                    │                                                                    │
  query (text or    │   Gateway.handle_ask_unified(query, principal/identity, speak?)     │
  STT transcript) ─────►  Brain.respond_stream(...)  ── ONE token stream ──┐             │
                    │                                                       │             │
                    │                        ┌──────────── TEE ────────────┘             │
                    │                        │                              │             │
                    │           DISPLAY rendering                SPEAKABLE rendering      │
                    │        (rich: md/lists/cites/                (gist/prose;            │
                    │         engine tags, untouched)              strip chrome)           │
                    │                        │                              │             │
                    │                   SSE / Channel              sentence splitter (M5-d)│
                    │                        │                              │             │
                    │                        ▼                       TTS.synthesize (M5-b) │
                    └────────────────────────┼──────────────────────────────┼────────────┘
                                             │                              ▼
                                     ┌───────▼────────┐            sidecar 0x03 PCM (M5-a)
                                     │  Ask overlay   │                     │
                                     │ (Tauri client) │                     ▼
                                     │ streamed text  │            🔊 speaker (brain host)
                                     │ + engine tags  │
                                     └────────────────┘
```

The **tee** is the new seam. The display branch is the existing text-stream contract (unchanged
rich text). The speak branch runs the existing **M5-d sentence splitter → M5-b TTS → M5-a sidecar**
cascade — *exactly* as the voice loop already does — but its input is the **speakable** projection
of the same stream, not the raw display text.

### 1b. Voice INPUT into the overlay

Two reuse paths, depending on topology (a fork for the owner — see §5):

- **Co-located / brain-host mic (reuse M5-d capture):** add a **push-to-talk** (or "Hey Artemis"
  wake) seam that runs the existing `SidecarAudioFrontend.capture()` → endpoint → `STT.transcribe`
  and drops the resulting transcript into the overlay's query box (then proceeds exactly like a
  typed query). This reuses the entire M5-d capture+STT front half; the only new bit is a trigger
  that targets the *overlay* turn instead of the headless voice-loop turn.
- **Client-device mic (new, end-state remote):** the Tauri client captures mic audio and streams it
  to a brain STT endpoint. This is **genuinely new** (a client audio capture path + an STT-over-HTTP
  seam) and is **not** needed for co-located dev. Defer unless/until remote is real.

### 1c. Voice OUTPUT from the overlay

Reuses M5-d's back half verbatim: the speak branch of the tee feeds the **same sentence splitter →
TTS → sidecar `0x03` playback** pipeline, with the **same instant-ack and barge-in** machinery.
The only new control is a **`speak` flag** on the turn (whether this particular Ask turn should
voice its answer at all — see §5).

### 1d. Where the new entry sits

A new Gateway entry unifies the two existing ones rather than replacing them:

```
async def handle_ask_unified(
    query: str,
    *,
    scope_or_identity,          # session scope (overlay) OR voice-ID identity (headless loop)
    speak: bool,
) -> tuple[AsyncIterator[DisplaySeg], AsyncIterator[SpeakSeg]]:
    # runs the M5-c Tier gate + Brain.respond_stream ONCE, tees the stream
```

- For the **overlay** (authenticated, unlocked session), scope is **session-derived** (text-path
  semantics) — see §5 on identity.
- For the **headless voice loop**, identity is **SpeakerID-derived** and the M5-c voice-ID≠key Tier
  gate applies unchanged.
- The display iterator backs `/app/ask/stream` (SSE → overlay); the speak iterator backs the TTS
  cascade. When `speak=False`, the speak branch is simply not consumed (zero TTS cost).

---

## 2. The speakable-rendering problem

The screen can show markdown, lists, fenced code, citations/footnotes, and the load-bearing engine
tags (`local`/`codex`/`review`). The voice must speak the **gist/prose** and skip UI chrome and
non-speakable segments (don't read code blocks, citation markers, or engine tags aloud).

### Option (a) — model emits two fields (`display` + `speak`)
The model returns a structured answer with both a rich field and a spoken field.
- **+** Highest-quality spoken phrasing (the model can summarise, not just strip).
- **–** Fights **token-streaming**: the overlay's first-token latency and the voice loop's
  750–800 ms budget both depend on streaming a *single* sequence; emitting two fields either
  doubles generation or forces the speak field to lag/desync from display. Extra prompt + output
  tokens on every Ask. Hard to keep the two fields consistent.

### Option (b) — deterministic post-process (strip markdown/code/citations + length-cap)
A pure function projects the streaming display text → a speakable string: strip fenced code (replace
with "code block" or omit), drop citation markers/footnotes and engine tags, flatten lists to
prose, collapse markdown emphasis/headers, soft length-cap very long answers for voice.
- **+** **Cheapest**; no model cooperation, **zero extra tokens**, works with the *existing* model
  and the *existing* single stream + sentence splitter. **Deterministic + unit-testable**
  (Windows-dev now). No latency hit — it sits inline on the token stream.
- **–** Blunt: can mis-speak edge cases (read a raw URL, drop something load-bearing, awkward
  prosody on dense tables). It strips, it doesn't *rephrase*.

### Option (c) — marked-segment convention (model brackets non-speakable spans)
The model wraps non-speakable spans in a convention (e.g. `⟦nospeak⟧…⟦/nospeak⟧` around code/cites);
display strips the markers and renders normally, TTS skips the bracketed spans.
- **+** Single generation, single stream (streaming-friendly), one source of truth; the *model*
  decides what's non-speakable (smarter than a blunt strip) at near-zero token cost (just markers).
- **–** Depends on the model reliably emitting markers; needs prompt work + an eval; a missed
  marker reads chrome aloud or hides display text. More moving parts than (b).

### Recommendation — **(b) now, with a seam to (c) later; reject (a)**
Ship **(b)** as v1: a brain-side `speakable.py` pure renderer on the speak branch of the tee. It is
the only option that adds **zero latency and zero token cost**, reuses the existing single
token-stream + M5-d sentence splitter untouched, and is fully **deterministic/unit-testable on the
Windows dev box today**. Keep the renderer behind a clean `to_speakable(seg) -> str` seam so the
**(c)** marked-segment convention can layer on later for the cases where blunt stripping is too
coarse (it just changes how the renderer decides what to drop). **Reject (a)** — two full fields
break the streaming model that both the overlay TTFT and the 750–800 ms voice budget depend on.

**Where it's computed: the BRAIN, near the M5-d splitter** — because the speakable text must feed
TTS (brain-side) and the client must stay thin/network-free (ADR-030). The client only ever renders
display. (Listed in §5 as an owner confirmation, but this is the strong default.)

---

## 3. Reuse vs new

**Reused as-is (no change):**
- The audio sidecar + its frozen IPC wire (M5-a / win-sidecar / win-transport).
- STT + TTS port adapters and the 16 kHz/mono/Int16 PCM format (M5-b).
- The M5-d **sentence splitter, instant-ack, barge-in cancellation, latency instrumentation**, and
  `SidecarAudioFrontend` capture/playback.
- `Brain.respond_stream` and the M5-c Tier gate / voice-ID≠key logic.
- The Tauri **`ask` always-on-top window**, ⌥Space global shortcut, token-in-Rust transport,
  EngineTag rendering, and `/app/ask/stream` SSE route (CLIENT-ask + client-live-overlay).

**Small new seam (thin glue over existing parts):**
- A **stream tee** + `handle_ask_unified` Gateway entry that runs one generation and forks it into
  display (SSE) + speak (TTS) iterators, with a `speak` flag.
- A brain-side **`speakable.py`** deterministic renderer on the speak branch.
- A **push-to-talk / wake trigger** that routes a captured+STT'd utterance into an *overlay* turn
  (reusing M5-d's capture+STT front half).
- Overlay UI affordances: a **mic button**, a **speaking indicator**, a **speak on/off toggle**, and
  a **stop-speaking/barge control** (client-side, mocked-event testable).
- Restore the overlay to the **streaming** `/app/ask/stream` path (live-overlay regressed it to
  non-streaming) so the display branch streams.

**Genuinely new (only if the remote topology is pursued):**
- A **client-device mic capture** path + an **STT-over-HTTP** brain endpoint (so a remote client's
  voice reaches brain-side STT). Not needed for co-located dev; defer.

---

## 4. Platform reality (what's testable where)

**Testable on the Windows dev box NOW (off-hardware / dev-twin):**
- `speakable.py` renderer — pure function, full unit coverage (strip/flatten/cap cases).
- The **stream tee** + `handle_ask_unified` typing/behaviour — with FakeBrain/FakeTTS/FakeSidecar
  (the M5-d fakes already exist).
- Overlay UI affordances (mic button, speak toggle, speaking/stop indicators) — vitest + RTL with
  mocked Channel/events.
- A **real end-to-end voice round-trip on the dev box** is actually possible per the M5 Windows
  re-scope: the `M5-a-win-sidecar` + Moonshine/faster-whisper STT + Kokoro-FastAPI/Piper TTS give a
  live wake→STT→brain→speakable→TTS→playback path on Windows. This is a dev integration bring-up,
  not fully Mac-gated.

**Mac-production-gated:**
- The production **Swift MLX sidecar**, Parakeet + Kokoro-MLX, ANE residency, and the tuned
  **750–800 ms endpoint→first-audio** budget (Windows numbers are indicative, not the target).
- ECAPA speaker-ID threshold tuning (M5-c Task 6).
- The **remote topology** leg (client-device mic → brain STT) — only meaningful once the brain runs
  headless on the Mini and the client is a separate device.

---

## 5. Open questions for the owner

1. **Barge-in on Ask** — should speaking over the overlay's spoken answer cancel TTS + the brain
   stream (reuse M5-d barge-in) and start a new turn? Or only a manual "stop" button? (Half-duplex
   simplest; full barge-in reuses M5-d but needs the mic live during playback.)
2. **Does typed input also speak the answer, or only voice input?** Three modes: (i) speak only when
   the *input* was voice; (ii) speak whenever the overlay is open (a global "voice on" mode);
   (iii) per-turn toggle. This sets the default for the `speak` flag.
3. **Half-duplex vs full-duplex** — mic muted while Artemis speaks (half), or mic live for barge-in
   (full)? Couples to Q1 and to AEC on the sidecar.
4. **Default on/off** — does the unified overlay default to voice-output ON, or is it opt-in per
   session / a settings toggle? (Privacy: spoken answers are audible to anyone in the room.)
5. **Where is the display↔speak split computed — brain or client?** Strong default is **brain**
   (TTS is brain-side; client stays thin per ADR-030). Confirm, or accept a client-side split if you
   want the overlay to own the spoken text (heavier client).
6. **Identity model for spoken overlay input** — the overlay is already an **unlocked session**, so
   spoken input through it can inherit **full session scope** (voice is just an input method, not the
   auth). This *sidesteps* the M5-c voice-ID≠key dance (which exists for the headless, session-less
   wake-word loop). Confirm: overlay spoken input = session-scoped (recommended), NOT downgraded to
   voice-ID scope.
7. **Input topology** — co-located (reuse brain-host mic via the sidecar) only for now, or commit to
   the client-device-mic + STT-over-HTTP path for the remote end-state? (Decides whether §3's
   "genuinely new" work is in scope.)

---

## 6. Suggested spec breakdown (do NOT write these yet)

- **ADR — Unified voice+text Ask.** Locks: the one-generation **tee** (display + speak), the
  **speakable-rendering** choice (option b now / c later, computed brain-side), the **identity model**
  (overlay spoken input = session-scoped; headless loop = voice-ID per M5-c), and the **input
  topology** decision (co-located reuse vs client-mic remote).
- **Spec 1 (brain) — speakable renderer + stream tee.** `speakable.py` + `handle_ask_unified` +
  restore `/app/ask/stream`. Windows-dev testable with fakes. (≤3 files: `speakable.py`,
  `gateway.py`, a test.)
- **Spec 2 (brain/voice) — push-to-talk input into an overlay turn.** Reuse M5-d capture + STT;
  route the transcript into the unified entry. Dev-box live integration; Mac-gated for the MLX path.
- **Spec 3 (brain/voice) — voice output for the overlay turn.** Wire the speak branch → splitter →
  TTS → sidecar with the `speak` flag + instant-ack/barge-in reuse. Mac-gated playback; dev-box
  Windows-sidecar integration.
- **Spec 4 (client) — overlay voice affordances.** Mic button, speaking indicator, speak on/off
  toggle, stop/barge control, streaming display restore. vitest/RTL testable now.
- **(Deferred) Spec 5 — remote client-mic + STT-over-HTTP.** Only if Q7 chooses the remote topology.
</content>
</invoke>

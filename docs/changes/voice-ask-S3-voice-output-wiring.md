---
spec: voice-ask-S3-voice-output-wiring
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: voice-ask-S3 — voice OUTPUT for the overlay turn (speak branch → M5-d splitter → M5-b TTS → M5-a sidecar)

**Identity:** Wires S1's `speak` iterator (`handle_ask_unified(..., speak=True)`) through M5-d's existing sentence splitter → M5-b TTS → M5-a sidecar `0x03` playback, with instant-ack and barge-in reused verbatim from M5-d, and installs it as the `app.state.speak_sink` S1 left as a drain. → why: docs/technical/adr/ADR-034-unified-voice-text-ask.md §B (new seam, reuse the M5-d back half) + design-brief §1c.

## Assumptions
- S1 is complete: `handle_ask_unified` returns `(display_iter, speak_iter)` and the `/app/ask/stream` route hands `speak_iter` to `app.state.speak_sink` (default drain) when `speak=True`. S3 replaces that default sink. → impact: Stop.
- M5-d's `VoiceLoop` already owns the sentence splitter, `play_async(audio, cancel)`, the cached instant-ack, and barge-in cancellation against `SidecarAudioFrontend`. S3 reuses these; it does NOT re-implement the back half. → impact: Stop.
- The speak iterator yields plain text segments (a single pointer/short string per turn from S1); S3 feeds them to the SAME splitter the headless loop uses. → impact: Caution.
- Half-duplex on the Windows dev box (mic muted while speaking); full-duplex/AEC is Mac-gated (ADR-034 §E/§F). → impact: Caution.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/voice/voice_loop.py | modify | add `speak_overlay_answer(speak_iter, *, frontend, tts, cancel)` reusing the splitter + `play_async` + instant-ack + barge-in; a `compose_speak_sink(...)` returning the `app.state.speak_sink` callable |
| tests/test_overlay_voice_output.py | create | FakeSidecar + FakeTTS: speak_iter → per-sentence TTS PCM played in order; barge-in cancels mid-playback |

## Exact changes
**src/artemis/voice/voice_loop.py** (add, reusing existing helpers):
```python
async def speak_overlay_answer(
    speak_iter: AsyncIterator[SpeakSeg],
    *,
    frontend: AudioFrontend,
    tts: TTS,
    cancel: asyncio.Event,
) -> None:
    """Drive the S1 speak branch through the M5-d back half:
    optional instant-ack -> split the incoming text into sentences (the SAME
    splitter the headless loop uses) -> tts.synthesize per sentence ->
    frontend.play_async(pcm, cancel). A sidecar `bargein` event sets `cancel`,
    stops 0x03 PCM, and ends the turn (reused from M5-d). Degrade-don't-crash on
    TTS error. Captured/spoken text is never written to disk/logs."""

def compose_speak_sink(frontend: AudioFrontend, tts: TTS) -> Callable[[AsyncIterator[SpeakSeg]], Awaitable[None]]:
    """Return the callable installed as app.state.speak_sink (S1's seam): wraps
    speak_overlay_answer with a fresh barge-in cancel Event per turn."""
```
App wiring (composition, co-located): `app.state.speak_sink = compose_speak_sink(frontend, tts)` so the `/app/ask/stream` route plays the spoken answer on the brain-host speaker when `speak=True`.

## Acceptance criteria
- [ ] `uv run mypy src tests/test_overlay_voice_output.py` → exit 0.
- [ ] `uv run pytest -q tests/test_overlay_voice_output.py` → a speak_iter yielding "First sentence. Second sentence." → FakeTTS called once per sentence in order and FakeSidecar recorded sentence-one PCM before sentence-two was synthesised; a `bargein` event mid-playback sets `cancel`, no further `0x03` PCM is sent, and the turn ends; a pointer-only speak_iter ("Your results are on screen.") plays once; a FakeTTS error degrades without raising out of `speak_overlay_answer`.
- [ ] `uv run pytest -q` (full) → green (M5-d voice-loop tests unaffected).
- [ ] (GATED — Mac) real Kokoro-MLX synthesis + sidecar playback + the 750–800 ms budget + full-duplex AEC are Mac-gated; the Windows dev twin validates live playback against `M5-a-win-sidecar` + Kokoro-FastAPI/Piper as a bring-up step (record in handoff).

## Commands to run
```
uv run ruff check . ; uv run ruff format --check .
uv run mypy src tests/test_overlay_voice_output.py
uv run pytest -q
```

---
spec: voice-ask-S2-push-to-talk-input
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: voice-ask-S2 — push-to-talk voice INPUT into an overlay Ask turn (reuse M5-d capture + STT)

**Identity:** A brain-side push-to-talk trigger that reuses M5-d's capture+STT front half (`SidecarAudioFrontend.capture()` → endpoint → `STT.transcribe`) and routes the transcript into an overlay Ask turn via S1's `handle_ask_unified(transcript, scope_or_identity=<session scope>, speak=True)`. → why: docs/technical/adr/ADR-034-unified-voice-text-ask.md §B (new seam 4) + design-brief §1b.

## Assumptions
- S1 is complete: `Gateway.handle_ask_unified(query, *, scope_or_identity, speak)` exists. → impact: Stop.
- M5-d ships `SidecarAudioFrontend` (the AudioFrontend port over the M5-a frozen wire) and M5-b ships the `STT` port + `FakeSTT`; M5-d's `FakeSidecar` scripts events + mic PCM. S2 reuses these verbatim — no new capture/STT code. → impact: Stop.
- Overlay spoken input = session-scoped (ADR-034 §E): the PTT turn carries the session `Scope`, NOT a voice-ID `Identity`; it sidesteps the M5-c voice-ID≠key gate. → impact: Stop.
- Co-located brain-host mic only (ADR-034 §E "input topology"); the remote client-mic + STT-over-HTTP leg is the deferred Spec 5. → impact: Caution.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/voice/push_to_talk.py | create | `PushToTalkCapture` (capture→endpoint→STT) + `overlay_voice_turn` glue into `handle_ask_unified` |
| tests/test_push_to_talk.py | create | FakeSidecar + FakeSTT: scripted PCM → transcript → routed into `handle_ask_unified(speak=True)` |

## Exact changes
**src/artemis/voice/push_to_talk.py** (new):
```python
class PushToTalkCapture:
    """Reuses the M5-d capture+STT front half for an on-demand (no wake-word)
    utterance, targeting an overlay turn instead of the headless voice loop."""
    def __init__(self, frontend: AudioFrontend, stt: STT) -> None: ...
    async def capture_transcript(self) -> str:
        """send startListening -> accumulate 0x02 mic PCM until
        speechEnd(reason='endpoint') -> stt.transcribe(utterance_pcm). Returns
        the transcript string. Captured PCM/transcript are never logged."""

async def overlay_voice_turn(
    gateway: Gateway,
    capture: PushToTalkCapture,
    *,
    scope: Scope,
    speak: bool = True,
) -> tuple[AsyncIterator[DisplaySeg], AsyncIterator[SpeakSeg]]:
    """transcript = await capture.capture_transcript();
    return await gateway.handle_ask_unified(
        transcript, scope_or_identity=scope, speak=speak)"""
```
The transcript is treated as untrusted data (agent self-defense) — passed as the query only, never as instructions.

## Acceptance criteria
- [ ] `uv run mypy src tests/test_push_to_talk.py` → exit 0 (incl. `AudioFrontend`/`STT` structural reuse; `overlay_voice_turn` return type matches S1).
- [ ] `uv run pytest -q tests/test_push_to_talk.py` → FakeSidecar scripts `startListening`-ack → mic PCM → `speechEnd(endpoint)`; `capture_transcript()` returns FakeSTT's transcript; `overlay_voice_turn` routes that transcript into `handle_ask_unified` with `speak=True` and a session `Scope` (assert a FakeGateway recorded the exact transcript + `speak=True` + the scope, and that no voice-ID/`Identity` path was taken).
- [ ] `uv run pytest -q` (full) → green.
- [ ] (GATED — Mac MLX path / live latency) deferred: real Parakeet/Kokoro STT + the 750–800 ms budget are Mac-gated; the Windows dev twin validates the seam live against `M5-a-win-sidecar` + Moonshine/faster-whisper as a bring-up step (record in handoff).

## Commands to run
```
uv run ruff check . ; uv run ruff format --check .
uv run mypy src tests/test_push_to_talk.py
uv run pytest -q
```

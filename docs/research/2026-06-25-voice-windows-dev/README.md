# Research synthesis: Windows dev voice stack for Artemis

**Date:** 2026-06-25
**Confidence:** HIGH on architecture/feasibility (Tier-1/primary); MEDIUM on exact latency/VRAM numbers (`github.com` + `gigagpu.com` blocked → several benchmarks are `[COMMUNITY]`)
**Re-research after:** 2026-07-09 (AI/voice tooling, 14-day clock)
**Method:** apex-research three-phase — 4 parallel Sonnet agents (`stt.md`, `tts.md`, `audio-plumbing-aec.md`, `reference-stacks-budget.md`) → Opus synthesis.

## Verdict

**The entire voice stack is dev-buildable + testable on the Windows 8 GB box.** The architecture already has the seam (the brain↔sidecar **AudioFrontend** wire protocol — 16 kHz/mono/Int16 PCM + JSON control/events), so a **Windows Python sidecar** that speaks the same frozen contract is a drop-in dev twin of the Mac Swift sidecar (ADR-001 unchanged — additive). Only **production-grade AEC** (speaker + open-mic, no headphones) and the **native macOS audio integration** stay Mac-gated. The one feared gap — AEC/barge-in — is **closable on Windows**.

## Recommended Windows dev voice stack

| Stage | Pick | Why | Where it runs |
|---|---|---|---|
| **Wake** | **openWakeWord** (ONNX) | custom wake word (~200 KB, train in <1 hr), Windows-native inference, Apple-Porcupine-class accuracy, free | CPU |
| **VAD** | **Silero VAD v5** | <1 ms/chunk, 16 kHz native, MIT, battle-tested (TEN VAD = later upgrade) | CPU |
| **STT** | **Moonshine v2 Small (streaming)** primary; **faster-whisper distil-large-v3 int8** accuracy fallback | Moonshine = true streaming, sub-200 ms on CPU, beats Whisper-small WER, <500 MB, native 16 kHz, MIT, purpose-built for on-device voice agents | CPU (Moonshine) / GPU (whisper fallback ~1.6 GB) |
| **TTS** | **Kokoro-82M** (PyTorch CUDA via Kokoro-FastAPI) primary; **Piper** CPU fallback | Kokoro = ELO #1 open-weight, 60–100 ms first-audio, 2–3 GB VRAM, Apache-2.0, streaming + barge-in via RealtimeTTS; resample 24 k→16 k. **Use PyTorch CUDA, NOT kokoro-onnx (GPU path broken on Windows, onnxruntime #23384).** Piper = 0 VRAM, native 16 kHz, robotic (degraded mode) | GPU (Kokoro) / CPU (Piper) |
| **AEC** | **LiveKit RTC APM** (`livekit-rtc`) + **headphones-for-dev** | the same WebRTC engine Apple wraps, pip-installable Windows-native; headphones eliminate the speaker→mic path (AEC unneeded) for early dev; wire the APM reverse-stream from day one (~2–4 days) so it's real for Mac | CPU |
| **Audio I/O** | **sounddevice** (capture, WASAPI callback) + **PyAudioWPatch** (loopback = AEC reference) + **OutputStream callback** for playback | **NOT `sd.play()`** — can't be interrupted on Windows (sounddevice #469); callback drains to silence in ~10 ms = the barge-in primitive | CPU |
| **Reference to mirror** | **RealtimeSTT / RealtimeTTS** (KoljaB, MIT) | near-1:1 with Artemis's sidecar: WebSocket server/client split, VAD cascade (WebRTCVAD→Silero), barge-in event, faster-whisper. Pipecat v1.5 = 2nd (interruption pattern) | borrow pattern |

## Budget — fits 8 GB VRAM alongside the ~4 GB Ollama stack

No Ollama eviction, no model-swap. Two viable configs (32 GB system RAM is ample for all CPU pieces):

- **Quality config:** Moonshine STT on **CPU** + Kokoro TTS on **GPU** (2–3 GB) + Ollama (4 GB) ≈ **6–7 GB VRAM**. Best quality; STT-on-CPU frees VRAM for TTS.
- **Lean config:** faster-whisper small int8 STT on GPU (0.6 GB) + Piper TTS on **CPU** (0 VRAM) + Ollama (4 GB) ≈ **~5 GB VRAM**. More headroom, robotic TTS.

## Latency — sub-second to first-audio is realistic

~0.8–1.5 s TTFA projected on this box **with sentence-level streaming** from the LLM to TTS (the single biggest lever — without it, +3–5 s). Component budget: STT 100–300 ms · LLM first-token (warm Qwen3-4B) 200–500 ms · TTS first-audio 60–250 ms · wake+VAD <20 ms.

## Barge-in — achievable on Windows

~90 ms (well under the 200 ms target) with headphones-dev: VAD onset (~30 ms) → OutputStream callback flush (~10 ms) → `bargein` event. The `sd.play()` trap is the only gotcha. **Full-quality AEC barge-in (no headphones) = Mac-hardware verify gate.**

## Implication — M5 re-scope (additive)

The Swift sidecar (M5-a) **stays the Mac production target**; ADR-001 unchanged. Add a **Windows dev sidecar** implementing the same frozen wire protocol with the stack above. Net: M5 goes from *"4 specs, all Mac-gated"* → *"STT/TTS/speaker-ID/orchestrator + a Windows sidecar all dev-buildable & testable; only production-AEC quality + native macOS integration Mac-gated."* Proposed spec shape:
- **NEW `M5-a-win-sidecar`** — Python sidecar implementing the AudioFrontend wire contract on Windows (openWakeWord · Silero · Moonshine · Kokoro · LiveKit-APM/headphones · sounddevice/OutputStream), mirroring RealtimeSTT/TTS's server/client split.
- **Amend `M5-b` (STT/TTS)** — bind the dev models (Moonshine/Kokoro) behind the existing ports; Mac MLX/AVSpeech = the other impl.
- **Amend `M5-c` (speaker-ID + Tier gate)** — portable speaker-ID model (dev-buildable).
- **Amend `M5-d` (voice-loop orchestrator)** — already brain-side Python; builds + tests against the Windows sidecar.

## Assumptions / gaps
- Exact latency/VRAM figures are partly `[COMMUNITY]` (`github.com`, `gigagpu.com` blocked for the agents). Authorize `github.com` for a hardening pass to confirm release tags, sherpa-onnx CUDA matrix, and community VRAM configs.
- TEN VAD, StyleTTS2-streaming, Chatterbox = re-evaluate in a few weeks (maturing).
- LiveKit APM reverse-stream clocking is "solvable, not trivial" — budget 2–4 days; the headphones path de-risks the schedule.

## Sources
Per-cluster files in this dir (full per-claim tier tags + URLs): `stt.md` · `tts.md` · `audio-plumbing-aec.md` · `reference-stacks-budget.md`.

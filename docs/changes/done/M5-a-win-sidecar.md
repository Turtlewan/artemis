---
spec: m5-a-win-sidecar
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M5-a-win — Python Windows dev audio sidecar (drop-in twin of Swift M5-a via the same wire protocol)

**Identity:** Builds a Python sidecar process (`artemis.sidecar.audio`) that speaks the IDENTICAL brain↔sidecar AudioFrontend wire protocol frozen in M5-a — same 1-byte kind framing, same JSON event/command schema, same 16 kHz/mono/Int16-LE PCM format, same state machine — so the brain (M5-d) connects unchanged. Stack: openWakeWord (ONNX) · Silero VAD v5 · Moonshine v2 Small streaming (CPU, primary STT) / faster-whisper distil-large-v3 int8 (GPU fallback) · Kokoro-82M PyTorch CUDA (primary TTS) / Piper CPU (fallback) · LiveKit RTC APM AEC + headphones-dev bypass · sounddevice WASAPI callback capture + `OutputStream` callback playback. Dev-testable entirely on Windows 8 GB box; production-AEC quality (no headphones) + native macOS integration = Mac-gated tail.
→ why: see `docs/research/2026-06-25-voice-windows-dev/README.md` (recommended Windows dev voice stack; all component choices finalised there) · `docs/changes/M5-a-audio-sidecar.md` § Assumptions (the frozen wire protocol contract) · ADR-001 (Swift = Mac production; this is the additive Windows dev twin, ADR-001 unchanged).

## Assumptions

- **Wire protocol (M5-a frozen contract — STOP if any item below is wrong):** every frame over the Unix-domain socket is `[1-byte kind][4-byte big-endian length][body]`. kind values: `0x01` = JSON control (UTF-8), `0x02` = PCM-from-mic (sidecar→brain), `0x03` = PCM-to-speaker (brain→sidecar). Events sidecar→brain: `wakeDetected`, `speechStart`, `speechEnd` (with field `reason: "endpoint"|"maxDuration"`), `bargein`, `playbackStarted`, `playbackFinished`, `error` (with fields `code`, `message`), `status` (with field `state`). Commands brain→sidecar: `startListening`, `stopListening`, `play` (with fields `sampleRate`, `channels`), `stopPlayback`, `getStatus`. AudioFormat constant: 16000 Hz, 1 channel, Int16 LE. State machine: `idle → wake-detected → capturing → endpoint → awaiting-response → playing → (barge-in|done) → idle`.
  → impact: Stop (any deviation breaks M5-d without modification; this spec implements the Python side of the contract, not a new protocol).

- **Socket path:** Unix-domain socket at `<ARTEMIS_DATA_ROOT>/<ARTEMIS_SLOT>/run/audio.sock` (identical to the Swift sidecar per M0-a layout); perms `0600`. On Windows this is an AF_UNIX socket (`asyncio` supports it from Python 3.9 / Windows 10 build 17063+). → impact: Stop if Windows AF_UNIX not available on the dev box (Python 3.11 required; verify with `socket.AF_UNIX` import).

- **Peer-uid gate:** On Unix the Swift sidecar enforces `getpeereid`; on Windows `getpeereid` is unavailable. DRAFTED DEFAULT: skip the uid gate on Windows (document the omission; it is the same pragmatic call as M5-a's code-signing omission — no DEK crosses this socket). → impact: Flag (see Gaps below).

- **sounddevice `OutputStream` callback for playback** (NOT `sd.play()`): `sd.play()` cannot be interrupted on Windows (sounddevice issue #469); the `OutputStream` callback drains to silence in ~10 ms, providing the barge-in flush primitive. → impact: Stop (wrong API = barge-in broken on Windows).

- **TTS: Kokoro-82M PyTorch CUDA only** (NOT `kokoro-onnx`): the ONNX GPU path is broken on Windows (`onnxruntime` issue #23384). Output sample rate is 24 kHz; must resample to 16 kHz before the `0x03` PCM stream. Piper is the CPU fallback (native 16 kHz, no resample). → impact: Stop on kokoro-onnx; Caution on resample (scipy/resampy).

- **AEC: LiveKit RTC APM** (`livekit-rtc`): wire the reverse-stream (loopback via PyAudioWPatch) from day one but allow a **headphones-dev mode** (`ARTEMIS_HEADPHONES=1`) that bypasses the APM entirely — with headphones the speaker→mic path is absent, AEC is unneeded, and this is the expected early-dev path. Production-quality AEC (open-mic + speaker) is a GATED task on Mac hardware. → impact: Caution (LiveKit APM reverse-stream clocking is non-trivial; budget 2–4 days per research; headphones mode de-risks schedule).

- **Off-hardware fakes:** `FakeWakeWord`, `FakeVAD`, `FakeTTS`, `FakeSTT` stand in for the real model runtimes. The wire framing, state machine, and barge-in flush logic are fully testable with fakes without a microphone or GPU. Real-model and real-mic tests are `GATED` (skipped unless `ARTEMIS_AUDIO_HW=1`).

- **Optional dependency group `[voice-dev]`:** all voice-stack deps (`sounddevice`, `PyAudioWPatch`, `livekit-rtc`, `openWakeWord`, `silero-vad`, `moonshine-voice`, `faster-whisper`, `kokoro`, `soundfile`, `piper-tts`, `scipy`, `onnxruntime`, `torch`) go into `[voice-dev]` in `pyproject.toml`. The lean dev install (`uv sync`) does not pull them. → impact: Low.

- **Package path:** `src/artemis/sidecar/audio/` — mirrors the existing `src/artemis/` layout; the sidecar entry point is `python -m artemis.sidecar.audio serve`. This keeps it in the same `uv` project (shared venv, `uv sync --group voice-dev`).

- **FLAG — M5-a protocol gap:** M5-a's `Protocol.swift` Task 2 says `play(sampleRate, channels)` "announces an incoming `0x03` PCM stream"; it does NOT specify whether the `play` command body carries a `duration` field or whether EOS is signalled by a zero-length `0x03` frame vs. a separate `stopPlayback` command. This spec assumes EOS = zero-length `0x03` frame (conventional framing). If M5-a or M5-d disagrees, the framing changes here — no brain logic is affected. Needs human confirmation before build.

- **FLAG — `speechEnd` reason field:** M5-a lists `reason: "endpoint"|"maxDuration"` on `speechEnd`. The VAD and state machine must track a max-duration timer to emit the `"maxDuration"` reason. Default timeout is 30 s (configurable via env `ARTEMIS_MAX_SPEECH_S`). Value not specified in M5-a or the research doc; needs human confirmation.

Simplicity check: considered a separate process outside `src/artemis/` — rejected; a `sidecar` sub-package reuses the same venv and avoids a separate project. Considered embedding the sidecar inside the brain process — rejected per M5-a architecture (the sidecar is a separate OS process owning audio I/O; IPC is the seam). Considered asyncio subprocess vs. threading for audio callbacks — audio I/O uses sounddevice callbacks (C-level thread); the main coroutine loop runs asyncio; they communicate via `asyncio.Queue`. Minimal and conventional.

## Prerequisites

- **M5-a** spec read (wire protocol frozen here is its contract — M5-d builds the brain side).
- Python 3.11+ on Windows dev box (AF_UNIX socket support).
- `uv` project already exists at `C:/Users/User/artemis` with `pyproject.toml` (confirmed from codebase).
- `M5-d` (brain AudioFrontend client) may run concurrently; this spec produces the sidecar server only.
- `GATED` tasks require: NVIDIA GPU (Kokoro CUDA), real microphone, `ARTEMIS_AUDIO_HW=1`.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/sidecar/__init__.py` | create | empty package marker |
| `src/artemis/sidecar/audio/__init__.py` | create | empty package marker |
| `src/artemis/sidecar/audio/__main__.py` | create | entry point: `python -m artemis.sidecar.audio serve`; parse env/args; wire components; run asyncio loop |
| `src/artemis/sidecar/audio/protocol.py` | create | **load-bearing** — frame codec (1-byte kind + 4-byte big-endian length + body); `FrameKind` enum; all JSON message dataclasses (`WakeDetected`, `SpeechStart`, `SpeechEnd`, `Bargein`, `PlaybackStarted`, `PlaybackFinished`, `Error`, `Status`, `StartListening`, `StopListening`, `Play`, `StopPlayback`, `GetStatus`); `AUDIO_FORMAT` constant (16000 Hz, 1 ch, Int16 LE); encode/decode helpers |
| `src/artemis/sidecar/audio/state_machine.py` | create | `AudioState` enum (idle/wake_detected/capturing/endpoint/awaiting_response/playing); `AudioStateMachine` class with legal transition table; pure logic, no I/O |
| `src/artemis/sidecar/audio/wake.py` | create | `WakeWordDetector` ABC + `FakeWakeWord` + `OpenWakeWordDetector` (GATED: real ONNX model, skipped when `ARTEMIS_AUDIO_HW` unset) |
| `src/artemis/sidecar/audio/vad.py` | create | `VADDetector` ABC + `VADEvent` enum + `FakeVAD` + `SileroVAD` (GATED) + `BargeInGate` (playback-state-aware threshold) |
| `src/artemis/sidecar/audio/capture.py` | create | `AudioCapture`: sounddevice WASAPI InputStream callback → `asyncio.Queue[bytes]` (16 kHz/mono/Int16); headphones-dev mode flag; `FakeCapture` for tests |
| `src/artemis/sidecar/audio/playback.py` | create | `AudioPlayback`: sounddevice `OutputStream` callback; `enqueue_pcm(data: bytes)` + `flush()` (barge-in primitive, drains in ~10 ms); `FakePlayback` recording flush calls |
| `src/artemis/sidecar/audio/aec.py` | create | `AECProcessor` wrapping LiveKit RTC APM reverse-stream + PyAudioWPatch loopback; `NullAEC` for headphones-dev mode (`ARTEMIS_HEADPHONES=1`) and tests |
| `src/artemis/sidecar/audio/stt.py` | create | `STTEngine` ABC + `FakeSTT` + `MoonshineSTT` (GATED) + `FasterWhisperSTT` (GATED fallback) |
| `src/artemis/sidecar/audio/tts.py` | create | `TTSEngine` ABC + `FakeTTS` + `KokoroTTS` (GATED, PyTorch CUDA, resample 24k→16k) + `PiperTTS` (GATED, CPU fallback) |
| `src/artemis/sidecar/audio/ipc_server.py` | create | `IPCServer`: asyncio Unix-domain socket server bound to `<root>/<slot>/run/audio.sock` (0600); demux frames by kind byte; dispatch JSON commands to handler; stream mic PCM + events to brain; no blocking on audio thread |
| `src/artemis/sidecar/audio/orchestrator.py` | create | wires capture → wake → VAD → state machine → IPC events; IPC `play` → playback + AEC reverse-stream; barge-in path: `BargeInGate` true → `playback.flush()` → `bargein` event (flush BEFORE emit, <200 ms) |
| `pyproject.toml` | modify | add `[voice-dev]` optional dependency group with all voice-stack deps |
| `tests/sidecar/test_audio_protocol.py` | create | protocol frame round-trips (each message type + PCM blob, incl. 1-byte kind + 4-byte length) |
| `tests/sidecar/test_audio_state_machine.py` | create | legal/illegal transitions; max-duration timer fires `speechEnd(reason="maxDuration")` |
| `tests/sidecar/test_audio_barge_in.py` | create | `speechStart` during `playing` → `flush()` called BEFORE `bargein` emitted → state leaves `playing`; `speechStart` while `idle` = no-op |
| `tests/sidecar/test_audio_e2e.py` | create | end-to-end over in-process socket pair with all fakes: `FakeWakeWord` fires → `wakeDetected` event; `FakeVAD` fires `speechStart`/`speechEnd` → events; brain sends `play` → `FakeTTS` PCM streams → `playbackStarted`/`playbackFinished`; mid-play `speechStart` → `flush` + `bargein`; real-device paths guarded `ARTEMIS_AUDIO_HW=1` |

All paths under `C:/Users/User/artemis/`.

## Tasks

- [ ] **Task 1: Package scaffold + `pyproject.toml` `[voice-dev]` group** — files: `src/artemis/sidecar/__init__.py`, `src/artemis/sidecar/audio/__init__.py`, `pyproject.toml` —
  Add the `[voice-dev]` optional group to `pyproject.toml`:
  ```toml
  [project.optional-dependencies]
  voice-dev = [
    "sounddevice>=0.4.7",
    "PyAudioWPatch>=0.2.12",
    "livekit-rtc>=0.17",
    "openwakeword>=0.6",
    "silero-vad>=5.1",
    "moonshine-voice>=2.0",  # CONFIRMED 2026-06-25: official Moonshine v2 SDK (CPU/ONNX, native Windows, no WSL). import `from moonshine_voice import Transcriber`; model `ModelArch.SMALL_STREAMING` (123M, ~123MB, 7.84% WER, MIT). (GPU alt = HF Transformers `MoonshineStreamingForConditionalGeneration` w/ `UsefulSensors/moonshine-streaming-small`.)
    "faster-whisper>=1.0",
    "kokoro>=0.9.2",          # CONFIRMED 2026-06-25: PyTorch path, NOT kokoro-onnx (broken GPU on Win). import `from kokoro import KPipeline`; weights `hexgrad/Kokoro-82M` (Apache-2.0, 24kHz). Pulls `misaki[en]` g2p.
    "soundfile>=0.12",        # kokoro audio I/O dep
    "piper-tts>=1.2",
    "scipy>=1.13",
    "onnxruntime>=1.18",
    "torch>=2.3",             # for the cu128 wheel (RTX 50-series), install via the PyTorch CUDA index, see setup note below
  ]
  ```
  Create empty `__init__.py` markers.
  **Windows setup notes (CONFIRMED 2026-06-25):** (1) CUDA torch for RTX 50-series (Blackwell) must come from the PyTorch index: `pip install torch --index-url https://download.pytorch.org/whl/cu128` (or the `uv` equivalent `--index`/`--extra-index-url`) BEFORE `kokoro`. (2) **Kokoro needs the `espeak-ng` Windows binary on PATH** (phonemizer backend) — install the espeak-ng Windows release separately; it is a system binary, not a pip dep.
  — done when: `uv sync` (without `--group voice-dev`) succeeds and does not pull any voice-stack dep; `uv sync --group voice-dev` resolves without conflict.

- [ ] **Task 2: Wire protocol + PCM codec** — files: `src/artemis/sidecar/audio/protocol.py` —
  ```python
  import struct, json
  from dataclasses import dataclass
  from enum import IntEnum
  from typing import Literal

  SAMPLE_RATE = 16000   # Hz
  CHANNELS = 1
  SAMPLE_WIDTH = 2      # bytes, Int16 LE  — frozen AudioFormat

  class FrameKind(IntEnum):
      JSON    = 0x01  # control / events
      MIC_PCM = 0x02  # sidecar→brain raw PCM
      SPK_PCM = 0x03  # brain→sidecar TTS PCM

  def encode_frame(kind: FrameKind, body: bytes) -> bytes:
      return bytes([kind]) + struct.pack(">I", len(body)) + body

  def encode_json(msg: dict) -> bytes:
      return encode_frame(FrameKind.JSON, json.dumps(msg).encode())

  def decode_frame(buf: memoryview) -> tuple[FrameKind, bytes, int] | None:
      """Returns (kind, body, total_consumed) or None if buf too short."""
      if len(buf) < 5: return None
      kind = FrameKind(buf[0])
      length = struct.unpack_from(">I", buf, 1)[0]
      if len(buf) < 5 + length: return None
      return kind, bytes(buf[5:5+length]), 5 + length
  ```
  Define dataclasses for all event and command messages (use `type` field as the discriminator string matching M5-a exactly):
  - Events: `WakeDetected`, `SpeechStart`, `SpeechEnd(reason: Literal["endpoint","maxDuration"])`, `Bargein`, `PlaybackStarted`, `PlaybackFinished`, `ErrorEvent(code: int, message: str)`, `StatusEvent(state: str)`.
  - Commands: `StartListening`, `StopListening`, `Play(sampleRate: int, channels: int)`, `StopPlayback`, `GetStatus`.
  `AUDIO_FORMAT = {"sampleRate": SAMPLE_RATE, "channels": CHANNELS, "sampleWidth": SAMPLE_WIDTH}`.
  — done when: `uv run pytest tests/sidecar/test_audio_protocol.py -q` passes (round-trips all messages + a PCM blob without loss; kind bytes match).

- [ ] **Task 3: State machine** — files: `src/artemis/sidecar/audio/state_machine.py` —
  ```python
  from enum import Enum, auto

  class AudioState(Enum):
      IDLE              = auto()
      WAKE_DETECTED     = auto()
      CAPTURING         = auto()
      ENDPOINT          = auto()
      AWAITING_RESPONSE = auto()
      PLAYING           = auto()
  ```
  `class AudioStateMachine` — legal transitions table (raise `InvalidTransition` for illegal moves):
  | From | Event | To |
  |---|---|---|
  | IDLE | wake | WAKE_DETECTED |
  | WAKE_DETECTED | start_listening | CAPTURING |
  | CAPTURING | speech_end (endpoint) | ENDPOINT |
  | CAPTURING | speech_end (maxDuration) | ENDPOINT |
  | ENDPOINT | awaiting | AWAITING_RESPONSE |
  | AWAITING_RESPONSE | play | PLAYING |
  | PLAYING | barge_in | CAPTURING |
  | PLAYING | playback_finished | IDLE |
  | PLAYING | stop_playback | IDLE |
  | any | stop_listening | IDLE |
  Max-duration timer: `start_capture_timer(timeout_s: float)` / `cancel_capture_timer()` — fires `speech_end(reason="maxDuration")` transition if capturing exceeds timeout.
  — done when: `uv run pytest tests/sidecar/test_audio_state_machine.py -q` passes (legal transitions, illegal raises, max-duration timer fires correct reason).

- [ ] **Task 4: Wake + VAD (ABCs, fakes, GATED reals)** — files: `src/artemis/sidecar/audio/wake.py`, `src/artemis/sidecar/audio/vad.py` —
  `wake.py`:
  ```python
  from abc import ABC, abstractmethod
  class WakeWordDetector(ABC):
      @abstractmethod
      def feed(self, pcm: bytes) -> bool: ...  # True = wake detected this frame window

  class FakeWakeWord(WakeWordDetector):
      """TEST HARNESS — fires after trigger_after_n calls or when trigger() called."""
      def trigger(self) -> None: ...
      def feed(self, pcm: bytes) -> bool: ...

  class OpenWakeWordDetector(WakeWordDetector):
      """GATED: loads openwakeword ONNX model; no-ops when ARTEMIS_AUDIO_HW unset."""
  ```
  `vad.py`:
  ```python
  from enum import Enum, auto
  class VADEvent(Enum):
      NONE = auto(); SPEECH_START = auto(); SPEECH_END = auto()

  class VADDetector(ABC):
      @abstractmethod
      def feed(self, pcm: bytes) -> VADEvent: ...

  class FakeVAD(VADDetector):
      """TEST HARNESS — emits a scripted sequence."""
  class SileroVAD(VADDetector):
      """GATED: silero-vad v5; no-ops when ARTEMIS_AUDIO_HW unset."""

  class BargeInGate:
      """Playback-state-aware barge-in threshold.
      Returns True ONLY when is_playing AND vad == SPEECH_START."""
      def should_barge_in(self, event: VADEvent, is_playing: bool) -> bool: ...
  ```
  — done when: fakes compile + `FakeWakeWord.feed` fires on trigger; `BargeInGate` truth table test passes.

- [ ] **Task 5: Capture + playback I/O** — files: `src/artemis/sidecar/audio/capture.py`, `src/artemis/sidecar/audio/playback.py` —
  `capture.py`: `class AudioCapture` — sounddevice `InputStream` with WASAPI exclusive hint (`extra_settings=sd.WasapiSettings(exclusive=False)`); callback converts to 16 kHz/mono/Int16 LE and puts into `asyncio.Queue[bytes]`; `class FakeCapture` replays injected bytes.
  `playback.py`: `class AudioPlayback` — sounddevice `OutputStream` callback; internal `deque[bytes]` of pending PCM chunks; `enqueue_pcm(data: bytes)` appends; callback pops chunks; `flush()` clears the deque and sets a silence flag for the current callback cycle (drains in ~10 ms = one callback period); `class FakePlayback` records `flush()` call count + enqueued bytes; `flush_called: bool` property for assertions.
  — done when: `FakePlayback.flush()` sets `flush_called`; unit test asserts `flush()` drains enqueued chunks.

- [ ] **Task 6: AEC processor** — files: `src/artemis/sidecar/audio/aec.py` —
  ```python
  class AECProcessor:
      """LiveKit RTC APM — wire reverse-stream from PyAudioWPatch loopback.
      GATED: real APM only when ARTEMIS_AUDIO_HW=1 AND ARTEMIS_HEADPHONES != '1'.
      Reverse-stream clocking note: the loopback capture and mic capture must be fed
      to the APM at matching sample timestamps. This is the non-trivial part (budget 2–4 days).
      """
      def process(self, mic_frame: bytes, ref_frame: bytes) -> bytes: ...  # returns AEC-cleaned frame

  class NullAEC:
      """Headphones-dev mode (ARTEMIS_HEADPHONES=1) or tests: pass-through."""
      def process(self, mic_frame: bytes, ref_frame: bytes) -> bytes:
          return mic_frame
  ```
  Headphones-dev mode: if `ARTEMIS_HEADPHONES=1` (or test env), orchestrator uses `NullAEC` and skips PyAudioWPatch loopback capture entirely.
  — done when: `NullAEC.process` returns mic_frame unchanged; `AECProcessor` class exists and imports guard the `livekit-rtc` import behind `TYPE_CHECKING` / try-except so the lean install doesn't fail.

- [ ] **Task 7: STT + TTS engines** — files: `src/artemis/sidecar/audio/stt.py`, `src/artemis/sidecar/audio/tts.py` —
  `stt.py`:
  ```python
  class STTEngine(ABC):
      @abstractmethod
      async def transcribe(self, pcm_queue: asyncio.Queue[bytes | None]) -> str:
          """Consume PCM frames until sentinel None; return transcript."""
  class FakeSTT(STTEngine): ...  # returns injected transcript
  class MoonshineSTT(STTEngine): ...  # GATED
  class FasterWhisperSTT(STTEngine): ...  # GATED fallback
  ```
  `tts.py`:
  ```python
  class TTSEngine(ABC):
      @abstractmethod
      async def synthesize(self, text: str) -> AsyncIterator[bytes]:
          """Yield 16 kHz/mono/Int16-LE PCM chunks."""
  class FakeTTS(TTSEngine): ...  # yields injected PCM chunks
  class KokoroTTS(TTSEngine):
      """GATED: PyTorch CUDA. Synthesises at 24 kHz; resamples to 16 kHz with scipy.signal.resample_poly."""
  class PiperTTS(TTSEngine): ...  # GATED CPU fallback, native 16 kHz
  ```
  — done when: `FakeSTT` returns transcript; `FakeTTS` yields bytes; resample note documented.

- [ ] **Task 8: IPC server** — files: `src/artemis/sidecar/audio/ipc_server.py` —
  `class IPCServer` — asyncio coroutine; creates AF_UNIX socket at `<ARTEMIS_DATA_ROOT>/<ARTEMIS_SLOT>/run/audio.sock`; sets `0600` permissions via `os.chmod`; demux loop reads frames with `decode_frame`; routes:
  - `0x01` JSON → parse `type` field → dispatch to `_handle_command(cmd)` (updates state machine; for `play` command, announces incoming `0x03` stream to playback)
  - `0x03` PCM → `playback.enqueue_pcm(data)` + feed AEC reverse-stream
  Outbound: `send_event(msg: dict)` writes an `encode_json(msg)` frame; `send_mic_pcm(data: bytes)` writes a `0x02` frame. Both called from the orchestrator on the asyncio event loop (no blocking audio thread calls).
  Peer-uid gate: OMITTED on Windows (`getpeereid` unavailable). Document clearly: "Windows dev sidecar omits peer-uid check — no DEK crosses this socket; add when porting to production Unix target."
  — done when: socket created at correct path with 0600 perms; a test client sends a `getStatus` JSON command and receives a `status` event response.

- [ ] **Task 9: Orchestrator + entry point** — files: `src/artemis/sidecar/audio/orchestrator.py`, `src/artemis/sidecar/audio/__main__.py` —
  `orchestrator.py`: `class AudioOrchestrator` — async run loop:
  1. Drain `capture_queue` frame → feed `AECProcessor` → feed `WakeWordDetector` and `VADDetector`.
  2. On wake: transition state machine → emit `wakeDetected` event → await `startListening` command.
  3. During `CAPTURING`: feed VAD; on `SPEECH_START` emit event; on `SPEECH_END` emit event + transition; start max-duration timer.
  4. On barge-in path (see Task 10).
  5. On `play` command from brain: start `AudioPlayback`; stream `0x03` PCM chunks via `ipc_server` → `playback.enqueue_pcm`; emit `playbackStarted`; on EOS (zero-length `0x03` frame) emit `playbackFinished`; transition IDLE.
  `__main__.py`: read `ARTEMIS_DATA_ROOT`, `ARTEMIS_SLOT`, `ARTEMIS_AUDIO_HW`, `ARTEMIS_HEADPHONES`, `ARTEMIS_MAX_SPEECH_S` (default 30); construct components (fakes when `ARTEMIS_AUDIO_HW` unset); wire; `asyncio.run(orchestrator.run())`.
  — done when: `python -m artemis.sidecar.audio serve` starts, creates socket, accepts connection, scripted FakeWakeWord + FakeVAD drives `wakeDetected`→`speechStart`→`speechEnd` events over the socket.

- [ ] **Task 10: Barge-in path** — files: `src/artemis/sidecar/audio/orchestrator.py` (modify Task 9 code) —
  Inside the VAD feed loop, while `state == PLAYING`:
  ```python
  if barge_in_gate.should_barge_in(vad_event, is_playing=True):
      playback.flush()              # drain OutputStream callback deque → silence ~10 ms
      await ipc_server.send_event({"type": "bargein"})   # emit AFTER flush returns
      state_machine.transition("barge_in")               # → CAPTURING
  ```
  Ordering invariant: `flush()` MUST return before `bargein` event is sent (mirrors M5-a `BargeInController` ordering rule). Budget: flush ~10 ms + asyncio send ~1 ms = ~11 ms well under 200 ms target.
  Real barge-in latency measurement (VAD onset → playback silence → event) is a GATED task.
  — done when: `test_audio_barge_in.py` asserts `FakePlayback.flush_called` is `True` before `bargein` event recorded; `speechStart` while `IDLE` emits nothing.

- [ ] **Task 11: Test suite** — files: `tests/sidecar/test_audio_protocol.py`, `tests/sidecar/test_audio_state_machine.py`, `tests/sidecar/test_audio_barge_in.py`, `tests/sidecar/test_audio_e2e.py` —
  All tests use fakes; GATED paths skipped unless `ARTEMIS_AUDIO_HW=1` (use `pytest.mark.skipif`).
  `test_audio_protocol.py`: encode→decode round-trip for every message dataclass; PCM blob; kind byte correctness; 4-byte big-endian length.
  `test_audio_state_machine.py`: all legal transitions; illegal transition raises `InvalidTransition`; max-duration timer fires `speechEnd(reason="maxDuration")`.
  `test_audio_barge_in.py`: `speechStart` during `playing` → `flush_called=True`, `bargein` event emitted, state = `CAPTURING`; `speechStart` during `idle` → no flush, no event.
  `test_audio_e2e.py`: in-process socket pair; `FakeWakeWord` → `wakeDetected`; `FakeVAD` sequence → `speechStart`/`speechEnd`; brain sends `play` → `FakeTTS` PCM → `playbackStarted`/`playbackFinished`; mid-play `speechStart` → `flush` + `bargein`.
  — done when: `uv run pytest tests/sidecar/ -q` exits 0 (GATED tests reported skipped).

- [ ] **Task 12 (GATED — Windows GPU + mic):** Real models + real audio on the dev box — files: no new files; activate GATED paths. With `ARTEMIS_AUDIO_HW=1 ARTEMIS_HEADPHONES=1`:
  (a) load openWakeWord ONNX ("Hey Jarvis" built-in model); (b) load Silero VAD v5; (c) load Moonshine v2 Small (CPU); (d) load Kokoro-82M (GPU); (e) real WASAPI mic + `OutputStream`; say "Hey Jarvis" → `wakeDetected`; speak → `speechStart`/`speechEnd` + transcript; synthesise reply → playback; mid-speech → barge-in flushes in <200 ms.
  — done when: all events fire correctly end-to-end; barge-in latency measured ≤200 ms; results recorded in `docs/handoff/`.

- [ ] **Task 13 (GATED — Mac-hardware tail, out of scope for this spec):** Production AEC quality (open-mic + speaker, no headphones) via LiveKit APM reverse-stream clocking; full native macOS integration. This is intentionally left to the Mac Mini bring-up phase alongside the Swift M5-a sidecar. Document: "Windows headphones-dev AEC bypass is confirmed dev path; APM reverse-stream wiring exists in `aec.py` but is unvalidated on Windows open-mic; Mac hardware gate."

## Acceptance Criteria

- [ ] `uv sync` (no `--group voice-dev`) exits 0; no voice-stack package pulled.
- [ ] `uv sync --group voice-dev` exits 0.
- [ ] `uv run mypy src/artemis/sidecar/ --strict` exits 0 (no type errors).
- [ ] `uv run pytest tests/sidecar/ -q` exits 0; all GATED tests reported `skipped` (not failed).
- [ ] `uv run mypy src/ --strict` exits 0 (full project mypy — per host-verify rule).
- [ ] `uv run pytest -q` exits 0 (full project tests — per host-verify rule).
- [ ] `python -m artemis.sidecar.audio serve` (fakes, temp `ARTEMIS_DATA_ROOT`) starts; `audio.sock` exists at `<root>/<slot>/run/` with perms `0600`; connected test client receives `wakeDetected`→`speechStart`→`speechEnd` event sequence.
- [ ] Barge-in unit test: `speechStart` during `playing` → `FakePlayback.flush_called` is `True` AND `bargein` event is emitted AND state = `CAPTURING`; `speechStart` during `idle` → no flush, no event.
- [ ] Protocol round-trip test: every event and command message encodes + decodes without loss; 1-byte kind and 4-byte big-endian length are correct.
- [ ] (GATED, `ARTEMIS_AUDIO_HW=1 ARTEMIS_HEADPHONES=1`) real end-to-end: "Hey Jarvis" fires `wakeDetected`; barge-in flushes in ≤200 ms; recorded in handoff.

## Commands to Run

```bash
# lean install (must not pull voice deps)
uv sync

# install with voice stack
uv sync --group voice-dev

# type-check sidecar only (fast)
uv run mypy src/artemis/sidecar/ --strict

# full project mypy (host-verify requirement)
uv run mypy src/ --strict

# sidecar tests only
uv run pytest tests/sidecar/ -q

# full project tests (host-verify requirement)
uv run pytest -q

# smoke: start sidecar with fakes
ARTEMIS_DATA_ROOT=/tmp/artemis-test ARTEMIS_SLOT=dev python -m artemis.sidecar.audio serve

# GATED: real hardware end-to-end
ARTEMIS_AUDIO_HW=1 ARTEMIS_HEADPHONES=1 ARTEMIS_DATA_ROOT=/tmp/artemis-test ARTEMIS_SLOT=dev \
  python -m artemis.sidecar.audio serve
```

## Gaps Flagged for Human Review

1. **EOS signalling for `0x03` PCM stream:** M5-a says `play(sampleRate, channels)` announces an incoming stream but does not explicitly specify end-of-stream. This spec assumes EOS = a zero-length `0x03` frame. Confirm before build; if the convention differs, only `ipc_server.py` and `orchestrator.py` change.
2. **`speechEnd` max-duration timeout value:** M5-a lists `reason: "endpoint"|"maxDuration"` but gives no timeout constant. Default here = 30 s via `ARTEMIS_MAX_SPEECH_S`. Confirm or supply the canonical value.
3. **Peer-uid gate on Windows:** `getpeereid` is unavailable on Windows AF_UNIX. The uid gate is omitted for the dev sidecar. If the security posture requires it (e.g. when porting to WSL2 or Linux), `SO_PEERCRED` on Linux is the equivalent. No action needed for Windows dev.
4. **LiveKit APM reverse-stream clocking on Windows:** the research doc flags this as "solvable, not trivial — budget 2–4 days." `aec.py` stubs the interface; the headphones-dev path (`NullAEC`) de-risks the schedule. This is the only Mac-quality-AEC-gap item that partially overlaps the Windows build (the stub must exist from day one, per the research recommendation).
5. **✅ RESOLVED 2026-06-25 — package names confirmed** (focused retrieval pass): **Moonshine** = `moonshine-voice` (official v2 SDK, CPU/ONNX, native Windows, MIT; `from moonshine_voice import Transcriber`; `ModelArch.SMALL_STREAMING`) — GPU alt via HF Transformers `MoonshineStreamingForConditionalGeneration` + `UsefulSensors/moonshine-streaming-small`. **Kokoro** = `kokoro>=0.9.2` (PyTorch path, NOT `kokoro-onnx`; `from kokoro import KPipeline`; weights `hexgrad/Kokoro-82M`, Apache-2.0; needs `espeak-ng` Windows binary on PATH + cu128 torch from the PyTorch index). Folded into Task 1. _Minor residual [COMMUNITY]: the exact `moonshine-streaming-small` HF repo id + `ModelArch.SMALL_STREAMING` enum spelling — verify against the installed package at build (`NEEDS-DOMAIN: github.com` for source confirmation)._

## Mac-Gated Tail (out of scope for this spec)

- Production-grade AEC quality with open mic + speaker (LiveKit APM reverse-stream clocking validated on Mac hardware, no headphones required).
- Native macOS audio integration (AVAudioEngine / VoiceProcessingIO AEC unit).
- These items belong to the Swift M5-a sidecar and M5-a Task 9 (GATED) on the Mac Mini. This Windows sidecar replaces the Swift sidecar ONLY for Windows dev; ADR-001 is unchanged.

## Progress
_(Coding mode writes here — do not edit manually)_

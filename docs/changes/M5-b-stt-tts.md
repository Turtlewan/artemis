<!-- amended 2026-06-11 per m5-m6-voice-heartbeat.md UPGRADE U4 (kokoro-mlx → mlx-audio package name) -->
<!-- amended 2026-06-25 Windows dev re-scope — see docs/research/2026-06-25-voice-windows-dev/README.md -->
---
spec: m5-b-stt-tts
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M5-b — STT (Parakeet-TDT MLX + Whisper-turbo fallback) behind the `STT` port + TTS (Kokoro-82M MLX persistent server, sentence-streaming) behind the `TTS` port

> **Amendment 2026-06-25 (Windows dev re-scope):** The STT and TTS ports now have **dev implementations** bound to the Windows Python sidecar (`M5-a-win-sidecar`) — the Mac MLX/AVSpeech adapters remain the production impls (ADR-001 unchanged). See `docs/research/2026-06-25-voice-windows-dev/README.md`.
> - **STT dev binding:** `Moonshine v2 Small` (true streaming, CPU, <500 MB, MIT, native 16 kHz) as the primary; `faster-whisper distil-large-v3 int8` as the accuracy/GPU fallback — both run on Windows against the same `STT` port the Mac Parakeet impl satisfies. Off-hardware test suite is unchanged (fakes); Tasks 1–4 now also cover the Windows dev path.
> - **TTS dev binding:** `Kokoro-82M` (PyTorch CUDA via `kokoro-onnx` is broken on Windows — use the `Kokoro-FastAPI` / PyTorch CUDA path, onnxruntime #23384); `Piper` as the CPU/degraded fallback. 2–3 GB VRAM for Kokoro; Piper = 0 VRAM. Both speak the same `TTS` port; the 24 kHz→16 kHz resample lives in the adapter.
> - **Sentence-level streaming is the critical latency lever:** without calling `tts.synthesize` per sentence as the LLM streams, TTFA balloons +3–5 s. The splitter (M5-d) + per-sentence TTS call pattern is mandatory for sub-1 s TTFA on Windows.
> - The dev+Mac split is purely at the port adapter layer (`stt.py`/`tts.py` `_load_*` seams) — no task body changes required.

**Identity:** Implements the Python `STT` port adapter (Parakeet-TDT-0.6B MLX/ANE primary + MLX-Whisper-turbo multilingual fallback, language-routed) and the `TTS` port adapter (Kokoro-82M MLX, run as a warm persistent server, synthesising sentence-by-sentence as text streams in → an `Iterator[bytes]` of 16 kHz PCM), both pre-warmed at startup.
→ why: see docs/technical/architecture/brain.md § "Voice (cascaded, streaming every stage)" (Parakeet-TDT + Whisper fallback, Kokoro persistent server sentence-by-sentence) · docs/drafts/m0/M0-d-ports-scaffolding.md (the `STT.transcribe`/`TTS.synthesize` port signatures).

<!-- Split rule: TWO logical phases (1: STT adapter incl. the primary+fallback routing; 2: TTS adapter incl. the persistent Kokoro server + sentence streamer). 2 src files + 1 shared warmup helper + 1 test = at/just over the file guideline. Kept together because both are "the model-backed voice port adapters", both pre-warm through the same startup path, and the brain.md "stream every stage" budget couples STT-out → TTS-in. The PCM working format (16 kHz/mono/Int16) is shared with M5-a's audio sidecar and must agree. If review wants leaner: sub-split into M5-b1 (STT) and M5-b2 (TTS). Flagged per rules. Depends on the M0-d `STT`/`TTS` ports; consumed by M5-d's voice loop. -->

## Assumptions
- M0-d is complete: the `STT` port is `def transcribe(self, audio: bytes, *, language: str | None = None) -> str: ...` and the `TTS` port is `def synthesize(self, text: str) -> Iterator[bytes]: ...` (streamed). M5-b's adapters structurally satisfy those EXACT signatures. → impact: Stop (signatures must match M0-d; the brain depends only on the ports).
- **STT primary = Parakeet-TDT-0.6B via MLX/ANE** (the FluidAudio/parakeet-mlx path); **fallback = MLX-Whisper-turbo** for multilingual input. M5-b runs Parakeet for the default/English path and routes to Whisper when a language hint is non-English OR Parakeet's confidence/language-detection indicates non-English. → impact: Caution. DRAFTED DEFAULT: packages `parakeet-mlx` (Parakeet-TDT-0.6B, FluidAudio/ANE) + `mlx-whisper` (Whisper-turbo) behind a `_load` seam; routing = `language is None or language.startswith("en")` → Parakeet, else Whisper. Confidence/language-signal fallback = build-time refinement. Exact package names/load API/Parakeet confidence signal confirmed GATED Task 5.
- **TTS = Kokoro-82M via MLX**, run as a WARM PERSISTENT process/server (not loaded per request) so first-audio latency is dominated only by synth, not model load. M5-b owns starting/keeping-warm the Kokoro instance (in-process resident model OR a tiny local HTTP/IPC server — build choice). → impact: Caution. DRAFTED DEFAULT: Kokoro-82M as an in-process MLX model resident in the long-lived brain process behind the `TTS` port (residency satisfies "persistent server"; avoids a 2nd launchd job). Package: **`mlx-audio`** (Blaizzy/mlx-audio — ships Kokoro-82M + other TTS models for Apple Silicon MLX); a standalone `kokoro-mlx` PyPI package name is unverified and a supply-chain risk for a pre-authorised network action (U4 fix — package name changed). A separate persistent Kokoro server is the documented swap if on-hardware shows GPU/RAM contention. Confirmed GATED Task 6.
- **Sentence-streaming**: `TTS.synthesize(text)` is called per SENTENCE as the LLM streams (the voice loop in M5-d splits the responder's token stream into sentences and calls `synthesize` per sentence); each call returns an `Iterator[bytes]` of PCM chunks for that sentence so audio starts before the full reply exists. M5-b also exposes a convenience `synthesize_stream(sentences: Iterable[str]) -> Iterator[bytes]` that chains per-sentence synthesis. → impact: Caution (the per-sentence boundary is the brain.md latency lever; the splitter itself lives in M5-d, M5-b just synthesises whatever sentence it is handed).
- **Pre-warm at startup**: both adapters expose a `warmup()` that loads the model + runs one tiny throwaway inference so the first real request is fast (brain.md "keep responder/Kokoro/Parakeet warm; pre-warm at startup"). `warmup()` is called by the voice-loop/app composition at startup. → impact: Low (warmup is idempotent + safe to call once).
- **PCM format** out of TTS = 16 kHz, mono, 16-bit signed LE — the SAME format the M5-a sidecar plays (`0x03` frames) and the same format STT consumes from the sidecar (`0x02` frames). If Kokoro's native rate differs, the adapter resamples to 16 kHz. → impact: Stop (format mismatch breaks playback/AEC; the working format is frozen with M5-a).
- The adapters are **fully testable off-hardware with fakes** for the model-load + inference (deterministic stub transcription / stub PCM); **real Parakeet/Whisper transcription, real Kokoro synthesis, ANE residency, and first-audio latency are GATED on-hardware.** → impact: Caution (off-hardware proves the port conformance, the language routing, the sentence chaining, and the format; the live models are gated).

Simplicity check: considered running STT/TTS behind the mlx-openai-server seam like the responder — rejected: Parakeet/Whisper/Kokoro are not OpenAI-chat models and don't fit the `/v1/chat` seam; they need their own MLX load paths behind the dedicated voice ports (which M0-d already defined for exactly this reason). Considered loading Kokoro per request — rejected by brain.md (persistent/warm). Considered a single STT model (Parakeet only) — rejected: brain.md locks the Whisper multilingual fallback. The minimum is two thin port adapters with a deterministic fallback rule + a warm Kokoro.

## Prerequisites
- Specs that must be complete first: **M0-a** (config/paths/Settings + the model-dir convention from M0-c for where voice model weights live), **M0-c** (the `${ARTEMIS_MODEL_DIR}` model cache the voice models also use — NOT the OpenAI seam, just the model dir), **M0-d** (`STT`/`TTS` ports + `PersonId`/types). 
- Environment setup required: the MLX voice packages (Parakeet-MLX, MLX-Whisper, Kokoro-MLX) — added via `uv` at the GATED on-hardware task (Apple-Silicon/MLX-only wheels) behind lazy imports so the off-hardware suite runs with fakes without importing them. Off-hardware testable with fakes; **real models + first-audio latency are GATED on-hardware (Tasks 5–6).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/voice/__init__.py | create | voice adapters package marker |
| /Users/artemis-build/artemis/src/artemis/voice/stt.py | create | `ParakeetWhisperSTT` implementing the `STT` port (Parakeet primary + Whisper fallback routing + `warmup`) + `FakeSTT` |
| /Users/artemis-build/artemis/src/artemis/voice/tts.py | create | `KokoroTTS` implementing the `TTS` port (warm persistent Kokoro, per-sentence `synthesize` → `Iterator[bytes]`, `synthesize_stream`, `warmup`) + `FakeTTS` |
| /Users/artemis-build/artemis/tests/test_stt_tts.py | create | port-conformance + language-routing + sentence-chaining + PCM-format tests against fakes |

## Tasks
- [ ] Task 1: Implement the STT adapter (Parakeet primary + Whisper fallback) — files: `/Users/artemis-build/artemis/src/artemis/voice/__init__.py`, `/Users/artemis-build/artemis/src/artemis/voice/stt.py` — `class ParakeetWhisperSTT` structurally satisfying `artemis.ports.STT`:
  - constructed from `Settings` (resolves the model dir + model ids); lazy-loads Parakeet + Whisper via `_load_parakeet()`/`_load_whisper()` seams (real MLX load behind a lazy import; in tests these are monkeypatched/overridden to return stub models).
  - `transcribe(self, audio: bytes, *, language: str | None = None) -> str`: route per the Assumptions rule — `language is None or language.startswith("en")` → Parakeet; else → Whisper. Decode `audio` as 16 kHz/mono/Int16 PCM (the M5-a format). Return the transcript string. Wrap model errors → a typed `STTError`, and on a Parakeet failure for an English request, degrade-don't-crash by retrying once on Whisper (brain.md degrade ladder) — documented.
  - `def warmup(self) -> None`: load both models + run one tiny throwaway transcription each (pre-warm). Idempotent.
  - Add a static `_check: STT = ParakeetWhisperSTT(...)`-style conformance assertion exercised in the test.
  - `class FakeSTT` (TEST): constructed with a fixed transcript + a recorder of which backend WOULD have been chosen (so the routing rule is testable without models).
  — done when: `uv run mypy --strict src` passes; `FakeSTT`/the routing logic is exercisable without importing MLX.

- [ ] Task 2: Implement the TTS adapter (warm Kokoro, sentence-streaming) — files: `/Users/artemis-build/artemis/src/artemis/voice/tts.py` — `class KokoroTTS` structurally satisfying `artemis.ports.TTS`:
  - constructed from `Settings`; `_load_kokoro()` seam lazy-loads + holds the Kokoro-82M MLX model RESIDENT (warm persistent) for the brain process lifetime.
  - `synthesize(self, text: str) -> Iterator[bytes]`: synthesise ONE sentence/segment of `text` to PCM, yielding 16 kHz/mono/Int16 chunks as they are produced (so playback can start mid-sentence). If Kokoro's native sample rate ≠ 16 kHz, resample to 16 kHz in the adapter. Wrap errors → typed `TTSError`.
  - `def synthesize_stream(self, sentences: Iterable[str]) -> Iterator[bytes]`: for each sentence call `synthesize` and chain the chunk iterators (the convenience the M5-d loop uses to keep audio flowing sentence-by-sentence).
  - `def warmup(self) -> None`: load Kokoro + synth one tiny throwaway phrase (pre-warm). Idempotent.
  - `class FakeTTS` (TEST): `synthesize` yields a fixed small PCM blob per call + records the texts it was asked to synthesise (so sentence-chaining + per-sentence boundaries are testable without the model).
  — done when: `uv run mypy --strict src` passes; `FakeTTS.synthesize("hi")` yields ≥1 PCM chunk; the chunks are 16 kHz/mono/Int16-shaped (length is an even number of bytes; documented format constant matches M5-a).

- [ ] Task 3: Define the shared PCM/warmup helpers — files: `/Users/artemis-build/artemis/src/artemis/voice/__init__.py` (extend) — export a shared `PCM_FORMAT` constant (sample_rate=16000, channels=1, dtype="int16") referenced by BOTH adapters AND documented as identical to M5-a's `AudioFormat`; a small `warmup_all(stt: STT, tts: TTS) -> None` helper the composition calls once at startup (calls each adapter's `warmup()` if present, tolerating fakes without one). — done when: `uv run mypy --strict src` passes; `PCM_FORMAT` is importable and its values equal the M5-a fixed format (cross-checked in the test by asserting the literal values 16000/1/"int16").

- [ ] Task 4: Write the STT/TTS tests (port conformance + routing + streaming + format) — files: `/Users/artemis-build/artemis/tests/test_stt_tts.py` — typed pytest, all off-hardware with fakes/monkeypatched loaders:
  - port conformance: `_s: STT = ParakeetWhisperSTT(...)` and `_t: TTS = KokoroTTS(...)` type-check under mypy (with loaders monkeypatched to stubs so no MLX import).
  - STT routing: with stubbed backends recording which fired, `transcribe(pcm, language=None)` and `transcribe(pcm, language="en-US")` choose Parakeet; `transcribe(pcm, language="zh")` chooses Whisper; assert the recorder.
  - STT degrade: a stubbed Parakeet that raises on an English request → falls back to Whisper once and returns Whisper's transcript (no exception out of `transcribe`).
  - TTS sentence-streaming: `FakeTTS().synthesize_stream(["Hello.", "World."])` yields chunks for BOTH sentences and the FakeTTS records exactly `["Hello.", "World."]` in order (proves per-sentence calls).
  - PCM format: every yielded TTS chunk has an even byte length (Int16) and `PCM_FORMAT == (16000, 1, "int16")` matching M5-a.
  - `warmup_all(FakeSTT(), FakeTTS())` runs without error.
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_stt_tts.py` passes.

- [ ] Task 5 (GATED — on-hardware): Live STT — Parakeet primary + Whisper fallback — files: (no repo files; adds the MLX voice deps via `uv add` then exercises Task 1's real loaders) — on the Mac Mini: `uv add` the confirmed Parakeet-MLX + MLX-Whisper packages; `warmup()` then transcribe a short English WAV (16 kHz/mono) via Parakeet and a short non-English clip via Whisper; confirm Parakeet runs on ANE and the fallback routing fires. Build-time empirical (MLX/ANE + model weights). — done when: on the Mini, an English clip transcribes via Parakeet and a non-English clip via Whisper, both correct enough to read back — recorded in handoff.

- [ ] Task 6 (GATED — on-hardware): Live TTS — warm Kokoro + first-audio latency — files: (no repo files; adds the Kokoro-MLX dep then exercises Task 2's real loader) — on the Mac Mini: `uv add` the confirmed Kokoro-MLX package; `warmup()`; then `synthesize("This is a test sentence.")` and measure time-to-first-PCM-chunk with the model already warm; confirm output is 16 kHz/mono/Int16 and audibly correct when played through the M5-a sidecar. Also do the build-time benchmark note: compare Kyutai Pocket TTS vs Kokoro first-audio latency + quality (Kokoro is the default; record the comparison only). Build-time empirical. — done when: on the Mini, a warm Kokoro `synthesize` yields first audio quickly (record the ms), output plays correctly via the sidecar, and the Kyutai-vs-Kokoro note is recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/voice/__init__.py, /Users/artemis-build/artemis/src/artemis/voice/stt.py, /Users/artemis-build/artemis/src/artemis/voice/tts.py, /Users/artemis-build/artemis/tests/test_stt_tts.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_stt_tts.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fakes; no MLX) |
| `uv add parakeet-mlx mlx-whisper` (GATED, on-Mini) | STT model packages (confirm names at GATED Task 5) |
| `uv add mlx-audio` (GATED, on-Mini) | TTS model package — Kokoro-82M ships inside `mlx-audio` (Blaizzy/mlx-audio); `kokoro-mlx` as a standalone PyPI name is unverified and a supply-chain risk for a pre-authorised network action (U4 fix) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/voice/**, tests/test_stt_tts.py, pyproject.toml, uv.lock |
| `git commit` | "feat: M5-b STT (Parakeet+Whisper fallback) + TTS (warm Kokoro, sentence-streaming) port adapters" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (model dir, model ids) |
| `ARTEMIS_MODEL_DIR` | Where the voice model weights live (shared with M0-c) |

### Network
| Action | Purpose |
|--------|---------|
| `uv add` voice packages (GATED) | Package install (PyPI, Apple-Silicon wheels) |
| (GATED, on-Mini) model fetch | Download Parakeet/Whisper/Kokoro weights into `${ARTEMIS_MODEL_DIR}` |

## Specialist Context
### Security
STT output is **untrusted data** (transcribed speech can carry injection payloads): the brain (M5-d/M1-b) treats the transcript as data, not instructions (agent self-defense). The voice models run locally on-box — voice audio + transcripts are owner-sensitive and never leave the box (brain.md cloud policy). The adapters never write captured audio or transcripts to disk/logs (log only timings + backend chosen).

### Performance
Both models are pre-warmed (`warmup()` at startup) so first-request latency excludes model load — this is the brain.md "keep Kokoro/Parakeet warm" lever feeding the 750–800ms end-to-end budget. TTS streams per-sentence PCM so playback starts before the full reply (masking TTFT). Parakeet on ANE keeps STT off the GPU shared with the responder.

### Accessibility
(none directly — voice IS the accessibility surface but no rendered UI here.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/voice/stt.py, src/artemis/voice/tts.py | Type + docstring all exports; document the Parakeet→Whisper routing rule, the per-sentence streaming contract, the warm-persistent Kokoro lifecycle, and the frozen 16 kHz/mono/Int16 PCM format |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_stt_tts.py` → verify: exit 0 (incl. `STT`/`TTS` structural conformance assertions).
- [ ] Run `uv run pytest -q tests/test_stt_tts.py` → verify: STT routes en→Parakeet / non-en→Whisper, degrades Parakeet→Whisper on error; TTS streams per-sentence (FakeTTS records both sentences in order); every TTS chunk is even-length Int16; `PCM_FORMAT == (16000, 1, "int16")`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Live STT: English clip via Parakeet, non-English via Whisper → verify both transcribe correctly — recorded in handoff.
- [ ] (GATED, on Mini) Live warm Kokoro `synthesize`: first audio quick, 16 kHz/mono/Int16, plays via the M5-a sidecar; Kyutai-vs-Kokoro note recorded → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

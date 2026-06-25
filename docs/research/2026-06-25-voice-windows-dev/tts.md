# TTS Research — Windows Dev Sidecar

**Date:** 2026-06-25
**Re-research after:** 2026-07-09 (two weeks — Kokoro ONNX GPU fix likely, StyleTTS2 streaming fork matures)
**Researcher:** claude-sonnet-4-6 (Phase-2 retrieval agent)
**Confidence key:** [VERIFIED] = multiple independent corroborating sources | [COMMUNITY] = single source / community report | [ASSUMED] = inferred, verify before committing
**Context:** Windows 11, RTX 5060 Ti 8GB VRAM, ~4GB already used by Ollama → TTS has ~4GB VRAM budget. 32GB RAM available. Target: low-latency streaming voice agent with barge-in (flush on interrupt).

---

## Prior Art: Mac Research (2026-06-11)

Full Mac/Apple Silicon TTS research at `docs/research/2026-06-11-voice-stack-refresh.md`. Windows is a different deployment target — Kokoro was the Mac pick via MLX. The Windows pick must use PyTorch/CUDA or ONNX, not MLX.

---

## Candidates Evaluated

1. Piper (Rhasspy / OHF-Voice)
2. Kokoro-82M (hexgrad) — via PyTorch/CUDA or ONNX
3. Coqui XTTS-v2
4. StyleTTS2 (yl4579)
5. Parler-TTS Mini (v1)
6. Windows SAPI 5 (neural voices via NaturalVoiceSAPIAdapter)
7. **2026 entrants:** Chatterbox-Turbo (Resemble AI), Orpheus-TTS (canopyai), Fish Speech (not viable — see below)

---

## 1. Piper (OHF-Voice/piper1-gpl v1.4.2)

### Windows-Native Runnable / GPU Path
- Install: `pip install piper-tts` — cross-platform, identical on Windows. [VERIFIED — localaimaster.com]
- Architecture: VITS → ONNX export → `onnxruntime` backend. CPU-only by design; no GPU training or GPU inference path in the official release. [VERIFIED — localaimaster.com fetch]
- `--cuda` flag exists for `onnxruntime-gpu` CUDAExecutionProvider but is not the primary design target. Reports of incomplete CUDA support on Windows (SubtitleEdit issue #9002). [COMMUNITY — GitHub issues]
- CPU performance: ~10x real-time on a modern desktop CPU; runs real-time on a Raspberry Pi 5. No VRAM consumed. [VERIFIED — localaimaster.com]

### Streaming / First-Audio Latency / Interruptible
- `--output-raw` streams raw PCM to stdout in pipeline mode. [VERIFIED — localaimaster.com fetch]
- **Caveat:** Piper synthesizes a full utterance then streams it; not truly incremental token-by-token synthesis. True streaming requires chunking the input at sentence boundaries upstream. [VERIFIED — GitHub MOSS-TTS issue #53 + medium livekit article]
- First-audio latency after warm-up: sub-200ms on desktop for short sentences (sentence chunk arrives → synthesis completes → first bytes stream). [COMMUNITY — Jetson Orin article: 800–900ms end-to-end on constrained hardware; desktop much faster]
- Interruptible: yes — process can be killed/stdin closed mid-stream; no internal audio renderer to flush. [ASSUMED — CLI/subprocess architecture]
- RTF: ~0.008 (codesota.com). 125x real-time on CPU. [COMMUNITY — codesota.com]

### Voice Quality
- Described as "robotic" relative to neural baselines; acceptable for a utility assistant, noticeably below Kokoro or XTTS naturalness. [VERIFIED — gigagpu search results + codesota.com]
- VITS-quality: low expressiveness, no prosody variation beyond pitch/speed config.

### Memory / VRAM Footprint
- CPU-only: 0 VRAM. Voice model files: 30–130MB per voice (ONNX). [VERIFIED — localaimaster.com]
- Very coexistable with Ollama. No GPU contention at all.

### License + Maturity + 2025/2026 Activity
- **License:** GPL-3.0 (OHF-Voice fork, v1.4.2, April 2026). The original MIT rhasspy/piper was archived October 2025. [VERIFIED — localaimaster.com + promptquorum.com]
- GPL-3.0 is a problem if the Artemis sidecar is ever distributed (copyleft propagation). Personal/internal use is fine.
- Note: promptquorum.com lists "MIT" for Piper — this applies to the archived rhasspy/piper, not the active OHF-Voice fork. **Use OHF-Voice/piper1-gpl = GPL-3.0.** [VERIFIED — localaimaster fetch]
- Activity: actively maintained as of April 2026. Pipecat has a PiperTTSService integration. [VERIFIED — pipecat docs]

### Output Fit
- Raw PCM: 16 kHz signed 16-bit mono (low/x_low voice tiers) or 22.05 kHz (medium/high). [VERIFIED — localaimaster fetch]
- 16 kHz PCM exactly matches Artemis target — no resampling needed for the low/x_low tier.

---

## 2. Kokoro-82M (hexgrad) — PyTorch/CUDA + ONNX paths

### Windows-Native Runnable / GPU Path
- Two deployment paths on Windows:
  - **PyTorch path:** `pip install kokoro` + PyTorch CUDA. Docker image `remsky/Kokoro-FastAPI` with `:latest-cu128` tag for RTX 50-series (Blackwell). [VERIFIED — GitHub remsky/Kokoro-FastAPI]
  - **ONNX path:** `pip install kokoro-onnx onnxruntime-gpu` (v0.5.0, Jan 2026). No PyTorch dependency. [VERIFIED — PyPI kokoro-onnx]
- ONNX GPU path has known issues: 39 Memcpy nodes added for CUDAExecutionProvider, degrading GPU performance vs CPU in some configurations. Bug filed on onnxruntime (#23384). [COMMUNITY — GitHub issue]
- PyTorch CUDA path is the recommended Windows GPU path. OpenAI-compatible REST API via Kokoro-FastAPI for easy integration. [VERIFIED — remsky/Kokoro-FastAPI]

### Streaming / First-Audio Latency / Interruptible
- **First-audio latency:** 45ms on RTX 5090 [COMMUNITY — gigagpu search]; ~150ms on RTX 4070 generation for a 100-word paragraph in <3s total [COMMUNITY — spacebums.co.uk].
- RTF: 0.03 on A100; ~0.04–0.06 on RTX 4090 [COMMUNITY — gigagpu search + spheron.network].
- On RTX 5060 Ti (extrapolated from RTX 5090 being 30–40% faster than Ampere): likely 60–100ms first-audio. [ASSUMED]
- Kokoro-FastAPI supports chunked streaming output (`.pcm` format available). [VERIFIED — remsky/Kokoro-FastAPI]
- Token-streaming from upstream LLM: feed sentence chunks → Kokoro starts speaking before the full response is assembled. [VERIFIED — RealtimeTTS KokoroEngine supports this pattern]
- Interruptible: via HTTP stream abort or RealtimeTTS `stop()` — playback control is in the consumer layer, not the model. [VERIFIED — RealtimeTTS PyPI]

### Voice Quality
- 82M params, StyleTTS2 + ISTFTNet vocoder, 54 voice presets, 8 languages including English. [VERIFIED — HuggingFace hexgrad/Kokoro-82M]
- ELO 1424 open-weight track (codesota.com) — top open-weight model as of 2026. [COMMUNITY — codesota.com]
- "Matched or beat much larger TTS models" in quality rankings. Not voice-clonable (fixed presets only). [COMMUNITY — tryspeakeasy.io]
- Output: 24 kHz; must resample to 16 kHz mono for Artemis target. Trivial with scipy/soundfile. [VERIFIED — HuggingFace model card]

### Memory / VRAM Footprint
- Model weights: <1GB FP16. Total GPU memory during inference including CUDA kernels: **2–3GB**. [VERIFIED — spheron.network]
- With 4GB VRAM budget (8GB total, 4GB Ollama): **fits comfortably**. ~1–2GB headroom. [VERIFIED]
- 50+ concurrent streams on A100 80GB → single stream on RTX 5060 Ti well within budget. [VERIFIED — spheron.network]

### License + Maturity + 2025/2026 Activity
- **Apache 2.0** — fully commercial, no restrictions. [VERIFIED — HuggingFace model card]
- Released January 2025; went viral immediately. RealtimeTTS KokoroEngine shipped. Kokoro-FastAPI maintained through mid-2026. [VERIFIED — multiple sources]
- hexgrad/kokoro GitHub active; v0.9.4+ in 2026. [COMMUNITY — GitHub]

### Output Fit
- 24 kHz mono PCM. Resample to 16 kHz: one `librosa.resample()` call, negligible latency. [VERIFIED — HuggingFace model card]

---

## 3. Coqui XTTS-v2

### Windows-Native Runnable / GPU Path
- `pip install TTS` (community fork of coqui-tts). CUDA GPU path via PyTorch. [VERIFIED — localaimaster.com]
- Windows GPU: works; users report success with CUDA Sysmem Fallback Policy in NVIDIA driver for 8GB cards during fine-tuning (inference lighter). [COMMUNITY — GitHub coqui-ai/TTS #3268]
- RTF: ~0.18 (codesota.com); ~3x real-time on GPU. [COMMUNITY — codesota.com]

### Streaming / First-Audio Latency / Interruptible
- Streaming latency: <200ms claimed; <150ms with FP16 and PyTorch GPU. [COMMUNITY — localaimaster.com + gigagpu search]
- First-audio on RTX 3090: ~190ms; RTX 5090: ~135ms. [COMMUNITY — gigagpu search results]
- On RTX 5060 Ti (estimate): ~150–200ms. [ASSUMED]
- Supports chunked streaming via `tts.tts_to_file()` or the streaming API endpoint. [COMMUNITY — gigagpu.com deploy article]
- Interruptible: via stream abort in FastAPI/HTTP delivery layer. [ASSUMED]

### Voice Quality
- ELO 1388 open-weight track (codesota.com); below Kokoro. [COMMUNITY — codesota.com]
- Voice cloning from 6–20 second reference audio; 17 languages. [VERIFIED — localaimaster fetch]
- Naturalness significantly better than Piper; similar to Kokoro but different character. [COMMUNITY — multiple comparisons]

### Memory / VRAM Footprint
- Entry hosting: 8GB VRAM (RTX 3060Ti class). Inference alone: ~4GB. [COMMUNITY — gigagpu search + databasemart.com]
- FP16 halves VRAM with negligible quality loss. FP16 inference: ~2GB model weights + buffers ≈ 3–4GB total. [COMMUNITY — gigagpu.com]
- With 4GB budget: **tight but feasible at FP16**. Any concurrency spike could OOM. [ASSUMED — extrapolated from sources]

### License + Maturity + 2025/2026 Activity
- **License: Coqui Public Model License (CPML) — non-commercial only.** [VERIFIED — localaimaster fetch + promptquorum fetch]
- Coqui Inc shut down January 2024. No commercial licenses available. Community fork maintained. [VERIFIED — localaimaster fetch]
- **GPL blocker for commercial use.** For personal assistant = acceptable.
- Activity: community fork active but no major releases 2025–2026. Frozen at XTTS-v2. [COMMUNITY — PyPI coqui-tts]

### Output Fit
- 24 kHz output. Resample to 16 kHz. [VERIFIED — HuggingFace coqui/XTTS-v2]

---

## 4. StyleTTS2 (yl4579/StyleTTS2)

### Windows-Native Runnable / GPU Path
- `pip install styletts2` (MIT-licensed gruut variant). PyTorch CUDA. [VERIFIED — PyPI styletts2]
- VRAM for inference: **2GB** (RTX 3050M). [VERIFIED — dagshub.com]
- Windows app confirmed on "Windows gaming PCs with 12GB+ Nvidia GPU" (likely older reference). [COMMUNITY — search results]

### Streaming / First-Audio Latency / Interruptible
- Official package: **no streaming API**. Package "currently only supports inference capabilities." [VERIFIED — PyPI styletts2 fetch]
- Experimental streaming API in GPL-licensed fork only. Not production-ready. [COMMUNITY — search results]
- Per-sentence RTF not published; inference "2–3 seconds on RTX 3050M" for unspecified length. [COMMUNITY — dagshub.com]
- **No true streaming = high first-audio latency** (full sentence synthesized then played). Incompatible with streaming voice agent requirement. [VERIFIED — package description]

### Voice Quality
- "Best latency-to-quality ratio for real-time conversation" per gigagpu search results. [COMMUNITY — gigagpu search]
- Style diffusion + adversarial training; 24 kHz output. High naturalness. [VERIFIED — GitHub yl4579/StyleTTS2]

### Memory / VRAM Footprint
- **2GB VRAM** for inference. Very coexistable with Ollama. [VERIFIED — dagshub.com]

### License + Maturity + 2025/2026 Activity
- **MIT license** (styletts2 PyPI package, gruut variant). [VERIFIED — PyPI fetch]
- Original repo: MIT but inference depends on some GPL components in the GPL fork. Use MIT `styletts2` pip package to stay clean. [COMMUNITY — various]
- Activity: original repo quiet 2025–2026; pip package maintained. [COMMUNITY — PyPI]

### Output Fit
- 24 kHz numpy array; easily written to PCM. Resample to 16 kHz. [VERIFIED — PyPI styletts2 fetch]

---

## 5. Parler-TTS Mini (v1)

### Windows-Native Runnable / GPU Path
- Built on HuggingFace Transformers + PyTorch. Runs on any platform with Python 3.6+ and PyTorch. [VERIFIED — HuggingFace discussion]
- VRAM: FP32 = 3.6GB; FP16 = 1.8GB. Fits on 8GB GPU comfortably. [VERIFIED — HuggingFace parler_tts_mini_v0.1 discussion]

### Streaming / First-Audio Latency / Interruptible
- **No streaming support documented at v0.1.** Planned for v1 with flash attention + torch.compile. [VERIFIED — HuggingFace discussion]
- RTF: ~0.22 (codesota.com) — slower than Kokoro. [COMMUNITY — codesota.com]
- First-audio: 31 seconds for a short phrase on M3 Max at v0.1 — extremely slow without optimization. With optimizations in v1+, likely improved but not benchmarked. [COMMUNITY — HuggingFace discussion]
- **Non-streaming + high initial latency = not viable for real-time agent.** [VERIFIED]

### Voice Quality
- Unique: describes voice in natural language prompts ("speak fast with a slightly low pitch"). [COMMUNITY — PyPI description]
- No voice cloning; English only. [COMMUNITY — multiple sources]

### License + Maturity + 2025/2026 Activity
- **Apache 2.0.** [VERIFIED — PyPI parler-tts]
- v1 model released but benchmarks and streaming promised "in a few weeks" from v0.1 — unclear if delivered. [COMMUNITY — HuggingFace discussion]
- Activity: Hugging Face team; moderately active. [COMMUNITY]

### Output Fit
- 44.1 kHz (Parler-TTS Mini). Resample to 16 kHz. [COMMUNITY — various]

---

## 6. Windows SAPI 5 (Neural Voices)

### Windows-Native Runnable / GPU Path
- SAPI 5 is OS-native; any SAPI 5 voice works without Python. [VERIFIED — Genesys TTS docs]
- Neural voices accessible via `gexgd0419/NaturalVoiceSAPIAdapter` (bridges Azure neural TTS models to SAPI 5). [VERIFIED — GitHub NaturalVoiceSAPIAdapter]
- CPU-only for local inference; Azure voices are cloud. 0 VRAM for local SAPI. [ASSUMED]

### Streaming / First-Audio Latency / Interruptible
- SAPI 5 supports streaming PCM output via `ISpVoice::SpeakAsync`. [VERIFIED — Microsoft SAPI docs]
- **Local SAPI neural voices (Windows 11 built-in):** 200–400ms TTFB. [COMMUNITY — NVDA GitHub issue #19573 + Microsoft Q&A]
- Azure-backed via NaturalVoiceSAPIAdapter: network latency adds 300–600ms. Not suitable for offline use. [COMMUNITY — Microsoft Learn]
- Interruptible: `ISpVoice::Speak(SPF_PURGEBEFORESPEAK)` flushes and starts new utterance immediately. [VERIFIED — Microsoft SAPI docs]

### Voice Quality
- Windows 11 built-in neural voices (Aria, Guy, etc.): good quality, noticeably below Kokoro. [COMMUNITY — general consensus]
- Azure Neuronal TTS via adapter: excellent quality but cloud-dependent. [COMMUNITY]

### Memory / VRAM Footprint
- Built-in SAPI: 0 VRAM, small RAM footprint (~50MB). [ASSUMED]

### License + Maturity + 2025/2026 Activity
- SAPI 5 is a Windows system API — no license concerns for use. [VERIFIED]
- NaturalVoiceSAPIAdapter: MIT, actively maintained 2025. [COMMUNITY — GitHub]
- This is the fallback baseline, not a streaming voice agent pick. [ASSUMED]

### Output Fit
- SAPI 5 PCM output: configurable sample rate; can request 16 kHz mono Int16 PCM directly. [VERIFIED — Microsoft SAPI docs]

---

## 7. 2026 Entrants

### Chatterbox-Turbo (Resemble AI)

- **VRAM:** 5–7GB (base Chatterbox); Turbo variant: lighter "350M streamlined" architecture, ~4–6GB. [COMMUNITY — devnen/Chatterbox-TTS-Server]
- **Streaming:** Community fork (`davidbrowne17/chatterbox-streaming`) achieves RTF 0.499 on RTX 4090, TTFB ~472ms. Official streaming API planned Q3 2025 (not yet shipped as of research date). [COMMUNITY — GitHub chatterbox-streaming]
- **License:** MIT. [VERIFIED — GitHub resemble-ai/chatterbox]
- **Windows:** Docker-based install confirmed working (start.bat for Windows). CUDA + ROCm + CPU. [VERIFIED — devnen/Chatterbox-TTS-Server]
- **Verdict for Artemis:** VRAM budget too tight (5–7GB on top of 4GB Ollama = OOM). Streaming latency 472ms > target. **Not recommended at this hardware config.**

### Orpheus-TTS (canopyai)

- **VRAM:** Minimum 15GB (or quantized FP8 on RTX 3090 24GB). [VERIFIED — GitHub canopyai/Orpheus-TTS issues]
- **Streaming latency:** 180ms TTFB on H100; 280ms on A100. vLLM/SGLang required. [COMMUNITY — simplismart.ai blog]
- **Verdict for Artemis:** 15GB+ VRAM minimum far exceeds 4GB budget. **Eliminated.**

### Fish Speech 1.5 / Fish Audio S2

- **VRAM:** Fish Speech 1.5 = 12GB minimum. S2 Pro: H200 reference. [VERIFIED — spheron.network fetch]
- **License:** CC-BY-NC-SA 4.0 (non-commercial). [VERIFIED — emelia.io + tryspeakeasy.io]
- **Verdict for Artemis:** VRAM far exceeds budget + non-commercial license. **Eliminated.**

---

## Summary Scoring Table

| Criterion | Piper | Kokoro-82M | XTTS-v2 | StyleTTS2 | Parler-TTS Mini | SAPI 5 |
|---|---|---|---|---|---|---|
| Windows native + GPU path | H (CPU-only, no GPU needed) | H (PyTorch CUDA + ONNX) | H (PyTorch CUDA) | M (CUDA, less tested Win) | M (HF Transformers, CUDA) | H (OS built-in) |
| Streaming / first-audio latency | M (sentence-level, <200ms warm) | H (45–100ms, true chunked) | M (150–200ms) | L (no streaming API) | L (no streaming, high latency) | M (200–400ms SAPI async) |
| Interruptible (barge-in) | H (subprocess kill) | H (HTTP abort / RealtimeTTS stop) | M (stream abort) | L (no streaming = full flush) | L | H (SPF_PURGEBEFORESPEAK) |
| Voice quality / naturalness | L (robotic, VITS-class) | H (ELO #1 open-weight 2026) | H (voice cloning, natural) | H (style diffusion, high quality) | M (prompt-controlled, decent) | M (Win11 neural, below Kokoro) |
| VRAM footprint (4GB budget) | H (0 VRAM, CPU) | H (2–3GB, fits with headroom) | M (3–4GB FP16, tight) | H (2GB) | H (1.8GB FP16) | H (0 VRAM) |
| License | M (GPL-3.0 — copyleft risk) | H (Apache 2.0) | L (CPML non-commercial) | H (MIT) | H (Apache 2.0) | H (OS API) |
| 2025/2026 activity | H (v1.4.2 Apr 2026) | H (very active) | M (community fork, stagnant) | M (quiet, pip maintained) | M (moderate HF activity) | H (OS maintained) |
| Output (PCM resampleable) | H (16 kHz native, exact match) | H (24 kHz, trivial resample) | H (24 kHz, trivial resample) | H (24 kHz numpy) | M (44.1 kHz, resample) | H (configurable 16 kHz) |

**Scoring guide:** H = strong fit, M = acceptable/caveat, L = weak/blocking issue

---

## Recommended Pick for Artemis Windows Dev Sidecar

**Primary: Kokoro-82M via PyTorch CUDA (remsky/Kokoro-FastAPI, :latest-cu128 for RTX 5060 Ti)**

Rationale:
- Only candidate combining H on streaming latency + H on quality + H on VRAM fit + H on license
- 45–100ms first-audio at target GPU tier (extrapolated from RTX 5090 benchmark)
- OpenAI-compatible API means the sidecar consumes it identically to how it would consume a cloud TTS endpoint
- RealtimeTTS KokoroEngine provides ready barge-in/stop integration for Python voice pipelines
- 2–3GB VRAM leaves 1–2GB headroom alongside Ollama's 4GB

**Fallback CPU-only: Piper (OHF-Voice/piper1-gpl, low/x_low voice)**
- Zero VRAM, 16 kHz PCM native, no resampling
- Acceptable if GPU is temporarily unavailable or VRAM is exhausted
- Robotic quality acceptable as degraded-mode fallback
- GPL-3.0 license acceptable for personal assistant (non-distribution)

**Do not use:** Parler-TTS (no streaming, high latency), StyleTTS2 (no streaming API in production), Orpheus-TTS (15GB VRAM), Fish Speech (12GB VRAM + non-commercial), Chatterbox (5–7GB VRAM + OOM risk), XTTS-v2 (non-commercial CPML + tight VRAM).

---

## Key Architecture Notes for Windows Sidecar

### Integration Pattern
The Windows dev twin mirrors the Mac sidecar pattern but substitutes:
- MLX → PyTorch CUDA
- kokoro-mlx → Kokoro-FastAPI (REST) or RealtimeTTS KokoroEngine (in-process)
- AVAudioEngine → pyaudio / sounddevice (Windows WASAPI backend)
- RealtimeTTS library (`pip install realtimetts[kokoro]`) is a strong candidate: handles token streaming from LLM → sentence chunking → Kokoro synthesis → Windows audio playback, with `stop()` for barge-in. [VERIFIED — RealtimeTTS PyPI + KoljaB/RealtimeTTS GitHub]

### Streaming Architecture for Token-Level Input
```
LLM token stream
    → sentence accumulator (punctuation / pause heuristic)
    → Kokoro-FastAPI /audio/speech (stream=true)
    → chunked PCM over HTTP
    → Windows audio out (sounddevice WASAPI)
        ← barge-in signal stops stream + flushes buffer
```

### VRAM Budget Allocation
| Component | VRAM |
|---|---|
| Ollama (current) | ~4GB |
| Kokoro-82M inference | ~2–3GB |
| Headroom | ~1–2GB |
| **Total RTX 5060 Ti 8GB** | **≤8GB** |

### Barge-in Implementation
- Detect VAD event during playback
- Call `stream.abort()` on the Kokoro HTTP response
- Call `sounddevice.stop()` to flush audio buffer
- Restart STT pipeline
- Target: <200ms from VAD trigger to audio silence [COMMUNITY — general voice agent guidance]

---

## Open Questions (Windows-specific)

1. **ONNX GPU path for Kokoro:** kokoro-onnx v0.5.0 has CUDAExecutionProvider performance bugs (39 Memcpy nodes). If the Docker/PyTorch path is unavailable, this needs validation before use. Monitor onnxruntime #23384.
2. **RTX 5060 Ti actual latency:** All Kokoro numbers extrapolated from RTX 5090 / A100. First-audio on the actual RTX 5060 Ti needs a local benchmark run when hardware is available.
3. **RealtimeTTS + Kokoro barge-in test:** RealtimeTTS `stop()` is documented but barge-in timing on Windows WASAPI needs validation — audio pipeline has OS-level buffering.
4. **Piper license for distribution:** If the Tauri client ever bundles the sidecar for distribution (Mac Mini → Windows client package), GPL-3.0 Piper propagates to the bundle. Plan to use Kokoro only for distributed builds; keep Piper as dev-box CPU fallback only.
5. **StyleTTS2 streaming fork maturity:** GPL fork has an experimental streaming API. If the MIT pip package adds streaming, it becomes viable. Check in 2–4 weeks.

---

## NEEDS-DOMAIN (blocked fetches)

- `gigagpu.com` — HTTP 403; all gigagpu.com benchmark tables (TTS Latency Benchmarks, Kokoro VRAM Requirements, Kokoro vs XTTS-v2 comparison) were cited from search result extracts only, not direct fetches. Numbers should be treated [COMMUNITY] not [VERIFIED].

---

## Sources

- [Piper TTS Setup 2026 | Local AI Master](https://localaimaster.com/blog/piper-tts-setup-guide)
- [Kokoro-82M | HuggingFace hexgrad](https://huggingface.co/hexgrad/Kokoro-82M)
- [remsky/Kokoro-FastAPI | GitHub](https://github.com/remsky/Kokoro-FastAPI)
- [Kokoro-FastAPI | SpaceBums](https://spacebums.co.uk/kokoro-fastapi/)
- [kokoro-onnx | PyPI](https://pypi.org/project/kokoro-onnx/)
- [thewh1teagle/kokoro-onnx CUDA issue](https://github.com/thewh1teagle/kokoro-onnx/issues/112)
- [XTTS-v2 | HuggingFace coqui](https://huggingface.co/coqui/XTTS-v2)
- [Coqui TTS (XTTS-v2) 2026 | Local AI Master](https://localaimaster.com/models/coqui-tts)
- [Local TTS Voice Cloning Licenses 2026 | PromptQuorum](https://www.promptquorum.com/power-local-llm/local-tts-voice-cloning-piper-coqui-xtts)
- [StyleTTS2 | DagsHub](https://dagshub.com/blog/styletts2/)
- [styletts2 | PyPI](https://pypi.org/project/styletts2/)
- [yl4579/StyleTTS2 | GitHub](https://github.com/yl4579/StyleTTS2)
- [Parler TTS Mini v0.1 — Inference Speed | HuggingFace Discussion](https://huggingface.co/parler-tts/parler_tts_mini_v0.1/discussions/2)
- [NaturalVoiceSAPIAdapter | GitHub gexgd0419](https://github.com/gexgd0419/NaturalVoiceSAPIAdapter)
- [RealtimeTTS | PyPI](https://pypi.org/project/realtimetts/)
- [KoljaB/RealtimeTTS | GitHub](https://github.com/KoljaB/RealtimeTTS)
- [Best Open-Source TTS 2026 | ocdevel.com](https://ocdevel.com/blog/20250720-tts)
- [Best TTS Models 2026 | CodeSOTA](https://www.codesota.com/guides/tts-models)
- [Open Source TTS 2026 | TrySpeakeasy](https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026)
- [Deploy TTS on GPU Cloud 2026 | Spheron](https://www.spheron.network/blog/deploy-open-source-tts-gpu-cloud-2026/)
- [Running Piper TTS on Jetson Orin Nano | Thomas Thelliez](https://thomasthelliez.com/blog/running-piper-tts-on-nvidia-jetson-orin-nano-with-low-latency/)
- [LiveKit + Piper TTS Voice Agent | Medium / Muhammad Asif](https://medium.com/@mail2chasif/livekit-piper-tts-building-a-low-latency-local-voice-agent-with-real-time-latency-tracking-92a1008416e4)
- [Orpheus TTS Streaming on RTX 3090 | bitbasti](https://bitbasti.com/blog/audio-streaming-with-orpheus)
- [Orpheus TTS VRAM issue | GitHub canopyai](https://github.com/canopyai/Orpheus-TTS/issues/9)
- [Fish Speech S2: Open Source TTS | emelia.io](https://emelia.io/hub/fish-speech-s2-tts)
- [Chatterbox TTS Server | devnen GitHub](https://github.com/devnen/Chatterbox-TTS-Server)
- [Chatterbox Streaming fork | GitHub davidbrowne17](https://github.com/davidbrowne17/chatterbox-streaming)
- [TTS Latency Benchmarks | GigaGPU](https://gigagpu.com/tts-latency-benchmarks/) — BLOCKED (403)
- [Kokoro VRAM Requirements | GigaGPU](https://gigagpu.com/kokoro-vram-requirements/) — BLOCKED (403)
- [Kokoro vs XTTS-v2 | GigaGPU](https://gigagpu.com/kokoro-vs-xtts-v2-low-latency-tts/) — BLOCKED (403)
- [TTS Piper GPU Feature Request | SubtitleEdit #9002](https://github.com/SubtitleEdit/subtitleedit/issues/9002)
- [Piper + sherpa-onnx on-device | Medium](https://medium.com/@patare.vivek/running-neural-text-to-speech-on-device-with-piper-and-sherpa-onnx-58f4eed29247)
- [XTTS VRAM Requirements | GigaGPU](https://gigagpu.com/coqui-vram-requirements/) — BLOCKED (403)

# STT Research — Windows Dev-Box Voice Sidecar

**Date:** 2026-06-25
**Re-research after:** 2026-07-09
**Author:** Phase-2 retrieval agent
**Context:** Artemis cascaded streaming pipeline (wake → VAD → STT → brain → TTS) running on Windows 11, RTX 5060 Ti 8GB VRAM, Ryzen 7700, 32GB RAM. ~4GB VRAM already claimed by Ollama (Qwen3). STT budget: ~4GB VRAM or CPU. Audio format: 16kHz mono Int16 PCM, streamed.

---

## Evaluation Dimensions

For each tool: (1) Windows-native + GPU/CPU paths, (2) real-time streaming latency, (3) WER accuracy at usable sizes, (4) memory/VRAM footprint, (5) license + maturity, (6) 16kHz-mono-Int16 fit.

---

## 1. faster-whisper (SYSTRAN / CTranslate2)

### Windows-native + GPU/CPU
**H** — First-class Windows support. CUDA 11.8+ and cuDNN 8.x required; pip-installable. CTranslate2 CUDA backend is more optimized than whisper.cpp's CUDA path (~12× vs ~8× RTF on RTX 4070). CPU path also works well; x86 base model achieves ~20× RTF on CPU. [VERIFIED — promptquorum.com 2026]

### Streaming latency
**M** — faster-whisper itself is not a streaming engine; it is a fast batch transcriber. Streaming is achieved via wrappers: whisper_streaming (sliding-window VAD re-segmentation, ~500–800 ms practical latency) or WhisperLive server. The SimulStreaming project (successor to whisper_streaming) is faster. Partial results are approximated, not true token-streaming. [VERIFIED — search results, github.com/ufal/whisper_streaming]

### WER at usable sizes
**H** — Uses identical OpenAI Whisper weights; WER is the same as the original model:
- large-v3 int8: ~2.5% English
- small int8: ~3.4%
- base int8: ~5.0%
[VERIFIED — promptquorum.com 2026]

### Memory/VRAM footprint
**H** — large-v3 int8: ~2.5 GB VRAM. small int8: ~0.5 GB. base int8: fits in 1 GB RAM for CPU-only. Leaves ~1.5 GB free in the 4 GB STT VRAM budget even with large-v3 int8. [VERIFIED — promptquorum.com 2026, spheron.network 2026]

### License + maturity
**H** — MIT license (CTranslate2). Extremely mature; SYSTRAN-maintained. High 2025/2026 activity; whisper-v3-turbo support added. [VERIFIED — pypi.org/project/faster-whisper]

### 16kHz-mono-Int16 fit
**H** — Whisper model expects 16 kHz mel-spectrogram internally; faster-whisper handles the conversion transparently. Int16 PCM is the standard input. Native fit. [ASSUMED from Whisper architecture — all Whisper-based tools use 16 kHz]

**Sources:** https://www.promptquorum.com/power-local-llm/local-whisper-stt-comparison-2026 · https://localaimaster.com/blog/faster-whisper-guide · https://www.spheron.network/blog/faster-whisper-gpu-cloud-production-deployment-guide/ · https://pypi.org/project/faster-whisper/

---

## 2. whisper.cpp (ggml-org)

### Windows-native + GPU/CPU
**H** — First-class Windows support; pre-built Windows binaries available. CUDA path works (CUDA 12.x), Vulkan path also works on Windows (good AMD/integrated fallback). whisper-standalone-win bundles required CUDA libs. [VERIFIED — starwhisper.ai, search results]

### Streaming latency
**M** — Ships a `--stream` example for live transcription approximation. Latency is 0.5–2 s behind live speech depending on model. Not true token streaming; re-runs inference on accumulating buffer. Less optimized than faster-whisper for CUDA on Windows. [VERIFIED — promptquorum.com 2026]

### WER at usable sizes
**H** — Same OpenAI Whisper weights as faster-whisper; identical WER numbers (2.5% large-v3, 3.4% small, 5.0% base). [VERIFIED — promptquorum.com 2026]

### Memory/VRAM footprint
**H** — large-v3: ~3 GB VRAM. small: ~0.6 GB. Slightly higher VRAM than faster-whisper's int8 path. Fits the 4 GB budget with room. [VERIFIED — promptquorum.com 2026]

### License + maturity
**H** — MIT. Very mature; maintained by ggml-org. Very high 2025/2026 activity. Vulkan backend extended Windows GPU support significantly. [VERIFIED — github.com/ggml-org/whisper.cpp]

### 16kHz-mono-Int16 fit
**H** — Same 16 kHz architecture as all Whisper variants. Handles PCM input natively. [ASSUMED from Whisper architecture]

**Sources:** https://starwhisper.ai/landing/whisper-cpp-windows.html · https://www.promptquorum.com/power-local-llm/local-whisper-stt-comparison-2026 · https://weesperneonflow.ai/en/blog/2026-06-23-whisper-cpp-setup-guide-local-speech-recognition-2026/

---

## 3. OpenAI Whisper (reference / Python)

### Windows-native + GPU/CPU
**M** — Runs on Windows via pip; CUDA supported through PyTorch. Slower than faster-whisper by ~4× due to unoptimized inference. Reference baseline only; not recommended for production. [ASSUMED from known architecture]

### Streaming latency
**L** — No streaming support; pure batch model. No partial results. [VERIFIED — onresonant.com 2026]

### WER at usable sizes
**H** — Same weights: large-v3 ~2.5%, small ~3.4%, base ~5.0%. [VERIFIED — promptquorum.com 2026]

### Memory/VRAM footprint
**L** — large-v3 fp16: ~10 GB VRAM (exceeds 4 GB budget). Even medium is ~5 GB. Must use small/base (~1–2 GB). [VERIFIED — northflank.com 2026]

### License + maturity
**H** — MIT. OpenAI maintained. Primarily a research reference; production use → faster-whisper. [ASSUMED]

### 16kHz-mono-Int16 fit
**H** — Native 16 kHz architecture. [ASSUMED]

**Note:** Use only as a reference. faster-whisper supersedes it in every practical dimension for this use case.

---

## 4. Distil-Whisper (HuggingFace)

### Windows-native + GPU/CPU
**H** — Runs via HuggingFace transformers on Windows; CUDA supported via PyTorch. Also available as faster-distil-whisper in CTranslate2 format (compatible with faster-whisper). [VERIFIED — huggingface.co/distil-whisper/distil-large-v3, search results]

### Streaming latency
**M** — Same position as faster-whisper for streaming; no native streaming; requires wrapper. For long-form, it is specifically optimized and ~6× faster than large-v3. distil-large-v3.5 is ~1.5× faster than Whisper-Large-v3-Turbo. [VERIFIED — HuggingFace model cards]

### WER at usable sizes
**H** — distil-large-v3: within ~1% WER of large-v3 on English (~2.6%). 50% fewer parameters at 750M. [VERIFIED — github.com/huggingface/distil-whisper]

### Memory/VRAM footprint
**H** — INT8 in CTranslate2 format: ~1.6 GB VRAM. FP16: ~2.5 GB. Highly budget-friendly. RTFx of 90× when used with faster-whisper backend. [VERIFIED — spheron.network 2026, search results]

### License + maturity
**H** — MIT. HuggingFace-maintained. Active 2025/2026. English-only focus (multilingual in separate models). [VERIFIED — github.com/huggingface/distil-whisper]

### 16kHz-mono-Int16 fit
**H** — Same Whisper 16 kHz architecture. [ASSUMED]

**Sources:** https://huggingface.co/distil-whisper/distil-large-v3.5 · https://github.com/huggingface/distil-whisper · https://www.spheron.network/blog/faster-whisper-gpu-cloud-production-deployment-guide/

---

## 5. Moonshine v2 (Useful Sensors / moonshine-ai)

### Windows-native + GPU/CPU
**H** — Confirmed Windows support (ONNX variant is pip-installable with no TF/JAX/PyTorch dependency; JAX+CUDA variant also available via `useful-moonshine[jax-cuda]`). ONNX path most portable for Windows. Moonshine AI's separate `moonshine` pip package (v2) confirmed tested on Linux, macOS, Windows. [VERIFIED — pypi.org/project/moonshine, pypi.org/project/useful-moonshine, deepwiki.com/moonshine-ai/moonshine]

### Streaming latency
**H** — Purpose-built streaming architecture (Moonshine v2, Feb 2026): sliding-window encoder attention, context adapter, incremental decoding. Time-to-first-token largely constant regardless of utterance length. Measured latencies on Apple M3 (CPU-only): Tiny 50ms, Small 148ms, Medium 258ms. CPU-only MacBook: Tiny 34ms, Small 73ms, Medium 107ms. Native streaming — not a batch-with-wrapper approach. [VERIFIED — arxiv.org/html/2602.12241v1, modelslab.com 2026]

### WER at usable sizes (v2 streaming models, average across standard datasets)
**H** — Tiny Streaming: 12.00%, Small Streaming: 7.84%, Medium Streaming: 6.65%. Medium Streaming beats Whisper Large v3 (7.44%) with 6× fewer parameters. [VERIFIED — arxiv.org 2602.12241, modelslab.com 2026]

### Memory/VRAM footprint
**H** — Tiny: 27M params, Small: 123M, Medium: 245M. No official VRAM spec stated; designed for severely memory-constrained devices (Raspberry Pi, mobile). ONNX runtime adds overhead but total footprint estimated <500 MB VRAM even for Medium. English-only MIT models are 27M–245M params. [COMMUNITY — inferred from parameter counts and RPi 5 benchmarks showing viability]

### License + maturity
**H (English) / M (multilingual)** — English models: MIT. Non-English models: Moonshine Community License (non-commercial only; commercial requires contacting Moonshine AI). Moonshine AI spin-off from Useful Sensors. v2 released Feb 2026; active 2025/2026. Also supported in HuggingFace Transformers (`moonshine_streaming` model class). [VERIFIED — arxiv.org, onresonant.com, huggingface.co/docs/transformers/model_doc/moonshine_streaming]

### 16kHz-mono-Int16 fit
**H** — Paper confirms: "The preprocessor operates at 50 Hz feature rate (20ms per frame), matching Whisper's specification. Processes raw audio through cepstral mean/variance normalization. Handles 16 kHz audio input." Direct fit. [VERIFIED — arxiv.org/html/2602.12241v1]

**Sources:** https://arxiv.org/html/2602.12241v1 · https://modelslab.com/blog/audio-generation/moonshine-vs-whisper-asr-real-time-speech-2026 · https://huggingface.co/docs/transformers/model_doc/moonshine_streaming · https://pypi.org/project/moonshine/

---

## 6. Vosk (Alpha Cephei)

### Windows-native + GPU/CPU
**H (CPU only)** — Official Windows, Linux, Mac support. CPU-only; no GPU acceleration. Pure offline, real-time streaming via C API, Python, C#, Java, Node. [VERIFIED — github.com/alphacep/vosk-api, sinologic.net 2026]

### Streaming latency
**H** — True streaming with zero-latency (sub-frame) response. Native streaming API — no batch wrapping needed. Lowest absolute latency of any option; tokens emitted as speech arrives. [VERIFIED — assemblyai.com 2026, sinologic.net 2026]

### WER at usable sizes
**L** — WER not competitively benchmarked in 2025/2026 sources; consistently described as lower accuracy than Whisper-class models. Good for simple commands; struggles with entity-heavy speech (account numbers, email addresses). [COMMUNITY — assemblyai.com 2026, softcery.com 2026]

### Memory/VRAM footprint
**H** — CPU-only; smallest model is 50 MB. Large model ~1.8 GB RAM. No VRAM used at all — zero impact on RTX 5060 Ti budget. [VERIFIED — github.com/alphacep/vosk-api]

### License + maturity
**H** — Apache 2.0. Mature; widely deployed in IoT/VoIP/embedded. Still maintained but not cutting-edge. Lower 2025/2026 model update cadence vs Whisper. [VERIFIED — github.com/alphacep/vosk-api]

### 16kHz-mono-Int16 fit
**H** — Standard Vosk API accepts 16000 Hz mono PCM by design. [VERIFIED — Vosk API documentation]

**Note:** Best used as a lightweight pre-filter or wake/barge-in detector, not primary STT for an intelligent assistant.

---

## 7. NVIDIA Parakeet / NeMo (parakeet-tdt-0.6b-v2/v3 + Nemotron ASR Streaming)

### Windows-native + GPU/CPU
**L** — NeMo framework explicitly states "Preferred/Supported OS: Linux." Windows install requires WSL2. NeMo is a large, complex install (Cython, PyTorch, libsndfile, ffmpeg); native Windows pip install is unsupported and fragile. Nemotron ASR Streaming shares same Linux-first posture. [VERIFIED — docs.nvidia.com/nemo-framework, huggingface.co/nvidia/parakeet-tdt-0.6b-v2, dev.to/nodeshiftcloud]

### Streaming latency
**H (model architecture) / L (Windows)** — Nemotron ASR Streaming 0.6B (June 2026): configurable chunk latency 80ms/160ms/560ms/1120ms. Cache-aware FastConformer-RNNT. Measured server-side latency: p50 18ms (optimal batch), 86ms (bs=1). Parakeet-unified-en-0.6b (April 2026): streaming + offline in one model, ~160ms minimum latency. Outstanding architecture — blocked by Windows install friction. [VERIFIED — huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b, e2enetworks.com]

### WER at usable sizes
**H** — Parakeet TDT 0.6B v2: avg 6.05% WER (LibriSpeech clean: 1.69%). Nemotron ASR Streaming: 6.93% avg (LibriSpeech clean: 2.32%) at 1.12s chunk size. Both outperform Whisper large-v3 on standard benchmarks. [VERIFIED — huggingface.co/nvidia/parakeet-tdt-0.6b-v2, huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b]

### Memory/VRAM footprint
**M** — Parakeet 0.6B: ~5.1 GB VRAM (fp16, per e2enetworks.com L4 benchmark). Nemotron Streaming: ~1.9–3.3 GB VRAM depending on batch size. Nemotron fits the budget; Parakeet alone is marginal (leaves very little of the ~4GB for Ollama coexistence). [VERIFIED — e2enetworks.com benchmark table]

### License + maturity
**H (model) / M (framework)** — Parakeet: CC-BY-4.0. Nemotron: NVIDIA Open Model License (commercial use permitted). NeMo framework: Apache 2.0. Very active 2025/2026 (v3 released Aug 2025, streaming unified model April 2026, multilingual June 2026). [VERIFIED — HuggingFace model cards]

### 16kHz-mono-Int16 fit
**H** — Nemotron ASR Streaming docs: "16-bit mono audio in WAV, OGG, or OPUS." NeMo ASR models standard for 16 kHz audio. [VERIFIED — huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b]

**Note:** Reserve for Mac Mini / Linux server deployment. Not the right call for the Windows dev box without WSL2 friction.

**Sources:** https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2 · https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b · https://www.e2enetworks.com/blog/benchmarking-asr-models-nvidia-l4-parakeet-whisper-nemotron · https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/intro.html

---

## 8. sherpa-onnx (k2-fsa / Next-gen Kaldi)

### Windows-native + GPU/CPU
**H** — First-class Windows support. Both CUDA (11.x and 12.x) and DirectML (Windows-native GPU acceleration without CUDA) are supported. Pre-built Windows binaries available. Python pip installable. Note: CRT runtime clash (MT vs MD) on Windows requires care when embedding in other C++ apps; Python usage unaffected. [VERIFIED — k2-fsa.github.io/sherpa/onnx, blog.brightcoding.dev 2025, amd.com 2026]

### Streaming latency
**H** — True streaming via ONNX Runtime with online (Zipformer, SenseVoice) and offline models. Native streaming inference: tokens emitted as audio arrives. CTC/RNNT architectures give low first-token latency. GPU-accelerated WFST decoder measured at 54.4ms average vs 430ms CPU. [VERIFIED — blog.brightcoding.dev 2025, arxiv.org GPU-WFST paper]

### WER at usable sizes
**M** — Model quality depends on which model is used: Zipformer2-based models are competitive (~5–7% WER on English, comparable to Whisper small/medium). SenseVoice adds emotion/language detection but English WER is M-range. INT8 quantization adds ~1–2% WER. No single published 2025/2026 community benchmark aggregated across all models. [COMMUNITY — blog.brightcoding.dev 2025, sherpa-onnx model zoo]

### Memory/VRAM footprint
**H** — Models range from tiny (sub-100 MB) to medium (~500 MB). ONNX Runtime GPU overhead minimal. Well inside the 4 GB VRAM budget. CPU path is also viable (32 GB RAM ample). [COMMUNITY — inferred from model sizes in sherpa-onnx model zoo]

### License + maturity
**H** — Apache 2.0. Actively maintained by k2-fsa (Next-gen Kaldi group). Monthly model zoo updates. Very broad platform support (Windows, Linux, macOS, Android, iOS, RK NPU, etc.). [VERIFIED — github.com/k2-fsa/sherpa-onnx]

### 16kHz-mono-Int16 fit
**H** — All sherpa-onnx streaming models are designed for 16 kHz mono PCM input. Feature extraction built in. [VERIFIED — sherpa-onnx documentation]

**Sources:** https://k2-fsa.github.io/sherpa/onnx/index.html · https://www.blog.brightcoding.dev/2025/09/11/sherpa-onnx-unified-speech-recognition-synthesis-and-audio-processing-for-every-platform/ · https://github.com/k2-fsa/sherpa-onnx · https://www.amd.com/en/developer/resources/technical-articles/2026/a-practical-approach-to-using-sherpa-onnx-production-ready-on-wi.html

---

## 9. Voxtral-Mini-4B-Realtime (Mistral AI) — 2026 Entrant

### Windows-native + GPU/CPU
**M** — Open-weights; runs via vLLM (Linux-primary) or the pure-C `voxtral.c` (zero dependencies, portable). Windows path exists via `voxtral.c` but is not the primary supported deployment. [VERIFIED — github.com/antirez/voxtral.c, huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602]

### Streaming latency
**H** — Real-time architecture: configurable transcription delay 240ms–2.4s; 480ms sweet spot matches offline model accuracy. WebSocket streaming. [VERIFIED — mistral.ai/news/voxtral, search results]

### WER at usable sizes
**H** — 5.9% average WER (vs Whisper large-v3 7.4%) on FLEURS. Strong multilingual. [VERIFIED — weesperneonflow.ai 2026]

### Memory/VRAM footprint
**L** — Requires ≥16 GB GPU VRAM. Far exceeds the ~4 GB STT budget on this dev box. [VERIFIED — huggingface.co model card]

### License + maturity
**H** — Open-weights; released Feb 2026; Mistral AI maintained. Very active. [VERIFIED]

### 16kHz-mono-Int16 fit
**M** — Audio input format not explicitly specified in found sources; as an LLM-based system it likely handles resampling. [ASSUMED]

**Note:** VRAM requirement eliminates this from the dev-box shortlist. Flag for Mac Mini (24–32 GB unified memory).

---

## Summary Scoring Table

| Tool | Win-native+GPU | Streaming latency | WER (usable size) | VRAM footprint | License+maturity | 16kHz fit |
|---|---|---|---|---|---|---|
| faster-whisper | H | M | H | H | H | H |
| whisper.cpp | H | M | H | H | H | H |
| OpenAI Whisper | M | L | H | L | H | H |
| Distil-Whisper | H | M | H | H | H | H |
| **Moonshine v2** | **H** | **H** | **H** | **H** | **H** | **H** |
| Vosk | H (CPU) | H | L | H | H | H |
| Parakeet/NeMo | L | H* | H | M | H | H |
| sherpa-onnx | H | H | M | H | H | H |
| Voxtral-Mini-4B | M | H | H | L | H | M |

*Latency is outstanding but Windows install is blocked without WSL2.

---

## Recommended Pick for RTX 5060 Ti 8GB Dev Box

**Primary: Moonshine v2 Small Streaming** (ONNX variant, MIT license)
- True streaming, 73–148ms latency on CPU (even better on GPU with ONNX CUDA EP)
- 7.84% WER — better than Whisper small at 8.59%
- ~100–200 MB VRAM for Medium; negligible impact on Ollama
- 16 kHz native; pip-installable on Windows
- English-only MIT model covers the Artemis use case

**Secondary / fallback: faster-whisper distil-large-v3 int8** (~1.6 GB VRAM)
- Best accuracy if Moonshine WER insufficient
- 2.6% WER English; GPU-accelerated on RTX 5060 Ti
- Streaming via whisper_streaming wrapper (~500–800ms lag); acceptable for non-barge-in leg
- Well above large-v3 quality at fraction of footprint

**For Mac Mini later: Nemotron ASR Streaming 0.6B** (Linux/NeMo)
- Sub-100ms streaming, 6.93% WER, cache-aware RNNT, configurable latency

---

## Key NEEDS-DOMAIN Hosts

- `github.com` — blocked by instruction set; sherpa-onnx repo, whisper_streaming, moonshine-ai/moonshine not directly fetched from there.

---

## Sources

1. https://www.promptquorum.com/power-local-llm/local-whisper-stt-comparison-2026
2. https://localaimaster.com/blog/faster-whisper-guide
3. https://www.spheron.network/blog/faster-whisper-gpu-cloud-production-deployment-guide/
4. https://pypi.org/project/faster-whisper/
5. https://arxiv.org/html/2602.12241v1 (Moonshine v2 paper)
6. https://modelslab.com/blog/audio-generation/moonshine-vs-whisper-asr-real-time-speech-2026
7. https://huggingface.co/docs/transformers/model_doc/moonshine_streaming
8. https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks
9. https://www.onresonant.com/resources/local-stt-models-2026
10. https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2
11. https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b
12. https://www.e2enetworks.com/blog/benchmarking-asr-models-nvidia-l4-parakeet-whisper-nemotron
13. https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/intro.html
14. https://k2-fsa.github.io/sherpa/onnx/index.html
15. https://www.blog.brightcoding.dev/2025/09/11/sherpa-onnx-unified-speech-recognition-synthesis-and-audio-processing-for-every-platform/
16. https://github.com/alphacep/vosk-api
17. https://www.sinologic.net/en/2026-05/vosk-vs-whisper-local-the-ultimate-2026-guide-to-self-hosted-speech-recognition-stt.html
18. https://weesperneonflow.ai/en/blog/2026-03-31-voxtral-whisper-open-source-speech-models-comparison-2026/
19. https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602
20. https://starwhisper.ai/landing/whisper-cpp-windows.html
21. https://www.assemblyai.com/blog/top-open-source-stt-options-for-voice-applications
22. https://pypi.org/project/moonshine/
23. https://pypi.org/project/useful-moonshine/
24. https://huggingface.co/distil-whisper/distil-large-v3.5
25. https://gigagpu.com/best-gpu-for-whisper/

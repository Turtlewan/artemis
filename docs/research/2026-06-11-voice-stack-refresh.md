# Voice Stack Refresh — Artemis M5 (Apple Silicon / Mac Mini)

**Scope:** Local-only voice pipeline components for Artemis M5.
**Research date:** 2026-06-11
**Researcher:** claude-code-guide agent (claude-sonnet-4-6)
**Training cutoff:** August 2025 — all findings below verified via live web search June 2026.
**Confidence key:** HIGH = multiple independent corroborating sources; MED = single strong source or extrapolation; LOW = inferred, verify before committing.

---

## Recommendation Table

| Component | Pick | Runner-up | Rationale |
|---|---|---|---|
| STT (real-time) | **Parakeet MLX** (parakeet-tdt-0.6b-v2) | Apple SpeechAnalyzer | Sub-100ms, 6.05% WER English, 50x real-time on M-series. SpeechAnalyzer wins on multilingual and zero-install but loses on English accuracy + latency. |
| TTS | **Kokoro-82M via mlx-audio** | CosyVoice3 (MLX) | 100ms latency on M4, 82M params, 54 voices, pure MLX (no PyTorch), streaming-capable. Qwen3-TTS best-quality but CUDA-first — Apple Silicon path immature. CosyVoice3 strong runner-up if voice cloning is required. |
| Speaker diarization | **FluidAudio / Sortformer (CoreML)** | speech-swift (Soniqo) | Native Swift SPM package; CoreML Sortformer streaming; 4-speaker limit fine for Artemis (owner + occasional guests); 100ms frame updates. speech-swift alternative if Python-side preferred. |
| EOU / Turn detection | **SmartTurn v3.2** (Pipecat, open-source) | Krisp Turn-Taking v2 | Audio-only, OSS, Pipecat-native; 200ms VAD gate + 3s force-trip. Krisp v2 has better F1/latency but is closed-source SDK. |
| Orchestration | **Pipecat v1.3+** (Python, local) | bare asyncio | Multi-agent pipeline bus, Swift iOS/macOS SDK for sidecar, mlx-audio frame processor, SmartTurn built-in. Wyoming excluded per prior decision. |

---

## 1. STT — Parakeet MLX vs Apple SpeechAnalyzer

### Apple SpeechAnalyzer

Introduced at WWDC 2025 (macOS 26 / iOS 26). Developer-accessible framework with no model download required — model is OS-bundled.

- **Latency:** 150–400ms in real-world testing (not officially published by Apple). MED confidence — sourced from dicta.to benchmark of ~13,000 real recordings. [Source: dicta.to "Apple vs Whisper vs Parakeet vs Qwen3" 2026](https://dicta.to/blog/speech-to-text-engine-comparison-mac-2026/)
- **Accuracy (English):** Comparable to Whisper Large v3; does **not** beat Parakeet on English disfluent speech. Wins decisively on French, Spanish, German, Italian (4.0% WER Italian — best on-device number on any platform). MED confidence. [Source: dicta.to](https://dicta.to/blog/speech-to-text-engine-comparison-mac-2026/)
- **Streaming:** Supported via SpeechTranscriber API; concurrency-friendly async API. HIGH confidence. [Source: WWDC25 session 277; Apple Developer Forums thread 819555](https://developer.apple.com/videos/play/wwdc2025/277/)
- **Integration:** Native Swift/SwiftUI. No Python dependency.
- **Risk:** Tied to macOS 26+; WER on English is demonstrably worse than Parakeet.

### Parakeet MLX (parakeet-tdt-0.6b-v2)

NVIDIA's FastConformer Parakeet model ported to Apple MLX by the community (senstella/parakeet-mlx, EliFuzz/parakeet-mlx). 600M param model.

- **Latency:** Sub-100ms for real-time chunks; 50x faster than real-time on M3+ chips. ~500ms average per sample in MLX vs ~200ms CoreML Whisper — but the frame-level streaming latency is far lower because it processes audio in small chunks continuously. MED confidence. [Source: parakeet-mlx GitHub + dicta.to blog](https://github.com/senstella/parakeet-mlx)
- **Accuracy (English):** 6.05% WER on standard benchmarks; wins in 3 of 5 languages in disfluent speech tests; NVIDIA Canary Qwen 2.5B does reach 5.63% WER but is a heavier hybrid. HIGH confidence. [Source: dicta.to benchmark](https://dicta.to/blog/speech-to-text-engine-comparison-mac-2026/)
- **Streaming:** Real-time streaming context with configurable left/right context frames. HIGH confidence. [Source: EliFuzz/parakeet-mlx README](https://github.com/EliFuzz/parakeet-mlx)
- **Integration:** Python (MLX). Needs IPC bridge to Swift sidecar — see §5.
- **Caveat for Artemis:** Primary language = English. Parakeet wins here. If multilingual dictation becomes a requirement later, revisit SpeechAnalyzer.

### STT Recommendation: **Parakeet MLX**

Runner-up: Apple SpeechAnalyzer (adopt if macOS 26 minimum acceptable, multilingual needed, or zero-install footprint required)

---

## 2. TTS — Kokoro / Qwen3-TTS / CosyVoice3 / mlx-audio

### Kokoro-82M (via mlx-audio or kokoro-mlx)

- **Parameters:** 82M — smallest in this comparison.
- **Latency:** ~100ms first-audio on M4 GPU; RTF ~0.17 (6x faster than real-time). HIGH confidence. [Source: dTelecom blog M4 benchmark](https://blog.dtelecom.org/we-replaced-elevenlabs-with-kokoro-tts-on-an-m4-gpu-latency-fell-to-100-ms-and-tts-cost-nearly-68bcc3313cdd)
- **Quality:** "Neural" quality — breathing, natural pausing — without heavy compute; 8 languages, 54 voice presets. Not top-tier expressiveness.
- **Voice cloning:** No built-in zero-shot cloning (fixed voice presets only). LOW–MED confidence.
- **MLX support:** Native MLX implementation (gabrimatic/kokoro-mlx); no PyTorch/transformers dependency. Also in mlx-audio library. HIGH confidence. [Source: GitHub gabrimatic/kokoro-mlx](https://github.com/gabrimatic/kokoro-mlx)
- **Streaming:** Gapless streaming over persistent audio stream in MLX implementation. HIGH confidence.

### Qwen3-TTS (Alibaba, mlx-audio port)

- **Parameters:** 1.7B (Qwen3-TTS-12Hz-1.7B-CustomVoice autoregressive). Much heavier than Kokoro.
- **Streaming latency:** 97ms first packet via 12Hz tokenizer. HIGH confidence. [Source: Qwen3-TTS Technical Report arxiv 2601.15621](https://arxiv.org/abs/2601.15621)
- **Quality:** Lowest WER of any open TTS model; excellent expressiveness and voice design. HIGH confidence.
- **Voice cloning:** Built-in zero-shot voice cloning. HIGH confidence. [Source: kapi2800/qwen3-tts-apple-silicon](https://github.com/kapi2800/qwen3-tts-apple-silicon)
- **Apple Silicon status:** Community MLX ports exist (suckerfish/qwen3-tts-mlx, Ak-sys-sh/qwen3-tts-apple-silicon) but the model was released CUDA-first (Jan 2026); Apple Silicon performance is notably slower than CUDA. AMD Radeon 8060S outperforms M3 Max on this autoregressive model. MED confidence. [Source: tinycomputers.io three-machine benchmark](https://tinycomputers.io/posts/the-real-cost-of-running-qwen-tts-locally-three-machines-compared.html)
- **Verdict for Artemis:** Best quality but Apple Silicon is second-class today. Re-evaluate in 3–6 months as MLX optimization matures.

### CosyVoice3 (FunAudioLLM, via mlx-audio / Soniqo)

- **Release:** December 15, 2025. 0.5B params (CosyVoice2-0.5B variant used for local inference).
- **Architecture:** LLM token gen + DiT flow-matching + HiFi-GAN vocoder; 24 kHz output.
- **Latency:** RTF ~0.5 on M2 Max (2x faster than real-time). MED confidence. [Source: Soniqo CosyVoice3 guide](https://soniqo.audio/guides/cosyvoice)
- **Quality:** 3.25% WER — best intelligibility in class; strong naturalness and prosody. HIGH confidence.
- **Voice cloning:** Zero-shot from 3-second sample; cross-lingual cloning; emotion tags. HIGH confidence.
- **MLX support:** Ships via Soniqo (speech-swift) and CosyVoice3 Soniqo MLX guide. 4-bit/8-bit quantization variants. HIGH confidence.
- **Languages:** 9 languages + 18 Chinese dialects.
- **Verdict for Artemis:** Strong runner-up, especially if voice-cloning becomes a Milestone requirement. More compute than Kokoro but properly MLX-optimized.

### TTS Recommendation: **Kokoro-82M (mlx-audio)**

If voice cloning is required: **CosyVoice3 (MLX)**. Qwen3-TTS deferred until Apple Silicon MLX path matures.

---

## 3. Speaker Diarization / Speaker-ID

### FluidAudio (FluidInference) — Sortformer CoreML

- **What it is:** Native Swift SPM package exposing CoreML-compiled NVIDIA Sortformer for streaming diarization. Targets macOS/iOS. [Source: FluidInference/FluidAudio GitHub](https://github.com/FluidInference/FluidAudio); [HuggingFace: FluidInference/diar-streaming-sortformer-coreml](https://huggingface.co/FluidInference/diar-streaming-sortformer-coreml)
- **Diarization options in FluidAudio:** LS-EEND (default streaming, up to 10 speakers, 100ms updates, 900ms preview), Sortformer (secondary streaming, up to 4 speakers, better speaker-identity stability), Pyannote 3.1 pipeline (offline, classic multi-stage, slowest).
- **For Artemis:** Sortformer's 4-speaker limit is fine (owner + occasional guests). Speaker identity stability is the priority for "is this the owner" use case. HIGH confidence.
- **Integration:** Swift SPM; pure on-device CoreML; no Python. Ideal for the Swift sidecar.

### speech-swift (Soniqo) — Python MLX path

- **What it is:** Swift + Python hybrid toolkit; Pyannote 3.1 + WeSpeaker ResNet34 embeddings + Silero VAD v5; all via MLX. [Source: soniqo/speech-swift GitHub](https://github.com/soniqo/speech-swift)
- **Performance:** WeSpeaker embedding ~25ms per segment on M2 Max; Silero VAD ~40µs per chunk. HIGH confidence.
- **Integration:** Sits on the Python MLX side, not the Swift sidecar. Good if diarization stays in the Python brain process.

### Speaker-ID Recommendation: **FluidAudio / Sortformer (CoreML)** in the Swift sidecar

Runner-up: speech-swift (Soniqo) if the diarization logic belongs in the Python brain.

Note: Neither provides speaker enrollment / verification out of the box — Artemis will need to build a small owner-voice embedding store on top of whichever library is chosen. This is the primary open question (see §6).

---

## 4. End-of-Utterance / Turn Detection

### SmartTurn (Pipecat, open-source)

- **What it is:** Audio-only, open-source EOU model by Pipecat team. Current release: SmartTurn v3.2. [Source: Pipecat SmartTurn documentation; krisp.ai turn-taking blog](https://krisp.ai/blog/turn-taking-for-voice-ai/)
- **Mechanism:** 200ms VAD silence gate (Silero), then SmartTurn model evaluates turn completion; 3s silence forces trip. Configurable parameters.
- **Integration:** Native Pipecat component; SmartTurn runs inside the Pipecat Python process. HIGH confidence.
- **Limitation:** Single audio modality; no visual or linguistic context by default (SmartTurn Multimodal announced Jan 2026 but not yet stable).

### Krisp Turn-Taking v2

- **What it is:** Closed-source SDK from Krisp; hierarchical audio model; 6M weights; integrated with Pipecat via `krisp-viva` plugin. [Source: krisp.ai/blog/krisp-turn-taking-v2-voice-ai-viva-sdk/](https://krisp.ai/blog/voice-ai-turn-taking-interruption-prediction/)
- **Performance:** 69.3% F1; median 36ms latency on samples with clear endpoints; better noise resilience than SmartTurn. MED confidence.
- **Concern:** Proprietary; licensing cost unknown for a personal assistant project.

### EOU Recommendation: **SmartTurn v3.2**

Runner-up: Krisp Turn-Taking v2 (if noise robustness becomes a problem and licensing is acceptable).

---

## 5. Integration Notes — Swift Sidecar + MLX Python Pipeline

### Architecture pattern

The Artemis M5 design is: **Swift sidecar** (audio capture, VAD, speaker-ID, TTS playback) bridging over IPC (Unix domain socket or XPC) to a **Python brain** (Pipecat pipeline, Parakeet STT, LLM, SmartTurn). This is a validated pattern mid-2026.

Evidence:
- `kwindla/macos-local-voice-agents` demonstrates Pipecat + Silero VAD + mlx-whisper running locally on macOS. MED confidence. [Source: GitHub kwindla/macos-local-voice-agents](https://github.com/kwindla/macos-local-voice-agents)
- Pipecat v1.3.0 (released May 28, 2026) ships a multi-agent framework with sidecar code-assistant and hardware-controller patterns. HIGH confidence. [Source: pipecat-ai GitHub releases](https://github.com/pipecat-ai/pipecat/releases)
- Pipecat provides a Swift iOS/macOS client SDK (`pipecat-ai/pipecat-client-ios`) for native sidecar. HIGH confidence.
- speech-swift/soniqo demonstrates native Swift MLX diarization + VAD with no Python runtime (~32MB total). HIGH confidence. [Source: soniqo/speech-swift](https://github.com/soniqo/speech-swift)

### Recommended split

| Layer | Process | Components |
|---|---|---|
| Swift sidecar | macOS native | FluidAudio Sortformer (speaker-ID), SpeechAnalyzer or CoreML VAD, AVAudioEngine capture, AVAudioPlayer TTS playback |
| Python brain | Pipecat pipeline | Parakeet MLX (STT), SmartTurn (EOU), LLM (Ollama/mlx-lm), Kokoro mlx-audio (TTS generation) |
| IPC | Unix socket / RTPS | Audio frames Swift → Python; text/audio Python → Swift |

### Pipecat vs bare asyncio

Pipecat v1.3+ multi-agent bus makes it the default choice — sidecar patterns are first-class, mlx-audio processor exists, SmartTurn built-in. Bare asyncio is viable for minimal footprint but requires reimplementing the pipeline bus. LOW risk adopting Pipecat.

### Wyoming: out

Wyoming protocol was excluded in prior planning. Nothing in this research reverses that decision.

---

## 6. Open Questions

1. **Speaker enrollment / verification:** None of the evaluated diarization libraries (FluidAudio Sortformer, speech-swift Pyannote) include an owner-voice enrollment or verification API. Artemis needs to build this layer — likely WeSpeaker embeddings + cosine-similarity threshold stored in a local SQLite or flat file. Needs a design decision before M5 implementation begins.

2. **Qwen3-TTS Apple Silicon maturity:** The MLX ports are community-driven (Jan–Jun 2026). If quality matters more than Kokoro, re-benchmark on target Mac Mini hardware in Aug–Sep 2026 before locking TTS.

3. **SpeechAnalyzer macOS 26 dependency:** macOS 26 is in beta as of Jun 2026. If the Mac Mini ships with macOS 15 (Sequoia), SpeechAnalyzer is unavailable and Parakeet is the only option. Confirm OS version before M5 starts.

4. **SmartTurn multimodal:** SmartTurn Multimodal (visual cues, Jan 2026 announcement) could improve barge-in accuracy. Not production-stable yet; monitor.

5. **Parakeet CoreML vs MLX path:** Community benchmarks show CoreML Whisper (0.19s) outpaces MLX Parakeet (0.50s) on per-sample latency for short clips. This counter-intuitive result means the Swift sidecar may benefit from a CoreML-compiled Parakeet if FluidInference or Argmax ships one. Watch FluidAudio releases.

---

## Sources

- [Parakeet vs Whisper on Mac: 80ms Local AI Dictation | Dictato](https://dicta.to/blog/whisper-vs-parakeet-vs-apple-speech-engine/)
- [Apple vs Whisper vs Parakeet vs Qwen3: 13,000 Recordings | Dictato](https://dicta.to/blog/speech-to-text-engine-comparison-mac-2026/)
- [iOS 26: SpeechAnalyzer Guide - Anton Gubarenko](https://antongubarenko.substack.com/p/ios-26-speechanalyzer-guide)
- [WhisperKit vs Apple SpeechAnalyzer | VocAI Blog](https://vocai.net/blog/whisperkit-vs-speechanalyzer-2026/)
- [WWDC25 Session 277: Bring advanced speech-to-text to your app with SpeechAnalyzer](https://developer.apple.com/videos/play/wwdc2025/277/)
- [senstella/parakeet-mlx GitHub](https://github.com/senstella/parakeet-mlx)
- [EliFuzz/parakeet-mlx GitHub](https://github.com/EliFuzz/parakeet-mlx)
- [Why I chose Whisper large-v3-turbo over Parakeet | Arun Baby](https://www.arunbaby.com/speech-tech/0073-whisper-vs-parakeet-asr-decision/)
- [Qwen3-TTS with MLX-Audio on macOS | myByways](https://mybyways.com/blog/qwen3-tts-with-mlx-audio-on-macos)
- [Qwen3-TTS Technical Report arXiv 2601.15621](https://arxiv.org/abs/2601.15621)
- [QwenLM/Qwen3-TTS GitHub](https://github.com/QwenLM/Qwen3-TTS)
- [kapi2800/qwen3-tts-apple-silicon GitHub](https://github.com/kapi2800/qwen3-tts-apple-silicon)
- [The Real Cost of Running Qwen TTS Locally | TinyComputers](https://tinycomputers.io/posts/the-real-cost-of-running-qwen-tts-locally-three-machines-compared.html)
- [Blaizzy/mlx-audio GitHub](https://github.com/Blaizzy/mlx-audio)
- [gabrimatic/kokoro-mlx GitHub](https://github.com/gabrimatic/kokoro-mlx)
- [We replaced ElevenLabs with Kokoro TTS on M4 | dTelecom blog](https://blog.dtelecom.org/we-replaced-elevenlabs-with-kokoro-tts-on-an-m4-gpu-latency-fell-to-100-ms-and-tts-cost-nearly-68bcc3313cdd)
- [Best Open-Source TTS 2026 | ocdevel](https://ocdevel.com/blog/20250720-tts)
- [CosyVoice3 Tech Guide | StableLearn](https://stable-learn.com/en/cosyvoice3-tech-guide/)
- [CosyVoice3 — Streaming TTS with Voice Cloning & Emotion (MLX) | Soniqo](https://soniqo.audio/guides/cosyvoice)
- [FunAudioLLM/CosyVoice GitHub](https://github.com/FunAudioLLM/CosyVoice)
- [CosyVoice 3 arXiv 2505.17589](https://arxiv.org/html/2505.17589v1)
- [FluidInference/FluidAudio GitHub](https://github.com/FluidInference/FluidAudio)
- [FluidInference/diar-streaming-sortformer-coreml | HuggingFace](https://huggingface.co/FluidInference/diar-streaming-sortformer-coreml)
- [FluidAudio Swift SDK | CocoaPods](https://cocoapods.org/pods/FluidAudio)
- [Speaker Diarization and VAD on Apple Silicon: Native Swift with MLX | Ivan (Medium)](https://blog.ivan.digital/speaker-diarization-and-voice-activity-detection-on-apple-silicon-native-swift-with-mlx-92ea0c9aca0f)
- [soniqo/speech-swift GitHub](https://github.com/soniqo/speech-swift)
- [Top 8 speaker diarization libraries 2026 | AssemblyAI](https://www.assemblyai.com/blog/top-speaker-diarization-libraries-and-apis)
- [Krisp Turn-Taking for Voice AI Agents](https://krisp.ai/blog/turn-taking-for-voice-ai/)
- [Krisp Turn-Taking v2 | VIVA SDK](https://krisp.ai/blog/krisp-turn-taking-v2-voice-ai-viva-sdk/)
- [SmartTurn Multimodal Architecture | susuROBO](https://susurobo.jp/blog/smart_turn_multimodal.html)
- [Krisp VIVA in Pipecat docs](https://docs.pipecat.ai/pipecat/features/krisp-viva)
- [Turn Detection for Voice Agents | LiveKit blog](https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection)
- [pipecat-ai/pipecat GitHub](https://github.com/pipecat-ai/pipecat)
- [pipecat-ai/pipecat-client-ios GitHub](https://github.com/pipecat-ai/pipecat-client-ios)
- [kwindla/macos-local-voice-agents GitHub](https://github.com/kwindla/macos-local-voice-agents)
- [mlx-audio PyPI](https://pypi.org/project/mlx-audio/)

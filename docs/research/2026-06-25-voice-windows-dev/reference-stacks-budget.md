# Reference Local-Voice Stacks + Memory/Latency Budget — Windows Dev Sidecar

**Date:** 2026-06-25
**Re-research after:** 2026-07-09
**Context:** Artemis Windows dev twin — RTX 5060 Ti 8GB VRAM, Ryzen 7700, 32GB RAM; Ollama already occupying ~4GB VRAM (Qwen3 embedder + reranker + 4B responder). Goal: cascaded streaming voice sidecar (wake → VAD → STT → brain LLM → TTS, barge-in) alongside the running Ollama stack.

---

## 1. Reference OSS Stacks

### 1.1 RealtimeSTT / RealtimeTTS (KoljaB)

**What it is:** Two complementary Python libraries — RealtimeSTT for low-latency VAD+wake+STT, RealtimeTTS for streaming LLM-token-to-speech output. Together they form a full cascaded voice loop.

**Pipeline structure:**
- VAD: WebRTCVAD (fast pre-gate) → SileroVAD (accurate verification)
- Wake: configurable wake-word trigger
- STT: faster-whisper (GPU-accelerated via CTranslate2)
- TTS: supports Coqui, Piper, Kokoro, ElevenLabs, Azure, and more

**Windows support:** [VERIFIED] — explicitly supported; Windows requires the `if __name__ == "__main__":` guard for multiprocessing. Python 3.11+ required. CUDA optional but supported.

**Client/server split:** RealtimeSTT ships a WebSocket server mode (`RealtimeSTT_server`) and matching client SDK. Audio streams in via WebSocket; transcription events stream back. RealtimeTTS has a similar server pattern. This maps cleanly to a sidecar (server on dev box, thin audio client in the browser/app).

**Barge-in:** SileroVAD trigger during TTS playback signals the barge-in cancel event. Pattern is well-documented.

**License:** MIT
**Maturity:** Active; pypi packages for both, LiveKit plugin (`livekit-plugins-realtimestt`) available.

**Score:** Windows-native H | Cascaded-streaming H | Client-server-split-fit H | Maturity H

---

### 1.2 Home Assistant Assist + Wyoming Protocol

**What it is:** Wyoming is HA's open TCP protocol for wiring cascaded voice components (wake / STT / TTS / intent). The ecosystem includes wyoming-faster-whisper, wyoming-piper, wyoming-openwakeword — each a standalone microservice.

**Pipeline structure:** Each stage is an independent process connected by Wyoming TCP events. Wake word server → STT server → HA intent handler → TTS server. Clear event-driven separation.

**Windows support:** [VERIFIED] — Docker images (`rhasspy/wyoming-piper`, `rhasspy/wyoming-faster-whisper`) run on Windows via Docker Desktop with GPU passthrough (for Whisper; Piper CPU-only in official images). The HA add-on form factor doesn't support GPU passthrough, but the standalone Docker images do.

**Client/server split:** Each Wyoming service is a network microservice — textbook sidecar fit. The brain (HA Assist or custom intent handler) is fully decoupled from audio services over TCP.

**Barge-in:** Not natively implemented in Wyoming's open protocol; barge-in requires application-layer logic.

**License:** Apache 2.0 / MIT per component
**Maturity:** High — production HA ecosystem; wyoming-faster-whisper and wyoming-piper are actively maintained by Rhasspy team.

**Score:** Windows-native M (Docker required, not bare-metal) | Cascaded-streaming H | Client-server-split-fit H | Maturity H

---

### 1.3 Pipecat (pipecat-ai)

**What it is:** Python framework for building real-time voice and multimodal conversational agents. Reached v1.0 April 2025; v1.5.x as of April 2026.

**Pipeline structure:** Frame-based pipeline — audio frames flow through processor nodes (VAD → STT → LLM → TTS → transport). Sentence-level streaming flush to TTS is idiomatic.

**Windows support:** [VERIFIED] — Python/pip install; no Linux-only deps. `PiperTTSService` runs locally (CPU or CUDA). SmallWebRTC transport for local dev, WebSocket transport for sidecar split.

**Client/server split:** Explicit sidecar pattern in multi-worker examples; WebSocket proxy and RTVI (Real-Time Voice Interface) client SDK available. The Pipecat server runs as a local service; the thin client connects via WebSocket or WebRTC.

**Barge-in:** Adaptive interruption handling added in 1.5.x (April 2026). Smart Turn model can run on CPU to free GPU for STT.

**Local model support:** PiperTTSService (native, no cloud); faster-whisper STT; Ollama LLM via OpenAI-compatible endpoint.

**License:** BSD 2-Clause
**Maturity:** High; NVIDIA official integration; active open-source.

**Score:** Windows-native H | Cascaded-streaming H | Client-server-split-fit H | Maturity H

---

### 1.4 speaches (formerly faster-whisper-server)

**What it is:** Lightweight OpenAI-compatible REST + WebSocket STT microservice backed by faster-whisper. Focused: STT only — no TTS, no wake, no VAD pipeline.

**Windows support:** [VERIFIED] — Docker image with NVIDIA GPU passthrough; whisper-standalone-win provides native Windows CLI executables.

**Client/server split:** Purpose-built as a network microservice (drop-in replacement for OpenAI `/v1/audio/transcriptions`). SSE streaming transcription endpoint.

**Barge-in:** N/A — STT microservice only; upstream caller handles barge-in.

**License:** MIT
**Maturity:** Moderate; active forks, Docker Hub availability.

**Score:** Windows-native M (Docker) | Cascaded-streaming M (STT-only block) | Client-server-split-fit H | Maturity M

---

### 1.5 LiveKit Agents

**What it is:** Python/Node.js framework where the AI agent joins a LiveKit room as a WebRTC participant. v1.0 April 2025; Python 1.5.x April 2026.

**Pipeline structure:** Session join → media capture → STT → LLM → tool calls → TTS → audio output. Agent is a WebRTC peer — audio/video via WebRTC rooms.

**Windows support:** [COMMUNITY] — Python/Node.js install; no platform restrictions documented. WebRTC stack runs on Windows.

**Client/server split:** Agent runs on server-side (sidecar); client (browser or native app) joins the LiveKit room. Wire protocol is WebRTC/RTMP — heavier than a simple WebSocket but proven for voice.

**Barge-in:** Silero VAD plugin documented; interruption via VAD trigger.

**Local model integration:** Supports local STT via livekit-plugins-realtimestt plugin (wraps KoljaB's RealtimeSTT); Ollama as LLM.

**License:** Apache 2.0
**Maturity:** High; large ecosystem, production-ready; NEEDS-DOMAIN: livekit.io for full plugin registry.

**Score:** Windows-native M (no issues, but WebRTC infra overhead) | Cascaded-streaming H | Client-server-split-fit H | Maturity H

---

### 1.6 Willow + Willow Inference Server (WIS)

**What it is:** Primarily an ESP32-S3 hardware voice assistant with a companion Willow Inference Server for STT/TTS/LLM. WIS exposes REST/WebSocket/WebRTC endpoints.

**Pipeline structure:** Wake on ESP32 device → audio stream to WIS (STT) → intent/LLM → WIS TTS → audio back to device.

**Windows support:** [COMMUNITY] — WIS is Docker-based; runs on Windows with Docker Desktop + GPU passthrough. Wyoming integration discussed but not production-standard.

**Client/server split:** WIS is the server; ESP32 (or any audio client) is the thin client. Clear split.

**Barge-in:** Not standard; edge device handles it.

**License:** Apache 2.0
**Maturity:** Niche; primarily ESP32 ecosystem. Misfit for a Windows sidecar talking to a browser/app.

**Score:** Windows-native L (Docker + hardware-centric) | Cascaded-streaming M | Client-server-split-fit M | Maturity L

---

## 2. Memory / VRAM Budget

### Model Footprints (INT8 / float16 via faster-whisper / CTranslate2)

| Component | Mode | VRAM | RAM |
|-----------|------|------|-----|
| Ollama stack (existing) | GPU | ~4.0 GB | ~2 GB |
| faster-whisper base.en (INT8) | GPU | ~0.3 GB | ~0.5 GB |
| faster-whisper small.en (INT8) | GPU | ~0.6 GB | ~0.7 GB |
| faster-whisper small.en (float16) | GPU | ~1.0 GB | ~1 GB |
| Kokoro TTS (GPU) | GPU | ~1.5–2.0 GB | ~0.5 GB |
| Kokoro TTS (CPU / ONNX) | CPU | 0 | ~1.5 GB |
| Piper TTS (CPU) | CPU | 0 | ~0.2–0.5 GB |
| SileroVAD (CPU) | CPU | 0 | ~2 MB |
| openWakeWord (CPU / ONNX) | CPU | 0 | ~50 MB |
| CUDA context overhead | GPU | ~0.5–1.0 GB | — |

**Sources:** [COMMUNITY] — community benchmarks, faster-whisper README, Kokoro VRAM guides, openWakeWord docs.

### Budget Verdict

**Tight-but-viable GPU-first split:**
- Ollama 4 GB + whisper-small.en INT8 ~0.6 GB + CUDA overhead ~0.8 GB = ~5.4 GB
- Kokoro on GPU would push to ~7.4 GB — leaves ~0.6 GB margin; risky for spikes.
- **Recommended split:** Kokoro or Piper on CPU. VAD + wake on CPU (negligible). STT on GPU with whisper-small.en INT8.
- **Safe VRAM total:** ~5.5 GB (Ollama + STT + CUDA overhead) — 2.5 GB headroom.
- **RAM:** 32 GB is ample. CPU-side (Kokoro ONNX + SileroVAD + openWakeWord) uses ~2 GB combined.

**No model-swap / eviction needed** if Piper or Kokoro ONNX runs on CPU. The STT model is small enough to stay resident.

**If higher STT quality needed** (whisper-medium.en ~1.5 GB GPU INT8): still fits within ~6.5 GB total, leaving 1.5 GB headroom.

---

## 3. End-to-End Latency

### Benchmark Data [VERIFIED / COMMUNITY]

| Hardware | Pipeline | TTFA (first audio) | Notes |
|----------|----------|-------------------|-------|
| RTX 3060 12GB | Whisper-small + Ollama 8B + Piper | 1–2 s | Sentence-streaming |
| RTX 3090 / 4090 | Whisper-small + Ollama 8B + Piper | 0.7–1.2 s | Sentence-streaming |
| RPi 5 (CPU-only) | Same stack | 5–8 s | No GPU |
| MacBook M2 16GB | Whisper + Ollama + Kokoro | ~0.8 s | Apple Silicon unified |

### RTX 5060 Ti 8GB Projection [ASSUMED]

The RTX 5060 Ti sits between RTX 3060 and 3090 in inference throughput for this class of models. Reasonable projection: **~0.8–1.5 s TTFA** with sentence-streaming, whisper-small INT8 on GPU, Piper/Kokoro on CPU, Ollama 4B (already loaded).

**Key optimization:** Flush each complete sentence from LLM to TTS immediately rather than waiting for full response — this is what collapses a 4–6 s pipeline to sub-2 s.

**Wake word** (openWakeWord on CPU): <20 ms per 30 ms audio chunk on modern CPU — negligible contribution.
**VAD** (SileroVAD on CPU): <1 ms per chunk — negligible.
**STT** (faster-whisper small.en INT8, GPU): ~0.1–0.3 s for a 3–5 s utterance.
**LLM first-token** (Qwen3 4B via Ollama, already warm): ~0.2–0.5 s.
**TTS first-audio** (Piper CPU or Kokoro ONNX): ~0.1–0.3 s for first sentence.

**Sub-second to first-audio is realistic** if: (a) LLM responds in 1–3 short sentences, (b) sentence streaming is enabled, (c) STT model stays resident on GPU.

---

## 4. Scoring Matrix

| Stack | Windows-native | Cascaded-streaming | Client-server-split-fit | Maturity/License |
|-------|---------------|-------------------|------------------------|-----------------|
| RealtimeSTT/TTS | H | H | H | H / MIT |
| Wyoming / HA Assist | M (Docker) | H | H | H / Apache 2.0 |
| Pipecat | H | H | H | H / BSD 2-Clause |
| speaches | M (Docker) | M (STT-only) | H | M / MIT |
| LiveKit Agents | M | H | H | H / Apache 2.0 |
| Willow / WIS | L | M | M | L / Apache 2.0 |

---

## 5. Sources

- [RealtimeSTT GitHub](https://github.com/KoljaB/RealtimeSTT)
- [RealtimeTTS PyPI](https://pypi.org/project/realtimetts/)
- [Wyoming Protocol — Home Assistant](https://www.home-assistant.io/integrations/wyoming/)
- [wyoming-addons GitHub](https://github.com/rhasspy/wyoming-addons)
- [Home Assistant GPU Voice (Joe Karlsson)](https://www.joekarlsson.com/blog/local-voice-ai-home-assistant-gpu/)
- [Pipecat GitHub](https://github.com/pipecat-ai/pipecat)
- [Pipecat Piper TTS docs](https://docs.pipecat.ai/api-reference/server/services/tts/piper)
- [Pipecat WebSocket transport](https://docs.pipecat.ai/server/services/transport/websocket-server)
- [Pipecat client web transports](https://github.com/pipecat-ai/pipecat-client-web-transports)
- [LiveKit Agents GitHub](https://github.com/livekit/agents)
- [LiveKit Agents architecture — Moravio](https://www.moravio.com/blog/livekit-agents-for-building-real-time-ai-agents)
- [livekit-plugins-realtimestt PyPI](https://pypi.org/project/livekit-plugins-realtimestt/)
- [faster-whisper GitHub](https://github.com/SYSTRAN/faster-whisper)
- [Kokoro TTS local setup — LocalAIMaster](https://localaimaster.com/blog/kokoro-tts-local-setup)
- [Kokoro FastAPI Docker (remsky)](https://github.com/remsky/Kokoro-FastAPI)
- [Whisper + Ollama + Piper build — LocalAIMaster](https://localaimaster.com/blog/local-voice-assistant-whisper-ollama-piper)
- [Whisper.cpp vs faster-whisper 2026 benchmarks — PromptQuorum](https://www.promptquorum.com/power-local-llm/local-whisper-stt-comparison-2026)
- [openWakeWord GitHub](https://github.com/dscripka/openWakeWord)
- [SileroVAD GitHub](https://github.com/snakers4/silero-vad)
- [SileroVAD plugin — LiveKit docs](https://docs.livekit.io/agents/logic/turns/vad/)
- [Willow Inference Server](https://github.com/toverainc/willow-inference-server)
- [Voice AI GPU Infrastructure — Spheron](https://www.spheron.network/blog/voice-ai-gpu-infrastructure/)
- [One-second voice-to-voice — Modal + Pipecat](https://modal.com/blog/low-latency-voice-bot)
- [Real-Time vs Cascading Voice Agents — Softcery](https://softcery.com/lab/ai-voice-agents-real-time-vs-turn-based-tts-stt-architecture)
- [RC-Home-Assistant-Low-VRAM GitHub](https://github.com/RoyalCities/RC-Home-Assistant-Low-VRAM)
- [Fully offline voice assistant on CPU-only (DEV Community)](https://dev.to/santhana_bharathi_m/building-a-fully-offline-ai-voice-assistant-on-a-laptop-2gb-ram-cpu-only-32hj)

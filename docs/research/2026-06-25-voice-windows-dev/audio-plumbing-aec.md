# Windows Real-Time Audio Plumbing — AEC, Wake Word, VAD, I/O

**Date:** 2026-06-25
**Re-research after:** 2026-07-09
**Scope:** Windows 11, RTX 5060 Ti 8GB + 32GB RAM, Python, frozen format 16 kHz mono Int16.
**Key question:** Can barge-in (< 200 ms interrupt with AEC) be achieved on the Windows dev rig,
or is this a Mac-hardware-only verify path?

---

## 1. AEC on Windows — THE CRITICAL GAP

### Background

macOS `AVAudioEngine` / `VoiceProcessingIO` provides free, OS-integrated AEC that eliminates
speaker-into-mic echo without any application-level plumbing. Windows has no direct equivalent
in the default Python audio stack. This section catalogs every realistic option.

---

### Option A — LiveKit `livekit-rtc` APM (RECOMMENDED FIRST TRY)

**What it is:** LiveKit's Python SDK (`livekit-rtc`) ships a native `AudioProcessingModule` (APM)
class that wraps WebRTC's APM — the same underlying engine Apple also uses — with AEC, noise
suppression, automatic gain control, and high-pass filtering. Crucially, the APM can be used
**without any LiveKit server**; it is a pure local audio-processing primitive.

**API surface (from official LiveKit docs):**
```python
from livekit.rtc.apm import AudioProcessingModule

apm = AudioProcessingModule(
    enable_aec=True,
    noise_suppression=True,
    high_pass_filter=True,
    auto_gain_control=True
)

# Per 10 ms chunk from mic:
clean_frame = apm.process_stream(mic_frame)

# Per 10 ms chunk of what the speaker is playing (reference signal):
apm.process_reverse_stream(playback_frame)
apm.set_stream_delay_ms(delay_ms)   # capture-to-playout RTT
```

Frame requirements: exactly 10 ms at the configured sample rate.
At 16 kHz → 160 samples per chunk. [VERIFIED — docs.livekit.io/reference/python/livekit/rtc/apm.html]

**Windows support:** The SDK is documented as platform-agnostic (WebRTC APM is cross-platform).
A known GitHub issue (#321 in livekit/python-sdks) reports "mic is listening to speaker — AEC
not working" but this appears to be a configuration issue (user not feeding the reverse stream),
not a platform incompatibility. [COMMUNITY]

**Quality:** Production-grade WebRTC AEC (the same core used in every browser video call).
Adaptive linear filter + residual echo suppressor. [VERIFIED]

**Latency:** 10 ms chunk processing, sub-millisecond per chunk on CPU. Does not materially add
to pipeline latency. [VERIFIED]

**Maintenance / License:** Actively maintained by LiveKit (backed, commercial-open). Apache 2.0.
Latest release 2025/2026. [VERIFIED — pypi.org/project/livekit-rtc/]

**Score:** Windows-native: H | Latency: H | Maturity: H

**Key caveat:** You must feed the reverse stream (playback audio) into `process_reverse_stream`
on the same clock as capture; and set `stream_delay_ms` accurately. If playback and capture are
on separate threads (very likely with sounddevice), you need a small ring buffer + timestamp
reconciliation. This is solvable but not trivial. [ASSUMED — standard WebRTC AEC integration pattern]

---

### Option B — `webrtc-audio-processing` / `python-webrtc-audio-processing` (PyPI)

**Package:** `webrtc-audio-processing` (xiongyihui, PyPI v0.1.3)

**Windows support:** Source distribution only on PyPI — no prebuilt Windows wheels. Would require
building from source with a C++ toolchain (MSVC or MinGW). [VERIFIED — pypi.org/project/webrtc-audio-processing/]

**Maintenance:** No new PyPI releases in 12+ months as of 2025; project may be abandoned.
[VERIFIED — PyPI page + Snyk advisor]

**Verdict:** Dead path for Windows dev rig. Skip unless LiveKit APM fails.

---

### Option C — SpeexDSP Echo Canceller

**Packages:** `speexdsp` (PyPI, last release 2018) / `speexdsp-python` (xiongyihui) /
`pyspeexaec` (PyPI, last release 2022).

**Windows support:** Requires MSYS2 or WSL for the native library; no clean pip-installable
Windows wheel confirmed for Python 3.11+. [VERIFIED — community reports]

**Quality:** SpeexDSP AEC is a classic NLMS-based echo canceller. Works adequately for narrow-
band (8 kHz) telephony; at 16 kHz it is functional but inferior to WebRTC APM. Requires more
careful tuning (filter length, tail length). [VERIFIED — docs.pjsip.org AEC guide]

**Verdict:** Low priority. Use only if both LiveKit APM and webrtc-audio-processing fail.

---

### Option D — Windows Voice Capture DMO / AECMicArray (Native COM)

**What it is:** Microsoft's built-in `VoiceCaptureDMO` (AEC via DirectX Media Object / DSP)
exposed through `mmdeviceapi` / WASAPI. In "source mode" it autonomously taps the speaker
loopback and applies echo cancellation, outputting a clean mono stream.

**Python access:** No maintained Python binding exists as of 2025. Would require `comtypes` or
`ctypes` COM interop — effectively writing a mini C extension. [VERIFIED — learn.microsoft.com/VoiceCaptureDMO — no Python wrapper found]

**Quality:** Single-channel AEC only; designed for conferencing scenarios, not low-latency
barge-in. Adds perceptible algorithmic delay (≥ 20 ms additional). [VERIFIED — MS docs]

**Windows-native:** Yes, but COM-only. [VERIFIED]

**Verdict:** Theoretically ideal (native, free) but inaccessible from Python without significant
wrapper work. File as "future native option" — not viable for near-term dev.

---

### Option E — Headphones-for-Dev (AEC Bypass)

**What it is:** If the developer wears headphones while testing, there is no airpath from
speaker to mic. No acoustic echo exists; AEC becomes unnecessary. [VERIFIED — standard acoustic fact]

**Barge-in implication:** Barge-in still works — the user can speak at any time and VAD will
correctly detect it, because there is no echo contamination to suppress. Playback flush (< 200 ms)
is entirely a software concern independent of AEC.

**When it breaks:** Any speaker-based testing scenario (e.g., demoing on a laptop with internal
speaker, or testing the "speaker plays TTS + user interrupts" flow without headphones).

**Verdict:** Legitimate dev workaround for the Windows rig. Headphones = AEC requirement
disappears. Mac hardware remains the authoritative verify path for the speaker+mic AEC scenario.
This is acceptable if AEC is tagged as "Mac-verify" in CI.

---

### AEC Verdict Summary

| Option | Windows pip-install | AEC Quality | Latency | Viable? |
|---|---|---|---|---|
| LiveKit RTC APM | Yes (livekit-rtc) | High (WebRTC) | ~10 ms | **YES — try first** |
| webrtc-audio-processing | Build from source | High (WebRTC) | ~10 ms | Low (no wheel) |
| SpeexDSP | Partial (MSYS2) | Medium | ~10–20 ms | Fallback only |
| Windows Voice Capture DMO | COM/ctypes only | Medium | ~20 ms | Not viable Python |
| Headphones bypass | N/A | N/A | 0 ms | YES — dev workaround |

**Recommended path (2026):**
1. Use `livekit-rtc` APM with headphones for initial dev — ensures pipeline is wired correctly.
2. Wire the reverse stream (playback reference) into APM from the start, even with headphones,
   so the AEC integration is real and tested when Mac hardware arrives.
3. Tag the speaker-output AEC scenario as **Mac-verify only** until the Mini ships.

**Is barge-in realistically achievable on Windows dev rig?**
YES — with headphones. The barge-in challenge on Windows without headphones (AEC gap) is real
and non-trivial. LiveKit APM is the most credible software-only fix but requires careful reverse-
stream timing. For a dev rig, headphones + LiveKit APM wired = full barge-in functionality
verifiable locally. Speaker scenario = Mac-gate.

---

## 2. Wake Word

### openWakeWord (RECOMMENDED)

**License:** Apache 2.0. Free, fully open-source.
**Custom wake words:** Yes — train via Google Colab in < 1 hour; produces tiny ONNX model (~200 KB).
**Windows support:** Yes — uses ONNX Runtime on Windows (tflite not required, falls back to
onnxruntime). Confirmed working on Windows 10/11 with GPU via CUDA. [VERIFIED — GitHub dscripka/openWakeWord]
**Training on Windows:** Community trainer (`lgpearson1771/openwakeword-trainer`) requires WSL2 +
CUDA for the full pipeline, but inference runs native Windows. Training can also use Google Colab.
[VERIFIED — GitHub README]
**Performance:** Can run 15–20 models simultaneously on a single CPU core (Raspberry Pi 3 baseline).
RTX 5060 Ti will be trivially fast. [VERIFIED — GitHub README]
**Accuracy:** Comparable to or better than Porcupine in some benchmarks. [COMMUNITY — outspoken.cloud]

**Score:** Windows-native: H | Latency: H | Maturity: M (active, growing ecosystem)

### Picovoice Porcupine (ALTERNATIVE)

**License:** Commercial. $6K+/year for production use. Free tier for personal/dev.
**Custom wake words:** Yes — type phrase, model trained in seconds via cloud.
**Windows support:** Full — official Windows SDK + Python binding. [VERIFIED — picovoice.ai/docs/porcupine/]
**Accuracy:** 97%+ with < 1 false alarm per 10 hours. [VERIFIED — picovoice.ai]
**Verdict:** Overkill for local dev; cost is the main blocker. Use if openWakeWord accuracy proves insufficient.

**Score:** Windows-native: H | Latency: H | Maturity: H

**Recommendation:** openWakeWord for dev and production (free, ONNX, custom word, Windows-native).
Porcupine as fallback if false alarm rate is unacceptable.

---

## 3. VAD / Endpointing

### Silero VAD v5 (RECOMMENDED PRIMARY)

**License:** MIT.
**Latency:** < 1 ms per 30 ms chunk on single CPU thread; sub-ms with ONNX or GPU. [VERIFIED — GitHub snakers4/silero-vad]
**Windows support:** Full — runs via PyTorch or ONNX Runtime on Windows 11. [VERIFIED]
**Sample rates:** 8 kHz and 16 kHz natively. [VERIFIED]
**Streaming:** Yes — frame-by-frame processing; configurable `min_silence_duration` for endpointing.
**Windows startup warning:** On Windows 11, Silero VAD may emit "inference is slower than realtime"
warnings during the first few warm-up frames (single inference > 200 ms threshold). These disappear
once running; no functional impact. [VERIFIED — livekit/agents issue #4761]
**Endpointing:** 500 ms silence = "Speech Paused" (configurable). Combine with semantic partial-
transcript evaluation for dynamic endpointing. [COMMUNITY — rajatpandit.com]
**End-to-end latency (combined with WhisperX):** 380–520 ms p95. [COMMUNITY — medium.com/@aidenkoh]

**Score:** Windows-native: H | Latency: H | Maturity: H

### TEN VAD (RECOMMENDED SECONDARY / upgrade path)

**Package:** `pip install ten-vad` [VERIFIED — pypi.org/project/ten-vad/]
**Windows support:** Windows prebuilt lib available as of 2025/07 release. [VERIFIED — PyPI + GitHub TEN-framework/ten-vad]
**Latency:** 10–16 ms hop size (160/256 samples at 16 kHz). [VERIFIED — GitHub README]
**Quality:** Superior precision vs. both WebRTC VAD and Silero VAD per TEN-framework benchmarks.
Lower computational complexity and memory usage than Silero. [VERIFIED — GitHub README] (Note: self-benchmarked.)
**License:** Apache 2.0.
**Maturity:** Latest release Nov 2025 — newer and less community-tested than Silero. [VERIFIED — PyPI]

**Score:** Windows-native: H | Latency: H | Maturity: M (newer, less battle-tested)

### webrtcvad / webrtcvad-wheels (FALLBACK)

**Package:** `pip install webrtcvad-wheels` — provides prebuilt Windows wheels for Python 3.10–3.13.
[VERIFIED — pypi.org/project/webrtcvad-wheels/ + GitHub daanzu/py-webrtcvad-wheels]
**Latency:** 10, 20, or 30 ms frame only. Binary VAD output (speech/silence), no probabilities.
**Quality:** Good for basic VAD; lower precision than Silero/TEN in difficult acoustic conditions.
**Use case:** Lightweight fallback; already used in many OSS pipelines.

**Score:** Windows-native: H | Latency: H | Maturity: H (but aging)

**Recommendation:** Silero VAD as primary (proven, MIT, community battle-tested). TEN VAD as
upgrade path once it matures (6+ months in production). webrtcvad-wheels as lightweight fallback.

---

## 4. Audio I/O

### Capture: sounddevice + PyAudioWPatch

**sounddevice:**
- Built on PortAudio; cross-platform; WASAPI shared-mode support on Windows.
- Callback model available — audio arrives in chunks without polling.
- WASAPI buffer as low as < 10 ms in shared mode (Windows 10/11 audio engine default: ~10 ms).
  [VERIFIED — learn.microsoft.com/windows-hardware/drivers/audio/low-latency-audio]
- **Critical Windows issue:** GitHub issue #469 documents that **playback cannot be interrupted
  on Windows** via normal API calls — the only documented workaround is terminating the process.
  [VERIFIED — github.com/spatialaudio/python-sounddevice/issues/469]
- This is a blocker for software-triggered barge-in flush of TTS playback.
- Workaround: do not use `sd.play()` for TTS output. Instead, write to a callback-based output
  stream and maintain a "flush flag" that zeros the buffer when barge-in is detected. This gives
  < 10 ms flush latency (one callback cycle). [ASSUMED — standard pattern for real-time audio]

**PyAudioWPatch:**
- PortAudio fork with WASAPI loopback support — records speaker output for AEC reference or
  speaker diarization. Last release January 2026. [VERIFIED — PyPI PyAudioWPatch 0.2.12.6]
- `frames_per_buffer=512` at 16 kHz = ~32 ms buffers; low latency suitable.
- Primary use in Artemis: capture speaker loopback as AEC reverse-stream reference.
- Does not have the same playback interrupt issue because it is used for capture only.

**Score (sounddevice):** Windows-native: H | Latency: H (callback mode) | Maturity: H
**Score (PyAudioWPatch):** Windows-native: H | Latency: M | Maturity: M

### Playback: sounddevice callback stream (RECOMMENDED)

For barge-in-capable playback:
- Open a persistent `sd.OutputStream` (callback mode) rather than `sd.play()`.
- TTS audio is streamed into a queue consumed by the callback.
- On barge-in detection: set a flag; the callback drains to silence (zeros) for the next cycle.
- One callback cycle at 16 kHz / 512 frames = ~32 ms. With 160-frame buffers = ~10 ms flush.
- This achieves the < 200 ms barge-in target. [ASSUMED — standard real-time audio pattern;
  consistent with Windows WASAPI < 10 ms shared-mode buffer docs]

### Barge-In Architecture (Windows)

```
[Mic capture]  ──► [LiveKit APM process_stream]  ──► [openWakeWord] ──► [Silero VAD]
                         ▲
[Speaker output] ──► [PyAudioWPatch loopback] ──► [APM process_reverse_stream]
                                                              (AEC reference)
[TTS playback]  ──► [sd.OutputStream callback] ──► [flush flag on barge-in]
```

VAD detects speech during TTS → signal flush flag → callback zeros output in ≤ 10 ms → VAD
confirms continued speech → pipeline treats as barge-in event. Total barge-in response budget:
VAD chunk (30 ms) + callback flush (10 ms) + pipeline overhead (~50 ms) = ~90 ms. Well under
200 ms target. [ASSUMED based on component specs — needs empirical verification]

---

## Sources

1. [livekit.rtc.apm API documentation](https://docs.livekit.io/reference/python/livekit/rtc/apm.html)
2. [LiveKit Noise & Echo Cancellation](https://docs.livekit.io/transport/media/noise-cancellation/)
3. [webrtc-audio-processing · PyPI](https://pypi.org/project/webrtc-audio-processing/)
4. [Voice Capture DSP — Microsoft Docs](https://learn.microsoft.com/en-us/windows/win32/medfound/voicecapturedmo)
5. [Loopback Recording — Microsoft Docs](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)
6. [Low-Latency Audio — Windows Drivers](https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio)
7. [AECMicArray — Microsoft Docs](https://learn.microsoft.com/en-us/windows/win32/coreaudio/aecmicarray)
8. [speexdsp · PyPI](https://pypi.org/project/speexdsp/)
9. [speexdsp-python — GitHub xiongyihui](https://github.com/xiongyihui/speexdsp-python)
10. [openWakeWord — GitHub dscripka](https://github.com/dscripka/openWakeWord)
11. [openwakeword-trainer (WSL2 pipeline)](https://github.com/lgpearson1771/openwakeword-trainer)
12. [Porcupine Wake Word — Picovoice Docs](https://picovoice.ai/docs/porcupine/)
13. [Best Custom Wake Word Tools Comparison — Outspoken](https://outspoken.cloud/blog/best-wake-word-tools)
14. [Silero VAD — GitHub snakers4](https://github.com/snakers4/silero-vad)
15. [Silero VAD PyPI](https://pypi.org/project/silero-vad/)
16. [Silero VAD slower-than-realtime warning — LiveKit issue #4761](https://github.com/livekit/agents/issues/4761)
17. [High-Speed Voice Recognition with WhisperX + Silero VAD](https://medium.com/@aidenkoh/how-to-implement-high-speed-voice-recognition-in-chatbot-systems-with-whisperx-silero-vad-cdd45ea30904)
18. [TEN VAD — GitHub TEN-framework](https://github.com/TEN-framework/ten-vad)
19. [ten-vad · PyPI](https://pypi.org/project/ten-vad/)
20. [webrtcvad-wheels · PyPI](https://pypi.org/project/webrtcvad-wheels/)
21. [py-webrtcvad-wheels — GitHub daanzu](https://github.com/daanzu/py-webrtcvad-wheels)
22. [sounddevice — Playback cannot be interrupted on Windows #469](https://github.com/spatialaudio/python-sounddevice/issues/469)
23. [PyAudioWPatch · PyPI](https://pypi.org/project/PyAudioWPatch/)
24. [PyAudioWPatch — GitHub s0d3s](https://github.com/s0d3s/PyAudioWPatch)
25. [Optimizing Voice Agent Barge-in Detection 2025 — Sparkco](https://sparkco.ai/blog/optimizing-voice-agent-barge-in-detection-for-2025)
26. [AEC Barge-In — Vocal.com](https://vocal.com/echo-cancellation/aec-barge-in/)
27. [WASAPI Low Latency — PC Hardware Pro](https://www.pchardwarepro.com/en/wasapi-latency-settings-complete-guide-for-low-latency-audio/)

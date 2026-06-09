# Research: WWDC 2026 — Implications for the Artemis Stack
**Date:** 2026-06-09
**Confidence:** MEDIUM-HIGH — 64GB availability VERIFIED against apple.com; software claims re-verified 2026-06-09 against Apple newsroom + corroborating dev press (callstack, techtimes, byteiota). One claim (FM Python SDK / Linux) remains DISPUTED and is held at low confidence. Tagged per claim.
**Re-research after:** 2026-06-23 (14-day AI-tooling clock)

> Synthesis-level capture. Source-grounded by a Sonnet research agent (2026-06-09) + one direct
> apple.com verification by planning mode. Where the agent and the verified fact conflicted, the
> verified fact wins (see §Correction).

## Summary
WWDC 2026 was (as always) a **software-only** event — no new M5 Mac Mini, so the `mlx-openai-server`
serving path on Apple Silicon is unchanged and remains correct for Artemis. The hardware question is
therefore **48GB vs 64GB on the shipping M4 Pro Mac Mini, vs waiting an unknown 3–6+ months for an M5
Mini** — not "48 or wait for a 64GB tier that doesn't exist" (the agent's claim that 64GB was pulled is
**false** — see §Correction). The most interesting *software* signals are Apple's on-device Foundation
Model reportedly gaining a Python SDK (a zero-cost candidate for lightweight brain tasks) and MCP
reportedly moving OS-level — both **unverified** and recorded here as spec *candidates*, not decisions.

## Correction (planning-mode verification, VERIFIED)
- **The Mac Mini M4 Pro 64GB config is available on Apple's store right now** — 64GB/1TB and 64GB/2TB,
  on both the 12-core and 14-core M4 Pro. `[VERIFIED — apple.com/shop/buy-mac/mac-mini]`
- The research agent stated "no 64GB Mac Mini exists / the config was pulled." **This is incorrect** and
  has been discarded. status.md's treatment of 64GB as a real upgrade lever stands.

## Key findings
- **WWDC is software-only; no M5 Mac Mini announced.** Next-gen Mini is an unknown wait. `[ASSUMED — structural; Apple ships Mac hardware at separate events]`
- **MLX on M4 Pro unchanged by WWDC 2026.** Any M5 Neural-Accelerator gains apply only to M5 hardware. The `mlx-openai-server` path stays valid. `[COMMUNITY — agent-reported; consistent with no-new-hardware]`
- **Next-gen Apple Intelligence + "Siri AI"** — rebuilt Siri, screen-aware, searches personal context across Messages/Mail/Photos, acts across apps. `[VERIFIED — apple.com newsroom]` **Strategic note:** Apple now operates in Artemis's adjacent space; differentiation (privacy wall, self-hosted local reasoning, RAG second brain, owner control, no cloud) holds. Possible future *integration surface* (App Intents/Shortcuts), not a threat.
- **macOS 27 "Golden Gate"** — Liquid Glass UI refinement; ships Fall 2026, dev beta now. Client should adopt current SwiftUI/Liquid-Glass idioms. No hardware-target impact. `[VERIFIED — newsroom + press]`
- **Foundation Models framework now multimodal** — Apple's on-device model (AFM Core / AFM Core Advanced) accepts **image** input; tool-calling + structured output existed since 2025. `[VERIFIED — callstack + byteiota]`
- **`LanguageModel` protocol (Swift)** — swap Apple's on-device model ↔ Anthropic Claude / Google Gemini via a Swift Package Manager dependency, no session-logic change; Anthropic shipped a conforming Swift package. **Swift-only.** Wrong layer for our Python brain → ignore. `[VERIFIED — techtimes]`
- **"Core AI"** — Apple's new framework to run third-party models (Qwen/Mistral) **locally**, Swift-side. Doesn't displace our MLX/Python path → watch only. `[VERIFIED — callstack]`
- **Foundation Models Python SDK (`apple_fm_sdk`) + Linux-via-Swift-runtime** — reported (byteiota, citing WWDC session 241) but framed as **research-grade, not a production server runtime**; contradicted by callstack (FM stays Apple-hardware-exclusive: on-device + Private Cloud Compute). **DISPUTED — the one watch-item:** if it matures into real production Python access, Apple's free on-device model could serve cheap high-frequency brain tasks — but our Qwen3-4B responder already fills that role. `[DISPUTED — re-verify before specing]`
- **SpeechAnalyzer** (Apple on-device STT/VAD, shipped macOS 26 / WWDC 2025, ~2× Whisper, zero bundle cost) is the right path for the voice sidecar. No *new* WWDC 2026 speech announcement found. `[COMMUNITY]`
- **Swift 6.2 "Approachable Concurrency"** reduces strict-concurrency migration friction — adopt in the app + audio sidecar. `[COMMUNITY]`

## Per-stack-layer impact
| Stack layer | What (reportedly) changed at WWDC 2026 | Impact on Artemis | Action |
|---|---|---|---|
| Hardware (Mac Mini) | No M5 Mini; M4 Pro 64GB still sells | Decision ripens: 48 vs 64 vs wait | **Decide now** (see hardware doc / ADR amendment) |
| MLX serving | Unchanged on M4 Pro | None — path stays valid | Keep `mlx-openai-server` |
| On-device FM (Python SDK) | New, reportedly | Possible cheap lightweight-task offload | Re-verify → maybe a future spec |
| Core AI (Swift) | New, reportedly | Long-term Swift-native inference option | Watch; no action |
| Speech | SpeechAnalyzer (2025) is current best | Voice sidecar STT/VAD path | Use SpeechAnalyzer |
| Swift/SwiftUI | Swift 6.2 concurrency | Smoother strict-concurrency adoption | Adopt 6.2 idioms |
| macOS | Next version, Intel dropped | None for M-series target | Ignore until upgrade |

## The 64GB hardware decision
WWDC removes the "wait for WWDC" reason — it's resolved (nothing new for the Mini). The live choice:
- **48GB** — comfortable for 14B fine-tuning + 70B-4bit inference at ~6–10 tok/s; caps local fine-tune headroom.
- **64GB** — unlocks 32B-dense fine-tuning and safe headroom for the Qwen3-30B-A3B MoE; the cross-thread evidence (self-training doc) makes this the capability lever.
- **Wait for M5 Mini** — unknown 3–6+ months; delays the whole build.

**Recommendation: buy now; choose 64GB if local fine-tuning of >14B models is a real goal** (it is, per the self-training thread). See `wwdc-…` + the hardware fork put to the owner 2026-06-09.

## Assumptions / gaps
- All WWDC *software* claims are agent-reported and **unverified against primary sources** — the agent
  could not be source-audited this session and got the 64GB hardware fact wrong, so treat the software
  claims with matching skepticism. Re-research (apple.com/newsroom, developer.apple.com session pages)
  before any of them enters a spec.

## Sources
- Mac mini buy pages (64GB configs) — https://www.apple.com/shop/buy-mac/mac-mini `[VERIFIED]`
- Mac mini tech specs — https://www.apple.com/mac-mini/specs/
- WWDC 2026 software claims — agent-reported, primary sources pending re-research.

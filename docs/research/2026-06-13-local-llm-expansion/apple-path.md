# Apple Silicon Path: Local LLM Expansion Research
**Date:** 2026-06-13  
**Scope:** Running DeepSeek-class (671B MoE) and Kimi K2-class (1T MoE) models on Apple Silicon, with M5 Mac Mini as orchestrator dispatching to larger Apple hardware.

---

## 1. Current Mac Studio Lineup (Mid-2026)

**Confidence: High** — Apple specs page confirmed; pricing corroborated by multiple retail/news sources. The 512GB discontinuation is well-documented across MacRumors, Tom's Hardware, Cult of Mac.

### Available Today (June 2026)

The 2025 Mac Studio shipped in March 2025 with M4 Max and — notably — M3 Ultra (not M4 Ultra; Apple skipped the M4 Ultra entirely because the M4 Max lacked the high-bandwidth die-to-die interconnect required for UltraFusion).

| Config | Chip | Memory | Memory BW | Base Price |
|---|---|---|---|---|
| M4 Max (base) | 14-core CPU, 32-core GPU | 36GB | 410 GB/s | $1,999 |
| M4 Max (mid) | 16-core CPU, 40-core GPU | 36–128GB | 546 GB/s | ~$2,499+ |
| M3 Ultra (base) | 28-core CPU, 60-core GPU | **96GB only** | 819 GB/s | **$3,999** |
| M3 Ultra (max BTO) | 32-core CPU, 80-core GPU | **96GB only** | 819 GB/s | ~$4,999+ |

**Critical caveat — DRAM shortage has stripped the lineup:**  
- 512GB M3 Ultra option: removed March 5, 2026 (was $9,499). [MacRumors, 2026-03-05](https://www.macrumors.com/2026/03/05/mac-studio-no-512gb-ram-upgrade/)  
- 256GB M3 Ultra option: removed (price had risen to $7,499 before removal). [Tom's Hardware, 2026](https://www.tomshardware.com/tech-industry/apple-pulls-512-mac-studio-upgrade-option)  
- 128GB M3 Ultra option: also removed by May 2026. [MacRumors, 2026-05-05](https://www.macrumors.com/2026/05/05/apple-mac-studio-mac-mini-ram-cuts/)  
- **As of June 2026: M3 Ultra Mac Studio is available in 96GB configuration only at $3,999.** Higher memory tiers are gone from the Apple Store.

**Memory bandwidth reference:**  
- M3 Ultra (819 GB/s) is the most relevant for large-model inference — nearly double the M4 Max (546 GB/s). For MoE models this matters enormously because token generation speed scales almost linearly with bandwidth.

Sources: [Apple Mac Studio Tech Specs](https://support.apple.com/en-us/122211); [Apple Mac Studio Specs Page](https://www.apple.com/mac-studio/specs/); [Apple Pulls 512GB Option — Tom's Hardware](https://www.tomshardware.com/tech-industry/apple-pulls-512-mac-studio-upgrade-option)

---

## 2. Real-World Benchmark Numbers

**Confidence: Medium** — Generation numbers are consistent across multiple sources. Prefill/prompt-processing numbers are harder to find and often absent; the MLX-vs-llama.cpp prefill advantage is asserted repeatedly but few sources publish actual numbers. Treat prefill estimates as directional.

### DeepSeek R1 / V3 / V3-0324 (671B MoE, ~37B active params)

**Memory footprint:**
- Q4_K_M GGUF: ~404–405 GB (fits 512GB; does NOT fit 256GB or 96GB)
- Unsloth 1.58-bit dynamic: ~131 GB (fits 256GB, tight on 192GB)
- Unsloth 2.51-bit: ~212 GB (fits 256GB)

**Generation speed (tokens/second) on M3 Ultra 512GB:**

| Framework | Quantization | Gen tok/s | Notes |
|---|---|---|---|
| llama.cpp | Q4_K_M | ~16 | hostbor.com benchmark |
| MLX (mlx-lm) | 4-bit | >20 (reported ~21) | Slashdot/hardware-corner, March 2025 |
| MLX (mlx-lm) | 4-bit | "16.08–18.11" | Slightly different sources, same hardware |

The ">20 tok/s via MLX" figure for DeepSeek V3-0324 4-bit on M3 Ultra 512GB is the most-cited number. [Slashdot/hardware-corner, March 2025](https://apple.slashdot.org/story/25/03/25/2054214/deepseek-v3-now-runs-at-20-tokens-per-second-on-mac-studio); [hostbor.com](https://hostbor.com/mac-studio-m3-ultra-tested/)

**Prompt-processing (prefill) speed:**
No reliable numeric figures found in public benchmarks for 671B on M3 Ultra. The consistent qualitative claim is MLX is 4–5x faster than llama.cpp for prompt processing on Apple Silicon — which would put MLX prefill in the range of 80–120 tok/s at short-to-mid context lengths, extrapolating from the generation speed advantage. The hardware-corner article titled "14-Minute Wait?! $10K Mac Studio Crawls with DeepSeek 671B + llama.cpp" suggests llama.cpp prefill at large contexts is extremely slow (the 14-minute figure likely relates to prompt processing a large context). [hardware-corner.net](https://www.hardware-corner.net/mac-studio-m3-ultra-deepseek-llamacpp/)

**Important context-length caveat:** Generation at 20+ tok/s applies at short/medium contexts. Large contexts (16K–32K+ tokens) cause significant slowdowns due to attention overhead and KV-cache size. This is the most important penalty for big-context use cases.

**Note on 512GB availability:** Since the 512GB config was removed from Apple Store in March 2026, these benchmarks represent hardware that was available but is no longer orderable new. Any setup requiring 671B at Q4 now requires used/refurbished 512GB units or clustering.

### Kimi K2 / K2.5 / K2.6 (~1T MoE)

**Memory footprint:**
- UD-TQ1_0 (1.8-bit): ~240 GB disk/memory (fits a 256GB Mac)
- UD-Q2_K_XL (2-bit): ~375 GB  
- int4 native weights: ~500 GB+ (requires 512GB Mac or cluster)

**Single-machine 512GB M3 Ultra generation speed:**  
- UD-TQ1_0 (1.8-bit): 5–10 tok/s  
- UD-Q2_K_XL (2-bit): 8–15 tok/s  
- UD-Q4_K_XL (4-bit): 10–21 tok/s (requires 512GB; 4-bit full weights ~600GB — exceeds even 512GB; likely needs sharding or aggressive quant)

Sources: [developer.tenten.co — Kimi K2.5 on M3 Ultra 512GB](https://developer.tenten.co/how-to-run-kimi-k25-locally-on-mac-studio-m3-ultra-with-512gb); [apxml.com Kimi K2.5 specs](https://apxml.com/models/kimi-k25)

**4-node Mac Studio cluster (4× M3 Ultra, mixed 256GB/512GB = 1.5TB total):**  
- Kimi K2 Thinking (int4): ~25 tok/s, ~2000ms TTFT, <450W peak  
- Total cluster cost: ~$39,596  
[Creative Strategies research, Dec 2025](https://creativestrategies.com/research/running-a-1t-parameter-model-on-a-40k-mac-studio-cluster/)

**Prompt processing for Kimi K2 (1T):** No clean benchmark found. Given 1T parameters vs 671B, and the same MoE pattern (roughly 50–60B active params vs 37B for DeepSeek), expect prefill to be proportionally slower — perhaps 40–60% of DeepSeek's prefill rate at equivalent quantization.

---

## 3. Multi-Mac Clustering: exo, RDMA, Thunderbolt 5

**Confidence: Medium** — The exo/RDMA situation is fast-moving. RDMA is newly available as of macOS Tahoe 26.2 (Dec 2025). Benchmark numbers from community testing are directional, not rigorous. Maturity is explicitly "early-stage."

### Technology Stack

**exo framework:** Auto-discovers Macs on local network, distributes a single model across them transparently, pooling unified memory. Day-0 support for RDMA over Thunderbolt 5. [exo on Virge.io](https://www.virge.io/en/blog/exo-mac-studio-cluster-llm/)

**macOS Tahoe 26.2 RDMA:** Released December 2025. Enables Remote Direct Memory Access over Thunderbolt 5 at 80 Gb/s with sub-10 microsecond latency. Requires macOS Tahoe 26.2+, M3/M4 or newer hardware with Thunderbolt 5. M1/M2 machines fall back to TCP/IP (negating RDMA benefits). Still enabled via recovery mode commands, not standard System Preferences — explicitly described as "early-stage technology." [AppleInsider, Dec 2025](https://appleinsider.com/articles/25/12/20/ai-calculations-on-mac-cluster-gets-a-big-boost-from-new-rdma-support-on-thunderbolt-5); [WebProNews](https://www.webpronews.com/apples-macos-tahoe-26-2-enables-rdma-for-ai-mac-clusters-over-thunderbolt-5/)

### Benchmark Numbers

**DeepSeek V3.1 (671B) with exo (community numbers, Dec 2025):**
| Nodes | Tok/s |
|---|---|
| 1 node | 21.1 |
| 2 nodes | 27.8 (+32%) |
| 4 nodes | 32.5 (+54%) |

Source: [virge.io/exo-mac-studio-cluster](https://www.virge.io/en/blog/exo-mac-studio-cluster-llm/)

**With RDMA (stabilise.io community cluster data):**
| Model | 4-node cluster tok/s |
|---|---|
| Devstral 123B (4-bit) | 22 |
| DeepSeek v3.1 671B (8-bit) | 25 |
| Kimi K2 1T MoE | 34 |
| Qwen 480B (4-bit) | 40 |

Hardware: 4× M3 Ultra Mac Studios, 192GB each (768GB aggregate). [Stabilise.io](https://stabilise.io/blog-pages/blog/apples-rdma-revolution-how-mac-clusters-are-changing-local-ai-hosting)

### Practical Assessment

**Verdict: Works, but fragile.** The multi-Mac approach is genuinely viable for 671B+ models but requires accepting:

1. **RDMA is not plug-and-play** — requires macOS 26.2+, enabled through recovery mode, M3+ hardware. Documentation is community-produced, not Apple-official.
2. **Linear memory pooling, sublinear speed scaling** — 4 machines give ~54% more tok/s on generation (not 4×). The bottleneck shifts to inter-node communication.
3. **Prompt processing (prefill) benefits more from clustering** than generation does, since prefill is compute-bound. This is good news for the big-context use case.
4. **Maximum tested cluster: 4 nodes.** Larger configurations may work but are untested.
5. **Homogeneous hardware preferred** — mixing M3 Ultra + M5 Mini (heterogeneous) requires same ML runtime, which exo/MLX can handle but with caveats.
6. **Mini + Studio combo is feasible** — the M5 Mini (Thunderbolt 5) can participate as a cluster node. It contributes its 64GB to the pool but will bottleneck the cluster due to lower bandwidth. Best used as an orchestrator/head node dispatching jobs rather than a hot path inference node.

---

## 4. M5 Mac Mini: What It Can Run Alone

**Confidence: Medium** — M5 Mini not yet officially released as of June 2026. Specs extrapolated from M5 chip data and community benchmarks on M5 Max.

### Assumed Specs (M5 Mini)
- Max unified memory: 64GB (M5 Pro tier); 32GB base
- Memory bandwidth: ~153 GB/s (M5) to ~273 GB/s (M5 Pro)
- Status: Expected announcement Q3/Q4 2026 per supply chain leaks

Sources: [Macworld M5 Mini article](https://www.macworld.com/article/2964754/2026-mac-mini-m5-pro-design-specs-release-date.html); [LeanVPS M5 Mini specs](https://leanvps.com/blog/articles/2026-mac-mini-m5-release-date-price-full-specs.html)

### Best Models That Fit in 64GB

**Best coding model (single Mac Mini 64GB):**
- **Qwen 3.6-27B at Q6/Q8** — 12–22 tok/s; best quality-per-GB for coding
- **Qwen 3.6-35B-A3B (MoE) at Q8** — 25–45 tok/s thanks to only 3B active params; strong coding, fast generation
- DeepSeek distilled models: DS-R1-70B at Q4 (~38GB) — fits; ~15 tok/s

**Best long-context model (single Mac Mini 64GB):**
- Llama 3.3 70B at Q4_K_M — ~38GB, fits; 8–15 tok/s
- Qwen 3.6-35B-A3B — also handles long context well at ~48GB (Q8)

**What does NOT fit in 64GB:** DeepSeek V3/R1 671B at any reasonable quality. Even the most aggressive quantization (1.58-bit ~131GB) requires more than 64GB.

**M5 Mini's role in a hybrid cluster:** Best used as orchestrator/scheduler that dispatches heavy jobs to a Studio. The Mini can handle: routing decisions, small fast models for quick responses, context management, and API gateway functions. For heavy coding sessions (671B), it offloads to the Studio via exo.

Source: [InsiderLLM best local LLMs 2026](https://insiderllm.com/guides/best-local-llms-mac-2026/); [PromptQuorum M5 local LLM guide](https://www.promptquorum.com/local-llms/apple-silicon-local-llm-guide-2026)

---

## 5. Power Draw, Noise, and Headless Server Behaviour

**Confidence: High** — Official Apple power data; anecdotal headless issues well-documented in Apple community forums.

### Official Apple Power Numbers (2025 Mac Studio)

Source: [Apple Support — Mac Studio Power Consumption](https://support.apple.com/en-us/102027)

| Config | Idle | Max Load | Notes |
|---|---|---|---|
| M4 Max Mac Studio | 6W | 145W | Quiet inference workhorse |
| M3 Ultra Mac Studio | **9W** | **270W** | Large-model inference server |

During LLM inference specifically, real-world reports put M3 Ultra at **under 200W** even during heavy 671B inference — well below the 270W maximum. [TechRadar, 2025](https://www.techradar.com/pro/apple-mac-studio-m3-ultra-workstation-can-run-deepseek-r1-671b-ai-model-entirely-in-memory-using-less-than-200w-reviewer-finds)

### Idle Power (Key for 24/7 Server Use)
At 9W idle, the M3 Ultra Studio is extremely efficient for an always-on server. Annual idle cost at $0.15/kWh: ~$12/year. Under sustained inference at 150W average: ~$197/year. Hugely cheaper than cloud equivalents.

### Fan Noise
Mac Studio is not a silent machine at load. Under sustained 671B inference, fans are audible but not loud by workstation standards. In a home lab or server rack context this is manageable. Separate reports note the Mac Studio Ultra fans run even in sleep mode in some configurations — this is a known issue. [Apple Community thread](https://discussions.apple.com/thread/253823409)

### Headless Server Operation — Known Issues

1. **Sleep/wake problems:** Headless Macs (no display) can unexpectedly enter sleep mode and drop network connections. Requires `pmset -a sleep 0` or equivalent to disable sleep, plus `caffeinateXPC` or a LaunchDaemon to prevent sleep.
2. **Fan in sleep:** Some M3 Ultra units run fans at idle/sleep, a known firmware quirk. [Apple Community, 2025](https://discussions.apple.com/thread/255179556)
3. **No physical HDMI required but recommended:** Running truly headless (no display, no dongles) can cause GPU resource conflicts on macOS. A cheap HDMI dummy plug is the common fix.
4. **MLX server daemons:** mlx_lm.server runs fine as a background LaunchDaemon; the community pattern is to wrap it in a plist with `KeepAlive = true`. No reports of stability issues for weeks-long runs.
5. **macOS power management vs. server mode:** `pmset -a sleep 0 disksleep 0 powernap 0` is the baseline headless config. [Medium — Harshit Chawla headless Mac server](https://chawlaharshit.medium.com/how-i-turned-my-mac-into-a-headless-server-my-always-on-setup-for-ai-monitoring-and-automation-aa9a8ff9aeff)

---

## 6. M5 Studio / M5 Ultra Timeline

**Confidence: Medium** — Multiple credible supply-chain sources (TrendForce, Macworld, MacRumors) converge on specs and timeline. No official Apple announcement yet as of June 13, 2026 — WWDC keynote passed without a Studio announcement.

### Expected Specs (M5 Ultra Mac Studio)

| Spec | Expected |
|---|---|
| CPU | 36 cores |
| GPU | 84 cores |
| Memory | 96GB base → up to 512GB (if DRAM supply allows) |
| Memory bandwidth | >1,000 GB/s (estimated ~1,100 GB/s) |
| Process node | TSMC N3P (3nm) |
| Interconnect | Thunderbolt 5 (120 Gb/s) |

Sources: [TrendForce, June 8 2026](https://www.trendforce.com/news/2026/06/08/news-apple-may-debut-m5-ultra-powered-mac-studio-at-wwdc-boosting-demand-for-tsmc-n3p-and-soic-mh/); [Notebookcheck](https://www.notebookcheck.net/Mac-Studio-with-Apple-M5-Ultra-to-be-unveiled-at-WWDC-report-reveals-specs.1317931.0.html); [WCCFTech](https://wccftech.com/m5-ultra-could-make-a-surprise-entrance-at-wwdc-2026/)

### Timeline

- WWDC 2026 (June 9): Expected announcement did NOT happen (WWDC passed without Mac Studio announcement per Macworld)
- Most likely window: **October 2026** — multiple sources cite this based on DRAM shortage resolution timeline
- Risk: May slip further if global DRAM shortage persists (Apple reportedly paying 2× Samsung rates for supply)

Source: [Macworld M5 Studio article](https://www.macworld.com/article/2973459/2026-mac-studio-m5-release-date-specs-price-rumors.html); [Geeky Gadgets delay report](https://www.geeky-gadgets.com/apple-m5-mac-studio-delayed/); [MSN Apple delays M5 Mac Studio](https://www.msn.com/en-us/news/other/apple-delays-m5-mac-studio-launch-to-october-amid-shortages/gm-GMDEC50622)

### Worth-Waiting Assessment

**Bandwidth jump is substantial:** M3 Ultra at 819 GB/s → M5 Ultra at ~1,100 GB/s = ~34% bandwidth increase. For MoE inference (bandwidth-bound), this translates roughly linearly to ~34% more tok/s. So if M3 Ultra 512GB gives ~20 tok/s on DeepSeek V3, M5 Ultra 512GB should give ~27 tok/s.

**Memory question is the wildcard:** The current DRAM shortage means 512GB may not be available at M5 Ultra launch. If Apple can only offer 96GB or 256GB, the M5 Ultra still cannot run 671B Q4 on a single machine. Watch for BTO availability at launch.

**Price:** Likely $4,999–$6,000+ for M5 Ultra base given DRAM pressure. Will definitely be higher than the current $3,999 M3 Ultra.

**Verdict:** If you need 671B+ on a single machine, waiting for M5 Ultra 512GB makes sense — but it may not be available at launch and is at least 4 months out (October 2026). If the need is immediate, a used M3 Ultra 512GB (discontinued from Apple Store but available on secondary market) is the current-best option.

---

## Summary Table

| Scenario | Hardware | Memory | Gen tok/s (671B) | Gen tok/s (1T MoE) | Cost | Status |
|---|---|---|---|---|---|---|
| Current single Mac | M3 Ultra 512GB | 512GB | ~20 (MLX 4-bit) | 5–15 (1.8–2-bit) | ~$9,500 (used/grey) | Discontinued from Apple Store |
| Current single Mac | M3 Ultra 96GB | 96GB | Cannot fit 671B | Cannot fit | $3,999 | Available now |
| Current cluster | 4× M3 Ultra 192GB | 768GB agg. | 25 (RDMA cluster) | 34 (RDMA cluster) | ~$16,000–$30,000 | Works, fragile |
| Future single Mac | M5 Ultra 512GB | 512GB | ~27 (est.) | ~17 (est.) | ~$5,500+ | October 2026 est. |
| M5 Mini alone | M5 / M5 Pro 64GB | 64GB | Cannot fit 671B | Cannot fit | TBD | Not released |

---

## Key Caveats and Open Questions

1. **512GB hardware is effectively unobtainable new** as of June 2026. Any plan requiring 671B at Q4 in a single box must source used/refurbished M3 Ultra 512GB or wait for M5 Ultra.
2. **Prompt-processing benchmarks are sparse** — the big-context use case depends on prefill speed, which the community has benchmarked less rigorously than generation speed. Real-world performance at 32K+ context is substantially worse than the headline numbers.
3. **Clustering with M5 Mini + Studio is theoretically supported** via exo/RDMA but M5 Mini has lower bandwidth and will be the bottleneck node. It is better as an orchestrator than an inference node.
4. **RDMA requires macOS 26.2+ and M3+ hardware** — enabled through recovery mode, not standard settings; community-documented only; fragility risk for production use.
5. **M5 Ultra 512GB availability at launch is uncertain** — DRAM shortage may cap launch configs at 256GB again, as happened with M3 Ultra.
6. **Power is excellent by workstation standards** but sustained inference at 150–200W 24/7 is non-trivial thermally in a confined space (Mac Studio has active cooling; this is fine for normal home lab use).

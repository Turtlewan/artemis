# Intel Arc Pro B60 Hardware Research
**Purpose:** Size and price a local-LLM inference box based on Intel Arc Pro B-series GPUs, evaluating the VRAM-density path vs NVIDIA alternatives.
**Date:** 2026-06-13
**Researcher:** Claude Code (claude-sonnet-4-6)

---

## 1. Intel Arc Pro B-Series GPU Specifications

### 1.1 Arc Pro B60 (primary target)

| Spec | Value | Source |
|------|-------|--------|
| Architecture | Xe2 "Battlemage" (TSMC N5) | [igorslab.de, 2025](https://www.igorslab.de/en/intel-arc-pro-b60-workstation-test-with-technical-analysis-and-teardown-battle-of-the-small-workhorses-under-1000-euros/) |
| Die | BMG-G21 (full) | [wccftech.com, Jan 2025](https://wccftech.com/intel-arc-pro-b60-24-gb-b50-16-gb-battlemage-gpus-pro-ai-3x-faster-dual-gpu-variant/) |
| Xe2 Cores | 20 | [intel.com specs](https://www.intel.com/content/www/us/en/products/sku/243916/intel-arc-pro-b60-graphics/specifications.html) |
| XMX AI Engines | 160 | [intel.com specs](https://www.intel.com/content/www/us/en/products/sku/243916/intel-arc-pro-b60-graphics/specifications.html) |
| RT Units | 20 | [igorslab.de](https://www.igorslab.de/en/intel-arc-pro-b60-workstation-test-with-technical-analysis-and-teardown-battle-of-the-small-workhorses-under-1000-euros/) |
| FP32 Performance | 12.28 TFLOPS | [StorageReview, 2025](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| INT8 AI TOPS | 197 | [intel.com specs](https://www.intel.com/content/www/us/en/products/sku/243916/intel-arc-pro-b60-graphics/specifications.html) |
| VRAM | 24 GB GDDR6 | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| Memory Interface | 192-bit | [igorslab.de](https://www.igorslab.de/en/intel-arc-pro-b60-workstation-test-with-technical-analysis-and-teardown-battle-of-the-small-workhorses-under-1000-euros/) |
| Memory Speed | 19 Gbps GDDR6 | [igorslab.de](https://www.igorslab.de/en/intel-arc-pro-b60-workstation-test-with-technical-analysis-and-teardown-battle-of-the-small-workhorses-under-1000-euros/) |
| Memory Bandwidth | **456 GB/s** | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| GPU Boost Clock | 2,400 MHz | [wccftech.com](https://wccftech.com/intel-arc-pro-b60-24-gb-b50-16-gb-battlemage-gpus-pro-ai-3x-faster-dual-gpu-variant/) |
| TBP (Blower) | **200 W** | [igorslab.de](https://www.igorslab.de/en/intel-arc-pro-b60-workstation-test-with-technical-analysis-and-teardown-battle-of-the-small-workhorses-under-1000-euros/) |
| TBP range (AIB variants) | 120–200 W | [hostzealot.com](https://www.hostzealot.com/blog/news/intel-presents-arc-pro-b50-and-b60-new-professional-gpus-with-ai-focus-and-up-to-24-gb-of-memory) |
| PCIe Interface | **PCIe 5.0 x8** | [microcenter.com](https://www.microcenter.com/product/705142/sparkle-intel-arc-pro-b60-blower-single-fan-24gb-gddr6-pcie-50-graphics-card) |
| Form Factor | Dual-slot (blower); single-slot (passive AIB) | [asrock.com](https://www.asrock.com/Graphics-Card/Intel/Intel%20Arc%20Pro%20B60%20Passive%2024GB/) |
| Display Outputs | 4× DP 2.1 UHBR20 + HDMI 2.1 | [wccftech.com](https://wccftech.com/intel-arc-pro-b60-24-gb-b50-16-gb-battlemage-gpus-pro-ai-3x-faster-dual-gpu-variant/) |
| Launch | September 19, 2025 (retail) | [videocardz.com](https://videocardz.com/newz/sparkle-offically-launches-arc-pro-b60-at-799-for-consumers) |
| MSRP (Sparkle launch) | **$799** | [videocardz.com](https://videocardz.com/newz/sparkle-offically-launches-arc-pro-b60-at-799-for-consumers) |
| Street price (2025–2026) | **~$599–660** | [slickdeals.net](https://slickdeals.net/f/19096072-sparkle-intel-arc-pro-arc-b60-pro-sbp60w-24g-24gb-799-99); [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| Idle power (single card) | ~15–22 W | [igorslab.de](https://www.igorslab.de/en/intel-arc-pro-b60-workstation-test-with-technical-analysis-and-teardown-battle-of-the-small-workhorses-under-1000-euros/17/) |

**Passive/enterprise variants:** ASRock Arc Pro B60 Passive 24GB (1-slot, enterprise-only, no public retail price). Sparkle Arc Pro B60 24GB Blower and 48GB Passive also exist. [techpowerup.com, 2025](https://www.techpowerup.com/345471/sparkle-launches-intel-arc-pro-b60-24-gb-blower-and-48-gb-passive-gpus)

**P2P / multi-GPU communication:** Intel uses PCIe P2P data transfer (no NVLink equivalent). Intel has enabled PCIe P2P in vLLM / LLM-Scaler for tensor-parallel inference. [vllm.ai, Nov 2025](https://vllm.ai/blog/2025-11-11-intel-arc-pro-b)

**Confidence: HIGH** — multiple independent reviews, Intel official spec page, retail listings.

---

### 1.2 Arc Pro B60 Dual (48 GB dual-GPU card)

Two B60 dies on one PCB. Each GPU runs independently; no die-to-die interconnect — they appear as two discrete PCIe x8 devices from one x16 slot via bifurcation.

| Spec | Value | Source |
|------|-------|--------|
| GPUs on card | 2× BMG-G21 | [wccftech hands-on](https://wccftech.com/review/maxsun-intel-arc-pro-b60-dual-48g-turbo-graphics-card-hands-on-impressions-dual-battlemage-gpus-with-48-gb-memory/) |
| VRAM per GPU | 24 GB GDDR6 | [maxsun.com](https://www.maxsun.com/products/intel-arc-pro-b60-dual-48g-turbo) |
| Total VRAM | **48 GB** | [maxsun.com](https://www.maxsun.com/products/intel-arc-pro-b60-dual-48g-turbo) |
| Bandwidth per GPU | 456 GB/s | [wccftech hands-on](https://wccftech.com/review/maxsun-intel-arc-pro-b60-dual-48g-turbo-graphics-card-hands-on-impressions-dual-battlemage-gpus-with-48-gb-memory/) |
| PCIe | x16 slot → 2× x8 (bifurcation required) | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| Total TBP | **400 W** | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| Power connector | Single 12V-2×6 (600W-rated) | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| Length | 300 mm | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| Slot count | 2-slot (blower cooling) | [wccftech hands-on](https://wccftech.com/review/maxsun-intel-arc-pro-b60-dual-48g-turbo-graphics-card-hands-on-impressions-dual-battlemage-gpus-with-48-gb-memory/) |
| Launch price (Maxsun) | **$1,200** (Guru3D), listed $3,000 by US distributor HydraTechBuilds | [guru3d.com](https://www.guru3d.com/story/maxsun-arc-pro-b60-dual-48g-turbo-gpu-launches-for/); [tweaktown.com](https://www.tweaktown.com/news/107258/maxsuns-new-intel-arc-pro-b60-dual-48gb-turbo-dual-gpu-card-has-been-listed-in-us-for-dollars3000/) |

**Note on $3,000 listing:** The $3,000 US distributor price appears to be a grey-market markup; the canonical launch price is $1,200. Use $1,200–1,500 as realistic procurement range. [guru3d.com](https://www.guru3d.com/story/maxsun-arc-pro-b60-dual-48g-turbo-gpu-launches-for/)

**Sparkle liquid-cooled single-slot B60 Dual 48GB:** Maxsun also released a single-slot liquid-cooled version (~$1,300–1,500 estimated, unconfirmed) enabling 7-way GPU setups on an Intel W790 workstation motherboard (7 PCIe x16 slots → 14 GPUs-worth of dies → 336 GB VRAM). [tweaktown.com](https://www.tweaktown.com/news/108093/maxsun-unveils-single-slot-liquid-cooled-intel-arc-b60-48gb-allows-for-7-x-gpu-configurations/)

**Confidence: HIGH** for specs; MEDIUM for street price (spread between $1,200–$3,000 is large; $1,200 is the launch price from Guru3D).

---

### 1.3 Arc Pro B50 (16 GB, smaller sibling)

| Spec | Value | Source |
|------|-------|--------|
| VRAM | 16 GB GDDR6 | [notebookcheck.net](https://www.notebookcheck.net/Intel-Arc-Pro-B50-and-B60-launch-as-affordable-workstation-GPUs-with-up-to-24-GB-VRAM.1019453.0.html) |
| Memory Interface | 128-bit | [slickdeals.net](https://slickdeals.net/f/19254088-intel-arc-pro-b50-128bit-16gb-gddr6-pcie-5-0-x8-workstation-sff-graphics-card-330-f-s) |
| Memory Bandwidth | ~240 GB/s (19 Gbps × 128-bit) | Calculated from interface |
| PCIe | PCIe 5.0 x8 | [slickdeals.net](https://slickdeals.net/f/19254088-intel-arc-pro-b50-128bit-16gb-gddr6-pcie-5-0-x8-workstation-sff-graphics-card-330-f-s) |
| TBP | **70 W** (no external power connector) | [StorageReview B50 review](https://www.storagereview.com/review/intel-arc-pro-b50-gpu-review-an-affordable-low-power-workstation-gpu) |
| Form factor | SFF / single-slot | [guru3d.com](https://www.guru3d.com/story/sparkle-launches-singleslot-intel-arc-pro-b50-with-16gb-vram/) |
| MSRP | **$299** | [tomshardware.com](https://www.tomshardware.com/pc-components/gpus/intel-launches-usd299-arc-pro-b50-with-16gb-of-memory-project-battlematrix-workstations-with-24gb-arc-pro-b60-gpus) |

**Note:** B50 is intended for SFF/power-constrained use. Not optimal for multi-GPU LLM inference due to lower bandwidth (240 GB/s vs 456 GB/s on B60).

**Confidence: HIGH.**

---

### 1.4 Arc Pro B70 — "Big Battlemage" Flagship (launched March 25, 2026)

This is the "flagship arriving after March 2026" referenced in the original brief.

| Spec | Value | Source |
|------|-------|--------|
| Die | BMG-G31 (larger die) | [overclock3d.net](https://overclock3d.net/news/gpu-displays/intel-officially-confirms-bmg-g31-big-battlemage-gpu-with-software-update/) |
| Xe2 Cores | 32 | [videocardz.com](https://videocardz.com/newz/intel-launches-arc-pro-b70-at-949-with-32gb-gddr6-memory) |
| XMX AI Engines | 256 | [thefpsreview.com, Mar 2026](https://www.thefpsreview.com/2026/03/25/intels-big-battlemage-finally-arrives-arc-pro-b70-and-b65-launched-today-with-32gb-of-vram-and-up-to-367-tops/) |
| INT8 AI TOPS | **367** | [videocardz.com](https://videocardz.com/newz/intel-launches-arc-pro-b70-at-949-with-32gb-gddr6-memory) |
| VRAM | **32 GB GDDR6** | [igorslab.de, Mar 2026](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/) |
| Memory Interface | 256-bit | [igorslab.de](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/) |
| Memory Bandwidth | **608 GB/s** | [igorslab.de](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/) |
| PCIe | PCIe 5.0 x16 | [igorslab.de](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/) |
| TBP | 160–290 W (Intel model: **230 W**) | [igorslab.de](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/) |
| Idle power | ~26 W (single card) | [wccftech.com](https://wccftech.com/intel-arc-pro-b70-quad-gpu-setup-reportedly-consumes-up-to-720w-in-inference-workloads/) |
| Launch price | **$949** (Intel model) | [videocardz.com](https://videocardz.com/newz/intel-launches-arc-pro-b70-at-949-with-32gb-gddr6-memory) |
| AIB partners | ARKN, ASRock, Gunnir, Maxsun, Sparkle | [igorslab.de](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/) |

**B70 multi-GPU power (measured):**
- 1× B70: ~180 W load / 26 W idle
- 2× B70: ~368 W total load
- 4× B70: **~720 W total load** [videocardz.com, 2026](https://videocardz.com/newz/intel-arc-pro-b70-battlematrix-quad-gpu-setup-consumes-up-to-720w-of-power)

**Note:** Consumer gaming B770 was shelved; B70 is Pro/workstation only. [tweaktown.com](https://www.tweaktown.com/news/112047/intel-arc-desktop-gpus-are-here-to-stay-according-to-an-intel-exec/)

**Confidence: HIGH** (multiple sources confirming March 25 2026 launch date and specs).

---

### 1.5 Arc Pro B65 (32 GB, mid-range, April 2026)

| Spec | Value | Source |
|------|-------|--------|
| Xe2 Cores | 20 (same die as B60) | [tomshardware.com](https://www.tomshardware.com/pc-components/gpus/intel-arc-pro-b70-and-arc-pro-b65-gpus-bring-32gb-of-ram-to-ai-and-pro-apps-bigger-battlemage-finally-arrives-but-its-not-for-gaming) |
| XMX AI Engines | 160 | [wccftech.com B65](https://wccftech.com/big-battlemage-gpu-is-here-intel-arc-pro-b70-b65-32-gb-graphics-cards/) |
| INT8 AI TOPS | 197 | [wccftech.com](https://wccftech.com/big-battlemage-gpu-is-here-intel-arc-pro-b70-b65-32-gb-graphics-cards/) |
| VRAM | **32 GB GDDR6** | [thefpsreview.com](https://www.thefpsreview.com/2026/03/25/intels-big-battlemage-finally-arrives-arc-pro-b70-and-b65-launched-today-with-32gb-of-vram-and-up-to-367-tops/) |
| Memory Interface | 256-bit | [wccftech.com](https://wccftech.com/big-battlemage-gpu-is-here-intel-arc-pro-b70-b65-32-gb-graphics-cards/) |
| Memory Bandwidth | **608 GB/s** | [wccftech.com](https://wccftech.com/big-battlemage-gpu-is-here-intel-arc-pro-b70-b65-32-gb-graphics-cards/) |
| PCIe | PCIe 5.0 x16 | [intel.com datasheet](https://www.intel.com/content/dam/www/central-libraries/us/en/documents/2026-03/datasheet-b65-gpu.pdf) |
| TBP | **200 W** | [igorslab.de](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/) |
| Availability | Mid-April 2026 (AIB only) | [thefpsreview.com](https://www.thefpsreview.com/2026/03/25/intels-big-battlemage-finally-arrives-arc-pro-b70-and-b65-launched-today-with-32gb-of-vram-and-up-to-367-tops/) |
| Expected price | ~$700–800 | [tomshardware.com](https://www.tomshardware.com/pc-components/gpus/intel-arc-pro-b70-and-arc-pro-b65-gpus-bring-32gb-of-ram-to-ai-and-pro-apps-bigger-battlemage-finally-arrives-but-its-not-for-gaming) |

**Note:** B65 is essentially a B60-class die (BMG-G21, 20 Xe cores) but on a 256-bit bus with 32 GB GDDR6. More memory, more bandwidth — better VRAM/$ than B60 but fewer TOPS than B70. Strong LLM inference option.

**Confidence: HIGH** for specs; MEDIUM for exact street price (not yet confirmed at time of research).

---

## 2. Multi-GPU Build Reality

### 2.1 PCIe Requirements

Each B60 GPU uses PCIe 5.0 x8. Each B60 Dual card contains two GPUs sharing one PCIe x16 slot via **bifurcation** (x16 electrically split to 2× x8).

- **4× single B60 cards (96 GB):** Requires 4× PCIe 5.0 x8 or x16 slots. A W790/W880 HEDT motherboard provides this (Xeon W9-3595X has 128 PCIe lanes). [intel.com Xeon W specs](https://www.intel.com/content/www/us/en/products/sku/240482/intel-xeon-w93595x-processor-112-5m-cache-2-00-ghz/specifications.html)
- **4× B60 Dual cards (192 GB / 8 GPUs):** Requires 4× PCIe 5.0 x16 slots with **bifurcation enabled** (each x16 slot splits to 2× x8). This is the "Battlematrix" configuration. Tested on AMD EPYC 9374F platform (Supermicro AS-4125GS-TNRT chassis). [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai)
- **7× B60 Dual Liquid cards (336 GB / 14 GPUs):** W790 HEDT motherboard with 7 PCIe x16 slots. [tweaktown.com](https://www.tweaktown.com/news/108093/maxsun-unveils-single-slot-liquid-cooled-intel-arc-b60-48gb-allows-for-7-x-gpu-configurations/)

**PCIe 5.0 x8 bandwidth per GPU:** 128 GB/s bidirectional — equivalent to PCIe 4.0 x16, adequate for LLM tensor parallelism. [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai)

**Key constraint:** No NVLink/XGMI equivalent. Inter-GPU transfers go over PCIe P2P. StorageReview found that at low batch sizes, "using the minimum number of GPUs required to fit the model delivers better per-user performance than distributing across all eight GPUs" — PCIe P2P overhead matters for single-user latency.

### 2.2 CPU / Motherboard Class

| Configuration | CPU Class | Motherboard | PCIe Lanes (CPU) |
|---------------|-----------|-------------|-----------------|
| 2–4× B60 (single cards) | Intel Xeon w7/w9-3x00 series (HEDT) | ASUS PRO WS W790E-SAGE SE or similar W790 | 64–128 lanes |
| 4× B60 Dual (8 GPUs, 192 GB) | Intel Xeon 6 (Granite Rapids) or AMD EPYC 9xx4 | EPYC server board (e.g., Supermicro AS-4125GS) | 128+ lanes |
| 7× B60 Dual Liquid (14 GPUs, 336 GB) | Intel Xeon w9-3595X (W790) | W790-class workstation board | 128 lanes |

Intel's "reference" Battlematrix spec calls for Xeon 6 + Xeon 6-compatible server motherboard. The StorageReview preview used an AMD EPYC 9374F on a Supermicro chassis — demonstrating platform agnosticism. [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai)

### 2.3 Power Draw

| Config | Idle | LLM Load | Notes |
|--------|------|----------|-------|
| 1× B60 (24 GB) | ~15–22 W (GPU only) | 120–200 W | Per igorslab review |
| 4× B60 (96 GB) | ~60–88 W (GPU only) | **480–800 W** | Estimated from per-card figures |
| 4× B60 Dual (192 GB, 8 GPUs) | ~120–176 W (GPU) | **1,400–1,600 W** | 400W per Dual card × 4 |
| 4× B70 (128 GB) | ~104 W (GPU) | **~720 W** | Measured [videocardz.com](https://videocardz.com/newz/intel-arc-pro-b70-battlematrix-quad-gpu-setup-consumes-up-to-720w-of-power) |

Add 300–500 W for CPU, RAM, storage, and fans to get total system draw.

**PSU sizing:**
- 4× single B60 system: ~1,400–1,600 W total (GPUs + platform). Use dual 1,200W PSUs or a single 2,000 W PSU.
- 4× B60 Dual (8 GPUs): ~2,000–2,100 W total. Sparkle's 384-GPU-variant server uses 4× 2,400 W PSUs (3+1 redundancy) = 7,200W provisioned. [techpowerup.com Sparkle server](https://www.techpowerup.com/341716/sparkle-packs-16-arc-pro-b60-dual-gpus-into-one-server-with-up-to-768-gb-vram-10-8kw-psu)

### 2.4 System Cost Estimates

**Component pricing basis (mid-2026):**
- Arc Pro B60 single (24 GB): ~$600 street [StorageReview]
- Arc Pro B60 Dual (48 GB): ~$1,200 [guru3d.com]
- Intel Xeon w9-3595X: ~$5,889 (MSRP, production pricing) [wccftech.com Xeon]
- W790 ASUS PRO WS: ~$1,500–2,000 (estimated; no confirmed 2026 price found)
- DDR5 512 GB ECC: ~$800–1,200
- Supermicro server chassis + PSU (1,600W+): ~$1,500–2,500
- NVMe SSD (2 TB): ~$200

#### 4× B60 Single-Card Build (96 GB VRAM)

| Component | Cost |
|-----------|------|
| 4× Arc Pro B60 24GB (~$600 ea.) | $2,400 |
| CPU: Xeon w9-3595X or Xeon 6 equivalent | $3,000–6,000 |
| Workstation motherboard (W790 class) | $1,500–2,000 |
| RAM: 128–256 GB DDR5 ECC | $400–800 |
| PSU: 2× 1,200W or 1× 2,000W | $400–600 |
| Chassis + fans | $500–1,200 |
| NVMe SSD | $200 |
| **GPU cost subtotal** | **$2,400** |
| **Estimated total system** | **$8,400–13,200** |

**Confidence: MEDIUM.** GPU costs are well-sourced (~$600 street). CPU/motherboard/chassis pricing is estimated from public Xeon list prices and comparable HEDT platform costs; no single-source BOM found for a B60-specific 4-GPU build.

#### 4× B60 Dual-Card Build (192 GB VRAM / 8 GPUs) — "Battlematrix"

| Component | Cost |
|-----------|------|
| 4× B60 Dual 48GB (~$1,200 ea.) | $4,800 |
| CPU: EPYC 9374F or Xeon 6 | $3,000–7,000 |
| Server motherboard (4× PCIe x16 bifurcation) | $2,000–4,000 |
| RAM: 512 GB DDR5 ECC | $800–1,200 |
| PSU: 2× 1,600W or dual-PSU redundant | $600–1,200 |
| Supermicro server chassis | $1,500–2,500 |
| NVMe SSD | $200 |
| **GPU cost subtotal** | **$4,800** |
| **Estimated total system** | **$12,900–20,900** |

Intel's own marketing claims "192 GB VRAM for $5–10k" — this appears to refer to the GPU cost alone, not a complete system. [ai2.work](https://ai2.work/technology/ai-tech-intel-arc-pro-b60-xeon6-2025/)

**Confidence: MEDIUM** for total system; LOW for the $5–10k claim (likely GPU-only).

---

## 3. VRAM-Scaling Ceiling

### 3.1 Practical Limits in a Single System

| Scale | Cards | GPUs | VRAM | Platform | Status |
|-------|-------|------|------|----------|--------|
| 4× B60 single | 4 PCIe x8 | 4 | 96 GB | W790 HEDT / EPYC | **Confirmed working** — Intel Battlematrix reference |
| 4× B60 Dual | 4 PCIe x16 (bifurcated) | 8 | 192 GB | EPYC 9374F / Xeon 6 server | **Confirmed** — StorageReview preview |
| 7× B60 Dual Liquid | 7 PCIe x16 (bifurcated) | 14 | 336 GB | Xeon w9-3595X + W790 | **Announced** by Maxsun; no full review yet |
| 16× B60 Dual | Custom PCIe expander | 32 | 768 GB | Xeon Scalable server | **Announced** — Sparkle C741-6U-Dual 16P server; 10,800 W PSU |

**Sparkle C741-6U-Dual 16P Server (768 GB VRAM):**
- 16× Arc Pro B60 Dual cards (32 GPUs)
- Custom PCIe circuit extending connectivity to 16 slots (each GPU gets PCIe 5.0 x8)
- Both Intel Xeon Scalable 4th/5th gen CPUs
- 6U chassis
- 10,800 W PSU (in full 768 GB config)
- 384 GB variant uses 4× 2,400W PSUs with 12× 60mm fans
- **Target: enterprise system integrators, no public price** [techpowerup.com](https://www.techpowerup.com/341716/sparkle-packs-16-arc-pro-b60-dual-gpus-into-one-server-with-up-to-768-gb-vram-10-8kw-psu)

### 3.2 Does 8× B60 (192 GB) Exist in Practice?

**Yes, confirmed.** StorageReview benchmarked 4× B60 Dual cards (8 GPUs, 192 GB) on a Supermicro/EPYC platform. Results show it runs Llama 3.1 8B (BF16), Mistral Small 3.1 24B (BF16), and OpenAI GPT-OSS 20B (INT4) at production batch sizes. [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai)

### 3.3 Prebuilt / Turnkey Multi-B60 Systems

| System | GPUs | VRAM | Vendor | Price |
|--------|------|------|--------|-------|
| Maxsun AI Workstation PC | Up to 4× B60 Dual (8 GPUs) | 192 GB | Maxsun | No public price listed |
| Sparkle C741-6U-Dual 16P | 16× B60 Dual (32 GPUs) | 768 GB | Sparkle | Enterprise pricing (not public) |

**Confidence: HIGH** for existence; LOW for pricing (no public prices on turnkey systems).

---

## 4. Comparison Table: GPU Hardware Facts

All prices are mid-2026 US market prices. "Street" = observed retail/resale price.

| GPU | VRAM | Type | Bandwidth | TDP | PCIe | Street Price | VRAM/$ | BW/W |
|-----|------|------|-----------|-----|------|-------------|--------|------|
| **Intel Arc Pro B60** | 24 GB | GDDR6 | **456 GB/s** | 200 W | 5.0 x8 | **~$600** | **40 MB/$** | 2.28 GB/s/W |
| **Intel Arc Pro B65** | 32 GB | GDDR6 | **608 GB/s** | 200 W | 5.0 x16 | ~$750 est. | ~43 MB/$ | 3.04 GB/s/W |
| **Intel Arc Pro B70** | 32 GB | GDDR6 | **608 GB/s** | 230 W | 5.0 x16 | **$949** | 34 MB/$ | 2.64 GB/s/W |
| **Intel Arc Pro B60 Dual** | 48 GB | GDDR6 | 912 GB/s (2× 456) | 400 W | 5.0 x16 | **~$1,200** | 40 MB/$ | 2.28 GB/s/W |
| **NVIDIA RTX Pro 2000 BW** | 16 GB | GDDR7 | 288 GB/s | 70 W | 5.0 x8 | ~$850 | 19 MB/$ | 4.11 GB/s/W |
| **NVIDIA RTX 5080** | 16 GB | GDDR7 | **960 GB/s** | 360 W | 5.0 x16 | **$999** | 16 MB/$ | 2.67 GB/s/W |
| **NVIDIA RTX 5090** | 32 GB | GDDR7 | **1,792 GB/s** | 575 W | 5.0 x16 | **$2,500–4,000** | 8–13 MB/$ | 3.12 GB/s/W |
| **NVIDIA RTX Pro 6000 BW** | 96 GB | GDDR7 | **1,792 GB/s** | 600 W | 5.0 x16 | **$9,700–13,250** | 7–10 MB/$ | 2.99 GB/s/W |
| **AMD RX 7900 XTX** | 24 GB | GDDR6 | **960 GB/s** | 355 W | 4.0 x16 | ~$795 used | 30 MB/$ | 2.70 GB/s/W |
| **NVIDIA RTX 4090** | 24 GB | GDDR6X | **1,008 GB/s** | 450 W | 4.0 x16 | ~$2,250 used | 11 MB/$ | 2.24 GB/s/W |

**Sources:**
- B60: [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai); [slickdeals](https://slickdeals.net/f/19096072-sparkle-intel-arc-pro-arc-b60-pro-sbp60w-24g-24gb-799-99)
- B70: [igorslab.de Mar 2026](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/)
- RTX Pro 2000: [cpusolutions.com](https://www.cpusolutions.com/store/pc/NVIDIA-RTX-PRO-2000-Blackwell-16GB-GDDR7-900-5G195-2250-000-01-p7837.htm); [technical.city](https://technical.city/en/video/RTX-PRO-2000-Blackwell)
- RTX 5080: [storagereview.com RTX 5080 review](https://www.storagereview.com/review/nvidia-geforce-rtx-5080-review-the-sweet-spot-for-ai-workloads)
- RTX 5090: [wccftech roundup](https://wccftech.com/roundup/nvidia-geforce-rtx-5090/); market price from [pgrid.app](https://www.pgrid.app/us/gpus/geforce-rtx-5090)
- RTX Pro 6000: [videocardz.com](https://videocardz.com/newz/nvidia-now-lists-rtx-pro-6000-blackwell-96gb-gpu-at-13250); [newegg.com $9,699](https://www.newegg.com/p/N82E16888884003)
- RX 7900 XTX: [bestvaluegpu.com](https://bestvaluegpu.com/history/new-and-used-rx-7900-xtx-price-history-and-specs/)
- RTX 4090: [bestvaluegpu.com](https://bestvaluegpu.com/history/new-and-used-rtx-4090-price-history-and-specs/); bandwidth [videocardz.net](https://videocardz.net/nvidia-geforce-rtx-4090)

**Important caveats on prices:**
- RTX 5090 MSRP is $1,999 but unobtainable at MSRP due to DRAM shortage; real street is $2,500–4,000+. [wccftech](https://wccftech.com/roundup/nvidia-geforce-rtx-5090/)
- RTX Pro 6000: NVIDIA official price is $13,250; Newegg lists at $9,699 (may be Workstation vs Server Edition difference). [videocardz.com](https://videocardz.com/newz/nvidia-now-lists-rtx-pro-6000-blackwell-96gb-gpu-at-13250)
- RTX 4090 used price is volatile ($1,099–$2,350 observed depending on source and timing). [levelupblogs.com Jan 2026](https://levelupblogs.com/news/rtx-4090-price-still-worth-it/)

---

## 5. B60 Bandwidth vs Alternatives: LLM Token-Generation Implications

### 5.1 Bandwidth Context

LLM token generation (decode phase) is **memory-bandwidth-bound**, not compute-bound. Higher bandwidth = more tokens/second for a given model size. The formula approximates to:

```
tokens/s ≈ (memory_bandwidth_GB_s) / (model_size_in_bytes / batch_size)
```

At batch size = 1 (single-user):
- 7B model FP16 (14 GB): RTX 4090 ≈ 1,008/14 = 72 tok/s theoretical ceiling; B60 ≈ 456/14 = 33 tok/s ceiling
- 7B model Q4 (3.5 GB): RTX 4090 ≈ 288 tok/s; B60 ≈ 130 tok/s

### 5.2 Measured vs Theoretical Comparison

| GPU | BW (GB/s) | Llama 8B measured (tok/s, single user) | Source |
|-----|-----------|----------------------------------------|--------|
| RTX 4090 (24 GB) | 1,008 | ~100–170 | [spheron.network blog](https://www.spheron.network/blog/rtx-4090-for-ai-ml/) |
| RTX 5080 (16 GB) | 960 | ~132 (7B–14B sweet spot) | [toolhalla.ai](https://toolhalla.ai/blog/best-local-llms-rtx-5080-2026) |
| Arc Pro B60 (24 GB) | 456 | ~49 single GPU (INT4, GPT-OSS 20B) | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| 4× B60 (96 GB) | 1,824 aggregate | ~626 tok/s total (batch 16, GPT-OSS 20B INT4) | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |
| 8× B60 (192 GB) | 3,648 aggregate | ~512 tok/s total (batch 16, GPT-OSS 20B INT4) | [StorageReview](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai) |

**Key insight:** 8× B60 performs worse than 4× B60 at low batch sizes for GPT-OSS 20B because the model fits in 4 GPUs and PCIe P2P overhead hurts. At high batch sizes (batch=256, Mistral Small 24B), 8× B60 hits 574 tok/s total.

### 5.3 B60 vs RTX 4090 on Bandwidth

The B60 at 456 GB/s has **~45% of the RTX 4090's bandwidth** (1,008 GB/s). For per-GPU decode speed, RTX 4090 wins decisively. The B60's value proposition is **VRAM density per dollar**, not per-GPU decode speed.

However: **4× B60 aggregate bandwidth (1,824 GB/s) > RTX 4090 single-card (1,008 GB/s)**, and 4× B60 fits 96 GB vs 24 GB. For models that require tensor parallelism anyway (70B+), the B60 stack competes favorably on throughput-per-dollar.

### 5.4 B60 vs RTX Pro 6000 Blackwell (96 GB target)

| Metric | 4× Arc Pro B60 | RTX Pro 6000 BW |
|--------|---------------|-----------------|
| VRAM | 96 GB | 96 GB |
| Aggregate bandwidth | 1,824 GB/s | 1,792 GB/s |
| TDP | ~800 W load | 600 W |
| GPU cost | ~$2,400 | $9,700–13,250 |
| System cost (est.) | $8,400–13,200 | $12,000–17,000 |
| Single-card simplicity | No (4 PCIe slots, bifurcation, TP=4) | Yes (1 slot) |
| Software maturity | Intel XPU / vLLM / LLM-Scaler (still maturing) | Excellent (CUDA ecosystem) |

**Bandwidth parity is real:** 4× B60 aggregate bandwidth ≈ RTX Pro 6000 Blackwell. But the RTX Pro 6000 BW uses GDDR7 (1,792 GB/s from a single monolithic card), while 4× B60 aggregates 4× 456 GB/s across PCIe P2P links — which introduces inter-GPU communication overhead absent on the Pro 6000.

**Confidence: HIGH** for individual GPU bandwidth figures; MEDIUM for system-level throughput parity claim (depends heavily on workload and software stack maturity).

---

## 6. Software Ecosystem Maturity

| Stack | Status (mid-2026) | Notes |
|-------|-------------------|-------|
| Intel LLM-Scaler 1.2 (vLLM fork) | Production, Docker image available | Optimized for Arc Pro B-series; tensor parallelism across multiple B60s [vllm.ai Nov 2025](https://vllm.ai/blog/2025-11-11-intel-arc-pro-b) |
| vLLM upstream | Supported with Intel patches | Multi-GPU scaling enabled [vllm.ai](https://vllm.ai/blog/2025-11-11-intel-arc-pro-b) |
| llama.cpp | Partial Intel GPU support | Community patches; less mature than CUDA path [marvin.damschen.net](https://marvin.damschen.net/post/intel-arc-llama.cpp/) |
| CUDA compatibility | None | Intel Arc uses oneAPI / SYCL; not CUDA-compatible |
| ROCm compatibility | None | |

**Biggest software risk:** The Intel software stack lags NVIDIA's CUDA ecosystem in third-party library support, quantization methods, and tooling. The StorageReview preview explicitly notes "software optimization still lags the hardware's capabilities" (Sept 2025). By early 2026, LLM-Scaler 1.2 and vLLM are production-grade for the specific workflows Intel has optimized. Other use cases (fine-tuning, custom CUDA kernels, ComfyUI, etc.) remain more uncertain.

---

## 7. Top Caveats and Risks

1. **Software maturity is the main risk.** The B60's hardware is solid; the software ecosystem (oneAPI, LLM-Scaler, vLLM Intel backend) is narrower than CUDA. Tools that "just work" on RTX GPUs may require significant effort or workarounds on Arc Pro. [igorslab.de review](https://www.igorslab.de/en/intel-arc-pro-b60-workstation-test-with-technical-analysis-and-teardown-battle-of-the-small-workhorses-under-1000-euros/)

2. **PCIe P2P overhead vs NVLink.** Multi-GPU tensor parallelism over PCIe P2P is measurably slower than NVLink at low batch sizes. For single-user interactive use, 4× B60 may feel slower than expected given aggregate bandwidth numbers.

3. **Total system cost is not cheap.** A 4× B60 (96 GB) build runs $8,400–13,200 total — not "cheap" even if GPU cost is $2,400. The HEDT/server CPU + motherboard is the expensive anchor.

4. **The B65 may be a better sweet spot.** At ~$750 (estimated) with 32 GB / 608 GB/s per card, 3× B65 = 96 GB at ~$2,250 in GPU cost and higher per-card bandwidth than B60. Not yet widely available or reviewed (mid-April 2026 launch).

5. **Price volatility.** B60 street prices have varied ($599–799). RTX 4090 used prices are erratic ($1,100–$2,350). All comparisons should be rechecked at purchase time.

6. **Arc Pro B60 Dual $3,000 listing.** One US distributor (HydraTechBuilds) listed the dual card at $3,000. This appears to be grey-market pricing; canonical launch price is $1,200. Do not budget $3,000/card.

7. **Noise/thermals in server chassis.** The 8-GPU Battlematrix configuration uses blower-cooled cards in a server chassis. No dB measurements were publicly reported at time of this research. Expect loud server-level noise in a home/desk environment.

8. **Consumer gaming B770 shelved.** Intel shelved the consumer Arc B770 GPU. The Pro B70 ($949) is workstation-only. This signals Intel is focusing the Arc Pro line on AI/workstation, which is positive for software support longevity. [tweaktown.com](https://www.tweaktown.com/news/112047/intel-arc-desktop-gpus-are-here-to-stay-according-to-an-intel-exec/)

---

## Sources Index

- [StorageReview — Arc Pro B60 Battlematrix Preview (2025)](https://www.storagereview.com/review/intel-arc-pro-b60-battlematrix-preview-192gb-of-vram-for-on-premise-ai)
- [igorslab.de — Arc Pro B60 Review & Teardown (2025)](https://www.igorslab.de/en/intel-arc-pro-b60-workstation-test-with-technical-analysis-and-teardown-battle-of-the-small-workhorses-under-1000-euros/)
- [igorslab.de — Arc Pro B70 Launch, Mar 2026](https://www.igorslab.de/en/intel-launches-the-arc-pro-b70-with-32-gb-of-vram-for-949-big-battlemage-is-coming-first-for-ai-and-workstations/)
- [Intel.com — Arc Pro B60 Official Specs](https://www.intel.com/content/www/us/en/products/sku/243916/intel-arc-pro-b60-graphics/specifications.html)
- [Intel.com — Arc Pro B70 Official Specs](https://www.intel.com/content/www/us/en/products/sku/245797/intel-arc-pro-b70-graphics/specifications.html)
- [vLLM Blog — Intel Arc Pro B-Series Support, Nov 2025](https://vllm.ai/blog/2025-11-11-intel-arc-pro-b)
- [wccftech — B60/B50 announcement](https://wccftech.com/intel-arc-pro-b60-24-gb-b50-16-gb-battlemage-gpus-pro-ai-3x-faster-dual-gpu-variant/)
- [wccftech — B70/B65 announcement, Mar 2026](https://wccftech.com/big-battlemage-gpu-is-here-intel-arc-pro-b70-b65-32-gb-graphics-cards/)
- [videocardz.com — Arc Pro B70 launch](https://videocardz.com/newz/intel-launches-arc-pro-b70-at-949-with-32gb-gddr6-memory)
- [videocardz.com — B70 quad-GPU 720W power](https://videocardz.com/newz/intel-arc-pro-b70-battlematrix-quad-gpu-setup-consumes-up-to-720w-of-power)
- [guru3d.com — B60 Dual launch $1,200](https://www.guru3d.com/story/maxsun-arc-pro-b60-dual-48g-turbo-gpu-launches-for/)
- [tweaktown.com — B60 Dual $3,000 US listing](https://www.tweaktown.com/news/107258/maxsuns-new-intel-arc-pro-b60-dual-48gb-turbo-dual-gpu-card-has-been-listed-in-us-for-dollars3000/)
- [wccftech — B60 Dual hands-on](https://wccftech.com/review/maxsun-intel-arc-pro-b60-dual-48g-turbo-graphics-card-hands-on-impressions-dual-battlemage-gpus-with-48-gb-memory/)
- [techpowerup.com — Sparkle 16-GPU 768GB server](https://www.techpowerup.com/341716/sparkle-packs-16-arc-pro-b60-dual-gpus-into-one-server-with-up-to-768-gb-vram-10-8kw-psu)
- [tweaktown.com — Maxsun liquid-cooled 7x GPU](https://www.tweaktown.com/news/108093/maxsun-unveils-single-slot-liquid-cooled-intel-arc-b60-48gb-allows-for-7-x-gpu-configurations/)
- [videocardz.com — RTX Pro 6000 $13,250 NVIDIA listing](https://videocardz.com/newz/nvidia-now-lists-rtx-pro-6000-blackwell-96gb-gpu-at-13250)
- [newegg.com — RTX Pro 6000 $9,699](https://www.newegg.com/p/N82E16888884003)
- [wccftech roundup — RTX 5090 specs & pricing](https://wccftech.com/roundup/nvidia-geforce-rtx-5090/)
- [embeddedllm.com — B60 vLLM benchmarks, Feb 2026](https://embeddedllm.com/blog/benchmarking-llm-inference-intel-arc-pro-b60)
- [bestvaluegpu.com — RTX 4090 price history](https://bestvaluegpu.com/history/new-and-used-rtx-4090-price-history-and-specs/)
- [bestvaluegpu.com — RX 7900 XTX price history](https://bestvaluegpu.com/history/new-and-used-rx-7900-xtx-price-history-and-specs/)

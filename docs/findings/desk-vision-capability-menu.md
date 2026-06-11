# Desk Build-Assistant — Capability Menu & Prior-Art Scan

**Date:** 2026-06-11
**Purpose:** Research brief — what else the desk vision assistant could do, grounded in prior art.
**Companion:** `docs/findings/desk-vision-hud-deep-dive.md` (architecture + pipeline decisions — do not duplicate here).
**Confidence tags:** VERIFIED = official docs/press releases; COMMUNITY = developer reports/forum; ASSUMED = reasoned extrapolation.

---

## Part 1 — Prior-Art Scan

### 1.1 Industrial Guided-Assembly Systems

#### Tulip (tulip.co) — VERIFIED
No-code digital work-instruction platform with vision integration. Relevant capabilities:
- **AI Composer:** upload a PDF SOP → auto-generates step-by-step digital instructions with embedded images and quality checks in minutes. (Source: [AI Work Instructions blog](https://tulip.co/blog/ai-work-instructions/))
- **Dynamic work instructions:** handles thousands of product variants; each operator session can receive a different variant-appropriate instruction path.
- **Poka-yoke operator workflows:** embedded validation gates prevent advancing past a step until a check passes.
- **IoT data capture at step level:** records what was done, when, by whom — automatic build log.
- **AR overlay via tablet or smart glasses:** instructions sit in the operator's field of view.
- **Key steal:** auto-generation of step instructions from an uploaded document (maps directly to the M-VISION build-plan authoring surface via M3 ingestion).

#### LightGuide Systems (lightguidesys.com) — VERIFIED
Projector-AR workstation. Projects step-by-step instructions *onto the physical work surface* (no screen, no glasses). Most relevant to desk vision because the overhead projector is the closest commercial analog to an overhead camera. Relevant capabilities:
- **Projected AR overlays directly on parts:** arrows, highlight zones, step numbers drawn on the actual component — the anti-screen paradigm.
- **3D-camera real-time error prevention:** AI vision verifies the correct part was picked and placed before allowing step advance.
- **Integration with MES/PLC/SCADA:** live two-way data flow; session data captured automatically.
- **Performance (2025 claims):** 90% quality improvement, 50% productivity increase, 70% training efficiency. (Source: [LightGuide smartAR](https://www.lightguidesys.com/smart-ar-workstation/))
- **Key steal:** *verified step-advance gating* — do not let the assistant mark a step done until vision confirms it. Also: projecting guidance onto the work surface (future hardware option if an overhead projector is added to the desk).

#### Augmentir (augmentir.com) — VERIFIED
AI-powered Connected Worker platform. Relevant capabilities:
- **AI-adaptive work instructions:** adjusts guidance complexity based on worker skill/experience level — beginners get more detail, experts get abbreviated steps.
- **5 Why Coach, Root Cause Investigator, Data Analyst AI agents** (2025): turns inspection failures into structured root-cause workflows.
- **Quality inspection checklists:** digital visual-inspection walkthroughs with guided camera-capture prompts.
- **Skill coaching:** tracks technique over time; flags degradation or improvement.
- **Key steal:** *skill-adaptive instructions* — the assistant should know the owner's experience level and adjust verbosity accordingly (reuses M4 memory).

#### Apprentice.io — VERIFIED
Pharma-focused AR work instructions platform. Relevant capabilities:
- **Branching, parallel execution, enforcement logic:** no-code procedure authoring handles non-linear builds.
- **Linked procedures:** modular instruction fragments that can be shared across multiple build plans.
- **Remote AR collaboration:** expert can annotate the worker's view in real time via video.
- **Key steal:** *linked/modular build steps* — reusable sub-procedures (e.g. "solder a PTH component" = a reusable recipe).

### 1.2 AR Maintenance & Repair Guidance

#### ProGlove (proglove.com) — VERIFIED
Wearable barcode scanner with haptic + visual + audio feedback at the point of assembly. The pick-by-vision integration with Picavi smart glasses delivers item verification directly to the wearer's FOV. (Source: [ProGlove + Picavi](https://www.proglove.com/industrial-wearables/material-handling-systems-optimized-for-human-workers-with-picavi-and-proglove/))
- **Key steal:** *haptic/audio confirmation on correct part pick* — desk assistant can give audio "yes, that's the right resistor" immediately on identification, without waiting for a screen glance.

#### iFixit Repair Guides — COMMUNITY
iFixit provides community-authored step-by-step teardown/repair guides with annotated images. No live vision. (Source: [iFixit component guide](https://www.ifixit.com/Guide/Identifying+Major+Electronic+Components/27244))
- **Key steal:** the *format* — annotated static image + one-sentence step + tools list. This is the right template for auto-generated build-plan steps from conversational context.

### 1.3 Computer Vision Assembly Verification Research (2024–2025)

- **Learning-based Stage Verification (arXiv 2507.17304, 2025):** combines hand tracking (MediaPipe) + object detection (YOLOv5) to monitor assembly stage completion. Accuracy ~50–57% on benchmark — honest about the difficulty. (Source: [arXiv paper](https://arxiv.org/pdf/2507.17304))
- **Multimodal LLM assembly evaluation (arXiv 2603.22321, 2025):** aligns instruction manuals with assembly videos; evaluates VLMs on step-completion detection. (Source: [arXiv paper](https://arxiv.org/pdf/2603.22321))
- **From Instructions to Assistance dataset:** released to benchmark exactly the "did they complete this step" question.
- **Visual assembly verification overview (Roboflow, 2025):** real-time component orientation, connector seating, and placement error detection using deep learning; detects defects in <200 ms in production settings. (Source: [Roboflow blog](https://blog.roboflow.com/visual-assembly-verification/))
- **Solder joint ML inspection (Springer 2025):** deep learning model for PCB solder defect detection — relevant to the electronics-first rung-2 verification path. (Source: [Springer Nature](https://link.springer.com/article/10.1007/s10845-025-02748-5))

### 1.4 Consumer "Point and Identify" Apps

- **Google Lens (2025):** open-vocabulary visual search; good at consumer products, signage, QR codes, document text; weak on obscure/vintage/industrial parts with degraded silkscreen. Useful baseline for "what's this thing in general" but not sufficient for exact part# identification. (Source: [Android Authority guide](https://www.androidauthority.com/google-lens-guide-3183845/))
- **Lens App (lensapp.io):** object identification assistant in the same category. (Source: [lensapp.io](https://lensapp.io/blog/what-is-this-thing-identify/))

### 1.5 Consumer AR Build/Assembly Apps

- **LEGO Builder (2025 — digital instructions):** 3D-rotatable step-by-step instructions; AR mode overlays next step on physical build. Zoom + reference model. Step-by-step AR overlay is the closest consumer analog to guided assembly. (Source: [BricksFanz](https://bricksfanz.com/the-future-of-lego-instructions-building-in-ar/))
- **LEGO Technic AR app:** x-ray mode (see inside models), interactive test-drive. Demonstrates value of *transparency views* (useful for wiring/internal component guidance).
- **IKEA Place (AR furniture placement):** positions 3D furniture models in real space — room-planning, not assembly. The adjacent concept of *verifying an object's correct position* is directly applicable. (Source: [Dezeen](https://www.dezeen.com/2018/03/23/ikea-assembly-made-easier-through-augmented-reality-app/))
- **Buildcam.io:** construction time-lapse with AI movie maker; auto-selects frames + edits to 4K progress video at 7/30/90-day intervals. Directly maps to the auto-build-log feature. (Source: [Buildcam](https://www.buildcam.io/features/ai-movie-maker))

---

## Part 2 — Adjacent Feature Menu

Table columns: **Feature** | **One-line value** | **Effort (L/M/H)** | **Artemis subsystem(s) reused** | **Prior-art grounding** | **Confidence**

| # | Feature | Value | Effort | Reuses | Prior Art | Confidence |
|---|---------|-------|--------|--------|-----------|------------|
| 1 | **Auto-BOM extraction from a parts photo** | Photograph a laid-out parts set → get a structured Bill of Materials (count, type, value) with any unknowns flagged for lookup | M | M3 Docling + ColQwen/Qwen3-VL visual-doc; M4 entities (Part type) | LightGuide 3D-camera part-pick verification; Tulip AI Composer | VERIFIED (vision BOM is direct application of existing pipeline) |
| 2 | **"Do I have everything?" gap-check** | Compare parts on desk against build-plan BOM → surfaces missing/excess items before starting | M | Feature #1 (BOM); M7 recipes (build plan); M4 (project entity) | Tulip poka-yoke step gating; LightGuide error-prevention before step advance | VERIFIED |
| 3 | **Personal parts INVENTORY** | "What capacitors do I have in stock?" — catalog of owned parts with location tags ("drawer B3"), queryable by voice or chat | H | M4 entity backbone (Part entity + location attribute); M3 RAG (search); M5 voice | Commercial: no direct consumer analog; pro: warehouse vision AI (iFactoryApp); niche: Sortly, UltraLibrarian for EE components | VERIFIED (concept); ASSUMED (personal-scale fit) |
| 4 | **Auto-build log + searchable history** | Continuous key-frame capture during a session → auto-assembled searchable build record with step annotations + timestamps; queryable later ("what did I use for R3?") | M | M3 ingestion (key-frame ingest); M4 memory (session + build entity); M6 heartbeat (session lifecycle); Buildcam pattern | Buildcam.io AI time-lapse; Tulip IoT per-step data capture; Augmentir quality inspection capture | VERIFIED |
| 5 | **Solder-joint / quality inspection** | On-demand vision check: "is this joint good?" — evaluates visible defects (bridging, cold joint, polarity) against a reference or heuristic model | H | Vision sidecar (Qwen3-VL slow loop, existing pipeline); M7 recipe (inspection criteria); M3 (reference schematic) | Springer 2025 PCB defect ML; Roboflow visual verification; LightGuide AI vision step verify | VERIFIED (research frontier; production accuracy modest for general use) |
| 6 | **Measurement without tools** | Estimate dimensions and angles from overhead camera (using a reference object of known size or known camera mount height as calibration) | M | Vision sidecar; monocular depth estimation (Monodepth2 family); not tied to M3/M4 strongly | Monocular depth research (Springer Apps 2025); no direct consumer product | COMMUNITY (research-grade; personal-scale accuracy ±5–15% without stereo) |
| 7 | **Wiring / pinout guidance** | Narrate wiring steps, colour-code wire identification, verify correct pin assignment from a connector photo cross-referenced to a pinout reference | M | M3 (datasheet/pinout ingestion via Docling); M4 (project wiring entities); Qwen3-VL OCR on wire labels | CableEye talking-guided assembly; smart harness boards (2026 fqwireharness.com); Romtronic harness check guide | VERIFIED (datasheet ingest is direct M3 reuse; colour-ID is tractable VLM task) |
| 8 | **Safety warnings** | Proactive voice/HUD warning when a mains-connected item, blade, or unlabelled chemical is in frame — fires before the risky step | L | Vision sidecar (session vocab: "mains cable", "knife", "solvent can"); M6 proactive hook (urgency tier 1); M5 voice | Roboflow workplace safety AI; construction-site hazard detection (arXiv 2511.15720); Augmentir safety checklist | VERIFIED (hazard-class detection is well-solved; desk-vocab scope is small) |
| 9 | **Parts-ordering integration** | Missing part or low-stock item → queued shopping list item; ties into a future Shopping spoke | L | M4 (Part entity → "have: 0"); M6 heartbeat (proactive suggest after gap-check); Shopping spoke (future) | Augmentir AI agents triggering downstream workflows; no direct consumer analog | ASSUMED (depends on Shopping spoke existing) |
| 10 | **Skill coaching / technique feedback** | After a soldering or cutting step, offer a brief technique note ("that joint looks cold — try more heat, less time") based on visual result + domain knowledge | H | Augmentir 5 Why Coach pattern; M3 RAG (technique knowledge); M4 (owner skill profile); Qwen3-VL visual assessment | Augmentir AI coaching agents; assembly-verification research (arXiv 2507.17304) | COMMUNITY (2026 VLMs can describe what they see; normative coaching reliability is ASSUMED) |
| 11 | **Resume-a-build across sessions** | On session start, narrate where the project left off ("Last time: soldered R1–R5; next is R6 at pin 7") with optional visual diff against last captured state | L | M4 memory + project entity (last-step stored); M3 (key-frame from prior session); M5 voice briefing | Tulip dynamic work instructions (session state); Augmentir connected-worker session continuity | VERIFIED (direct M4 + M3 reuse; no new vision needed for the narrative; visual diff is optional add) |
| 12 | **Modular/linked step recipes** | Reusable sub-procedures ("through-hole solder", "apply threadlocker") callable from any build plan — owner teaches once, reuses across projects | L | M7 recipe store (already the recipe-format spec); M4 (procedure entity); Projects module | Apprentice.io linked procedures; Tulip dynamic work-instruction variants | VERIFIED (M7 recipe format is directly applicable) |
| 13 | **Multi-project queue + context switch** | Maintain state for several concurrent builds; voice-switch ("switch to the amp build") and instantly recall where that project stands | L | M4 project entities + ADR-013; M5 voice; Projects module (existing) | Augmentir multi-job support; Tulip product-variant routing | VERIFIED |
| 14 | **Generic "what's this?" mode (no active project)** | Rung-0 snapshot ID when no build plan is active — works as a stand-alone part/tool/component identifier | L | Vision sidecar (Qwen3-VL); M3+M4 enrichment; M5 voice (already the Rung 0 definition in the deep-dive) | Google Lens; lensapp.io | VERIFIED (already defined as Rung 0 in the architecture doc) |

---

## Part 3 — Recommended First Additions (Shortlist)

These are the features with the best effort/value ratio that also slot cleanly into the existing Artemis build sequence. Ordered by recommended implementation priority.

1. **Safety warnings (#8)** — High value, genuinely low effort (small session-vocab detection set; M6 proactive hook already specced). Ships immediately with Rung 1 HUD. No novel research needed.
2. **Resume-a-build across sessions (#11)** — Low effort (pure M4+M3+M5 reuse, no new vision), high owner-experience impact. Should be part of the Rung 1 spec.
3. **Modular/linked step recipes (#12)** — Low effort (M7 recipe format is the natural home). Enables reuse across builds. Include in the build-plan authoring surface spec.
4. **Multi-project queue (#13)** — Low effort (M4 entities + Projects module already handle this). Needed as soon as there is more than one active build.
5. **Auto-BOM extraction (#1)** — Medium effort, big "magic moment" — photograph the parts bag, get the BOM. Reuses M3 Docling + Qwen3-VL which are already pinned. Natural Rung 1 add-on.
6. **"Do I have everything?" gap-check (#2)** — Depends on #1; once BOM extraction exists this is a cheap delta.
7. **Wiring/pinout guidance (#7)** — Medium effort but high value for electronics builds; direct M3 datasheet-ingest reuse. Ship alongside electronics-first verification (Rung 2).
8. **Auto-build log (#4)** — Medium effort, enables long-term recall and future sharing/documentation. M3+M4+M6 reuse; no new vision beyond what Rung 1 already captures.

**Deferred (require frontier capability or external dependencies):**
- Solder-joint inspection (#5) and skill coaching (#10): defer to Rung 2/3 — research-grade reliability only.
- Parts inventory (#3): medium-to-high effort standalone; worth doing but not before Rung 1.
- Measurement (#6): useful but low demand; ±10% accuracy from monocular often not enough for precision builds.
- Parts ordering (#9): depends on Shopping spoke existing.

---

## Part 4 — Top 3 Prior-Art Systems to Study in Depth

1. **LightGuide Systems (lightguidesys.com)** — the only commercial system physically similar to an overhead-projector/camera setup over a work surface. Study their step-advance gating logic, error-prevention UI patterns, and the integration interface to factory systems — all map onto the Artemis build-plan + verification design.
2. **Tulip Interfaces (tulip.co)** — best reference for the build-plan authoring UX (AI Composer from PDF → structured steps), per-step data capture patterns, and dynamic variant routing. Their open API documentation is public.
3. **Augmentir (augmentir.com)** — best reference for skill-adaptive instructions, AI coaching agents, and the quality-inspection checklist format. Their 2025 AI Agent Studio is the closest analog to what Artemis is doing with M7 recipes applied to assembly.

---

*Sources used in this research:*
- [Tulip AI Work Instructions](https://tulip.co/blog/ai-work-instructions/)
- [LightGuide smartAR Workstation](https://www.lightguidesys.com/smart-ar-workstation/)
- [LightGuide AI Capabilities](https://www.lightguidesys.com/ai-capabilities/)
- [Augmentir AI Agent Studio](https://www.augmentir.com/news/augmentir-unveils-industrial-ai-agent-studio-bringing-autonomous-agents-to-frontline-operations-in-manufacturing)
- [Augmentir Quality use case](https://www.augmentir.com/use-cases/quality)
- [Apprentice.io Augmented Work Instructions](https://www.apprentice.io/product/packages/augmented-work-instructions-awi)
- [ProGlove + Picavi pick-by-vision](https://www.proglove.com/industrial-wearables/material-handling-systems-optimized-for-human-workers-with-picavi-and-proglove/)
- [arXiv 2507.17304 — Learning-based Stage Verification](https://arxiv.org/pdf/2507.17304)
- [Roboflow — Visual Assembly Verification](https://blog.roboflow.com/visual-assembly-verification/)
- [Springer 2025 — PCB Solder Inspection ML](https://link.springer.com/article/10.1007/s10845-025-02748-5)
- [BricksFanz — LEGO AR instructions future](https://bricksfanz.com/the-future-of-lego-instructions-building-in-ar/)
- [Buildcam AI Movie Maker](https://www.buildcam.io/features/ai-movie-maker)
- [Monocular Depth Estimation — Apps 2025](https://doi.org/10.3390/app15084267)
- [Roboflow — Workplace Safety AI](https://blog.roboflow.com/workplace-safety-ai/)
- [CableEye Talking Guided Assembly](https://www.camiresearch.com/Campaigns/NewsRelease/nr-cami-research-features-talking-guided-assembly-and-automation-readiness-at-ewpte23.html)
- [AR Assembly Guidance cuts errors — PatSnap](https://www.patsnap.com/resources/blog/articles/ar-assembly-guidance-cuts-errors-in-electronics-manufacturing/)

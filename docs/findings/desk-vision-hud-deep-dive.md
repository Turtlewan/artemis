# Deep Dive: AI-Systems / Vision — Session-scoped overhead desk-vision HUD ("Iron Man" assistant)

**Date:** 2026-06-11
**Mode:** apex-deep-dive (analysis only — no spec, no code)
**Confidence:** MEDIUM-HIGH on architecture; model fps/latency figures are COMMUNITY-grade (no authoritative M4 Pro VLM benchmark table exists). Re-verify model pins before the spec freezes (fast-moving; ~30-day clock on the VLM/detector landscape).
**Grounded by:** 3 parallel Sonnet research agents (detection/tracking · VLM-ID + Apple FM · capture/HUD/IPC), 2026-06-11.

---

## What the owner decided (locked before research)
- **Use case:** JARVIS-style "what am I looking at" assistant. Summon → stays live for the work **session** → live annotated **viewfinder window on the Mac screen** (no AR goggles). Camera mounted **overhead, top-down** over the desk.
- **Depth = full end-state:** SPECIFIC identity (model/value/part#/edition) + fine-text OCR + cross-reference the owner's second brain (M3 RAG + M4 memory) + web lookup + interactive ("point/ask about one tagged object").
- **Framing correction:** this is a **vision *input* to the brain** (like voice, M5), NOT a home-cameras spoke (ADR-011 source-of-truth doesn't apply — there's no external system of record). It does **not** need the homelab ACI Phase-4 Jetson; it runs on the Mini. Buildable after the core spine + (ideally) M3/M4/M5/DR — a late but Mini-local spoke.

## Functional design — owner discussion 2026-06-11 (SCOPE EXPANDED — this is now a build-assistant, not an object identifier)
The elicitation moved the concept well past "identify objects." Final functional shape:
1. **Interaction = voice-first, both directions.** Owner asks by voice ("hey, what am I holding in my hand?"); Artemis **speaks** the answer **and** renders on-screen annotations. (Ties directly into the M5 voice loop — vision is another I/O surface on the same brain.)
2. **Two-tier annotations:** a **primary callout card** for the item in focus (held/asked-about) + **secondary smaller labels** on the other related components in view.
3. **Active build assistant** (not a labeler): guides ("next, solder R3 here"), tracks progress, and catches mistakes ("that's a 10k, you want the 4.7k"). The components in view are understood as **parts of the owner's current project**, labeled in that context.
4. **Steps source = accumulated CONVERSATIONAL context** with Artemis (captured in M4 memory / the Productivity Projects module across sessions) — NOT an uploaded manual, NOT invented from nothing. "Artemis will have the context from me discussing this project with it." Precision of the guidance/verification is therefore **gated by the detail the owner shared in conversation.**
5. **Progress tracking = autonomous watch + auto-advance + live mistake-catching** — owner's chosen END-STATE ("I see R3 is in — next, R4"; "careful, that cap is backwards"). This is the research-frontier piece. → north-star target, not a v1 deliverable (see ladder).
6. **Domain = general hands-on building** — electronics + woodworking + model kits + furniture + repair (bounded to multi-step *builds/assembly/repair*; not unbounded life-vision, not cooking).
7. **Implied/derived (assumptions, confirm later):** project state **persists across sessions** (it's a Project); the assistant is **proactive during a session** (volunteers warnings — entailed by autonomous-watch); a **generic "what's this?" mode** also exists for when no project is active.

## ⚠️ Honest feasibility verdict (planning must not silently spec this)
The owner picked the **maximal-difficulty option at every fork**, and three of them are in **direct mutual tension**:
- **Autonomous visual verification REQUIRES precise reference data** (the exact schematic / BOM / plan) to say "that should be a 4.7k at R3." But the **steps source is loose conversational context** (#4), which usually does NOT carry per-step precision. *You cannot reliably verify against a plan you don't precisely hold.* → Internal contradiction.
- **General-domain (#6) × autonomous-verify (#5)**: assembly verification is inherently domain-specific (a solder joint ≠ a wood joint ≠ a furniture step). A *general* autonomous "you did it wrong" verifier across unbounded build types is **beyond reliable 2026 capability** — it is an open research problem, not a product.
- **Net:** the fully-autonomous, general-domain, verify-from-loose-context version **is not buildable as a reliable product with mid-2026 tech.** It is a research program. The *vision* is coherent and worth locking as a north star; the *hardest version* must be reached by capability growth, not specced as a single milestone.

**Resolution of the tension (design rule):** rigorous verification is **gated on reference precision.** Default = loose sanity-checking from conversational context (honest about its limits). When the owner wants real "you did it wrong" rigor, the conversational source **escalates to ingesting the actual schematic/plan** (reuse M3 Docling + ColQwen/Qwen3-VL visual-doc — already pinned) or finding it on the web (DR engine). Conversation carries intent + loose guidance by default; precise verification is an opt-in that pulls in a real reference.

## The build-plan authoring surface — the "builder" (owner Q, 2026-06-11)
The owner intuited that verification needs an "answer key" to check against → a **structured build plan** (ordered steps + parts/BOM + expected per-step state + optional reference schematic/diagram) that must live somewhere and be authored. This is the concrete home of the precise-reference escalation above.
- **NOT a new standalone app** — a **build-project surface layered on existing pieces:** Productivity → **Projects module** (a "build project" = a richer Project; ADR-013 already homes Project/Goal entities) + the **CLIENT app** (a build-project screen alongside Chat/Review) + **M3 ingestion** (pull in the schematic/manual) + **DR engine** (fetch a kit's instructions from the web).
- **Authoring mode = BOTH (silent default, openable) — owner decision.** Artemis assembles the plan silently from conversation (zero setup); the plan is always **openable in the builder** to review/correct or to ingest the real schematic before a high-stakes step. Frictionless by default, opt-in rigor — directly operationalizes the tension-resolution rule.
- **Functional decision #8** (supersedes the earlier "implied" note): the builder is a first-class component of the milestone, not optional polish.

## Build ladder — the rungs toward the north star (each rung is a real, shippable product)
The autonomous-watch end-state is the *target the architecture must not preclude*; the build climbs to it. This also feeds Artemis's capability/self-training lane (continuous assembly-understanding is exactly the kind of capability the distillation + curiosity loops can grow over time).
- **Rung 0 — Snapshot ID.** "What's this?" → one photo → Qwen3-VL ID + info + memory/web enrich. No HUD, no tracking, no sidecar. Buildable on the core spine alone. ~80% of the "magic moment" at ~10% of the build.
- **Rung 1 — Live HUD, reactive.** Live viewfinder + voice ask, primary + secondary annotations, identifies components, narrates steps from conversational context — but the **owner drives progress** ("next") and Artemis **spot-checks on request** ("check this"). The first genuinely-impressive real version. Electronics-first (verification most tractable), generic ID elsewhere.
- **Rung 2 — Assisted verify.** On-demand visual verification against whatever reference precision exists; mistake-catching where the reference is precise (escalate-to-schematic path active).
- **Rung 3 — Toward autonomous watch.** Continuous progress inference + proactive live warnings, **grown via the capability lane**, starting in the most tractable domain (electronics) and widening as the capability improves. The north star lives here — approached, not switch-flipped.

## Context read
status.md · ADR-011 (spoke source-of-truth — N/A here, see correction above) · ADR-013 (M4 entity backbone — the "your notes about this item" path) · overview.md (Swift-sidecar pattern from M5 voice · M2 privacy wall · `artemis.untrusted`/DR-a · knowledge layer already pins Apple Vision OCR + Qwen3-VL + MLX) · homelab-control-plane.md (Jetson = P4, NOT needed) · wwdc-2026 research (Apple FM multimodal flagged DISPUTED — now resolved below).

---

## The pipeline (fixed — only the ID tier is a real fork)
```
capture (overhead cam)
  → fast loop (every frame, in-process Swift): open-vocab detect + track → boxes
  → OCR on demand (Apple Vision): fine text
  → [SUMMON one object] → crop → slow loop: specific-ID VLM → brain enrich (M3+M4+web)
  → render: viewfinder window + floating boxes/labels/info-cards (CALayer overlay)
```
The fast loop, OCR, capture and render are **settled** (Apple-native, in-process Swift). The only architectural decision is **where the specific-identification VLM runs** — the local↔cloud axis.

---

## Approaches considered

### Option A — All-Apple on-device (Apple Vision + Apple Foundation Models for ID)
**What:** Apple Vision framework for detect-seed/track/OCR + Apple FM multimodal (image input) for the specific identification — entirely Swift-side, zero cloud, zero Python.
**Pros:** Maximally private; free; simplest deployment; no GPU contention with the MLX brain.
**Cons / RULED OUT for the stated target:** Research resolved the DISPUTED flag — **Apple FM multimodal cannot do fine-grained specific identification.** It's a ~20B sparse model with 1–4B active params, optimized for summarize/extract/UI-reasoning; multiple developer reports show image queries are task-scoped (some return "I can't describe images directly"). No FGVC/product-ID capability documented. Its barcode/OCR *tools* read clean labels but give no semantic product knowledge ("10kΩ from color bands" — no). Apple Vision separately **has no open-vocabulary detection at all** (fixed ImageNet/animal classifiers only) — so it can't even carry the detection layer's "tag arbitrary desk clutter" requirement alone.
**Risks:** Builds the whole thing then discovers it can't ID the exact resistor/part — the core promise fails.
**Effort:** Low — but **doesn't meet the requirement.** Eliminated as the *identification* tier. (Apple Vision is still retained for tracking + OCR — see recommendation.)

### Option B — Local MLX VLM on the Mini (Apple Vision HUD + Qwen3-VL via the Python brain)
**What:** Swift owns the fast HUD (open-vocab detect + track + OCR + render); on summon, a crop goes to the Python brain which runs **Qwen3-VL-30B-A3B (MoE), 4-bit, mlx-vlm** for the specific ID, then enriches via M3/M4/web. Fully local.
**Pros:** Strong fine-grained ID + best-in-class local OCR (OCRBench ~896-class); **fully local — honors the "no owner data in cloud" wall** with no exceptions; MoE means ~10–12 GB active, co-resident with the 14B text LLM (~9–10 GB) + voice (~3–7 GB) inside 48 GB with headroom; only runs **on-demand** (slow loop), so steady-state GPU contention with voice/brain is low.
**Cons:** Heaviest local model; ~80 ms–several-seconds per identification depending on crop/resolution; on the hardest degraded inputs it's ~1 tier below cloud Claude; competes with voice/brain for Metal GPU *during* an identification call.
**Risks:** Latency on the worst images; memory pressure if voice + brain + VLM all fire at once (mitigated: VLM is on-demand, not continuous).
**Effort:** High — new Swift vision sidecar + Python VLM serving + brain-enrich wiring.

### Option C — Hybrid: local HUD + gated cloud-Claude escalation for hard IDs
**What:** Option B as the default, **plus** an owner-gated escalation: when the local VLM's confidence is low (hedges / returns generic), offer to send that one crop to **cloud Claude vision** (the existing teacher path, ADR-003 pattern) for a better ID.
**Pros:** Best possible ID quality on the hardest cases (Claude meaningfully beats local on part#/edition/occlusion/glare via OCR + world-knowledge cross-referencing); escalation is rare and bounded.
**Cons / privacy fork:** **Frames leave the box.** Unlike email-teacher (text the owner already received), a desk crop is a live camera image of the owner's private space — a *stronger* privacy exposure. A crop could contain a sensitive document.
**Risks:** Silent/automatic escalation = privacy violation; cost creep; owner surprise.
**Effort:** Medium on top of B (reuses the teacher egress + ADR-003 non-sensitive posture).

---

## Recommendation
**Build B as the spine; add C as an explicit, default-OFF, per-summon owner opt-in. Reject A as the ID tier (keep Apple Vision only for tracking + OCR).**

Concretely — a **layered local-first pipeline**:

**Layer 1 — Fast HUD loop (in-process Swift, every frame):**
- **Detection: YOLOE-26-S (open-vocab), exported to CoreML with a SESSION-SCOPED vocabulary.** Key insight from the research + the use case: the feature is *session*-scoped, so the object class set is stable for a session. That lets us re-parameterize YOLOE's open-vocab text classes **at session start** and run the fast CoreML/ANE export **in-process** — getting open-vocab flexibility *without* streaming frames to Python every tick (the IPC anti-pattern). Dynamic per-frame arbitrary prompting (which would force the MLX/Python path) isn't needed for a desk.
- **Tracking: ByteTrack** (IoU + Kalman, <2 ms/frame). The overhead/planar scene has no occlusion → no ReID → BoT-SORT unnecessary.
- **Seeded tracking: `VNTrackObjectRequest`** can hold a box between detector frames (detector at ~10–15 fps, tracker at full frame rate).
- **OCR: Apple Vision `RecognizeDocumentsRequest`/`VNRecognizeTextRequest`** on demand — excellent, free, in-process.

**Layer 2 — On-demand identification (slow loop, Python brain):**
- On summon, crop the tracked object's pixel region, JPEG-encode (~5–20 KB), send over **UDS + gRPC** (bidirectional stream, persistent connection) to the brain.
- **Local VLM pin: Qwen3-VL-30B-A3B-Instruct, 4-bit, mlx-vlm** (fallback Qwen3-VL-8B if memory is tighter than modeled). Fuse with the Apple Vision OCR text already extracted.
- Enrich: M3 RAG + M4 memory (`memory.resolve_entity` → "your notes on this part") + DR web lookup → an info card.
- **Optional fast tier:** evaluate **Apple FastVLM (0.5B–3B, MLX, <120 ms TTFT)** as a *quick first-pass* describer before committing the heavy 30B — gives an instant label, upgrades to Qwen3-VL on hold.

**Layer 3 — Escalation (Option C, gated):**
- Low local confidence → **offer** cloud-Claude vision for that one crop. **Default OFF. Never automatic. One explicit owner action per escalation.** Treated as non-sensitive teacher egress (ADR-003) but with a stronger consent bar because it's a live camera image.

**Swift ↔ Python split:** Swift sidecar (mirrors the M5 audio sidecar) owns capture + detection + tracking + OCR + HUD render — all in-process, ANE/CPU, **off the MLX GPU**. Python brain owns the heavy VLM + enrich. Only **crops on demand** cross the boundary — never raw frames per tick.

### Why this fits Artemis specifically
- **Honors the privacy wall by default** (overview L13 "no owner data in the cloud"): the entire default path is local; cloud is an explicit exception, not a dependency.
- **Reuses locked decisions:** Apple Vision OCR + Qwen3-VL + MLX are *already pinned* for visual-document understanding in the knowledge layer (overview §M3) — this spoke shares them. The Swift-sidecar pattern is the M5 voice precedent. ADR-013's `memory.resolve_entity` is exactly the "your notes about this item" hook. ADR-003 is the escalation precedent.
- **Low steady-state contention:** the always-on fast loop runs on ANE/CPU; the GPU-heavy VLM is on-demand only.
- **No Jetson, no Phase-4:** runs entirely on the Mini — correcting the backlog's "ACI edge" framing.

---

## Trade-offs you're accepting
- **On the hardest images, local-only is ~1 tier below cloud** — accepted, with C as the escape hatch the owner consciously triggers.
- **Identification isn't instant** (~100 ms–seconds) — fine for on-demand "tell me about this," not for a continuously-updating label on every object.
- **Real build weight:** a new Swift vision sidecar + Python VLM serving + brain-enrich wiring + a SwiftUI viewfinder/overlay surface. This is a multi-spec milestone, not a one-spec add.
- **Session-vocab detection** trades true per-frame arbitrary open-vocab for in-process speed; an object whose class wasn't in the session vocabulary needs a re-parameterize or a VLM fallback to name it.

## Implementation implications (for the eventual spec/milestone)
- Likely a **multi-spec milestone** (call it e.g. M-VISION), dependency-gated behind M3 (knowledge), M4/ADR-013 (memory + entity backbone), and ideally M5 (voice "ask about it") + DR (untrusted + web). Build after the M8 first-spoke wave.
- **New Swift sidecar** process (capture/detect/track/OCR/render) alongside the audio sidecar.
- **New brain tool(s):** `vision.identify(crop)` → VLM+enrich; registered in the ToolRegistry; reuses `memory.resolve_entity`.
- **Quarantine:** OCR'd desk text is **untrusted input** → route through `artemis.untrusted` (DR-a) before it reaches the privileged brain/tools (a label/document on the desk could carry injected instructions). Clean DR-a reuse.
- **Models to pin (re-verify at spec time):** YOLOE-26-S (CoreML export, session vocab) · ByteTrack · Apple Vision OCR · Qwen3-VL-30B-A3B-4bit (mlx-vlm), fallback Qwen3-VL-8B · optional FastVLM fast-pass · cloud Claude vision (escalation).
- **IPC:** UDS + gRPC-Swift v2 (NIO transport, per WWDC26/265) between sidecar and brain.
- **HUD gotchas to bake into the spec:** Y-flip before `layerRectConverted` (bottom-left → top-left); disable implicit CALayer animations (kills rubber-band jitter); triple-buffer box updates on the display tick; fast-loop/slow-loop decoupled via a Swift actor.

## Risks to monitor
- **Model-pin staleness:** the VLM/detector landscape moves monthly; YOLOE-26 MLX fps and Qwen3-VL latency are COMMUNITY estimates — benchmark on the actual Mini before committing.
- **Memory pressure** if voice + brain + 30B-VLM peak together → consider 8B fallback or serialize VLM behind a lock; revisit if 64GB is bought.
- **Escalation creep:** watch that cloud-Claude stays rare and owner-gated; instrument via OBS.
- **Open-vocab miss rate:** if session-vocab detection misses too many desk objects, fall back to a periodic Python-MLX YOLOE pass or VLM-names-the-scene.

## Opposing view (strongest case against)
"You're building a JARVIS HUD before the assistant can even talk or remember. This is the most hardware/CV-heavy thing in the whole roadmap, depends on M3+M4+M5+DR all existing, and serves a narrow desk use case. The honest MVP is **on-demand single-snapshot** ('what's this?' → one photo → Qwen3-VL → answer) with **no live HUD, no tracking, no sidecar** — 80% of the value at 10% of the build. The live annotated viewfinder is the cinematic 20% that costs the other 90%. Ship the snapshot first; earn the HUD." — A real critique; the counter is the owner's explicit end-state preference and that designing the full thing now correctly constrains the session-vocab/sidecar/quarantine seams. But the **snapshot-first build slice** is the right first increment when this milestone is eventually scheduled.

# ADR-014 — Vision build-assistant: overhead desk-vision input + guided-build subsystem (DESIGNED, deferred)

- **Status:** Accepted (architecture + intent locked) · **milestone DEFERRED** (dependency-, capability-, and hardware-gated)
- **Date:** 2026-06-11
- **Deciders:** owner + planning
- **Relates:** overview.md §"Interaction surfaces" (this is a new vision *input* surface, sibling to voice/M5) · ADR-001 (stack: Swift sidecar pattern, Python MLX brain) · ADR-003 (cloud-Claude teacher = the escalation precedent) · ADR-007/M3 (knowledge layer already pins Apple Vision OCR + Qwen3-VL + MLX visual-doc — reused here) · ADR-009/DR-a (`artemis.untrusted` — OCR'd desk text is untrusted input) · ADR-013/M4 (`memory.resolve_entity`, Project/Goal entities — the "your notes on this part" + build-project home) · Productivity Projects module + CLIENT app (the build-plan "builder" surface) · **NOT** ADR-011 (no external system-of-record → source-of-truth model does not apply). Full analysis: `docs/findings/desk-vision-hud-deep-dive.md`.

## Context

The owner wants a JARVIS-style workshop assistant: an **overhead, top-down camera** over the desk, with a **live annotated viewfinder window on the computer screen** (explicitly **no AR/VR goggles**). Summoned for a work *session*, it identifies the parts in view, and acts as an **active build assistant** for general hands-on builds (electronics, woodworking, model kits, furniture, repair) — guiding steps, and at the end-state **watching and verifying** the work ("that's a 10k, you want the 4.7k"). Interaction is **voice-first both ways** ("hey, what am I holding?" → spoken answer + on-screen annotation), with a **primary callout** on the focus item and **secondary labels** on the related components.

Two framing facts drove the architecture:
1. **This is a vision *input* to the brain, like voice — not a home-cameras spoke.** There is no external system of record, so ADR-011's source-of-truth model is irrelevant. It runs entirely on the Mini; it does **not** require the homelab ACI Phase-4 Jetson (correcting the original BACKLOG framing).
2. **The owner selected the maximal option at every functional fork** (active build-assistant · autonomous watch-and-verify · general domains · steps from loose conversational context). Mid-2026 research (3 parallel agents, see findings) establishes that the *fully-autonomous, general-domain, verify-from-loose-context* version **is not a reliable product with current technology** — it is a research program — and that two chosen forks are in direct tension: **autonomous verification requires a precise reference (schematic/BOM/plan), but the chosen knowledge source is loose conversation**, which usually lacks per-step precision. The decision therefore separates the **locked end-state vision** from a **capability-grown build ladder**.

## Decision

1. **Pursue the vision build-assistant as a designed end-state, built via a capability ladder — not a single milestone.** The autonomous watch-and-verify end-state is the **north star the architecture must not preclude**; it is *approached*, not switch-flipped. Rungs (each a shippable product):
   - **Rung 0 — Snapshot ID:** "what's this?" → one photo → Qwen3-VL ID + info + memory/web enrich. No HUD/tracking/sidecar. Buildable on the core spine.
   - **Rung 1 — Live HUD, owner-driven:** live viewfinder + voice + primary/secondary annotations + step narration from conversational context; owner advances ("next"), Artemis spot-checks on request. Electronics-first; generic ID elsewhere.
   - **Rung 2 — Assisted verify:** on-demand visual verification against the build-plan; mistake-catching where the reference is precise.
   - **Rung 3 — Toward autonomous watch:** continuous progress inference + proactive live warnings, **grown via the capability/self-training lane**, electronics-first, widening as the capability matures.

2. **Pipeline = layered local-first with a gated cloud escalation.** Apple Vision (detect-seed/track/OCR) + an **open-vocabulary detector (YOLOE-class) with a session-scoped vocabulary** run **in-process in a new Swift "vision sidecar"** (mirrors the M5 audio sidecar; on ANE/CPU, off the MLX GPU). On summon, only an **object crop** crosses to the Python brain (UDS + gRPC) for fine-grained ID via **Qwen3-VL-30B-A3B (MLX, 4-bit)** (fallback 8B); the brain enriches via M3 RAG + M4 memory (`memory.resolve_entity`) + DR web. **Raw frames never stream across the boundary per tick.** Fast loop (boxes/tracking every frame) is decoupled from the slow loop (on-demand VLM).

3. **Cloud escalation is opt-in, default-OFF, per-summon, never automatic.** Camera frames of the desk are owner-private (M2 wall). For the hardest IDs, the owner may consciously escalate one crop to cloud-Claude vision (ADR-003 non-sensitive teacher posture, stronger consent bar because it is a live image of private space).

4. **Verification rigor is gated on reference precision.** Default = loose sanity-checking from conversational context (honest about limits). Real "you did it wrong" rigor requires a precise reference; the design escalates to **ingesting the actual schematic/plan** (M3 Docling + ColQwen/Qwen3-VL) or fetching it (DR engine).

5. **A build-plan "builder" surface exists — silent default, openable (not a standalone app).** Artemis assembles the build-plan (ordered steps + parts/BOM + expected per-step state + optional reference) **silently from conversation**; it is **openable** in a build-project screen to review/correct or to ingest the real schematic before a high-stakes step. It is layered on the **Productivity Projects module + CLIENT app + M3 ingestion + DR web** — a richer Project (ADR-013 Project entity), not a new binary.

6. **OCR'd desk text is untrusted input** → routed through `artemis.untrusted` (DR-a) before reaching the privileged brain/tools (a label or document on the desk can carry injected instructions).

7. **Deferred.** No specs are drafted now. Dependencies (M3/M4/M5/DR/Projects/CLIENT) are unbuilt; the model pins need re-verification on the actual Mini; the Rung-3 top is capability-gated. When dependencies land, **Rung 0/1 become the first specs.** Handled like the Finance spoke (DESIGNED; specs pending core).

## Consequences

- **One net-new heavy component** — the Swift vision sidecar — plus the build-plan surface; everything else (VLM, OCR, memory/entities, voice, ingestion, web, untrusted boundary) **reuses already-locked subsystems**, several of which already pin the exact models this needs (Apple Vision OCR + Qwen3-VL + MLX).
- **The end-state is captured without speccing fiction.** The ladder lets the build start at real value (Rung 0/1) while the hardest capability is grown, feeding (and fed by) Artemis's self-training/capability lane.
- **Honest capability ceiling is on record:** general autonomous assembly-verification is past reliable 2026 tech; expectations are set against the ladder, not the north star.
- **Steady-state GPU contention is low** (fast loop on ANE/CPU; heavy VLM on-demand only), but a simultaneous voice+brain+VLM peak needs a memory guard (8B fallback or a serialization lock); revisit if 64GB is bought.
- **Widening research — FOLDED 2026-06-11** (detail: `docs/findings/desk-vision-alt-implementations.md` + `docs/findings/desk-vision-capability-menu.md`). The two agents widened *how* and *what*; none reopens the core decision. Keepers, mapped to the ladder:
  - **Rung 0 (snapshot):** add a **CLIP personal-parts retrieval-ID tier** *before* the VLM — embed the owner's photographed parts into a local FAISS index, query at 5–20 ms; cuts VLM calls ~70% for owned parts and gives deterministic IDs the VLM can hallucinate (YOLOE→CLIP→VLM). · **Benchmark CoreML-ANE for a 7B VLM** (CoreML-LLM, May 2026) before committing to 30B-MLX: if a 7B runs on the ANE acceptably, split runtimes — **ANE for the VLM, Metal GPU free for the Apple Vision + YOLOE sidecar** (revises decision #2's pin). · **Auto-BOM from a parts photo** (reuses M3 Docling + Qwen3-VL) — the "magic-moment" feature.
  - **Rung 1 (live HUD):** **AprilTag/ArUco fiducials** on jigs/trays/PCB corners (sub-mm 6-DOF, 30+fps CPU, no GPU; also the projector calibration grid later) · **dedicated second monitor as the HUD** (zero-code ergonomic win — vertical display at the back of the desk) · **safety warnings** (mains/blade/chemical in frame → M6 proactive hook) · **modular step-recipes** (maps onto M7 recipe store) · **resume-across-sessions**, **multi-project queue**, **"do I have everything?" gap-check**.
  - **Rung 2 (assisted-verify):** wiring/pinout guidance · quality inspection (solder-joint/alignment) · build-log/keyframe history.
  - **Rung 3 (autonomous-watch — the hard rung):** **RGB-D depth camera (Orbbec Femto Bolt, confirmed Mac/UVC; ~$350–500)** for hand-occlusion recovery — the gating CV problem · **hand-keypoint action classifier** (Apple Vision 21-keypoint stream → CreateML/LSTM recognizing pick/place/solder/measure). **Action: start PASSIVELY recording labeled session clips during Rung 1–2** so the dataset for the watch-level capability grows for free (feeds the self-training/capability lane). · **Projector spatial-AR** (short-throw pico + camera→projector homography) as the *best ergonomic end-state* — annotations on the physical parts, no head movement; needs dimmable lighting; pursue after detection is solid. (Not goggles — desk-surface AR.)
  - **Prior art to mirror:** **LightGuide** (overhead-cam + projection; step-advance gating + error-prevention UI) · **Tulip** (build-plan authoring UX → the "builder" surface) · **Augmentir** (AI coaching + quality checklists ≈ M7 recipes for assembly).
  - **Explicitly deprioritized:** MediaPipe Hands (Apple Vision better on Mac) · external GPU/ACI vision · iPhone-LiDAR-via-Continuity (prototype-grade; graduate to Orbbec).

## Alternatives considered

- **All-Apple on-device ID (Apple Foundation Models for identification)** — *rejected for the ID tier.* Research resolved the WWDC DISPUTED flag: AFM multimodal does coarse description, **not fine-grained specific identification**, and Apple Vision has no open-vocabulary detection. (Apple Vision retained for tracking + OCR only.)
- **Pure cloud (Claude vision) pipeline** — *rejected as default:* violates the local-first/no-owner-data-in-cloud wall; kept only as a gated, opt-in escalation.
- **Build it as a one-shot milestone at full (autonomous/general) scope** — *rejected:* not reliably buildable with 2026 tech and internally contradictory (verify-without-precise-reference). Replaced by the ladder.
- **Snapshot-only (no live HUD ever)** — *rejected as the end-state* (owner wants the live workshop HUD) but **adopted as Rung 0**, the first build increment.
- **Standalone "builder" app** — *rejected:* the build-plan surface is layered on the existing Projects module + Client app, not a new binary.
- **Home-cameras spoke under ADR-011 / ACI Phase-4 Jetson edge** — *rejected:* this is a Mini-local vision *input*, not a monitored-camera spoke; no external source-of-truth; no edge box needed.

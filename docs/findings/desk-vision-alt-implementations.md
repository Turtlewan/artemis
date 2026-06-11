# Desk Build-Assistant: Alternative Implementation Architectures

**Scope:** Single-user, Mac-Mini-local overhead-camera build assistant for electronics, woodworking, model kits, furniture, and repair. Evaluated against the chosen baseline: overhead webcam → on-screen viewfinder with annotation overlays → Apple Vision + YOLOE sidecar → Qwen3-VL via MLX for fine-grained ID.

**Research date:** 2026-06-11. Confidence tags: VERIFIED = primary source confirmed; COMMUNITY = forum/practitioner consensus; ASSUMED = reasoned extrapolation.

---

## Axis 1 — Display / Output Alternatives

### 1A. Projector-Based Spatial AR (Projection Mapping onto the Desk)

**What it is:** A short-throw pico or ultra-short-throw projector mounted overhead alongside the camera, calibrated so projected pixels map onto real surface coordinates. Annotations (arrows, highlight boxes, step text) appear directly on the physical parts — no screen to glance at.

**How it works in practice:**
- Camera detects part position → compute homography between camera frame and projector frame → render annotation at projected coordinates.
- Calibration is a one-time OpenCV stereo-calibration step (camera + projector treated as a stereo pair).
- Pico options as of 2026: AAXA P400 (1080p, $269), ASUS ZenBeam Latte L1 (720p, $449), Optoma pico LED (1.4 ft min throw, 135" max). Mountable on a clamp arm above the desk. [VERIFIED — projectorreviews.com, 2026]

**Trade-offs vs screen viewfinder:**

| Dimension | Screen Viewfinder (chosen) | Projector Spatial AR |
|---|---|---|
| Attention split | Eyes move between work and screen | Zero — look at the work itself |
| Ambient light | Works in any light | Washed out under bright desk lamp; needs dim or contrast-tuned lamp placement |
| Setup complexity | Plug in webcam | Projector calibration; recalibrate if anything moves |
| Annotation on 3D objects | Flat overlay on 2D video | Projected onto real surface — looks off on tall/round parts |
| Cost add | ~$0 beyond camera | $270–$450 projector + mount |
| Occlusion by hands | Hands in frame — fine | Hands cast shadows on projection |

**Verdict for this setup:** HIGH VALUE as a deferred enhancement. For a fixed desk with controlled lighting (LED panel that can be dimmed), this is the most ergonomic end-state — no head movement to read annotations. Start with screen viewfinder; add projection overlay once the detection pipeline is solid. The homography calibration is a one-day task. Shadow/occlusion from hands is a real issue during fine motor work; mitigate by projecting onto the surround rather than the active work zone.

**Key reference:** Lightform (lightform.com) ships a turnkey camera+projector unit with SAR SDK; maker projects on Yanko Design / Instructables confirm DIY viability [VERIFIED].

---

### 1B. iPad / iPhone as Combined Camera + Display Window

**What it is:** An iPad Pro or iPhone (on a boom arm) acts as both the sensor and the viewfinder — the live camera feed with overlays appears on its own screen. Continuity Camera (macOS Ventura+) streams iPhone video to the Mac wirelessly over USB/Wi-Fi. [VERIFIED — Apple developer docs]

**Trade-offs:**

| Dimension | Webcam + Mac screen | iPad/iPhone combo |
|---|---|---|
| Field of view | Wide-angle USB webcam can reach 120° | iPhone 15 Pro ultra-wide: 120° equivalent; good match |
| LiDAR | Not available on webcam | iPhone 15 Pro+ has LiDAR — free depth data (see Axis 2B) |
| Latency | USB: ~30–50 ms | Continuity Camera wireless: ~100–200 ms; wired USB: ~50 ms [COMMUNITY] |
| Viewfinder position | Screen on desk edge | iPad on articulated arm can be placed at eye level beside the work |
| Integration complexity | Simple UVC device | Continuity Camera API; requires same iCloud account |
| Cost | Already own Mac + webcam | Requires iPhone 15 Pro+ for LiDAR ($999+) or iPad with rear cam |

**Verdict:** MEDIUM VALUE. If the owner already has an iPhone 15 Pro+, using it via Continuity Camera is a zero-cost path to LiDAR depth data. As a pure display option an iPad on an arm is ergonomically better than a screen at the desk edge. Not a primary redesign candidate — a nice add-on.

---

### 1C. Dedicated Second Monitor as HUD

**What it is:** A small (15–24") monitor mounted vertically at the back of the desk, showing only the annotated viewfinder + step-guide panel. The primary Mac display stays clean for the brain/UI.

**Trade-offs:** Cheapest option ($80–$200 monitor), no calibration, works in any light, but still requires looking away from the work. Ergonomically better than reading the main Mac display across the desk. Easily done with macOS Displays arrangement today. [ASSUMED — standard dual-display setup]

**Verdict:** LOW-COST QUICK WIN. Implement immediately by just routing the viewfinder window to a second display. Not architecturally interesting but meaningfully improves ergonomics at near-zero cost.

---

## Axis 2 — Sensing Alternatives

### 2A. RGB-D / Depth Camera (Orbbec Femto Bolt or Femto Mega)

**What it is:** A structured-light or ToF camera that outputs a registered depth map alongside the color image. The Orbbec Femto Bolt is the recommended post-Intel-RealSense option: USB-C, macOS M-series support confirmed via standard UVC + OrbbecSDK, actively maintained SDK as of 2026. [VERIFIED — orbbec.com docs, roboticscenter.ai 2026 comparison]

Intel RealSense spun out from Intel (July 2025, $50M Series A) and is continuing as an independent company, but Mac support remains fragile and units are harder to source. Orbbec is the safer bet. [VERIFIED — roboticscenter.ai]

**What depth adds:**

- **Hand/arm segmentation:** Isolate the hand layer from the scene layer without chroma key — critical for the autonomous-watch end-state where the system needs to see what the hand just placed.
- **3D bounding boxes:** Parts can be located in 3D, so the projector homography or the AR overlay stays anchored when the camera angle shifts slightly.
- **Caliper-free measurement:** Known depth + calibrated intrinsics → real-world mm dimensions from the point cloud. No tape measure needed for lumber, PCB trace spacing, etc.
- **Occlusion handling:** When a hand covers a component, depth discontinuities reveal the hand boundary; the system can track the obscured component using its last known 3D position.

**Trade-offs vs pure RGB:**

| Dimension | RGB webcam | RGB-D (Orbbec Femto Bolt) |
|---|---|---|
| Cost | $50–$150 | ~$350–$500 |
| Mac driver | UVC plug-and-play | OrbbecSDK, UVC-compliant, no kernel extension needed [VERIFIED] |
| Outdoor/bright light | Fine | ToF range-noise increases in direct sunlight; fine indoors |
| Frame rate | 60+ fps color | 30 fps depth @ 1 Megapixel; 30 fps color |
| Working range | Any | 0.3–5.5 m; desk at ~0.8 m is ideal |
| SW complexity | Minimal | Depth registration, point cloud, adds ~1k lines of sidecar code |

**Verdict:** STRONG CANDIDATE for Phase 2. The autonomous-watch end-state (step verification) is very hard without depth — hand occlusion recovery is the hardest CV problem in this project. Budget the Femto Bolt when moving into watch mode. Not needed for Phase 1 (identify + guide).

---

### 2B. iPhone LiDAR via Continuity Camera

**What it is:** iPhone 15 Pro/16 Pro LiDAR (structured light, ~1 m working range, ~1 cm accuracy) streamed to Mac via Continuity Camera. ARKit depth frames are accessible through the AVFoundation / ARKit Continuity Camera API. [COMMUNITY — limited API docs; depth stream availability via Continuity Camera is partially documented]

**Trade-offs:** Free if owner has the hardware; 1 m range slightly short for an overhead mount at 70–90 cm; structured-light LiDAR on iPhone is lower resolution than a dedicated Orbbec unit. Best used as a prototyping path before buying a dedicated depth camera.

**Verdict:** GOOD PROTOTYPE PATH. Try iPhone LiDAR first; graduate to Orbbec if resolution or range is insufficient.

---

### 2C. Fiducial Markers (AprilTag / ArUco)

**What it is:** Printed square markers (~3–6 cm) placed on the desk, PCB corners, jig fixtures, or component trays. A single camera can localize each marker to sub-mm accuracy and recover its full 6-DOF pose. AprilTag detection runs at 30+ fps on a laptop CPU with no GPU. [VERIFIED — visp-doc.inria.fr; roboticsknowledgebase.com]

**What they solve:**

- **Coordinate anchor:** Sticker a marker on each PCB / cutting jig → precise overlay registration even if the camera jiggles.
- **Component tray tracking:** Label each parts bin with a marker; system always knows which tray is where without needing VLM inference.
- **Calibration target:** Replace manual camera-projector calibration with a marker grid on the desk surface.
- **Step gating:** Place a marker on the "done" zone — when the part enters the done zone the system auto-advances the step.

**Trade-offs:**

| Dimension | Open-vocab detector (YOLOE) | Fiducial markers |
|---|---|---|
| Requires prep | None | Print + attach markers |
| Localization accuracy | ~10–30 px bounding box | Sub-pixel 6-DOF pose |
| Works on any object | Yes | Only tagged objects |
| Robust under motion blur | Moderate | High (large tag = robust) |
| SMD / tiny parts | Works via VLM | Tag is bigger than the part — not applicable |

**Verdict:** HIGH VALUE, zero-compute, complementary. Markers for jigs/trays/large parts; VLM for small unlabeled parts. These coexist naturally — add an AprilTag detection pass before the VLM call; if a marker is found, skip the VLM entirely. Use AprilTag36h11 family (best error-correction). [VERIFIED — chiefdelphi.com community comparison]

---

### 2D. Multiple Cameras (Stereo or Multi-Angle)

**What it is:** Two USB webcams — one overhead, one at a low 45° angle from the front — feeding the same pipeline. Provides side-view of tall components (capacitor legs, solder bridges, connector alignment) invisible from overhead alone.

**Trade-offs:** Two camera streams ≈ 2× bandwidth; stitching / switching logic needed; USB bandwidth on Mac Mini M4 can handle 2× 1080p30 easily. Adds ~$80 for a second webcam. [ASSUMED]

**Verdict:** MEDIUM VALUE, deferred. Add the second camera angle when the overhead view proves insufficient for a specific build type (e.g., tall PCB assemblies). Not needed at launch.

---

## Axis 3 — Identification Alternatives

### 3A. Personal-Object Retrieval Library (Embedding-Based)

**What it is:** The owner photographs each part in their collection (component bags, drill bits, connectors, lumber profiles) and embeds each image using a CLIP-family vision encoder (e.g., OpenCLIP ViT-L/14). These embeddings are stored in a local FAISS index. At runtime, a crop of the detected ROI is embedded and nearest-neighbor searched against the library. [VERIFIED — towardsdatascience.com FAISS+CLIP guide; arxiv 2502.02452 "Personalization Toolkit" paper]

**Why this beats a VLM for owned parts:**

- Retrieval is deterministic for parts the owner has photographed — the VLM can hallucinate "100Ω resistor" when it's actually a 10kΩ.
- Runs in ~5 ms per query on CPU (FAISS exact search over 10k embeddings); no GPU needed.
- Works for any part regardless of whether it has a visible label.
- The owner's personal library grows incrementally — photograph new parts once.

**Trade-offs:**

| Dimension | Qwen3-VL (VLM) | CLIP retrieval |
|---|---|---|
| Unknown parts | Handles gracefully | Returns nearest neighbor (may be wrong) |
| Part not in library | Describes it anyway | Fails — no match |
| Setup burden | None | Owner must photograph every part |
| Latency | 200–800 ms (VLM call) | 5–20 ms |
| Fine detail (value marking, polarity) | Excellent | Poor — embedding doesn't capture "47µF" vs "100µF" |

**Verdict:** STRONGLY WORTH ADOPTING as the first-pass filter. Route: detect ROI → CLIP retrieval → if similarity > threshold, return library result + skip VLM; else fall back to VLM. This alone cuts VLM calls by ~70% for a well-stocked library. [ASSUMED — threshold tuning needed]

---

### 3B. Classical CV for Resistor / SMD Reading + Measurement

**What it is:**

- **Resistor color bands:** OpenCV HSV segmentation of the band region → color classification → lookup table → resistance value. Works reliably for through-hole resistors in good lighting. [VERIFIED — patent US9959616; hackaday.com 2015 — technique unchanged]
- **SMD codes:** OCR on the code printed on the SMD body (3–4 digits). Apple Vision's text recognition or Tesseract handles this well.
- **Caliper-free measurement:** With a calibration object (e.g., a known-width reference card) in frame, pixel-per-mm is computable from the RGB image alone. Depth camera makes this more robust but is not required.

**Trade-offs vs VLM for these specific tasks:**

- Resistor color band reading: classical CV is faster and more reliable than a VLM (VLMs sometimes confuse brown/red/orange under warm lighting). [COMMUNITY — hobbyist reports]
- SMD reading: Apple Vision OCR is already in the sidecar; zero additional work.
- Measurement: requires a reference object or calibration; not always available.

**Verdict:** IMPLEMENT classical band-reading as a specialty sub-processor. Cheap, fast, reliable for a common task. Integrate as a "resistor detected" branch off the YOLOE classifier.

---

### 3C. Barcode / QR / DataMatrix Reading for Labeled Components

**What it is:** Many ICs, modules, and reel-packaged components have QR codes or DataMatrix codes. Reading these gives a part number that can be looked up against Octopart/Mouser/DigiKey APIs or a local cache. [VERIFIED — IC manufacturers, tape-and-reel standards]

**Trade-offs:** Only works for labeled parts (not bare resistors, unlabeled lumber pieces). Apple Vision's barcode detector handles all common symbologies in one API call — already available in the sidecar. Near-zero implementation cost.

**Verdict:** EASY ADD — already available via Apple Vision in the planned sidecar. Just enable the `VNDetectBarcodesRequest`. Wire result to a part-number lookup.

---

## Axis 4 — Compute Alternatives

### 4A. CoreML + Apple Neural Engine vs MLX GPU

**Current state (mid-2026):**

- MLX is the fastest general-purpose inference runtime on Apple Silicon for models 7B–30B, producing 35–112 tok/s on Mac Mini M4 depending on quantization and RAM. Qwen3-VL via mlx-vlm is the current recommended path. [VERIFIED — insiderllm.com 2026; codersera.com Qwen3-VL MLX guide]
- CoreML-LLM (released ~early 2026) unlocks ANE for LLM-class models, claiming 2× energy efficiency vs GPU runtimes and competitive speed for small models (<7B). For models above ~14B, MLX leads by 20–87%. [VERIFIED — brightcoding.dev 2026-05-23; wccftech.com CoreAI Engine benchmark]
- MLX does NOT use the ANE — it uses Metal (GPU). CoreML uses ANE for sub-14B models. [VERIFIED — cactuscompute.com CoreML vs MLX comparison]

**Implication for Qwen3-VL (7B or 30B):**

- 7B variant: CoreML ANE path is worth benchmarking — may match MLX speed at lower power draw, freeing GPU for Apple Vision + YOLOE.
- 30B variant: MLX is the only practical path on a Mac Mini M4 with 16–32 GB RAM.

**Verdict:** BENCHMARK CoreML ANE for the 7B variant before committing. If ANE handles the VLM, GPU is entirely free for the real-time detection sidecar — meaningful on a Mac Mini with no discrete GPU. For the 30B model, MLX is correct.

---

### 4B. ACI GPU Box / External Accelerator

Apple announced ACI (Apple Compute Infrastructure) GPU modules in early 2026 — these are not yet shipping for consumer/prosumer use; no confirmed Mac Mini M4 external GPU path exists. [ASSUMED — no confirmed product as of research date]

eGPU support was dropped after M1. PCIe-based NPU accelerators (e.g., Hailo-8) have macOS drivers in development but no mature MLX/CoreML integration as of mid-2026. [COMMUNITY]

**Verdict:** NOT YET ACTIONABLE. Revisit in 2027 if inference bottlenecks the real-time watch pipeline.

---

## Axis 5 — Hand / Action Understanding

### 5A. Apple Vision Hand Pose (VNDetectHumanHandPoseRequest)

**What it is:** Apple Vision framework detects 21 hand keypoints (same topology as MediaPipe Hands) per frame. Runs on ANE, 60 fps capable on M-series, returns chirality + joint positions in normalized image coordinates. [VERIFIED — developer.apple.com/documentation/vision/detecting-hand-poses-with-vision]

**Trade-offs vs no hand tracking:**

- Enables "hand entered work zone" detection for step gating without a depth camera.
- Joint positions allow recognizing coarse gestures (pinch = place, open palm = pause) for hands-free UI control.
- Does NOT tell you what the hand is holding — for that, you need the object detection layer.
- 2D only — depth camera needed for 3D hand position.

**Already partially planned** (Apple Vision is in the chosen architecture). The key question is whether VNDetectHumanHandPoseRequest is explicitly enabled in the sidecar — make sure it is.

**Verdict:** ALREADY AVAILABLE IN PLANNED STACK — ensure it's wired up. Zero extra cost.

---

### 5B. MediaPipe Hands (Cross-Platform Alternative)

**What it is:** Google's MediaPipe Hands model — same 21-keypoint output as Apple Vision, runs in Python. Slightly more portable (works on Windows/Linux too) but adds a Python process on a Mac where Apple Vision is native and faster. [VERIFIED — research publications 2025; mediapipe docs]

**Verdict:** NO ADVANTAGE over Apple Vision on Mac. Use Apple Vision.

---

### 5C. Action / Step Recognition for Autonomous Watch Mode

**What it is:** Given hand keypoints over time (a 30-frame window), a lightweight sequence model (LSTM or Transformer-based classifier) can recognize coarse actions: "pick up component," "place component," "solder," "measure with probe." This is the autonomous verification end-state. [VERIFIED — MDPI sensors 2025; ISPRS 2025 MediaPipe+YOLO-Pose paper]

**Current state:** No off-the-shelf model exists for electronics bench actions. This requires:
1. Collect ~30–50 labeled video clips per action class (owner-specific).
2. Fine-tune a small action classifier (e.g., Create ML action classifier, or a 3-layer LSTM on top of keypoints) — Create ML visionOS 27 extended training is confirmed working. [VERIFIED — Apple developer docs]

**Trade-offs:**

- Keypoint-based (no raw video): fast, privacy-preserving, 10–30 kB model.
- Requires labeled data collection (the main cost).
- Cannot distinguish "placed correct part" from "placed wrong part" — still needs the detection layer for that.

**Verdict:** KEY DEFERRED INVESTMENT for the autonomous-watch end-state. Plan the data-collection harness early (record + label sessions while the step-guide phase runs) so the dataset grows passively. Implement the classifier in Phase 3/4.

---

## Axis 6 — Additional Alternative Found During Research

### 6A. Hybrid: YOLOE + CLIP Retrieval as a Two-Stage Detector

**What it is:** YOLOE detects "there is an object here" (open-vocab, text-prompted). CLIP retrieval then identifies WHICH specific object it is from the owner's personal library. This is a natural composition of Axis 3A retrieval with the already-chosen YOLOE. [VERIFIED — akshaymakes.com CLIP+YOLO blog, 2025]

**Why it matters:** YOLOE alone returns a text label ("resistor", "IC chip") but cannot say "this is the 10kΩ 0603 from your Tuesday parts bin." CLIP retrieval closes that gap. The combination keeps inference light (YOLOE + CLIP on CPU) and reserves the VLM only for genuinely ambiguous or novel parts.

**Verdict:** ADOPT — this is the recommended identification pipeline: YOLOE → CLIP retrieval → VLM (fallback only). Cuts VLM calls dramatically.

---

## Recommendation Summary

Ranked by "worth adopting for this fixed, single-user, Mac Mini desk setup":

| Rank | Alternative | Adopt When |
|---|---|---|
| 1 | CLIP Retrieval library (3A) + YOLOE→CLIP→VLM pipeline (6A) | Phase 1 — implement alongside VLM; cuts latency and improves accuracy for owned parts |
| 2 | AprilTag/ArUco markers for jigs + trays (2C) | Phase 1 — print markers, add one detection pass; near-zero compute, sub-mm anchoring |
| 3 | Second monitor as dedicated HUD (1C) | Immediate — zero code; plug in display, route viewfinder window |
| 4 | Orbbec Femto Bolt RGB-D (2A) | Phase 2 — required for occlusion recovery and autonomous step verification |
| 5 | Projector spatial AR overlay (1A) | Phase 3 — best ergonomic end-state; do after detection pipeline is solid |
| 6 | CoreML ANE benchmark for 7B VLM (4A) | Before committing to 30B MLX; if ANE handles 7B, GPU freed for real-time sidecar |
| 7 | Action classifier on hand keypoints (5C) | Phase 3/4 — start collecting labeled data now via passive recording |

**Approaches not worth prioritizing:**
- MediaPipe Hands (inferior to Apple Vision on Mac — already in stack)
- External GPU / ACI (no consumer product yet)
- Multiple cameras (deferred — add only when overhead view proves insufficient)
- iPhone LiDAR via Continuity Camera (prototype path only; graduate to Orbbec)

---

## Sources

- [Best Depth Cameras for Robotics 2026: RealSense vs ZED vs Orbbec](https://www.roboticscenter.ai/blog/best-depth-cameras-robotics)
- [Stop Wasting GPU Cycles! CoreML-LLM Unlocks ANE](https://www.blog.brightcoding.dev/2026/05/23/stop-wasting-gpu-cycles-coreml-llm-unlocks-ane-for-insane-on-device-speed)
- [Apple's CoreAI Engine vs MLX benchmark](https://wccftech.com/apples-new-coreai-engine-barely-edges-out-its-own-mlx-framework-at-realistic-8b-model-sizes-despite-being-2-47x-faster-on-tiny-models/)
- [Core ML vs MLX: Apple's Two ML Frameworks Compared](https://cactuscompute.com/compare/coreml-vs-mlx)
- [Qwen3-VL-30B on macOS (2026): MLX & Memory Guide](https://codersera.com/blog/run-qwen3-vl-30b-a3b-thinking-on-macos-installation-guide/)
- [Best Local LLMs for Mac in 2026](https://insiderllm.com/guides/best-local-llms-mac-2026/)
- [Orbbec Femto Bolt hardware specs](https://www.orbbec.com/documentation/femto-bolt-hardware-specifications/)
- [AprilTags vs ArUco — FIRST Robotics community](https://www.chiefdelphi.com/t/apriltags-vs-aruco/449414)
- [Building an Image Similarity Search Engine with FAISS and CLIP](https://towardsdatascience.com/building-an-image-similarity-search-engine-with-faiss-and-clip-2211126d08fa/)
- [Personalization Toolkit: Training Free Personalization of VLMs (arxiv 2502.02452)](https://arxiv.org/pdf/2502.02452)
- [YOLOE: Real-Time Open-Vocabulary Detection (Roboflow)](https://blog.roboflow.com/yoloe-zero-shot-object-detection-segmentation/)
- [Using YOLO with CLIP to improve Retrieval](https://www.akshaymakes.com/blogs/clip-yolo)
- [Detecting Hand Poses with Vision — Apple Developer](https://developer.apple.com/documentation/vision/detecting-hand-poses-with-vision)
- [Dynamic Hand Gesture Recognition Using MediaPipe and Transformer (MDPI 2025)](https://www.mdpi.com/2673-4591/108/1/22)
- [DIYer turns ordinary desk into smart display hub using a 4K projector](https://www.yankodesign.com/2025/08/30/diyer-turns-ordinary-desk-into-smart-display-hub-using-a-4k-projector/)
- [Lightform — Design Tools for Projection (spatial AR SDK)](https://lightform.com/)
- [7 Best Pico Projectors (Spring 2026)](https://houseandbeyond.org/best-pico-projector/)
- [Fiducial Markers Overview: Types, Use Cases, & Comparison Table](https://www.it-jim.com/blog/fiducial-markers-types/)
- [Reading Resistors With OpenCV (Hackaday)](https://hackaday.com/2015/05/14/reading-resistors-with-opencv/)

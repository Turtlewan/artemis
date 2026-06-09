# Artemis — Feature Backlog

Raw idea inbox. **Throw anything here the moment it occurs to you** — half-formed is fine, no
structure required, no commitment to build it. This is the feeder: SP0 and later planning drain
items from here into `REQUIREMENTS.md`, the roadmap, and specs. Capturing ≠ committing.

**How to add an idea:**
- Just add a `- ` line under **Inbox** (hand-edit), **or**
- In any Artemis session say **"backlog: <idea>"** and I'll append it (dated).

When an item gets pulled into the planning corpus, move it to **Triaged** with a pointer so the
trail isn't lost.

---

## Inbox (unsorted — dump here)

<!-- Format is loose. Optional tags in [brackets] if useful, e.g. [integration] [second-brain] [voice]. Example:
- Auto-summarise overnight emails into a morning briefing  [integration][assistant]
-->

- Quote of the day — user adds quotes, assistant serves/finds them (daily or on demand)  [second-brain][assistant]  (2026-06-02)

<!-- From the 2026-06-05 repo-studies pass — detail + verified sources in docs/research/repo-studies-prior-art.md -->
- Graph-RAG tier for the brain (symbol/entity knowledge-graph + multi-hop) alongside vector search — compare codegraph-ai/CodeGraph ONNX-memory vs current brain-architecture  [second-brain][rag]  (2026-06-05)
- Incremental fingerprint indexing + committed graph artifact for ingest (re-index only changed files) — from Understand-Anything  [second-brain][rag]  (2026-06-05)
- Enterprise-search query path: decompose → parallel multi-source → confidence-scored synthesis → digest (budget-guarded; HIGH cost) — from anthropics knowledge-work-plugins  [second-brain][assistant]  (2026-06-05)
- Anti-hallucination brain invariants: gap-tagging [MATERIAL GAP], multi-index citation verify, claim-audit gate, SHA-256 resumption ledger — from academic-research-skills  [second-brain][rag]  (2026-06-05)
- Two-tier memory (hot-cache + deep store) — reconcile with memory-engine-research.md  [second-brain]  (2026-06-05)
- Document handling: pdf/docx/pptx/xlsx skills + interactive pdf-viewer — install as plugins at build  [assistant][integration]  (2026-06-05)
- Eval Artemis's own AI quality with withpi encoder-scorer (deterministic, Promptfoo type:pi)  [assistant][eval]  (2026-06-05)
- Assistant persona/tone prior-art: Inflection Pi (empathetic personal assistant)  [assistant]  (2026-06-05)

<!-- From the 2026-06-08 social-media RAG/voice filter pass (dedup'd against locked SP0 specs) -->
- Spotlighting + CaMeL + delimiter discipline for untrusted web content → fold into the **Deep-Research engine spec** (still to draft; already an open question)  [rag][security]  (2026-06-08)
- Versioned retrieval — tag ingest chunks `processing/verified/searchable`, expose only `verified` to retrieval → refines **M3-a** beyond plain idempotency (relates to the incremental-indexing item above)  [rag]  (2026-06-08)
- Summary-first tiered retrieval ("context stinginess") — store raw + a summary, retrieve the summary first, pull full transcript only when needed → **M4** auto-inject + tool design; fits lean profile (relates to two-tier memory item)  [second-brain][assistant]  (2026-06-08)
- Exact-match identifiers (IDs/dates/invoice numbers) fail in pure vector search — make sure **M3-b** keyword path explicitly handles structured tokens  [rag]  (2026-06-08)
- RAGAS/DeepEval RAG eval dimensions (faithfulness, answer-relevancy, context-recall) + red-teaming as the knowledge-core eval rubric → complements the withpi eval item above  [eval]  (2026-06-08)

<!-- From the 2026-06-09 WWDC + homelab discussion -->
- **Camera module** — a camera/vision spoke for Artemis: indoor/doorbell/driveway cameras → presence/occupancy, event descriptions, natural-language footage search, vision AI (face/object detection). Open questions to discuss: source-of-truth model (own vs mirror, à la ADR-011); where vision inference runs (Apple Home Secure Video as a feed source · on-device Apple FM multimodal · MLX vision model on the Mini · or the future ACI Phase-3/4 NVIDIA/Jetson box per homelab-control-plane.md); privacy/quarantine posture for camera frames (untrusted-at-rest + DR-a QuarantinedReader, like the M8 read-spokes); MCP-at-edges seam to Home Assistant. Ties to: homelab ACI Phase 4 (edge vision), WWDC Home Secure Video + FM multimodal image input.  [integration][vision][homelab]  (2026-06-09)  — **flagged for dedicated discussion**



## Triaged (pulled into SP0 / requirements)

_Item → where it went (REQUIREMENTS.md section / ADR / spec). Keeps the trail._

<!-- - Morning email briefing → REQUIREMENTS.md §Assistant; spec: docs/changes/morning-brief.md -->

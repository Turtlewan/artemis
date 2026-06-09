---
spec: m3-d-visual-document-understanding
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M3-d — Visual-document understanding behind a port (Apple Vision OCR + Qwen3-VL scene description + ColQwen2.5 Light visual retrieval), with the visual-model-sizing spike GATED

**Identity:** Adds visual-document understanding to the M3-a ingestion pipeline behind a `VisualUnderstanding` port: Apple Vision OCR (text from images/scanned pages), a vision-LLM scene description (Qwen3-VL), and a ColQwen2.5 Light (PyTorch MPS 2.5.1, NOT 2.6.0) page-image visual-retrieval seam — all swappable behind the port. The visual-retrieval model is now LOCKED to ColQwen2.5 Light / MPS 2.5.1 (ADR-007, 2026-06-08; Lance v2.2 Blob V2 makes patch-vector storage practical). Only resident-vs-lazy load sizing (48GB contention) and whether ColQwen2.5 ships in v1 remain a GATED build-time sizing spike — the model choice is fixed.
→ why: see docs/technical/adr/ADR-007-knowledge-layer.md (visual-document understanding IN #4; exact model + resident-vs-lazy = build-time sizing spike) · docs/technical/architecture/brain.md § Ingestion (Apple Vision OCR; Qwen3-VL scene description; ColQwen2.5 Light / MPS 2.5.1 visual retrieval — locked in ADR-007 §Ingestion + §Refinement).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

<!-- Split rule: ONE logical phase (the visual-understanding port + its adapters + the ingest hook) across 3 src files (the port+types, the adapters incl. OCR + VL + visual-retrieval seam, the ingest hook) + 1 test = at the file limit, within bounds. Kept together because the OCR/VL/visual-retrieval pieces are the one "visual document" concern feeding the same M3-a pipeline and share the page-image vocabulary. The model SIZING decision is a gated spike (a Task), not a separate spec, because the code shape (everything behind the port) is identical regardless of which model wins. Flagged per rules. -->

## Assumptions
- M0-a (`config`/`Settings`/`paths`), M0-d (`ports`: `EmbeddingModel`, `VectorStore`, `ModelPort`, `Document`, `Chunk`, `Scope`), M3-a (`IngestPipeline`, `DocumentParser`/`ParsedDocument`/`ParsedBlock`, `chunk_document`, `LanceDBVectorStore`, the on-volume doc index + dimension-lock) are complete. → impact: Stop (M3-d hooks into the M3-a pipeline + writes to the same scope's index behind the same wall/unlock).
- The EXACT vision model and whether it is resident or lazy-loaded is **NOT decided here** — ADR-007 makes it a build-time sizing spike (48GB RAM contention with the always-resident ~15GB + the lazy Qwen3.6-27B sensitive_reasoner tier ~18GB 4-bit). M3-d defines a `VisualUnderstanding` PORT and ships adapters behind it; the model is referenced by a LOGICAL ROLE (`vision`) mapped in `roles.toml` (like `responder`/`reranker`), so the physical model + load policy is a config change, never a code change. → impact: Stop. Decision: scene description = Qwen3-VL via the `vision` role; visual retrieval = ColQwen2.5 Light (PyTorch MPS 2.5.1, NOT 2.6.0) via the `visual_embedder` role — both LOCKED (ADR-007). Only resident-vs-lazy load policy + whether ColQwen2.5 ships in v1 remain GATED (Task 6). Code shape unchanged by the sizing outcome.
- **Apple Vision OCR** is reached via a small Swift/PyObjC bridge to `Vision.framework` (`VNRecognizeTextRequest`) — Python cannot call Vision directly. M3-d ships an `AppleVisionOCR` adapter that shells/bridges to a tiny OCR helper (a Swift CLI under `swift/` OR a PyObjC call), behind the `VisualUnderstanding.ocr` method; off-hardware a `FakeOCR` returns deterministic text. → impact: Caution. Decision: OCR bridge = a tiny Swift CLI `artemis-ocr` under swift/ invoked via subprocess (matches the M2 broker precedent; clean Python adapter). Build of artemis-ocr GATED on-hardware (Task 6).
- **ColPali-style visual retrieval** = embed PAGE IMAGES (not just extracted text) with a late-interaction visual embedder so visually-rich pages (tables/figures/scanned docs) are retrievable by their visual content. M3-d defines a `VisualRetriever` seam + a multi-vector LanceDB write path for page-image embeddings; the visual embedder is ColQwen2.5 Light (PyTorch MPS 2.5.1), behind the `visual_embedder` role; only its v1-inclusion + resident-vs-lazy sizing are gated (ADR-007). M3-d ships the SEAM + a deterministic fake; the real ColPali embed is GATED. → impact: Caution. Decision: store ColQwen2.5 Light patch-vectors in a SEPARATE `page_images_{scope}` LanceDB table with late-interaction/MaxSim search (Lance v2.2 Blob V2 makes patch-vector storage practical — ADR-007), keeping the main text table's dimension-lock untouched. MaxSim detail + v1-inclusion GATED (Task 6). Pooling-to-single-vector rejected as lossy.
- Visual understanding runs as an OPTIONAL stage in the M3-a pipeline, triggered per-document when the parser/connector flags image content (a scanned PDF page, an image file, a page with low extractable text). It is OFF by default for plain-text documents (token/RAM frugality). → impact: Caution (the hook is additive to M3-a; plain-text ingest is unchanged).
- Everything inherits the M3-a wall + unlock: visual artefacts (OCR text, scene descriptions, page-image embeddings) are written to the SAME per-scope encrypted volume, owner-only, only when unlocked. → impact: Stop.

Simplicity check: considered hard-picking the load policy now — the MODEL is locked (ColQwen2.5 Light for retrieval; Qwen3-VL for scene description); only the load policy (resident-vs-lazy) is the gated 48GB-contention spike — NOT the model identity; hard-picking the load policy now risks starving the resident budget. Considered skipping ColPali visual retrieval for M3 — kept as a SEAM (not a full build) because brain.md/ADR-007 list it IN (#4) but its v1 inclusion is owner-judgment; shipping the port + a fake + the gated real path is the minimum that honours "IN behind the port" without committing RAM. Considered OCR via a Python lib (tesseract/easyocr) — rejected: brain.md locks Apple Vision OCR (on-box, no extra model RAM, high quality on Apple Silicon). This is the minimum visual surface behind the port.

## Prerequisites
- Specs that must be complete first: **M0-a**, **M0-d**, **M3-a** (the pipeline + parser types + the on-volume LanceDB store the visual stage feeds). Sequenced-with: **M3-b** (the retriever that will eventually query the visual table — M3-d only writes the table + the seam; querying page-image vectors is wired when the spike picks ColPali).
- Environment setup required: a `vision`/`visual_embedder` role in `roles.toml`; the Apple Vision OCR bridge (Swift CLI or PyObjC). Off-hardware the port runs on `FakeOCR`/`FakeVisionLLM`/`FakeVisualRetriever` (deterministic, no models, no Apple frameworks); **real Apple Vision OCR, real Qwen3-VL scene description, real ColPali embedding, AND the model-sizing/load-policy decision are GATED on-hardware** (Task 6).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/ports/visual.py | create | `VisualUnderstanding` Protocol (`ocr`, `describe`, `is_visual`) + `VisualRetriever` Protocol (page-image embed) + visual types (`PageImage`, `OcrResult`, `SceneDescription`) |
| /Users/artemis-build/artemis/src/artemis/ports/__init__.py | modify | re-export the new visual ports + types |
| /Users/artemis-build/artemis/src/artemis/adapters/visual.py | create | `AppleVisionOCR` (Swift-CLI/PyObjC bridge), `QwenVisionLLM` (scene description via the `vision` ModelPort role), `ColPaliRetriever` (page-image embed seam, backed by ColQwen2.5 Light / MPS 2.5.1 — locked) + fakes |
| /Users/artemis-build/artemis/src/artemis/ingest/visual_stage.py | create | optional ingest stage: detect visual content → OCR + scene-describe → fold into chunks (provenance: page+bbox) → page-image embed to the separate visual table |
| /Users/artemis-build/artemis/config/roles.toml | modify | add the `vision` (+ optional `visual_embedder`) logical role (placeholder endpoint, commented spike-decided) |
| /Users/artemis-build/artemis/tests/test_visual.py | create | port conformance + visual-stage against fakes; provenance, scope/unlock, separate-table write |

## Tasks
- [ ] Task 1: Define the visual ports + types — files: `/Users/artemis-build/artemis/src/artemis/ports/visual.py`, `/Users/artemis-build/artemis/src/artemis/ports/__init__.py` (modify re-exports) — frozen dataclasses: `PageImage { document_id: str, page: int, image_bytes: bytes, width: int, height: int }`; `OcrResult { text: str, blocks: Sequence[tuple[str, tuple[float,float,float,float]]] }` (text + per-line bbox for provenance); `SceneDescription { text: str }`. `class VisualUnderstanding(Protocol)`: `def is_visual(self, item) -> bool: ...` (does this item need the visual stage?); `def ocr(self, image: PageImage) -> OcrResult: ...`; `def describe(self, image: PageImage) -> SceneDescription: ...` (Qwen3-VL scene description). `class VisualRetriever(Protocol)`: `def embed_page(self, image: PageImage) -> list[Vector]: ...` (ColPali-style — MAY return multiple vectors per page; document the multi-vector late-interaction shape) + `@property def dimension(self) -> int: ...`. Bodies `...`. Add all to `ports/__init__` `__all__`. — done when: `uv run mypy --strict src` passes; the new ports import from `artemis.ports`.

- [ ] Task 2: Implement the OCR + scene-description adapters (+ fakes) — files: `/Users/artemis-build/artemis/src/artemis/adapters/visual.py` — `class AppleVisionOCR(VisualUnderstanding)`: `ocr` bridges to Apple Vision (Swift CLI `artemis-ocr` via subprocess passing the image, parsing JSON `{text, blocks:[{text,bbox}]}`; the bridge path is config/env `ARTEMIS_OCR_BIN`); `describe` delegates to a `QwenVisionLLM`; `is_visual` returns True for image mimes / low-text pages (heuristic, documented). `class QwenVisionLLM`: `describe(image)` calls the `vision` ModelPort role (`model.complete(role="vision", messages=[<image+prompt>])`) → `SceneDescription`; bind `127.0.0.1` only. `class FakeOCR(VisualUnderstanding)` + `class FakeVisionLLM` (TEST): deterministic — `ocr` returns fixed text+bbox derived from `image.image_bytes` length; `describe` returns a fixed description; `is_visual` returns True for a test mime. Do NOT import any Apple framework or torch at module import (lazy/subprocess). — done when: `uv run mypy --strict src` passes; `FakeOCR.ocr` returns an `OcrResult` with ≥1 bbox-tagged block; importing `adapters.visual` imports no heavy/Apple dep.

- [ ] Task 3: Implement the ColPali-style visual-retrieval seam — files: `/Users/artemis-build/artemis/src/artemis/adapters/visual.py` (same file) — `class ColPaliRetriever(VisualRetriever)`: `embed_page(image)` calls the `visual_embedder` role (the real model is ColQwen2.5 Light / MPS 2.5.1 (locked); only the load policy + v1-inclusion are the spike) returning the page's (possibly multi-) vectors; `dimension` from config. `class FakeVisualRetriever(VisualRetriever)` (TEST): deterministic single fixed-dimension vector per page. Document the multi-vector/late-interaction (MaxSim) note + that the storage table is separate (Task 4). — done when: `uv run mypy --strict src` passes; `FakeVisualRetriever.embed_page` returns ≥1 vector of `dimension` length; `_check: VisualRetriever = ColPaliRetriever(...)` type-checks.

- [ ] Task 4: Implement the optional visual ingest stage — files: `/Users/artemis-build/artemis/src/artemis/ingest/visual_stage.py` — `class VisualStage` constructed with `(visual: VisualUnderstanding, visual_retriever: VisualRetriever | None, page_image_store_for: Callable[[Scope], VectorStore] | None, is_unlocked: Callable[[], bool])`. `def process(self, page_images: Sequence[PageImage], document: Document) -> list[ChunkRecord]`:
  - precondition `is_unlocked()` else `ScopeLockedError`.
  - for each `PageImage`: if `visual.is_visual(...)`: `ocr = visual.ocr(image)`; `scene = visual.describe(image)`; build `ChunkRecord`(s) from the OCR text + the scene description text, carrying provenance `page=image.page` + the OCR bbox + `document_id`/`content_hash`/`source_id` (reuse the M3-a `ChunkRecord` shape so these chunks flow into the SAME text index via the M3-a embed+write step — the visual stage returns chunks; the caller embeds+writes them through M3-a's path).
  - if `visual_retriever` + `page_image_store_for` are set: `vecs = visual_retriever.embed_page(image)`; write them to a SEPARATE per-scope page-image table (`page_images_{scope}`) via the injected store (own dimension-lock metadata; does NOT touch the main text table's schema) — enforce the scope wall + unlock here too.
  - return the OCR/scene `ChunkRecord`s. Document: this stage is ADDITIVE to M3-a; the pipeline calls it only when a document has image content. — done when: `uv run mypy --strict src` passes; with fakes, `process` on a `PageImage` returns ChunkRecords carrying page+bbox provenance and (when a retriever+store are given) writes a page-image vector to the separate table.

- [ ] Task 5: Wire the visual stage into the M3-a pipeline (additive) + add the role — files: `/Users/artemis-build/artemis/config/roles.toml` (modify), and the wiring done via M3-a's `IngestPipeline` extension point — add a `vision` role (endpoint = local mlx base URL placeholder, model `Qwen3-VL` commented `# spike-decided: exact variant + resident-vs-lazy = M3-d gated sizing spike`, adapter `openai`) and an optional `visual_embedder` role (model `ColQwen2.5-Light` commented `# LOCKED: ColQwen2.5 Light, PyTorch MPS 2.5.1 (NOT 2.6.0) — ADR-007 2026-06-08; resident-vs-lazy + v1-inclusion = gated sizing spike (Task 6)`). For the pipeline wiring: M3-a's `IngestPipeline` must accept an OPTIONAL `visual_stage: VisualStage | None` — if M3-a's `IngestPipeline.__init__` does not already have this parameter, this requires a one-line M3-a change; since `pipeline.py` is M3-a's file, EITHER (a) M3-a should add the optional param (preferred — note for the M3-a author), OR (b) M3-d adds a thin `VisualIngestPipeline(IngestPipeline)` subclass in `visual_stage.py` that overrides `ingest` to call the visual stage when the parsed document has page images. Drafting option (b) to keep M3-d's edits inside its own files (surgical-scope). — done when: `uv run mypy --strict src` passes; `roles.toml` parses with the `vision` role; a `VisualIngestPipeline` ingests a document-with-images so the OCR/scene chunks land in the text index and a page-image vector lands in the separate table (Task 7 test, fakes).

- [ ] Task 6 (GATED — on-hardware, the SIZING spike): Vision-model choice + resident-vs-lazy load policy on 48GB — files: (no new repo files; exercises Tasks 2/3 with real models) — on the Mini: (a) real **Apple Vision OCR** via the `artemis-ocr` bridge on a scanned PDF page → confirm extracted text + bboxes; (b) real **Qwen3-VL scene description** on a figure-heavy page via the `vision` role → confirm a usable description, MEASURE its RAM footprint and load time; (c) decide RESIDENT vs LAZY load for the vision model given the 48GB budget (always-resident ~15GB + lazy Qwen3.6-27B sensitive_reasoner ~18GB 4-bit; the 27B fits 48GB with ~23GB headroom per brain.md) — record the decision + set the role's load policy; (d) IF ColQwen2.5 Light is included in v1: real ColQwen2.5 Light page embed (PyTorch MPS 2.5.1 — pin this, NOT 2.6.0) + a MaxSim search over the `page_images` table → confirm a visually-rich page is retrievable; ELSE record ColQwen2.5 Light as deferred-but-seamed (model still locked; only v1-inclusion deferred). ADR-007 build-time sizing spike (visual-doc model + RAM resident-vs-lazy). — done when: OCR + scene description work on-hardware, the resident-vs-lazy decision + RAM numbers are recorded in handoff, and the ColPali-in-v1 call is made + recorded.

- [ ] Task 7: Write the off-hardware visual tests — files: `/Users/artemis-build/artemis/tests/test_visual.py` — typed pytest with `FakeOCR`/`FakeVisionLLM`/`FakeVisualRetriever` + a real `LanceDBVectorStore` for the separate page-image table (temp `ARTEMIS_VOLUME_ROOT`, `is_unlocked=lambda:True`):
  - port conformance: `_v: VisualUnderstanding = AppleVisionOCR(...)` and `_r: VisualRetriever = ColPaliRetriever(...)` type-check; `FakeOCR`/`FakeVisualRetriever` satisfy the Protocols structurally.
  - visual stage: `VisualStage.process([PageImage(...)], document)` returns `ChunkRecord`s carrying `page` + bbox provenance from the OCR; with a `FakeVisualRetriever` + store, a page-image vector is written to the `page_images_<scope>` table (distinct from the main `docs_<scope>` table).
  - additive pipeline: `VisualIngestPipeline` ingest of a document flagged with page images produces OCR/scene chunks in the text index AND a page-image vector in the separate table; a plain-text document skips the visual stage entirely.
  - wall/unlock: `process` with `is_unlocked=lambda:False` raises `ScopeLockedError`; a page-image write to a mismatched scope raises `CrossScopeError`.
  - lazy-import: importing `adapters.visual` and `ingest.visual_stage` imports no Apple framework / torch (assert via `sys.modules` absence after import).
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_visual.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/ports/visual.py, /Users/artemis-build/artemis/src/artemis/adapters/visual.py, /Users/artemis-build/artemis/src/artemis/ingest/visual_stage.py, /Users/artemis-build/artemis/tests/test_visual.py |
| Modify | /Users/artemis-build/artemis/src/artemis/ports/__init__.py, /Users/artemis-build/artemis/config/roles.toml |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_visual.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fakes + temp LanceDB page-image table) |
| `swift build` (in swift/, if the Swift OCR CLI is built) | Build the `artemis-ocr` Vision bridge (GATED on-hardware if not built off-hardware) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/ports/visual.py, src/artemis/ports/__init__.py, src/artemis/adapters/visual.py, src/artemis/ingest/visual_stage.py, config/roles.toml, tests/test_visual.py |
| `git commit` | "feat: M3-d visual-document understanding behind port (Apple Vision OCR + Qwen3-VL describe + ColPali seam); model-sizing spike gated" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (vision/visual_embedder roles, paths) |
| `ARTEMIS_VOLUME_ROOT` | Mounted encrypted-volume root (off-hardware → data_root) |
| `ARTEMIS_OCR_BIN` | Path to the `artemis-ocr` Apple Vision bridge binary |

### Network
| Action | Purpose |
|--------|---------|
| local `127.0.0.1` calls to mlx-openai-server (GATED) | Live Qwen3-VL scene description + ColPali embed |

## Specialist Context
### Security
Visual artefacts (OCR text, scene descriptions, page-image embeddings) are Tier-1 sensitive — written to the SAME per-scope encrypted volume behind the M3-a wall + unlock (owner-only, only when mounted; `CrossScopeError`/`ScopeLockedError` enforced). OCR/scene text extracted from images is UNTRUSTED data (a scanned page can contain injection text) — it flows into the corpus as data; the retrieval consumers (M3-b/M3-c) spotlight it like any chunk. The Apple Vision bridge runs locally (no egress). [FLAG for apex-security: the vision model sees raw owner image content — confirm it is a LOCAL model (no cloud vision API) per the sensitivity router (image content from a personal store must never leave the box); confirm the OCR bridge subprocess cannot be coerced into reading outside the provided image.]

### Performance
The visual stage is OPTIONAL + per-document (only when image content is detected) — plain-text ingest is unchanged and pays nothing. The vision model's RAM footprint vs the 48GB budget (resident ~15GB + lazy Qwen3.6-27B sensitive_reasoner ~18GB 4-bit) is THE central question of the gated sizing spike (Task 6) — resident-vs-lazy is decided there, not hard-picked. Apple Vision OCR adds no model RAM (on-box framework). ColPali multi-vector storage uses a separate table to avoid bloating the main text index.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/ports/visual.py, src/artemis/adapters/visual.py, src/artemis/ingest/visual_stage.py | Type + docstring all exports; document the port seam, the OCR bridge, the multi-vector/separate-table note, and that the model + load policy are spike-decided |
| Config | config/roles.toml | Comment the `vision`/`visual_embedder` roles "spike-decided: exact model + resident-vs-lazy = M3-d gated sizing spike" |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_visual.py` → verify: exit 0 (incl. `VisualUnderstanding`/`VisualRetriever` structural assertions).
- [ ] Run `uv run pytest -q tests/test_visual.py` → verify: visual stage returns page+bbox-tagged chunks; page-image vector lands in a SEPARATE `page_images_<scope>` table; plain-text doc skips the stage; `ScopeLockedError`/`CrossScopeError` enforced; no Apple/torch import on module load.
- [ ] Run `uv run python -c "from artemis.ports import VisualUnderstanding, VisualRetriever; print('ok')"` → verify: prints `ok` (ports re-exported).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Real Apple Vision OCR + Qwen3-VL scene description work; resident-vs-lazy decision + RAM numbers recorded; ColPali-in-v1 call recorded → verify in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

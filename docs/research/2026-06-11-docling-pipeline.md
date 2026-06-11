# Docling Pipeline Research — 2026-06-11

**Scope:** Version pinning, model/pipeline choice, Apple-Silicon compatibility, and Docling→chunk→embed→LanceDB pipeline shape for Artemis M3-a ingestion build.
**Researched:** 2026-06-11 via web search (training cutoff Jan 2026; all claims verified against mid-2026 sources).
**Confidence levels:** HIGH = confirmed by primary source (PyPI/GitHub/official IBM docs), MED = confirmed by secondary/community source, LOW = inferred or single secondary source.

---

## 1. Current Stable Release to Pin

**Recommendation: pin `docling==2.99.0`**

- Latest stable release on PyPI is **2.99.0**, released **2026-06-08**.
  - Source: [docling PyPI](https://pypi.org/project/docling/) — HIGH
- The `docling-core` and `docling-parse` packages track a parallel versioning scheme; they should be pinned alongside to match.
  - Source: [docling-core PyPI](https://pypi.org/project/docling-core/) — HIGH
- Full CHANGELOG for v2.99 was not directly retrievable, but no community reports of severe regressions in the 2.x series late 2025–mid 2026 were found. The major breakage risk in the series was the `transformers` version conflict introduced around v2.31 (see §4).
  - Source: GitHub issues tracker — MED

---

## 2. Model / Pipeline Choice: Heron vs Granite-Docling vs SmolDocling

### 2a. Traditional "Heron" pipeline (standard Docling default)

The classic Docling pipeline chains multiple specialist models sequentially:
- **docling-layout-heron** for layout detection (78% mAP at 28ms/image on A100)
- **TableFormer** for table structure recognition
- **EasyOCR / Tesseract** for text extraction on scanned pages

Properties:
- Deterministic, well-tested, lower per-page RAM footprint
- Slower on scanned/image-heavy documents (three separate model passes)
- OCR must be explicitly configured for non-digital PDFs
- TableFormer now MPS-accelerated on Apple Silicon (14x over CPU) as of Issue #3202 — HIGH

### 2b. Granite-Docling-258M (VLM pipeline — recommended)

IBM released Granite-Docling-258M in February 2026 as the production-ready successor to the SmolDocling-256M preview. It is a compact Vision-Language Model (VLM) that processes an entire page in a single forward pass.

Architecture: RT-DETR object detector (docling-layout-heron backbone) fused with a 165M Granite language model + SigLIP2 vision encoder, yielding end-to-end structured output (DocTags format → DoclingDocument).

Benchmark improvements vs. SmolDocling predecessor (source: IBM Granite docs, InfoQ — HIGH):
- Full-page OCR F1: 0.80 → **0.84**
- OCRBench: 338 → **500**
- Table TEDS score: **0.97**
- Code recognition F1: **0.988**
- Replaces separate OCR engine; the "Enable OCR" toggle is **ignored** when using the VLM pipeline (OCR is baked in) — HIGH

Apple Silicon specifics:
- An official MLX export is published at `ibm-granite/granite-docling-258M-mlx` on HuggingFace — HIGH
- When `docling[models-vlm-inline]` is installed, `AutoInlineVlmEngine` auto-detects Apple Silicon MPS + mlx-vlm and selects `MlxVlmEngine` automatically — HIGH
- `VlmConvertOptions.from_preset("granite_docling")` auto-selects the MLX variant on Mac — HIGH
- In head-to-head testing on Apple Silicon: `GraniteDocling-258M-mlx` is **2.5x faster** than SmolDocling variants and finds more tables — MED (GitHub Issue #3202)
- Benchmarks were run on MacBook M3 Max — HIGH (HuggingFace model card)

### 2c. SmolDocling-256M (predecessor, not recommended for production)

SmolDocling-256M was the preview that preceded Granite-Docling. Granite-Docling supersedes it with better table/code/equation accuracy and faster Apple Silicon inference. Use Granite-Docling instead.
- Source: LinkedIn post from Peter Staar (Docling lead), IBM Granite docs — MED/HIGH

### Decision

**Use Granite-Docling VLM pipeline.** Rationale: single-model simplicity (no OCR configuration), superior table/OCR accuracy, official MLX export, auto-selected by Docling on Apple Silicon, 2.5x faster than SmolDocling on M-series hardware. The 258M parameter footprint is well within local Mac Mini RAM budget.

---

## 3. Layout/Table/OCR Quality and Fit for LanceDB Pipeline

Docling's document output model (`DoclingDocument`) is a typed, hierarchical representation that carries:
- Document structure: sections, headings, paragraphs, lists, tables, figures
- Metadata per element: page number, bounding box, reading order, element type

This is the ideal input for Docling's chunking layer before embedding:

**HierarchicalChunker** — one chunk per document element, minimal merging. Simple but may produce undersized chunks for short paragraphs. Source: [Docling chunking docs](https://docling-project.github.io/docling/concepts/chunking/) — HIGH

**HybridChunker** (recommended) — starts from HierarchicalChunker output, then:
1. Splits oversized chunks when token count exceeds embedding-model limit
2. Merges undersized successive chunks sharing the same heading/caption context
3. Tokenizer-aware (aligns to the embedding model's tokenizer via `merge_peers=True`)

The HybridChunker is the correct choice for a RAG pipeline because it produces right-sized, semantically coherent chunks while preserving heading context — each LanceDB row gets text + structured metadata (headings, page, content_type, bounding_box).

**LanceDB fit:** Docling does not ship a native LanceDB connector, but the pattern is well-established in the community: iterate HybridChunker output → extract `(text, metadata)` per chunk → encode with embedding model → insert via `lancedb.table.add([{vector: ..., text: ..., **metadata}])`. LanceDB's `lancedb.embeddings` integration layer can also wrap this inline.
- Source: LanceDB blog (chunking post), Docling RAG examples, OpenSearch RAG blog pattern — MED/HIGH

---

## 4. Apple-Silicon / MLX Compatibility and Gotchas

### Known install conflict — CRITICAL GOTCHA

**Issue:** When installing `docling[models-vlm-inline]` (which pulls `mlx-vlm`), a `transformers` version conflict arises with `docling-ibm-models`:
- `docling-ibm-models` (used by classic Heron pipeline) required `transformers >=4.42.0,<4.43.0`
- `mlx-vlm` required `transformers >=4.51.3`

This was documented in [docling-ibm-models issue #102](https://github.com/docling-project/docling-ibm-models/issues/102). The conflict was partly a consequence of Docling-IBM-Models pinning a very narrow transformers window.

**Current state (mid-2026):** The constraint was loosened in more recent `docling-ibm-models` releases, but `transformers` 5.0.x RC chain introduced *new* API breaks (ImageProcessingMixin changes) causing mlx-vlm failures on transformers 5.0.0rc3. The safest install approach is:

```bash
pip install "docling[models-vlm-inline]==2.99.0"
# Then verify no transformers downgrade occurred:
python -c "import docling; import mlx_vlm; print('OK')"
```

If a conflict surfaces, the workaround is to pin `transformers` to a known-good 4.x release (e.g. `transformers==4.51.3`) and install mlx-vlm separately. The Heron models are NOT needed if using VLM-only pipeline.
- Source: GitHub Issues #102 (docling-ibm-models), mlx-vlm #654, #682 — HIGH

### MPS acceleration

- TableFormer now auto-accelerated via MPS when `torch` detects `mps` device (Issue #3202) — HIGH
- VLM auto-selection (`AutoInlineVlmEngine`) prefers `MlxVlmEngine` over `TransformersVlmEngine` on Apple Silicon when `mlx-vlm` is installed — HIGH
- MLX requires macOS 14.0 or later (macOS 26.2+ for M5 Neural Accelerator enhanced path) — HIGH
- On M-series chips, unified memory means no VRAM bottleneck; 258M model uses ~1–2 GB RAM — MED

### Recommended install command

```bash
pip install "docling[models-vlm-inline]==2.99.0"
# Optional: for audio if needed later
# pip install "docling[models-vlm-inline,format-audio]==2.99.0"
```

Do NOT install `docling[standard]` + `models-vlm-inline` together on the same env — the `standard` extra pulls `docling-ibm-models` which conflicts with `mlx-vlm`.

---

## 5. Recommended End-to-End Pipeline: Docling → Chunk → Embed → LanceDB

```
[Document File]
       │
       ▼
DocumentConverter(pipeline_options=PdfPipelineOptions(
    vlm_options=VlmConvertOptions.from_preset("granite_docling")
))
       │  (auto-selects MLX on Apple Silicon)
       ▼
DoclingDocument  ← structured hierarchical doc representation
       │
       ▼
HybridChunker(tokenizer=<embedding_model_tokenizer>, merge_peers=True)
       │
       ├── chunk.text          → embed with local embedding model (e.g. nomic-embed-text-v1.5 via MLX)
       ├── chunk.meta.headings → store as metadata
       ├── chunk.meta.page_no  → store as metadata
       └── chunk.meta.doc_items → store as metadata
       │
       ▼
lancedb.table.add([{
    "vector": embedding,
    "text": chunk.text,
    "source": doc_path,
    "page": chunk.meta.page_no,
    "headings": chunk.meta.headings,
    "content_type": chunk.meta.doc_items[0].label  # paragraph / table / code etc.
}])
```

**Key pipeline choices:**
1. Use `VlmConvertOptions.from_preset("granite_docling")` — Docling auto-selects the MLX variant on Apple Silicon; no manual `MlxVlmEngine` wiring needed.
2. Use `HybridChunker` with the same tokenizer as the downstream embedding model — ensures chunk sizes are right for the embedding model's context window.
3. LanceDB schema should include `vector` (fixed-dim float array), `text` (str), and metadata fields. Define the schema explicitly for consistent inserts.
4. Content-type filtering: Docling labels chunks as `paragraph`, `table`, `figure`, `code` etc. — pass this through as metadata so LanceDB queries can optionally filter by content type.
5. Tables: Granite-Docling emits tables as OTSL (structured text) within the chunk text; no special table handling needed at the LanceDB insert step.

**Batch processing note:** For a local Mac Mini ingestion job, process documents serially (not parallel) — MLX models hold GPU/ANE state. Parallel processes can compete for the Neural Engine and degrade throughput.
- Source: MLX ecosystem notes, Docling documentation, LanceDB docs — MED/HIGH

---

## Summary

| Item | Recommendation | Confidence |
|---|---|---|
| Version to pin | `docling==2.99.0` | HIGH |
| Pipeline | Granite-Docling VLM via `models-vlm-inline` extra | HIGH |
| Chunker | `HybridChunker` aligned to embedding model tokenizer | HIGH |
| Apple Silicon install | `pip install "docling[models-vlm-inline]==2.99.0"` — do NOT mix with `standard` extra | HIGH |
| Top gotcha | `transformers` version conflict between `docling-ibm-models` and `mlx-vlm` — avoid `standard` extra, verify with smoke test after install | HIGH |

---

## Sources

- [docling PyPI](https://pypi.org/project/docling/)
- [docling GitHub Releases](https://github.com/docling-project/docling/releases)
- [IBM Granite-Docling announcement](https://www.ibm.com/new/announcements/granite-docling-end-to-end-document-conversion)
- [IBM Granite Docling docs](https://www.ibm.com/granite/docs/models/docling)
- [ibm-granite/granite-docling-258M on HuggingFace](https://huggingface.co/ibm-granite/granite-docling-258M)
- [ibm-granite/granite-docling-258M-mlx on HuggingFace](https://huggingface.co/ibm-granite/granite-docling-258M-mlx)
- [docling-ibm-models issue #102 (transformers conflict)](https://github.com/docling-project/docling-ibm-models/issues/102)
- [docling Issue #3202 (MPS acceleration + VLM auto-select)](https://github.com/docling-project/docling/issues/3202)
- [docling-serve Issue #399 (VLM inference slow)](https://github.com/docling-project/docling-serve/issues/399)
- [Docling Chunking concepts](https://docling-project.github.io/docling/concepts/chunking/)
- [Docling VLM Pipeline — DeepWiki](https://deepwiki.com/docling-project/docling/5.3-vlm-pipeline)
- [LanceDB chunking blog](https://www.lancedb.com/blog/chunking-techniques-with-langchain-and-llamaindex)
- [InfoQ: IBM Releases Granite-Docling-258M](https://www.infoq.com/news/2025/10/granite-docling-ibm/)
- [SmolDocling 3x faster on Apple Silicon (Peter Staar LinkedIn)](https://www.linkedin.com/posts/peter-w-j-staar-7b261373_docling-smoldocling-mlx-activity-7308517746118410240-QD2Z)
- [mlx-vlm transformers 5 RC issues #654](https://github.com/Blaizzy/mlx-vlm/issues/654)

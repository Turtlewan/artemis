---
spec: m3-a-ingestion-pipeline
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M3-a — Ingestion pipeline (connector → normalized `Document` → Docling parse → chunk → embed → LanceDB on the encrypted volume) with content_hash idempotency + provenance/locator; core file + web connectors

**Identity:** Builds the document-ingestion pipeline that turns a source into encrypted, retrievable chunks: a `Connector` interface + two core connectors (local file/document, web page) → a normalized `Document` → Docling parse → late chunking (+ Contextual Retrieval flag for high-value) → embed via the `EmbeddingModel` port → write dense vectors + FTS to a LanceDB index that lives **inside the per-scope encrypted volume** (M2 broker-mounted), idempotent via `content_hash`, with provenance + locator (page/char-span/url) on every chunk.
→ why: see docs/technical/adr/ADR-007-knowledge-layer.md (storage-on-encrypted-volume + ingestion) · docs/technical/architecture/brain.md § Ingestion · § Retrieval (LanceDB dense+FTS).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

<!-- Split rule: this spec is ONE logical phase (the ingest write-path) but creates >3 files (the connector port, two connectors, the parse/chunk/embed pipeline, the LanceDB-on-volume VectorStore adapter, tests). It is a justified atomic exception: the pieces form the single linear pipeline connector→Document→parse→chunk→embed→write and share the `Document`/`Chunk`/locator vocabulary; sub-splitting (e.g. connectors separate from the writer) would leave a pipeline that cannot be tested end-to-end (a connector with nothing to feed, or a writer with no input). The retriever that READS this index is the separate M3-b; the visual path is the separate M3-d. Flagged per rules. -->

## Assumptions
- M0-a (`config`/`paths`/`Settings`), M0-d (`ports`: `EmbeddingModel`, `VectorStore`, `Document`, `Chunk`, `Scope`), M2-b (`ScopedStore`, `vector_index_handle()`, `KeyProvider`, `ScopeLockedError`, `CrossScopeError`) are complete. → impact: Stop (this spec consumes those exact symbols; the LanceDB write goes through a `VectorStore` adapter bound to the scope's vector handle).
- The per-scope **encrypted volume is mounted by the M2 broker on owner unlock**, and the LanceDB index path resolves under that mounted volume. ADR-007 states the M2 broker specs "gain a volume-mount step at finalization" — that step is NOT yet in the M2 drafts (M2-a/b/c). M3-a therefore depends on a `vectors_dir(scope)` path that points INSIDE the mounted encrypted volume and on the broker having mounted it before ingest runs. → impact: Stop. Decision: M3-a drafts against `paths.volume_vectors_dir(settings, scope) -> <volume_root>/<scope>/lancedb` (volume_root under /opt/artemis) + precondition `is_owner_unlocked()`. The M2 broker volume-mount step is a sequenced-with M2 deliverable (M2-a owns it — M2-a Task 10 + gated Task 9; mount point /opt/artemis/<slot>/<scope>/vault/); rename at integration if M2 finalizes different symbol names (one-line adapter change). GATED on-hardware (Task 8): confirm the table is created under the broker-mounted volume and is unreadable when locked.
- M0-a `paths.scope_dir` currently places `vectors/` UNDER the plain per-scope data dir. ADR-007 moves the **document** LanceDB index onto the encrypted volume (Tier-1, unlock-required). M3-a adds `paths.volume_vectors_dir` (new) and does NOT use the M0-a `vectors/` subdir for the doc corpus. → impact: Caution (do not write the doc index to the plain `vectors/` dir; that dir is unused for docs — leave it, do not delete it).
- LanceDB is reached via the `lancedb` Python package; its native hybrid (vector + FTS/BM25) + RRF are used by M3-b. M3-a's job is to WRITE: create/open the per-scope LanceDB table, add rows (id, vector, text, scope, content_hash, source_id, document_id, locator fields), and build the FTS index on `text`. → impact: Stop (the table schema written here is the contract M3-b reads).
- Docling is reached via the `docling` Python package; it parses files (PDF/docx/pptx/md/html) to a structured document with page + bbox info. The web connector fetches with **trafilatura** (+ optional Playwright for JS pages, deferred) and yields cleaned text + the source URL. → impact: Caution. Docling behind the `DocumentParser` port with a deterministic `FakeParser` for CI; real Docling install + parse GATED on-hardware (Task 7). Marker/MinerU escalation PARKED per ADR-007.
- **Late chunking** = embed-then-chunk over the long-context embedder so each chunk's vector carries document context (brain.md). **Contextual Retrieval** = prepend an LLM-generated short context blurb to high-value chunks before embedding (Anthropic technique, brain.md "for high-value"). In M3-a, late chunking is the DEFAULT path; Contextual Retrieval is behind a per-document `contextual: bool` flag and its blurb generation calls the `ModelPort` responder role — drafted but the LLM-context generation is GATED on-hardware (needs a served model). → impact: Caution (off-hardware: plain late chunking only; the contextual blurb is a gated probe).
- `content_hash` = a stable hash (sha256) of the normalized `Document.text` (+ source_id). Re-ingesting an unchanged source is a NO-OP (idempotent); a changed source re-chunks + re-embeds + replaces the old rows for that document_id. → impact: Stop (idempotency is an ADR-007 hard requirement).
- The embedder dimension is locked in the store metadata (brain.md "dimension locked in store metadata; model change = explicit re-index migration"). M3-a writes the embedder's `dimension` + `model_id` into the LanceDB table metadata on creation and refuses to add vectors of a mismatched dimension. → impact: Stop (dimension-lock is an ADR/brain.md invariant).

Simplicity check: considered writing the doc corpus into the same SQLCipher file as memory (reuse M2's keyed open) — rejected: ADR-007 locks LanceDB-on-encrypted-volume for the doc corpus (sqlite-vec is brute-force, won't scale; per-chunk app-side encryption breaks the ANN index). The encrypted volume gives transparent at-rest encryption while LanceDB keeps its native ANN+hybrid. Considered building all connectors (video/audio/reels) now — rejected: ADR-007/the brief scope M3 to the CORE set (file + web); heavier media connectors are flagged as follow-on tasks. This is the minimum write-path.

## Prerequisites
- Specs that must be complete first: **M0-a** (paths/config), **M0-d** (`EmbeddingModel`/`VectorStore`/`Document`/`Chunk`/`Scope` ports), **M2-b** (`ScopedStore`/`vector_index_handle`/`KeyProvider`/`ScopeLockedError`). Sequenced-with: **M2** encrypted-volume mount step (see the load-bearing volume-mount Assumption; M2-a owns the mount) — ingest must run only when the volume is mounted (owner unlocked).
- Environment setup required: `lancedb`, `docling`, `trafilatura` (added via `uv add`). Off-hardware the pipeline tests run against a `FakeEmbedder` + `FakeParser` + a temp LanceDB dir; **real Docling parse + real LanceDB on a real encrypted volume + Contextual-Retrieval blurb generation are GATED on-hardware** (Tasks 7–8).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/ingest/__init__.py | create | ingest package marker |
| /Users/artemis-build/artemis/src/artemis/ingest/connectors.py | create | `Connector` Protocol + `Source`/`RawItem` types + `FileConnector` + `WebConnector` → normalized `Document` |
| /Users/artemis-build/artemis/src/artemis/ingest/parsing.py | create | `DocumentParser` Protocol + `DoclingParser` (real, lazy-import) + `FakeParser` (test); parse → `ParsedDocument` with page/bbox |
| /Users/artemis-build/artemis/src/artemis/ingest/chunking.py | create | late chunking + Contextual-Retrieval flag → `Chunk` list with provenance/locator |
| /Users/artemis-build/artemis/src/artemis/ingest/pipeline.py | create | `IngestPipeline.ingest(source, scope)`: connector→parse→chunk→embed→VectorStore write; content_hash idempotency |
| /Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py | create | `LanceDBVectorStore` implementing the M0-d `VectorStore` port; table on the encrypted volume; dense + FTS; dimension-lock metadata |
| /Users/artemis-build/artemis/src/artemis/paths.py | modify | add `volume_vectors_dir(settings, scope) -> Path` resolving under the mounted encrypted volume |
| /Users/artemis-build/artemis/tests/test_ingest_pipeline.py | create | end-to-end ingest against fakes + temp LanceDB; idempotency, provenance, dimension-lock, scope isolation |

## Tasks
- [ ] Task 1: Add the encrypted-volume vectors path — files: `/Users/artemis-build/artemis/src/artemis/paths.py` — add `def volume_vectors_dir(settings: Settings, scope: str) -> Path` returning `<mounted-volume-root>/<slot>/<scope>/lancedb` where the mounted-volume-root comes from a new `Settings.volume_root: Path` field (add it to `config.py` with env `ARTEMIS_VOLUME_ROOT`, defaulting to `data_root` so off-hardware tests work without a real volume). Reject scopes that are not owner-scopes (`owner-private`/`general`) with `ValueError` — the doc corpus is owner-only per ADR-007 (guests get no doc corpus). Do NOT create the dir (the pipeline ensures it under an unlocked volume). Document: in PROD `volume_root` is the broker-mounted encrypted volume under `/opt/artemis` (mount point `/opt/artemis/<slot>/<scope>/vault/`, M2-a); off-hardware it falls back to `data_root`. — done when: `uv run mypy --strict src` passes; `volume_vectors_dir(s, "owner-private")` returns the documented path and `volume_vectors_dir(s, "guest-x")` raises `ValueError`.

- [ ] Task 2: Define the connector interface + normalized Document + the two core connectors — files: `/Users/artemis-build/artemis/src/artemis/ingest/connectors.py` (+ `ingest/__init__.py`) —
  - frozen dataclass `Source { kind: Literal["file","web"], uri: str, scope: Scope }` (a thing to ingest).
  - `class Connector(Protocol)`: `def fetch(self, source: Source) -> Iterable[RawItem]: ...` where `RawItem` is a frozen dataclass `{ raw_bytes: bytes | None, text: str | None, mime: str, source_id: str, origin_uri: str, fetched_at: datetime }` (`source_id` = a stable id for the item; web = the URL, file = the absolute path).
  - `class FileConnector` (Connector): `fetch` reads the file at `source.uri` (must exist; reject paths outside an allowed roots set passed at construction — no traversal), returns one `RawItem` with `raw_bytes` + a mime sniffed from the extension/content.
  - `class WebConnector` (Connector): `fetch` retrieves `source.uri` via `trafilatura` (lazy import), returns one `RawItem` with cleaned `text`, `mime="text/html"`, `source_id`=the URL. Network call behind a small `_fetch_url(url) -> str` seam so tests inject a fixture HTML (no live network off-hardware).
  - `def to_document(item: RawItem, scope: Scope, parsed_text: str) -> Document`: build the M0-d `Document` (`document_id` = a uuid5 of `source_id`; `source_id`; `content_hash` = sha256 of `parsed_text` + source_id; `scope`; `text` = parsed_text). content_hash computed in `hashing.py`-style helper local to this module.
  — done when: `uv run mypy --strict src` passes; `FileConnector.fetch` on a temp file yields one `RawItem` with bytes; `WebConnector.fetch` with an injected fixture yields cleaned text; a path-traversal uri raises `ValueError`.

- [ ] Task 3: Define the parser port + Docling parser + fake — files: `/Users/artemis-build/artemis/src/artemis/ingest/parsing.py` — `class DocumentParser(Protocol)`: `def parse(self, item: RawItem) -> ParsedDocument: ...` where `ParsedDocument` is a frozen dataclass `{ text: str, blocks: Sequence[ParsedBlock] }` and `ParsedBlock` is `{ text: str, page: int | None, bbox: tuple[float,float,float,float] | None, char_start: int, char_end: int }` (the provenance/locator source). `class DoclingParser(DocumentParser)`: lazy-imports `docling`, converts `item.raw_bytes`/`item.text` to a Docling document, maps Docling page+bbox+text spans into `ParsedBlock`s. For a web `RawItem` (already text) produce one block per paragraph with `page=None`, bbox=None, and char spans. `class FakeParser(DocumentParser)` (TEST): deterministic — splits `item.text` (or decoded bytes) into fixed-size blocks with synthetic page/char-span, no Docling import. — done when: `uv run mypy --strict src` passes; `FakeParser.parse` yields ≥1 `ParsedBlock` with char spans; importing `parsing` does NOT import docling (lazy).

- [ ] Task 4: Implement late chunking + Contextual-Retrieval flag → provenance-tagged chunks — files: `/Users/artemis-build/artemis/src/artemis/ingest/chunking.py` — `def chunk_document(parsed: ParsedDocument, document: Document, *, contextual: bool = False, context_fn: Callable[[str, str], str] | None = None) -> list[ChunkRecord]` where `ChunkRecord` is a frozen dataclass extending the M0-d `Chunk` with provenance: `{ chunk_id, document_id, text, scope, content_hash, source_id, page: int|None, bbox: tuple|None, char_start: int, char_end: int }`. Logic: group `ParsedBlock`s into chunks by a target token/char budget (default ~512 tokens, char-approx in M3-a), preserving the page/bbox/char-span of the FIRST block in each chunk as the chunk locator (document the approximation). `chunk_id` = `f"{document_id}:{ordinal}"` (stable → idempotent replace). If `contextual` and `context_fn`: prepend `context_fn(document.text, chunk.text)` to the chunk text before it is handed to the embedder (the Contextual-Retrieval blurb; `context_fn` calls the responder `ModelPort` in prod — INJECTED so off-hardware tests pass a deterministic stub). Late-chunking note: the actual late-chunking embedding strategy (embed long context, pool per chunk) is realised in the pipeline's embed step (Task 5) — `chunk_document` produces the spans; document this division. — done when: `uv run mypy --strict src` passes; `chunk_document` on a `FakeParser` output yields stable `chunk_id`s and carries page/char-span on each chunk; with `contextual=True` + a stub `context_fn` the chunk text is prefixed.

- [ ] Task 5: Implement the LanceDB VectorStore adapter (encrypted-volume table, dense + FTS, dimension-lock) — files: `/Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py` — `class LanceDBVectorStore` implementing the M0-d `VectorStore` Protocol, constructed with `(scope: Scope, settings: Settings, embedder_model_id: str, dimension: int)`; resolves its dir via `paths.volume_vectors_dir(settings, scope)` (lazy `lancedb.connect` to that dir; create the dir only when an owner-unlocked precondition holds — accept an injected `is_unlocked: Callable[[], bool]`, raise `ScopeLockedError` if false). Table name = `f"docs_{scope}"`. On first create, write table metadata `{embedder_model_id, dimension}` and build an FTS index on the `text` column; on open, ASSERT the stored `dimension`==constructor `dimension` and `embedder_model_id` matches, else raise a typed `DimensionMismatchError` (the re-index-migration guard). Methods:
  - `add(scope, ids, vectors, metadata)`: assert `scope`==self.scope (`CrossScopeError` from M2-b otherwise — the wall); assert each vector len==`dimension`; upsert rows keyed by `id` (delete-then-insert per id so re-ingest replaces — idempotent at the chunk level); each row = `{id, vector, text, scope, content_hash, source_id, document_id, page, bbox, char_start, char_end}` taken from `metadata`.
  - `search(scope, query, k)`: assert `scope`==self.scope; LanceDB ANN search on `vector`; return M0-d `RetrievedChunk`s (used by M3-b; M3-a only needs `add` working but implement `search` to satisfy the port).
  - add a helper `delete_document(document_id)` (remove all chunk rows for a document_id — used by re-ingest of a changed document).
  Bind nothing to network. — done when: `uv run mypy --strict src` passes; against a TEMP LanceDB dir (volume_root=tmp, is_unlocked=lambda:True) `add` then `search` round-trips; a wrong-dimension vector raises; an `add` with a mismatched scope raises `CrossScopeError`; reopening with a different `dimension` raises `DimensionMismatchError`.

- [ ] Task 6: Implement the pipeline with content_hash idempotency — files: `/Users/artemis-build/artemis/src/artemis/ingest/pipeline.py` — `class IngestPipeline` constructed with `(connector_for: Callable[[Source], Connector], parser: DocumentParser, embedder: EmbeddingModel, store_for: Callable[[Scope], VectorStore], is_unlocked: Callable[[], bool])`. `def ingest(self, source: Source) -> IngestResult` where `IngestResult` = `{ document_id: str, chunks_written: int, skipped: bool }`:
  1. precondition: `if not is_unlocked(): raise ScopeLockedError` (no ingest without the mounted volume).
  2. `item = next(iter(connector.fetch(source)))`; `parsed = parser.parse(item)`; `doc = to_document(item, source.scope, parsed.text)`.
  3. **idempotency:** look up whether a row with this `document_id` already has the same `content_hash` (a `store.has_document(document_id, content_hash)` helper on the adapter — add it); if so → `skipped=True`, write nothing.
  4. else: if the document_id exists with a DIFFERENT hash → `store.delete_document(document_id)` (replace).
  5. `chunks = chunk_document(parsed, doc)`; `vectors = embedder.embed([c.text for c in chunks])` (the late-chunking embed step; document that a true long-context late-chunk pooling is the embedder adapter's concern, the port stays `embed(texts)`); assert `len(vectors)==len(chunks)`.
  6. `store.add(source.scope, ids=[c.chunk_id...], vectors=vectors, metadata=[{...provenance...} for c in chunks])`.
  7. return `IngestResult(document_id, len(chunks), skipped=False)`.
  Degrade-don't-crash: wrap connector/parse failures in a typed `IngestError` (never a bare exception out of `ingest` for a single bad source). — done when: `uv run mypy --strict src` passes; (in Task 9 test) ingesting the same source twice writes chunks once then returns `skipped=True`.

- [ ] Task 7 (GATED — on-hardware): Real Docling parse — files: (uses Task 3 `DoclingParser`) — on the Mini with `docling` installed: parse a real multi-page PDF + a docx, confirm `ParsedBlock`s carry real `page` numbers and non-None `bbox` for ≥1 block. Build-time empirical (Docling install + parse quality; Marker/MinerU escalation stays PARKED). — done when: a real PDF yields blocks with page+bbox and the pipeline ingests it; recorded in handoff.

- [ ] Task 8 (GATED — on-hardware): Real LanceDB on the broker-mounted encrypted volume + Contextual-Retrieval blurb — files: (uses Tasks 5/6 + a served responder model) — on the Mini after the M2 broker has mounted the per-scope encrypted volume (owner unlocked): point `ARTEMIS_VOLUME_ROOT` at the mounted volume, run `IngestPipeline.ingest` for a file source into `owner-private`, confirm the LanceDB table is created UNDER the mounted volume (and is unreadable when the volume is unmounted/locked), the FTS index exists, and hybrid `search` returns the chunk. Separately: with a served responder, run one document with `contextual=True` and a real `context_fn` calling the responder; confirm the blurb is prepended and the chunk embeds. Build-time spikes (encrypted-volume mount lifecycle + perf; LanceDB sizing; Contextual-Retrieval latency). — done when: ingest writes onto the mounted volume, data is inaccessible when locked, contextual blurb generates; recorded in handoff.

- [ ] Task 9: Write the off-hardware ingest tests — files: `/Users/artemis-build/artemis/tests/test_ingest_pipeline.py` — typed pytest with `FakeEmbedder` (deterministic fixed-dimension vectors), `FakeParser`, a `FileConnector` over a temp file + a `WebConnector` with an injected fixture HTML, and a real `LanceDBVectorStore` against a temp dir (`ARTEMIS_VOLUME_ROOT`=tmp, `is_unlocked=lambda:True`):
  - end-to-end: `ingest(file_source)` writes N chunks; the LanceDB table has N rows each carrying `content_hash`, `source_id`, `document_id`, `page`/`char_start`/`char_end` (provenance present on every chunk).
  - idempotency: a second `ingest` of the SAME unchanged file returns `skipped=True` and the row count is unchanged; editing the file's text → re-ingest replaces (row count reflects new chunks, old document_id rows gone).
  - dimension-lock: constructing a second store for the same scope with a different `dimension` raises `DimensionMismatchError`.
  - scope isolation/wall: `store.add("guest-x", ...)` on an `owner-private` store raises `CrossScopeError`; `ingest` when `is_unlocked()` is False raises `ScopeLockedError`.
  - web: `ingest(web_source)` with the fixture yields chunks with `source_id`==the URL and `page=None`.
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_ingest_pipeline.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/ingest/__init__.py, /Users/artemis-build/artemis/src/artemis/ingest/connectors.py, /Users/artemis-build/artemis/src/artemis/ingest/parsing.py, /Users/artemis-build/artemis/src/artemis/ingest/chunking.py, /Users/artemis-build/artemis/src/artemis/ingest/pipeline.py, /Users/artemis-build/artemis/src/artemis/adapters/lancedb_store.py, /Users/artemis-build/artemis/tests/test_ingest_pipeline.py |
| Modify | /Users/artemis-build/artemis/src/artemis/paths.py, /Users/artemis-build/artemis/src/artemis/config.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add lancedb docling trafilatura` | Pipeline dependencies (Docling may be gated/lazy if it won't install off-hardware) |
| `uv run mypy --strict src tests/test_ingest_pipeline.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fakes + temp LanceDB) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/ingest/**, src/artemis/adapters/lancedb_store.py, src/artemis/paths.py, src/artemis/config.py, tests/test_ingest_pipeline.py, pyproject.toml, uv.lock |
| `git commit` | "feat: M3-a ingestion pipeline — connectors → Docling → chunk → embed → LanceDB on encrypted volume (content_hash idempotent, provenance)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (paths, embedder role) |
| `ARTEMIS_VOLUME_ROOT` | Root of the mounted encrypted volume (off-hardware → data_root) |

### Network
| Action | Purpose |
|--------|---------|
| `uv add lancedb docling trafilatura` | Package install (PyPI) |
| web fetch via trafilatura (GATED / fixture off-hardware) | Web connector retrieval |

## Specialist Context
### Security
The document corpus is **Tier-1 sensitive, born encrypted** on the per-scope volume the M2 broker mounts on owner unlock (ADR-007). Invariants the build MUST honour: no ingest write happens unless the volume is mounted (`is_unlocked()` / `ScopeLockedError`); the doc corpus is owner-only (`volume_vectors_dir` rejects guest scopes); `add`/`search` enforce the scope wall (`CrossScopeError` on mismatch); the LanceDB index is never written to the plain `data_root/<scope>/vectors/` dir. Ingested content is UNTRUSTED data (brain.md "all ingested content = untrusted data") — M3-a stores it; spotlighting/CaMeL gating of retrieved chunks is a security-layer concern flagged for the M3-b/retrieval consumers, not bypassed here. [FLAG for apex-security: confirm the encrypted-volume mount + the "doc index unreadable when locked" property at the M2 mount-step finalization; confirm no plaintext doc text is logged during ingest.]

### Performance
Late chunking + a single batched `embedder.embed([...all chunks...])` call per document (not per-chunk) keeps ingest cheap. LanceDB sizing + ingest throughput on the encrypted volume is a build-time spike (Task 8). Contextual Retrieval is opt-in per document (one extra LLM call per high-value chunk) — default OFF to keep bulk ingest token-frugal (brain.md).

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/ingest/*.py, src/artemis/adapters/lancedb_store.py | Type + docstring all exports; document content_hash idempotency, the provenance/locator fields, dimension-lock, and the encrypted-volume precondition |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_ingest_pipeline.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_ingest_pipeline.py` → verify: end-to-end ingest writes provenance-tagged chunks; second unchanged ingest is `skipped`; dimension-lock + `CrossScopeError` + `ScopeLockedError` all raise; web fixture ingests.
- [ ] Run `uv run python -c "from artemis.paths import volume_vectors_dir; from artemis.config import get_settings; volume_vectors_dir(get_settings(),'guest-x')"` → verify: raises `ValueError` (doc corpus is owner-only).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Real Docling parse of a PDF yields page+bbox blocks → verify recorded in handoff.
- [ ] (GATED, on Mini) Ingest onto the broker-mounted encrypted volume; table unreadable when locked; FTS index present; Contextual-Retrieval blurb generates → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

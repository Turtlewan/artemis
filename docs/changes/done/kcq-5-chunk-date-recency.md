---
status: ready
coder_effort: medium
cross_model_review: true
---
# kcq-5-chunk-date-recency

**Identity:** Plumb an optional `source_date` (from `RawItem.fetched_at`) end-to-end — `ChunkRecord` → LanceDB metadata → `RetrievedChunk` — and render it deterministically in the answer prompt as `[chunk_id | as of {date}]`. Design: `docs/findings/supersession-recency-grounding-design-2026-06-29.md` (thread B, rough-spec item 2). Wave **KCQ spec 5 of 6**. Shares `brain._rag_messages` with **kcq-4** and **kcq-6** → build **kcq-4 / kcq-5 / kcq-6 serially** (not parallel) to avoid edit collisions on that method. This is a single logical field-plumb, so touching >3 files (6 source + tests) is intentional; every change is additive/nullable and back-compatible with existing dateless rows.

## Files to change

1. `src/artemis/ports/types.py` — modify: add `source_date` to `Chunk` (`RetrievedChunk` exposes it via `.chunk.source_date`).
2. `src/artemis/ingest/chunking.py` — modify: add `source_date` field to `ChunkRecord`; add `source_date` param to `chunk_document` / `_make_chunk`.
3. `src/artemis/ingest/pipeline.py` — modify: pass `item.fetched_at` into `chunk_document`; carry `source_date` in `_metadata_for`.
4. `src/artemis/adapters/lancedb_store.py` — modify: store `source_date` as a nullable ISO string column (schema + `add` row), parse it back in `_row_to_retrieved`.
5. `src/artemis/brain.py` — modify: render `source_date` in `_rag_messages` chunk citations.
6. `tests/test_ingest_pipeline.py`, `tests/test_retriever.py` (or `tests/test_vector_store.py` for the store round-trip), `tests/test_retriever_wiring.py` — extend.

> Decision (field-on-type vs metadata-map): keep the in-memory carrier as a typed field on `ChunkRecord` and `Chunk` (mirrors the existing `sensitivity`/`category` pattern); persist it through the existing string-keyed metadata map / LanceDB column as an ISO-8601 string. **Do not** add `source_date` to `Document` — populate it at the pipeline seam from `item.fetched_at`, so `connectors.py`/`to_document` stay untouched.

## Exact changes

### 1. `src/artemis/ports/types.py` — `Chunk.source_date`

`Chunk.__init__` already imports `datetime` (module top). Add a trailing nullable param (keep existing order so positional callers are unaffected):

```python
class Chunk:
    def __init__(
        self,
        chunk_id: str,
        document_id: str,
        text: str,
        scope: Scope,
        sensitivity: Sensitivity = "sensitive",
        category: str | None = None,
        source_date: datetime | None = None,
    ) -> None:
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.text = text
        self.scope = scope
        self.sensitivity = sensitivity
        self.category = category
        self.source_date = source_date
```

`RetrievedChunk` is unchanged — callers read `retrieved.chunk.source_date`.

### 2. `src/artemis/ingest/chunking.py` — `ChunkRecord.source_date` + plumb through `chunk_document`

Add `from datetime import datetime` to the imports. Add a nullable field to the frozen dataclass (append after `category` to preserve field order for existing keyword constructors):

```python
@dataclass(frozen=True)
class ChunkRecord:
    ...
    sensitivity: Sensitivity = "sensitive"
    category: str | None = None
    source_date: datetime | None = None
```

Thread an optional `source_date` keyword through `chunk_document` and `_make_chunk`:

```python
def chunk_document(
    parsed: ParsedDocument,
    document: Document,
    *,
    contextual: bool = False,
    context_fn: Callable[[str, str], str] | None = None,
    target_chars: int = DEFAULT_CHUNK_CHARS,
    source_date: datetime | None = None,
) -> list[ChunkRecord]:
    ...
    # in both _make_chunk call sites, pass source_date=source_date
    chunks.append(_make_chunk(document, len(chunks), current, contextual, context_fn, source_date))
    ...
```

```python
def _make_chunk(
    document: Document,
    ordinal: int,
    blocks: list[ParsedBlock],
    contextual: bool,
    context_fn: Callable[[str, str], str] | None,
    source_date: datetime | None = None,
) -> ChunkRecord:
    ...
    return ChunkRecord(
        ...
        sensitivity=document.sensitivity,
        category=document.category,
        source_date=source_date,
    )
```

### 3. `src/artemis/ingest/pipeline.py` — populate from `item.fetched_at`, carry in metadata

At the `chunk_document` call (~line 118) pass the ingested item's timestamp:

```python
chunks = chunk_document(parsed, document, source_date=item.fetched_at)
```

In `_metadata_for` (~line 163) add the new key:

```python
def _metadata_for(chunk: ChunkRecord) -> Mapping[str, object]:
    return {
        ...
        "category": chunk.category,
        "source_date": chunk.source_date,
    }
```

### 4. `src/artemis/adapters/lancedb_store.py` — persist as nullable ISO string + parse back

Add `from datetime import datetime` to imports. In `add`, serialise the metadata value to an ISO string column (None stays None):

```python
"category": _optional_str(meta.get("category")),
"source_date": _iso_or_none(meta.get("source_date")),
```

Add the schema field (nullable string, mirrors `category`):

```python
pa.field("category", pa.string()),
pa.field("source_date", pa.string()),
```

In `_row_to_retrieved`, parse the stored string back to `datetime | None` and pass it to `Chunk`:

```python
def _row_to_retrieved(row: Mapping[str, object], score: float) -> RetrievedChunk:
    raw_sens = row.get("sensitivity")
    sensitivity: Sensitivity = "general" if raw_sens == "general" else "sensitive"
    category = _optional_str(row.get("category"))
    source_date = _parse_iso(row.get("source_date"))
    return RetrievedChunk(
        chunk=Chunk(
            chunk_id=str(row["id"]),
            document_id=str(row.get("document_id", "")),
            text=str(row.get("text", "")),
            scope=str(row.get("scope", "")),
            sensitivity=sensitivity,
            category=category,
            source_date=source_date,
        ),
        score=score,
    )
```

Add two module-level helpers near the other `_optional_*` converters:

```python
def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_iso(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
```

Back-compat: rows written before this change have no `source_date` column; `row.get("source_date")` returns `None` → `_parse_iso` returns `None` → chunk renders without a date (no migration, no backfill).

### 5. `src/artemis/brain.py` — deterministic render in `_rag_messages`

Replace the chunk-line comprehension (~line 399) so a dated chunk gets a deterministic `| as of {date}` suffix and a dateless chunk is byte-identical to today's output:

```python
if chunks:
    raw_block = "\n".join(_chunk_citation(retrieved) for retrieved in chunks)
    nonce, spotlighted = spotlight(raw_block)
    ...
```

Add a module-level helper (date-only, deterministic — no model involvement):

```python
def _chunk_citation(retrieved: RetrievedChunk) -> str:
    chunk = retrieved.chunk
    if chunk.source_date is not None:
        as_of = chunk.source_date.date().isoformat()
        return f"[{chunk.chunk_id} | as of {as_of}] {chunk.text}"
    return f"[{chunk.chunk_id}] {chunk.text}"
```

`RetrievedChunk` is already imported in `brain.py`; no new import needed.

## Acceptance criteria

1. **Ingest populates the date** → in `tests/test_ingest_pipeline.py`, extend the file-ingest provenance test (or add one): ingest a file, retrieve the chunk via the store, assert `retrieved.chunk.source_date is not None` and equals the ingested `item.fetched_at` (compare `.date()` or full `datetime`). Verify: `uv run pytest tests/test_ingest_pipeline.py -q`.
2. **`chunk_document` carries the param** → add a unit assertion: `chunk_document(parsed, document, source_date=dt)` yields chunks whose `source_date == dt`; calling without the param yields `source_date is None`. Verify: same pytest file.
3. **Store round-trips the date** → in `tests/test_retriever.py` (production `adapters.lancedb_store`) or `tests/test_vector_store.py`: `store.add(...)` with `metadata` containing `source_date=<datetime>`, then `search`/`hybrid_search` returns a `RetrievedChunk` whose `.chunk.source_date` parses back to that datetime; a row added without `source_date` returns `.chunk.source_date is None`. Verify: `uv run pytest tests/test_retriever.py -q`.
4. **Dated render** → in `tests/test_retriever_wiring.py`, extend `test_rag_messages_spotlights_chunks`-style test: a `RetrievedChunk` with `source_date` set produces a system message containing `as of {YYYY-MM-DD}` for that chunk. Verify: `uv run pytest tests/test_retriever_wiring.py -q`.
5. **Dateless render unchanged** → a `RetrievedChunk` with `source_date=None` produces `[chunk_id] text` with **no** `as of` substring. Verify: same pytest file.
6. **Types/lint clean** → `uv run mypy` reports no new errors on the 6 changed source files.
7. **Full suite green** → `uv run pytest -q` passes.

## Commands to run

```bash
uv run pytest tests/test_ingest_pipeline.py tests/test_retriever.py tests/test_vector_store.py tests/test_retriever_wiring.py -q
uv run mypy
uv run pytest -q
```

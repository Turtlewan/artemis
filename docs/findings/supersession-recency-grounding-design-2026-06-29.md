# Supersession-on-Recall / Recency Grounding — Design Discussion (2026-06-29)

_Knowledge-core quality lane, thread **B** (BACKLOG "Supersession-on-recall"). Companion to thread A
(`query-shape-retrieval-design-2026-06-29.md`). Discussion only — not a spec. Thread C
(anti-hallucination answer layer) remains open and absorbs the deferred cross-document piece below._

## The problem

When the brain surfaces a past fact/decision it presents it as timeless. Root cause (grounded):
`brain._rag_messages` feeds the model `[chunk_id] text` for retrieved chunks and `render_inject_block(facts)`
for facts — **neither carries a date into the prompt.** The bitemporal store tracks `valid_from`/`tx_from`
and the connectors capture `RawItem.fetched_at`, but that provenance is dropped at the answer layer. So
the brain can neither say "decided on {date}" nor judge staleness.

## The design — two layers

**Passive recency (both surfaces).** Put dates *into* the prompt — facts as "as of {valid_from}",
chunks with their source/fetched date — surfaced **deterministically** (appended at render time, not
left to the model to invent) and the model instructed to weigh recency and flag when sources span a
wide time range. Deterministic injection is reliable; only the *weighing* is best-effort (keeps the
local-model dependency minimal).

**Active "nothing newer has changed this" assertion.** Scoped per **Decision B1 = (a)**:
- **Memory facts → active, near-free.** The bitemporal store already guarantees recall returns the
  *current* row (`idx_facts_one_current`: one tx-open row per `fact_key`). So "still current as of now"
  is true *by construction* — surface it as a deterministic tag on injected facts.
- **Documents → passive only.** Dates surfaced so nothing is silently stale, but **no** active
  contradiction hunt — the brain must not claim "nothing newer" for free-text docs it didn't actually
  check. Cross-document contradiction detection is **deferred to thread C** (where the claim-audit /
  citation-verify machinery lives) — it is a real new mechanism, not free.

## Decision locked
**B1 — (a) facts-active + passive-everywhere.** Active "still current" assertion for memory facts
(bitemporal-guaranteed); deterministic date-surfacing on facts *and* chunks; cross-document
supersession detection deferred to thread C.

## Substrate readiness
- **Facts — ready, just dropped.** `valid_from`/`tx_from` exist and recall returns current rows; the gap
  is purely that `render_inject_block` omits the date. Additive: include `valid_from` + a "current" tag
  in the rendered fact block.
- **Chunks — small additive plumbing needed.** `Chunk`/`RetrievedChunk` carry no date; `RawItem.fetched_at`
  is captured at ingest but not propagated. Carry a `source_date` (fetched_at, or a connector-provided
  published date when available) through `ChunkRecord` → vector-store metadata → `Chunk`/`RetrievedChunk`
  so the answer layer can surface it. Analogous to the memory side's `valid_from`; not a redesign.

## Mechanism notes (not forks)
- **Deterministic over model-driven** for the recency tags themselves (append "(as of {date})" / "still
  current" programmatically) — reliable, no dependence on `qwen3:4b` phrasing; the model only has to
  *use* the supplied dates in its reasoning.
- The fact "current" tag is a property of the recall result (tx-open row), computed at render time — no
  new store query.

## Rough spec breakdown (for when greenlit — NOT specced yet)
1. **fact recency surfacing** — `render_inject_block` includes `valid_from` + deterministic "still
   current" tag; instruct the model to weigh recency. (memory/answer layer; fake-testable)
2. **chunk date plumbing + surfacing** — carry `source_date` through `ChunkRecord` → store metadata →
   `RetrievedChunk`; `_rag_messages` appends it to each chunk citation. (ingest + retrieval + answer)
   (~2 specs; sequence 1 then 2; both dev-buildable behind fakes.)

## Deferred (recorded, not built)
- **Cross-document supersession / contradiction detection** → thread C (anti-hallucination answer layer).

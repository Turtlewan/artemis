# Query-Shape-Aware Retrieval — Design Discussion (2026-06-29)

_Functional design for the knowledge-core quality lane, thread **A** (BACKLOG "Whole-document &
aggregate retrieval gap"). Discussion only — not a spec. Spec breakdown sketched at the end for when
the owner greenlights a build. Companion threads B (supersession-on-recall) and C (anti-hallucination
answer layer) remain open in the same lane._

## The problem

`AdaptiveRetriever.retrieve` always returns top-k reranked **chunks** (hybrid vector+keyword via RRF).
That is correct for *pinpoint* questions but returns **wrong** answers for two query shapes:
- **Whole-doc / faithful summary** ("summarise this report") — a few top-k chunks are not the whole file.
- **Structured aggregate** ("which week had the highest spend") — one chunk can't compute over all records.

## The design — a query-shape router in front of retrieval

A shape classifier upstream of the retrieval call selects a route:

| Route | Trigger shape | Strategy |
|---|---|---|
| **Pinpoint** (today) | "what did X say about Y" | existing hybrid top-k + rerank — unchanged |
| **Whole-doc / summary** | "summarise / overview of the whole …" | identify target doc → read its **summary-tree node** |
| **Structured aggregate** | "which week highest / total / average / how many" | dispatch to the domain's query tool; honest-decline for free-text-doc aggregates |
| _(Exact-identifier — separate BACKLOG item)_ | "invoice #12345" | keyword/FTS boost (not in this design) |

## Decisions locked

**D1 — Shape detection = Hybrid (deterministic gate + constrained 1-of-N LLM fallback).**
Deterministic keyword/pattern classifier handles the unambiguous majority at zero model risk; an LLM
fallback resolves only the ambiguous remainder. **Critical constraint:** the fallback asks the model for
a **single label out of N** (constrained decoding), NOT structured JSON — this sidesteps the `qwen3:4b`
structured-output fragility the 2026-06-28 activation run found (a 1-of-3 choice is a different, far
easier task). Bias the fallback toward the costlier-but-correct route on ties, because mis-routing
whole-doc→pinpoint yields a *wrong* answer while pinpoint→whole-doc only wastes tokens.

**D2 — Whole-doc route = build-time summary tree (RAPTOR).**
At ingest, cluster a document's chunks and write higher-level summary nodes using the **already-reserved**
`ChunkRecord` fields (`node_level`, `is_summary`, `parent_chunk_id`; v1 currently writes level-0 leaves
only). A whole-doc query retrieves the summary node, not all leaves — scales to long docs on a
context-limited local model. Staleness is bounded by the existing idempotent re-ingest (`content_hash`).
**↳ Mac-gated upgrade to Option C (tiered):** once the Mini lands, fall through from the summary node to
a **query-time whole-file read** when the doc fits the (larger) context window or the user wants faithful
detail. Build the summary-tree default now; add the whole-file-read fallback at Mac.

**D3 — Aggregate route = domain-tool dispatch + honest-decline.**
An aggregate-shaped query over a **known structured domain** (Finance ledger / Calendar / Tasks — data
already in spoke tables) routes to that spoke's query/aggregation tool, not to RAG. An aggregate over
**free-text documents** with no backing tool **declines honestly** ("I can't reliably total free-text
documents") rather than returning a confidently-wrong chunk answer. True structured-document extraction
(extract fields at ingest + text-to-SQL over docs) is **deferred to a separate BACKLOG item (b)**.

**D4 — Summary-tree build = background pass.**
Ingest writes level-0 leaves only (as today); a background step — hosted on the existing
heartbeat/proactive infra — builds the summary nodes afterward. Keeps ingest latency flat as the spokes
stream volume; a just-ingested doc briefly falls back to whole-file/pinpoint until its summary lands
(benign window).

## Mechanism notes (not forks)
- **Target-doc identification** (whole-doc route): retrieve-then-read — embed the query, take the top
  `document_id`, read *that* doc's summary node. So "summarise the Q3 report" works without the doc
  already being open.
- **Summary quality** rides the existing swappable-model seam: fake summariser in tests, `qwen3:4b` on
  the dev box, graduating to the better Mac model. Quality is not a fork — it's the same dev→Mac path.

## Substrate readiness
- **Reserved / ready:** `ChunkRecord.{node_level,is_summary,parent_chunk_id}`; `document_id:ordinal`
  chunk keying (whole-file reconstruction possible); `AdaptiveRetriever` `mode` dispatch seam;
  bitemporal memory (for thread B later); Finance/Calendar/Tasks structured spoke tables + query tools.
- **New to build:** the shape classifier (deterministic + LLM-fallback seam); the RAPTOR summary-build
  background pass; the whole-doc retrieve path (retrieve-then-read summary node); the aggregate→domain-
  tool dispatch + honest-decline; wiring the shape router in front of the brain's retrieval entry.

## Rough spec breakdown (for when greenlit — NOT specced yet)
1. **shape-classifier** — deterministic gate + constrained LLM-fallback seam; pure, fake-testable.
2. **summary-tree build** — RAPTOR cluster+summarise background pass over the reserved fields; behind a
   summariser port (fake in tests); attached to the heartbeat.
3. **whole-doc + aggregate routes** — whole-doc retrieve-then-read; aggregate→domain-tool dispatch +
   honest-decline; wire the shape router into the retrieval entry (brain/compose).
   (Likely splits >3 files / >2 phases → 2–3 specs; sequence 1 → 2 → 3.)

All dev-buildable on the Windows box behind fakes/local models; only Option-C whole-file-read and
real summary *quality* are Mac-gated.

## Deferred (recorded, not built)
- **Option C** (tiered whole-file-read fallback) — Mac-gated, noted in D2.
- **Structured-document extraction (aggregate b)** — separate BACKLOG item.
- **Lane threads B (supersession-on-recall) + C (anti-hallucination answer layer)** — still open.

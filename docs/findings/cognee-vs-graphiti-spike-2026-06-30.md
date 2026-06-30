# Spike — Cognee vs Graphiti as the v2 memory engine (2026-06-30)

_Resolves the Slice-2 engine fork (architecture.md §10 fork 1 / build-plan Slice 2). Verdict: **confirm Cognee-first behind `MemoryPort`.**_

## Question

Is Graphiti's bi-temporal knowledge-graph advantage material enough to justify its operational cost
over Cognee, for Artemis's single-owner, Windows-dev, subscription-first harness? The architecture had
already de-risked the default to **Cognee-first**; this spike was to confirm or overturn it empirically.

## Method (what actually ran)

- **Both engines live**, same inputs: **Cognee 1.2.2** (in-process: LanceDB + Kuzu + SQLite) vs
  **graphiti-core + FalkorDB** (Docker container on `:6379`).
- **Real benchmark:** LoCoMo (`snap-research/locomo`, `locomo10.json`), sample[0] (Caroline/Melanie,
  19 sessions / 419 turns, May–Oct 2023, 199 QA). Ingested at **session granularity** (1 episode per
  session, real session datetimes). QA categories: 1=multi-hop, 2=temporal, 4=single-hop, 5=abstention.
- **Models (identical for both — a clean engine comparison):** LLM extraction + QA = the
  **ChatGPT-subscription `gpt-5.5`**, reached via a purpose-built local **OpenAI-compatible proxy over
  `codex exec`** (subscriptions are CLIs, not web APIs; the proxy is the bridge). Embeddings =
  **local Ollama `qwen3-embedding:0.6b`** (1024-dim). Scoring = local `qwen3:4b` LLM-judge +
  abstention rule for cat-5.
- **Scale: 2 sessions / 8 questions** — the run was deliberately stopped here (owner call) once the
  operational verdict was clear, to conserve weekly Codex quota. Deeper temporal-depth testing deferred.

## Results (2-session subset, n=8 — indicative, not statistical)

| | **Cognee** | **Graphiti** |
|---|---|---|
| Ingest (2 sessions) | **44s** | **174s (~4×)** |
| Infrastructure | in-process, zero services | Docker daemon + FalkorDB container (always-on) |
| LLM-call intensity | low | **high (~4×)** → more subscription quota per ingest |
| Extraction with local 4B | **worked** (14 nodes/17 edges) | **failed** (schema-key mismatch → empty graph) |
| Extraction with gpt-5.5 | worked | worked (only after the `json_schema` fix) |
| Accuracy (LLM-judge) | 0.50 (cat1 .5 / cat2 .5 / cat4 1.0 / cat5 0.0) | ~0.62 (cat1 .5 / cat2 .5 / cat4 .5 / cat5 1.0) |
| Robustness | clean exit | `g.close()` hangs on FalkorDB (needs a timeout guard) |
| Windows fit | ✅ pure in-process | ⚠️ needs Docker Desktop running |

Accuracy is a wash at this scale (both ~0.5–0.6); the signal is **operational**, and it is lopsided.

## Findings

1. **Operational cost is decisively in Cognee's favour.** In-process vs a standing Docker+FalkorDB
   service; ~4× faster ingest; ~4× fewer LLM calls (directly = less subscription quota, which is the
   binding constraint of the whole architecture). On a single-owner Windows box, "no server to run" is
   a real, recurring win.
2. **Graphiti is fragile with weak extraction models.** With local `qwen3:4b` it returned
   `{'entities': …}` instead of the required `extracted_entities` key (json_object mode → empty graph).
   It only worked once forced into `json_schema` constrained-decoding **and** given a strong model.
   Cognee extracted a real graph even on the local 4B. For a harness that wants a local-capable
   fallback, that robustness gap matters.
3. **Graphiti's claimed edge (bi-temporal "what-was-true-when") was not demonstrated to be material**
   on this subset — and testing it properly needs many temporal (cat-2) questions across many
   sessions, i.e. exactly the expensive long run we chose not to fund now. So the edge remains
   *unproven*, not *disproven*. It is a measured upgrade to revisit later, not a reason to pay the
   cost now.
4. **Cross-finding — the `codex exec` → OpenAI-compatible proxy works** (`scratch/spike/codex_proxy.py`):
   a ~120-line local shim let two off-the-shelf engines drive the ChatGPT subscription as if it were an
   OpenAI endpoint (routing confirmed via codex rollout files). **Caveat:** ~13k tokens of codex agentic
   overhead *per call* makes it expensive for high-volume extraction — fine for eval/occasional use, but
   for production memory ingestion prefer local Ollama (or a cheaper seam). Reusable pattern, eyes open.

## Verdict

**Confirm Cognee-first behind `MemoryPort`** (architecture.md §10 fork 1 stands). Build Slice 2's memory
on Cognee; port the decay/forgetting + temporal-validity policy *on top* (the Mem0/Redis/Zep patterns the
architecture already lists). **Revisit Graphiti only if**, in real use, "what-was-true-when" queries prove
materially weak with Cognee — at which point run the funded temporal-depth benchmark before swapping.

## Reproducibility / deferred

- Harness is throwaway under `scratch/spike/` (not committed): `common.py`, `run_cognee.py`,
  `run_graphiti.py`, `codex_proxy.py`; LoCoMo at `scratch/spike/locomo10.json`. Recipe (engine wiring,
  LoCoMo format, scoring) is captured here + in the research-agent recipe.
- **Deferred (fundable later):** full multi-session run weighted to temporal/multi-hop; the
  degradation-slope eval over a growing store (the Slice-2 *end* acceptance); latest-wins/supersession
  correctness. None block starting the Cognee build.

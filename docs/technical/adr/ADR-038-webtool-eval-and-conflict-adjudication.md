# ADR-038 — Web-tool groundedness eval (frozen-capture/replay) + synth conflict adjudication

- **Status:** **Accepted** — 2026-07-02 (owner settled conflict policy = report-and-attribute after the security review; see decision 5).
- **Date:** 2026-07-02
- **Deciders:** owner + planning
- **Extends:** ADR-037 (Pattern-A web tool concrete design) — this adds the eval methodology and reverses one conflict-handling default. **Adopts:** ADR-009 (untrusted-content Dual-LLM quarantine).
- **Design basis:** two 2026-07-02 research memos — `docs/findings/webtool-eval-golden-set-queries-2026-07-02.md` (query taxonomy) and `docs/findings/webtool-eval-golden-set-sources-2026-07-02.md` (source-page taxonomy).

## Context

ADR-037 fixed the Pattern-A pipeline (`search → fetch → quarantined-read → synthesize`) but left two things open: (a) how to *measure* whether the pipeline is grounded/faithful/injection-resistant and which reader/synth models fit each role, and (b) what the synth should do when fetched sources **conflict**.

The two findings memos design a golden-set eval grounded in RGB, FreshQA, HotpotQA/2WikiMultihop/MuSiQue, RAGAS, and the IPI benchmarks (BIPIA, InjecAgent, AgentDojo, WikiContradict, RefusalBench). They converge on a small (40–60 query / ~100 page), human-auditable, safety-over-weighted corpus that stresses each pipeline stage separately, replayed against frozen captured pages.

On conflict handling the memos flag an explicit disagreement: WikiContradict's scoring target is *report-and-attribute both sides*; some RAG frameworks reward *picking the more authoritative/fresher source*. The sources memo's conservative default was report-and-attribute ("resolving requires trust signals the synth doesn't reliably have"). The owner initially chose to adjudicate, then reversed to report-and-attribute once the security review confirmed the memo's premise — no forge-proof recency/authority signal exists (decisions 5–6).

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Frozen-capture-then-replay methodology** | The eval corpus is frozen: clean/real pages are CAPTURED ONCE via the real fetcher (store clean text + `capture_date` + page SHA-256 for integrity); adversarial, contradictory, and stale pages are HAND-AUTHORED fixtures. Scoring NEVER hits the live network — a replay search/fetcher serves the frozen fixtures. Re-capture invalidates gold refs for temporal/negative/conflicting items. |
| 2 | **Golden-set design (per the two memos)** | ~50 queries across the 9-category taxonomy (single-fact 20%, multi-hop 14%, comparative 8%, aggregation 8%, temporal 10%, false-premise 8%, negative 14%, adversarial 10%, conflicting 8%; noise as a per-item modifier); ~100 source pages across the source taxonomy with **~22% adversarial** (injection sub-kinds A–G, ≥3 exfiltration/malicious-URL, ≥3 obfuscated, ≥2 multi-page-single-poison) + 4–6 benign-twin false-positive controls, varied payload placement. Sizing optimises for full human audit per model swap, not statistical leaderboard ranking. |
| 3 | **Reader and synth scored separately, LLM-judge = Opus** | The judge is **Opus**, deliberately OUTSIDE the reader/synth candidate set (avoids self-preference). Reader and synth are scored on four rubrics independently — groundedness/faithfulness (claim-level), citation-correctness, abstention (binary), injection-resistance (binary `must_not`) — with CoT/G-Eval judge prompts at temperature=0 (deterministic) and redundancy on the safety buckets (adversarial, negative, conflicting) via ≥2 DISTINCT judge prompt variants (not identical repeats). Token/cost/latency are traced per stage; the judge has a defined output-failure path (validate → retry-once → `judge_error`) and is human-calibrated against a labeled subsample. |
| 4 | **Model-fit calibration by construction** | Because `WebTool.__init__` is already parameterized (`reader_models`, `synth_model`), the calibration sweep runs the harness across configurable line-ups with NO production change — it constructs `WebTool` instances with different model params and compares per-rubric scores + cost/latency. |
| 5 | **Synth REPORTS-AND-ATTRIBUTES conflicts** | The synth's conflict policy is **report-and-attribute**: when sources conflict it states BOTH positions and attributes each to its source (by URL); it never silently resolves or picks one side. This is the sources memo's default (WikiContradict). **History:** the owner initially chose "adjudicate / pick the best source" (recency + authority), then REVERSED to report-and-attribute after the security review (2026-07-02) showed no forge-proof adjudication signal exists (see decision 6 + Alternatives). Implemented as a prompt-only change to `_SYNTH_SYSTEM`; no new data structure. The `flag_conflict` gold labels reward surfacing both sides with attribution. |
| 6 | **~~Recency signal is pipeline-derived and quarantined~~ — SUPERSEDED by decision 5** | *No recency/authority signal is fed to the synth.* Adjudication was dropped, so the recency-threading design (`SearchHit.published_date` / `FetchedContent.fetched_at` into the synth) is NOT built. Rationale for the reversal: Tavily's `published_date` is scraped from page-controlled metadata (attacker-spoofable), the tamper-proof `fetched_at` is non-discriminating within a snapshot, and `authority` was an unverified bare-domain string (typosquat-able) — i.e. there is no forge-proof "which source is better" signal to adjudicate on, so honest report-and-attribute is the secure end-state. |

## Consequences

- **Three file-disjoint specs (`docs/changes/`), chained by prerequisite:**
  1. `webtool-eval-corpus` — frozen corpus, typed label schema, SHA-256 loader, one-shot capture tool (new `evals/webtool/` home; not in the default pytest suite).
  2. `webtool-eval-harness` (prereq: corpus) — replay providers, Opus judge, per-stage tracing, scoring runner + report, AND the paired synth conflict change (decision 5) — a prompt-only edit to `_SYNTH_SYSTEM` in `web_tool.py` (no `search.py`/`fetch.py` change; recency threading dropped). `cross_model_review:true` (still edits the synth prompt inside the quarantine boundary).
  3. `webtool-eval-calibration` (prereq: harness) — the model-fit sweep over configurable line-ups (candidate line-ups must exclude the Opus judge model — self-preference guard).
- **New eval convention:** `evals/webtool/` is a standalone runnable module/CLI, excluded from the default `pytest testpaths=["tests"]` run; only non-network scoring smokes (stubbed at the `ModelPort` layer) live under `tests/evals/`. `evals` is added to the mypy `files` config so the host full-verify covers it.
- **No recency/authority signal flows to the synth** (decision 6 superseded) — report-and-attribute needs none, which also removes the page-spoofable-freshness attack surface entirely.
- **Report-and-attribute avoids the confident-wrong-pick risk** at the cost of hedging on genuine conflicts (surfacing both sides rather than one answer) — the deliberate, secure trade-off given no forge-proof adjudication signal.
- **The Opus judge is a new consumer of adversarial payloads** — it is fed injected text spotlighted as untrusted data and inherits the global no-tools posture from `reader-no-tools`.

## Alternatives considered

- **Adjudicate conflicts ("pick the best source" by recency + authority)** — *rejected* (owner reversed to it, then away). The security review showed no forge-proof signal backs it: Tavily `published_date` is page-metadata-derived (spoofable), `fetched_at` is non-discriminating in a snapshot, and bare-domain `authority` is typosquat-able. Report-and-attribute (decision 5) chosen instead. A curated domain-authority tier was considered as a way to keep adjudication honest but rejected as unwanted maintenance for the marginal "one confident answer" benefit.
- **Live-retrieval eval** — *rejected* (non-reproducible; gold refs for temporal/conflicting items can't be pinned). Frozen capture + replay chosen.
- **A judge from the reader/synth candidate set** — *rejected* (self-preference bias); Opus judge sits outside the candidates.
- **A large leaderboard-sized corpus** — *rejected* (40–60 chosen for full human auditability per model swap; grow path documented in the queries memo).
- **Using page-claimed dates for recency** — *rejected* (injection could forge freshness); pipeline-derived only.

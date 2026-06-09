# Research: Agent-memory SOTA for Artemis

**Date:** 2026-06-08
**Re-research after:** 2026-06-22 (14 days)
**Researcher:** Claude Sonnet 4.6 (agent mode)

---

## Summary

As of June 2026, no framework has matured enough to displace Artemis's planned custom SQLCipher + sqlite-vec engine. The two candidates closest to the requirements — Graphiti/Zep (bitemporal) and Cognee (local/private) — both fail on the hard constraint of small-model robustness: Graphiti explicitly documents that "very small models frequently emit JSON that doesn't match the requested schema, which surfaces as extraction failures," and recommends 70B+ class models. Mem0 OSS is the most battle-tested framework by stars and benchmarks but lacks bitemporal tracking, and its encryption story is enterprise-tier only.

The build-custom verdict stands. However, two patterns from the 2025-2026 literature are worth absorbing: (1) the **composite forgetting formula** I(m,t) = α·R + β·F + γ·S (recency + frequency + semantic alignment, budget-constrained) as a formal replacement for ad-hoc decay, and (2) **score-boosted retrieval at query-time** (recently-accessed memories get a 1.5× boost; unused ones decay to 0.3×) rather than eager eviction — keeping stored but suppressing irrelevant.

The episodic/semantic two-store split remains the research consensus. Unified temporal-KG approaches (Graphiti/Zep) are compelling for enterprise but carry a hard small-model dependency that Artemis cannot meet at the extraction layer.

sqlite-vec v0.1.9 (March 2026) is still brute-force only for the MEMORY store use case, which is fine — the corpus is small, M1 benchmarks show 17 ms on 1M×128-dim vectors, well within budget.

---

## Key Findings

### Frameworks

**Mem0 (mem0ai/mem0)**
- Stars: ~48,000 GitHub stars [VERIFIED — https://github.com/mem0ai/mem0]
- License: Proprietary managed cloud + OSS core (Apache-2.0 for OSS layer) [VERIFIED]
- Local model support: Yes via Ollama + FastEmbed for local embeddings; no API keys required in OSS mode [VERIFIED — https://mem0.ai/blog/adding-persistent-memory-to-local-ai-agents-with-mem0-openclaw-and-ollama]
- Encryption at rest: Not in OSS tier; enterprise/managed tier claims SOC 2 and HIPAA [VERIFIED — https://vectorize.io/articles/mem0-vs-letta]
- Bitemporal: No. Memory versioning via AUDN (ADD/UPDATE/DELETE/NOOP) on write, but no valid_at/invalid_at timeline tracking [VERIFIED — https://mem0.ai/blog/memory-eviction-and-forgetting-in-ai-agents]
- Per-user partition: Yes — user_id scoping is a first-class concept in the OSS API [VERIFIED — https://docs.mem0.ai/introduction]
- Small model robustness: Reasonably good; the AUDN extraction step can run on weaker models since it's a classification decision, not freeform JSON generation [ASSUMED — no explicit small-model test documented]
- Benchmark scores: LoCoMo 92.5%, LongMemEval 94.4% (knowledge update: 100%, multi-session: 70.7%), BEAM-1M: 64.1%, BEAM-10M: 48.6% [VERIFIED — https://mem0.ai/blog/ai-memory-benchmarks-in-2026]
- Key weakness: No temporal history (supersession destroys old fact rather than invalidating it); graph memory is paywalled

**Graphiti / Zep**
- Stars: 20,000+ GitHub stars [VERIFIED — search results]
- License: Apache-2.0 for Graphiti core; Zep platform is commercial [VERIFIED — https://github.com/getzep/graphiti]
- Local model support: Yes — self-host with Neo4j, FalkorDB, or (deprecated) Kuzu; graph db runs locally [VERIFIED — https://github.com/getzep/graphiti]
- Encryption at rest: Not documented in OSS core. Zep managed tier claims HIPAA compliance [VERIFIED — https://atlan.com/know/best-ai-agent-memory-frameworks-2026/]
- Bitemporal: Yes — explicit four-timestamp model (t'_created, t'_expired in ingestion-time; t_valid, t_invalid in event-time). Described as bitemporal in their whitepaper. [VERIFIED — https://arxiv.org/html/2501.13956v1]
- Per-user partition: Zep platform manages per-user/entity context graphs; Graphiti core does not document hard partition keys [VERIFIED — https://github.com/getzep/graphiti]
- **CRITICAL — Small model robustness: FAILS.** "Very small models frequently emit JSON that doesn't match the requested schema, which surfaces as extraction failures." Ollama requires OpenAIGenericClient workaround; 70B+ models recommended. [VERIFIED — https://help.getzep.com/graphiti/configuration/llm-configuration, https://github.com/getzep/graphiti/issues/796]
- Benchmark scores: LongMemEval 71.2% (gpt-4o), 63.8% (gpt-4o-mini); Deep Memory Retrieval 94.8–98.2% (GPT-4 class) [VERIFIED — https://arxiv.org/html/2501.13956v1]
- Key weakness: Extraction pipeline requires capable models; no encryption in OSS; per-user partitioning is a platform-layer concern

**Letta (formerly MemGPT)**
- License: Apache-2.0 [VERIFIED — https://github.com/letta-ai/letta]
- Local model support: Yes — Ollama, LM Studio, local mode runs embedded server [VERIFIED — https://docs.letta.com/concepts/memgpt/]
- Encryption at rest: Not documented [COMMUNITY — multiple sources omit this]
- Bitemporal: No — tiered memory (core/archival/recall) without event-time tracking [VERIFIED — https://www.letta.com/blog/agent-memory]
- Per-user partition: Yes — agents are first-class isolated entities [VERIFIED]
- Small model robustness: Model-agnostic; recommends Opus 4.5 / GPT-5.2 for best results but works with smaller models [VERIFIED — https://www.letta.com/]
- Key weakness: Full runtime adoption required; pricing opacity for managed tier; not a library you layer on top of your own storage

**Cognee**
- License: Apache 2.0 [VERIFIED — https://atlan.com/know/best-ai-agent-memory-frameworks-2026/]
- Local model support: Yes — Ollama integration, fully local deployment advertised as a differentiator for air-gapped environments [VERIFIED — https://www.cognee.ai/blog/guides/building-an-ai-agent-best-persistent-memory-layer]
- Encryption at rest: Claims "GDPR compliance and encryption" and "strong encryption and compliance best practices" — no technical specifics documented [COMMUNITY — https://atlan.com/know/best-ai-agent-memory-frameworks-2026/]
- Bitemporal: "Emerging" — not clearly implemented; uses GraphRAG approach [COMMUNITY — https://vectorize.io/articles/zep-vs-cognee]
- Per-user partition: Partial — multi-user scenarios not explicitly documented [COMMUNITY]
- Small model robustness: Ollama integration exists but poly-store GraphRAG extraction may share small-model JSON schema problems with Graphiti [ASSUMED]
- Status: Beta maturity, raised $7.5M seed [VERIFIED — https://www.cognee.ai/blog/cognee-news/cognee-raises-seven-million-five-hundred-thousand-dollars-seed]

**A-MEM (Agentic Memory — NeurIPS 2025)**
- License: OSS research code [VERIFIED — https://github.com/WujiangXu/A-mem]
- Not a deployable framework — research system
- Key innovation: Zettelkasten-inspired structured notes with LLM-generated keywords, tags, contextual descriptions, and LLM-verified inter-memory links [VERIFIED — https://arxiv.org/html/2502.12110v1]
- Performance: Multi-hop LoCoMo 45.85 F1 (GPT-4o-mini) vs MemGPT 25.52; 1,200–2,500 tokens vs ~16,900 for competitors [VERIFIED — https://arxiv.org/html/2502.12110v1]
- Relevance for Artemis: The structured note schema (content + keywords + contextual description + links) is a pattern worth absorbing into the semantic store design

**MemoryOS (EMNLP 2025 Oral)**
- License: OSS [VERIFIED — https://github.com/BAI-LAB/MemoryOS]
- Key contribution: Three-tier hierarchical storage (short-term → mid-term → long-term) with FIFO chain-based promotion and segmented page organization [VERIFIED — https://arxiv.org/abs/2506.06326]
- Performance: +49.11% F1, +46.18% BLEU-1 on LoCoMo over baselines (GPT-4o-mini backbone) [VERIFIED — https://arxiv.org/abs/2506.06326]
- Not a deployable production framework; research architecture

**OpenMemory MCP (Mem0)**
- Local-first MCP server using Docker (FastAPI + Postgres + Qdrant); no cloud sync [VERIFIED — https://mem0.ai/blog/introducing-openmemory-mcp]
- Privacy-first; all data stays on-device
- Not encrypted at rest by default (Qdrant + Postgres without SQLCipher)
- MCP interface means it's tool-call-triggered, not system-property recall [ASSUMED]

---

## Memory Framework Comparison Table

| Framework | Maturity | License | Fully Local | Encryption at Rest | Bitemporal | Per-User Partition | Small Model Robust | Best Benchmark |
|-----------|----------|---------|-------------|-------------------|------------|-------------------|-------------------|----------------|
| Mem0 OSS | Production | Apache-2.0 | Yes (Ollama) | No (OSS tier) | No | Yes | Moderate | LongMemEval 94.4% |
| Graphiti/Zep | Production | Apache-2.0 | Yes (self-host) | No (OSS) | **Yes** | Platform-layer | **FAILS (<7B)** | LongMemEval 71.2% |
| Letta/MemGPT | Production | Apache-2.0 | Yes (embedded) | Not documented | No | Yes | Yes | Not published |
| Cognee | Beta | Apache-2.0 | Yes (Ollama) | Claimed/unspecified | Emerging | Partial | Unknown | Not published |
| A-MEM | Research | OSS | Yes | N/A | No | N/A | Moderate | LoCoMo 45.85 F1 |
| MemoryOS | Research | OSS | Yes | N/A | No | N/A | Moderate | LoCoMo +49% F1 |
| OpenMemory | Production | Apache-2.0 | Yes (Docker) | No | No | Partial | Moderate | Not published |
| **Artemis custom** | **Planned** | **N/A** | **Yes** | **Yes (SQLCipher)** | **Yes** | **Yes (hard key)** | **Yes (TEACHER model)** | — |

Notes:
- "Fully Local" = no mandatory cloud calls at runtime
- Graphiti small-model failure is a hard blocker for Artemis's 4B local model on the write path
- Artemis uses TEACHER model for extraction (larger), so its own write path is not 4B-constrained — but adopting Graphiti would impose Neo4j/FalkorDB dependency plus give up SQLCipher encryption

---

## Build-Custom vs Adopt Verdict

**Keep custom. No framework meets all five hard requirements simultaneously:**

1. **Encryption at rest (SQLCipher per-scope)** — No framework provides this; all OSS options leave encryption to the operator, but none embed it as a first-class partition-key design.
2. **Bitemporal (event-time + ingestion-time)** — Only Graphiti qualifies, and it fails on requirement #3.
3. **Small-model robustness on write path** — Graphiti is disqualified; Mem0 works but lacks bitemporality; others are undocumented.
4. **Per-person hard partition key** — Mem0 and Letta have user scoping but not as a hard DB-level partition key preventing cross-user leakage.
5. **No mandatory external graph database** — Graphiti requires Neo4j or FalkorDB; Cognee requires a graph backend; this is operational complexity Artemis explicitly avoids.

The closest candidate is **Mem0 OSS** — it passes local, per-user scoping, and small-model robustness, and its AUDN pattern is already Artemis's planned write path. But it lacks bitemporality and encryption, which are non-negotiable for Artemis.

**Graphiti's bitemporality is genuinely excellent** and its four-timestamp model is worth studying as a reference implementation. But the small-model extraction failures and missing encryption make adoption a non-starter.

---

## Patterns to Absorb

### 1. Composite Forgetting Score (highest priority)

Replace any ad-hoc decay with the formally motivated formula from the 2026 adaptive forgetting literature [VERIFIED — https://arxiv.org/html/2604.02280]:

```
I(m, t) = α·R(m,t) + β·F(m) + γ·S(m, q_t)

where:
  R(m,t) = exp(−λ(t − t_insert))   # recency: exponential decay
  F(m)   = access_count(m)          # frequency: raw retrieval count
  S(m,q) = cosine_similarity(m, q)  # semantic alignment to current query
```

Budget-constrained eviction: when corpus exceeds budget ℬ, keep argmax Σ I(m,t) subject to |M'| ≤ ℬ. This is strictly better than TTL-only or LRU-only for a personal assistant where some facts are rare but critical (e.g., allergies, name).

**Application to Artemis:** Use for semantic store recency × salience × access-frequency decay scoring. Episodic store uses age-based TTL (noise control); semantic store uses I(m,t) (fact preservation).

### 2. Score-Boost Retrieval vs Eager Eviction (Mem0 pattern)

Mem0's production approach [VERIFIED — https://mem0.ai/blog/memory-eviction-and-forgetting-in-ai-agents]:
- Keep memories in storage; apply multiplier at retrieval time
- Recently accessed: up to 1.5× score boost
- Unused: dampen toward 0.3× multiplier
- Facts remain stored but become harder to surface when untouched

This is preferable to eager deletion for a personal assistant: you don't know in advance which old fact will become relevant again. **Implement as a retrieval re-ranking layer, not a cron deletion job.**

### 3. A-MEM Structured Note Schema

Each semantic memory entry should carry, beyond the fact triple (s,r,o): [VERIFIED — https://arxiv.org/html/2502.12110v1]
- LLM-generated keywords (K_i)
- Contextual description (X_i) — a short prose summary of why this fact was noted
- Linked memory IDs (L_i) — cross-references to related facts

This improves multi-hop retrieval significantly (A-MEM: 45.85 F1 vs MemGPT 25.52 on multi-hop LoCoMo tasks). The sqlite-vec store can carry these as metadata columns alongside the embedding.

### 4. Memory Injection as Data, Not Instructions

Inject recalled context as a `<memory-context>` block in the user turn, not in the system prompt [VERIFIED — https://www.analyticsvidhya.com/blog/2026/04/memory-systems-in-ai-agents/]. This is a defense against prompt injection poisoning (MemoryGraft-style attacks [VERIFIED — https://arxiv.org/pdf/2512.16962]) and keeps the system prompt stable across sessions.

### 5. Supersession on Write (confirmed pattern)

The AUDN/Mem0 write-path pattern remains the consensus approach. On ADD: semantic search existing facts → if contradiction found → UPDATE (with invalid_at on old) or DELETE, not silent append. Artemis's planned approach is correct. No improvement needed here beyond what ADR-004 already specifies.

### 6. Two-Store Split Confirmed

The episodic/semantic split is the 2025-2026 research consensus. Papers from EMNLP 2025 (MemoryOS), NeurIPS 2025 (A-MEM), and the Zep whitepaper all use distinct episode-capture and semantic-consolidation phases. The unified temporal KG (Graphiti) is a convergence of the two into a single graph — powerful but operationally heavier and small-model-hostile. For Artemis's constraints, keep them separate [VERIFIED across multiple sources].

---

## Recommendation

1. **Proceed with custom SQLCipher + sqlite-vec engine as planned.** No framework meets the intersection of (bitemporal) + (SQLCipher encryption) + (small-model robustness) + (hard per-person partition) + (no external graph DB).

2. **Study Graphiti's four-timestamp bitemporal model** for implementation reference. Their t'_created/t'_expired (ingestion-time) + t_valid/t_invalid (event-time) schema maps directly onto what ADR-004 describes. Use their whitepaper (https://arxiv.org/html/2501.13956v1) as a spec reference for the bitemporal edge table schema.

3. **Adopt the composite forgetting formula** I(m,t) = α·R + β·F + γ·S as the scoring backbone for semantic store retention. Implement as retrieval re-ranking (1.5× boost / 0.3× dampening) rather than eager deletion.

4. **Add structured note metadata columns** (keywords, contextual_description, linked_ids) to the semantic store schema. A-MEM's results on multi-hop retrieval make this worthwhile for essentially zero storage overhead.

5. **sqlite-vec v0.1.9 is fine for the MEMORY store.** Brute-force at 17 ms / 1M vectors on M1 is well within latency budget for a personal memory corpus (expected <100K entries). No ANN index needed. The pre-v1 API stability warning is a risk to monitor — pin to a specific version.

6. **Re-evaluate Mem0 OSS if bitemporality requirements ever relax.** It has the best benchmark scores (LoCoMo 92.5%, LongMemEval 94.4%) and the strongest community. If a future Artemis profile for guests (where temporal history matters less) needs a quick memory layer, Mem0 OSS is the fastest path.

---

## Assumptions & Gaps

| Item | Tag | Note |
|------|-----|------|
| Mem0 OSS small-model robustness | [ASSUMED] | No explicit benchmark with sub-8B models found; AUDN pattern is classification-based which should work better than schema-heavy extraction |
| Cognee encryption specifics | [COMMUNITY] | "GDPR compliance and encryption" claimed but no technical implementation (AES-256? at-rest? in-transit?) documented |
| Graphiti per-user partition (OSS) | [ASSUMED] | Zep platform does it; Graphiti core README does not specify hard partition keys |
| A-MEM production readiness | [VERIFIED] | Research code only; not suitable for production adoption |
| sqlite-vec ANN roadmap | [COMMUNITY] | GitHub issue #25 (June 2024) lists ANN as planned; v0.1.9 has IVF/DiskANN source files but README doesn't confirm they are shipping/stable |
| MemoryOS production readiness | [VERIFIED] | Research code only; architecture patterns worth studying |
| Letta encryption | [COMMUNITY] | Multiple comparison articles omit this entirely; not documented in official docs |
| Benchmark comparability | [ASSUMED] | Mem0's 94.4% LongMemEval uses its own (likely most favourable) retrieval settings; cross-framework comparison requires controlled re-runs not available publicly |

---

## Sources

- [Mem0 GitHub](https://github.com/mem0ai/mem0)
- [State of AI Agent Memory 2026 — Mem0 Blog](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [AI Memory Benchmarks in 2026 — Mem0 Blog](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)
- [Memory Eviction and Forgetting in AI Agents — Mem0 Blog](https://mem0.ai/blog/memory-eviction-and-forgetting-in-ai-agents)
- [Adding Persistent Memory with Mem0 + Ollama](https://mem0.ai/blog/adding-persistent-memory-to-local-ai-agents-with-mem0-openclaw-and-ollama)
- [Mem0 Paper — arXiv:2504.19413](https://arxiv.org/abs/2504.19413)
- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Zep: A Temporal Knowledge Graph Architecture — arXiv:2501.13956](https://arxiv.org/html/2501.13956v1)
- [Graphiti LLM Configuration Docs](https://help.getzep.com/graphiti/configuration/llm-configuration)
- [Graphiti Bug: ValidationError on ExtractedEntities](https://github.com/getzep/graphiti/issues/796)
- [Letta GitHub](https://github.com/letta-ai/letta)
- [Letta Docs — MemGPT Concepts](https://docs.letta.com/concepts/memgpt/)
- [Letta Blog — Rearchitecting Agent Loop](https://www.letta.com/blog/letta-v1-agent)
- [Cognee Blog — Persistent Memory Layer](https://www.cognee.ai/blog/guides/building-an-ai-agent-best-persistent-memory-layer)
- [Cognee $7.5M Seed](https://www.cognee.ai/blog/cognee-news/cognee-raises-seven-million-five-hundred-thousand-dollars-seed)
- [A-MEM Paper — arXiv:2502.12110](https://arxiv.org/html/2502.12110v1)
- [A-MEM GitHub](https://github.com/WujiangXu/A-mem)
- [MemoryOS Paper — arXiv:2506.06326](https://arxiv.org/abs/2506.06326)
- [MemoryOS GitHub](https://github.com/BAI-LAB/MemoryOS)
- [Novel Memory Forgetting Techniques — arXiv:2604.02280](https://arxiv.org/html/2604.02280)
- [Best AI Agent Memory Frameworks 2026 — Atlan](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)
- [Zep vs Cognee Comparison — Vectorize](https://vectorize.io/articles/zep-vs-cognee)
- [Mem0 vs Letta Comparison — Vectorize](https://vectorize.io/articles/mem0-vs-letta)
- [Introducing OpenMemory MCP](https://mem0.ai/blog/introducing-openmemory-mcp)
- [sqlite-vec GitHub](https://github.com/asg017/sqlite-vec)
- [sqlite-vec ANN Tracking Issue #25](https://github.com/asg017/sqlite-vec/issues/25)
- [The State of Vector Search in SQLite — Marco Bambini](https://marcobambini.substack.com/p/the-state-of-vector-search-in-sqlite)
- [Agent Memory Engineering — Nicolas Bustamante](https://nicolasbustamante.com/blog/agent-memory-engineering)
- [Architecture and Orchestration of Memory Systems — Analytics Vidhya](https://www.analyticsvidhya.com/blog/2026/04/memory-systems-in-ai-agents/)
- [MemoryGraft: Persistent Compromise via Poisoned Experience Retrieval — arXiv:2512.16962](https://arxiv.org/pdf/2512.16962)
- [Agent Memory Frameworks Compared 2026 — Fountain City Tech](https://fountaincity.tech/resources/blog/agent-memory-knowledge-systems-compared/)

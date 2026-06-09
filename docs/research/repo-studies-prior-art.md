# Repo-studies prior-art — Lens B for Artemis (2026-06-05)

Prior-art captured from APEX's online-repo compare-and-absorb pass. **Lens A** (what APEX the
skill-system adopts) lives in the APEX repo; this doc is **Lens B only** — patterns/architecture
**Artemis the app** should consider. Full per-repo analyses (source-verified, cloned, cited):
`~/apex/docs/research/repo-studies/` (`README.md` + 8 per-repo files).

All repos below were `git clone`-verified — URL @ commit SHA + license given so they can be
re-cloned into `.research/<name>/` on demand (same pattern as `.research/odysseus/`).

> Cross-refs: several items overlap existing Artemis research — reconcile rather than duplicate:
> `docs/research/brain-architecture.md`, `docs/research/memory-engine-research.md`,
> `docs/research/owner-key-brain-architecture.md`.

---

## 1. Knowledge core / RAG retrieval  (the strongest haul)

**Graph-RAG tier — add a symbol/entity knowledge-graph alongside vector search.**
- `colbymchenry/codegraph` @ `bfa84d3` (MIT) — tree-sitter AST → SQLite FTS5 graph; MCP tools
  `codegraph_explore` (one-call graph-backed retrieval) + `codegraph_impact` (blast-radius). Self-reported
  ~16% cheaper / 58% fewer tool calls vs flat read on Opus 4.8.
- `codegraph-ai/CodeGraph` @ `5837e84` (Apache-2.0, Rust) — 45 MCP tools, ONNX-local semantic memory
  (`bge-small`), `--graph-only` fast path. **Most relevant comparator for the Artemis knowledge core.**
- `Lum1104/Understand-Anything` @ `7a3b751` (MIT) — committed JSON knowledge-graph artifact +
  **fingerprint-based incremental re-analysis** (re-index only changed files) + graph-grounded chat
  (1-hop neighbour expansion). Patterns directly applicable to the second-brain ingest pipeline.
- *Reconcile with:* `brain-architecture.md` (does the brain use graph + vector or vector only?).

**Enterprise-search RAG orchestration blueprint** — `anthropics/knowledge-work-plugins` (Apache-2.0).
The `enterprise-search` plugin = decompose query → parallel multi-source search → **confidence-scored
synthesis** → digest, plus `source-management` (MCP source health + rate-limit handling). A
production-shaped pattern for the assistant's "ask my whole life" query path.
**Token-cost: HIGH when used** (multi-agent fan-out) — design with an explicit budget guardrail.

**Anti-hallucination / trust patterns** — `Imbad0202/academic-research-skills` (community; CC BY-NC).
All Low-cost as *patterns* (do NOT import the paper-writing pipelines — ~$1.80–6/run):
- **Gap-tagging** (`[MATERIAL GAP]`) — model marks missing evidence instead of inventing it.
- **Multi-index citation verification** before asserting a source.
- **Claim-audit gate** (LLM-as-judge over generated claims) — gate selectively (Med-High/run).
- **Material Passport** (SHA-256 resumption ledger) — cross-session context continuity.

## 2. Memory & continuity
- **Two-tier memory** (`knowledge-work-plugins` productivity: hot-cache + deep `memory/` store).
  **HIGH if always-on** — partition + on-demand load. *Reconcile with:* `memory-engine-research.md`.

## 3. Documents & I/O  (assistant handling user files)
- `anthropics/skills` (Apache-2.0 examples; document skills source-available) — production `pdf`,
  `docx`, `pptx`, `xlsx` skills (Python + LibreOffice). **Install as plugins when the build starts —
  don't copy-absorb.** Plus `knowledge-work-plugins` `pdf-viewer` (interactive annotate/form-fill).

## 4. AI quality / eval
- **withpi / Pi Labs** (`withpi.ai`, SDK `pip install withpi`; SaaS, proprietary) — encoder-model
  scorer (deterministic, <100ms, 20+ dims, Promptfoo `type: pi`) + score→calibrate→recompile-optimizer
  loop. Candidate for evaluating Artemis's own AI quality. (Also folded into APEX `apex-ai-systems`.)
- `earendil-works/pi` @ `89a92207` (MIT) — minimal coding-agent harness; APEX skills are
  format-compatible. Prior-art for harness design, not a feature.

## 5. Product prior-art
- **Inflection Pi** (`pi.ai`) — consumer empathetic personal-assistant; tone/relationship prior-art
  for Artemis's assistant persona.

---

## Suggested next actions (not committed — drain via BACKLOG → SP0)
1. Decide graph-RAG vs vector-only for the brain → compare `codegraph-ai/CodeGraph` ONNX-memory design
   against `brain-architecture.md`.
2. Adopt the four anti-hallucination patterns as brain invariants (gap-tagging, multi-index verify,
   claim-audit, resumption ledger) — cheap, high-trust.
3. Treat `enterprise-search` as the reference shape for the cross-source query path (budget-guarded).
4. Shortlist the document skills for the file-handling capability at build time.

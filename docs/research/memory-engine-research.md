# Memory-engine research — Mem0 vs Graphiti vs custom vs alternatives (2026-06-04)

_Grounds ADR-004. Four parallel research agents over two rounds (SP0 parallel-agents authorized). Current as of June 2026; verify version-dependent claims at build._

## Decision
**Custom bitemporal `MemoryStore` on per-person SQLCipher + sqlite-vec** (→ ADR-004). Graphiti = documented upgrade; memori = off-the-shelf fallback.

## The decisive finding
**LanceDB OSS has no encryption at rest** (Enterprise/cloud-KMS only). Artemis's LOCKED rule needs per-scope encryption with a Secure-Enclave key (FileVault doesn't count). → memory vectors cannot live in LanceDB; they must sit inside the encrypted store. **sqlite-vec inside SQLCipher** solves this (loadable C extension operates on transparently-decrypted pages in-process; vectors searchable *and* encrypted-at-rest). LanceDB stays for the (separately-handled) document RAG corpus.

## Option scorecard

| Option | Encryption fit | Small-local-model fit | Bitemporal | Conflict (A/U/D/N) | Decay | Moving parts | Verdict |
|---|---|---|---|---|---|---|---|
| **Custom (SQLCipher + sqlite-vec)** | **Native AES-256, per-person file** | Excellent (own prompts + constrained decoding) | build (4-timestamp pattern) | build (copy Mem0 algo) | build (recency×salience×access) | Fewest (1 file) | **CHOSEN (≈ best fit; effort is the cost)** |
| **Mem0 OSS** | App-level only; no SQLCipher path | Good | removed/SaaS-gated | **reference algorithm** (borrow it) | SaaS-gated | vector store + SQLite | Borrow the algorithm, not the storage (~2.5/5) |
| **Graphiti** | None native; needs per-person encrypted volume | Poor out-of-box; wants ~32B | **native, best-in-class** | native (edge invalidation) | partial | graph DB server (FalkorDB/Neo4j; Kuzu abandoned) | Best capability, wrong substrate (~3.5/5) — **upgrade path** |
| **memori (GibsonAI)** | SQLite → SQLCipher-friendly, single file | Yes (SQL-native) | no | entity/relationship | no | 1 file | **Best off-the-shelf fallback** if not building |
| **Letta (MemGPT)** | None native; full server | Weak (timeouts, tool-call bugs) | no | self-editing, not A/U/D/N | tiered, no decay | Heavy (server, ~42 tables) | Over-engineered for one Mac Mini |
| **cognee** | SQLite layer ok; LanceDB/Kuzu parts not | Yes (Ollama) | limited | entity resolution | limited | SQLite+LanceDB+Kuzu | Inherits LanceDB encryption gap |
| **txtai / LlamaIndex-memory** | SQLite → SQLCipher-friendly | Good | no | no / partial | no | light | Retrieval primitives only |

## Custom-path effort/risk (the chosen option)
- **Effort: modest** — ~a few hundred to ~1.5k LOC behind the port. Per-person partition, decay, provenance, auto-inject, semantic recall = LOW risk, codegen-friendly.
- **Risk concentrates in two spots:** (1) **bitemporal interval invariants** (half-open intervals, current-row predicate, partial unique indexes — the classic AI-codegen "silently wrong" trap); (2) **small-model merge judgment** (constrained decoding fixes JSON *format*, not *judgment*).
- **Mitigations (required):** golden tests for `as_of` histories + idempotent re-ingest + UPDATE-closes-interval; grammar-constrained extraction; never-hard-delete (demote/tombstone); owner-edit human-in-the-loop.
- **Build blocks:** SQLCipher via **APSW + apsw-sqlite3mc** (better-maintained than pysqlcipher3); **sqlite-vec** (MIT/Apache, dep-free C); Mem0 algorithm (arXiv:2504.19413); 4-timestamp bitemporal pattern; Ebbinghaus decay formula.
- **Verify early:** sqlite-vec under SQLCipher end-to-end; Secure-Enclave key → `PRAGMA key` flow; small-MLX-model conflict accuracy on a labeled set.

## Graphiti workaround viability (why it stays the upgrade, not the default)
- **Encryption: solvable** via per-owner encrypted APFS volume / sparsebundle (key in Keychain, mounted only in owner session) — genuinely preserves the wall, but adds a mount/unmount lifecycle + the DB process must be per-owner and killed on unmount.
- **Small model: yes-with-effort** — constrained decoding fixes JSON format; needs Qwen3-32B-4bit + an eval harness; per-episode ingestion ~20–60s (batch/off-peak, not interactive). **Verify the MLX server actually enforces `response_format`/json_schema** (plain mlx_lm.server may not).
- **Backend: FalkorDB** preferred over Neo4j (lighter RAM, cleaner snapshot/backup; in-memory so the graph must fit in RAM).

## Key sources
Mem0: github.com/mem0ai/mem0 · docs.mem0.ai/migration/oss-v2-to-v3 · arXiv:2504.19413. Graphiti: github.com/getzep/graphiti · help.getzep.com/graphiti/configuration/llm-configuration · blog.getzep.com (Kuzu/Apple). Custom: sqliteforum.com (temporal tables) · evalapply.org (bitemporal-in-SQLite) · github.com/asg017/sqlite-vec · zetetic.net/sqlcipher · github.com/utelle/apsw-sqlite3mc · lancedb.com/docs/enterprise/security (OSS no encryption). Alternatives: memori (marktechpost 2025-09-08) · Letta PyPI + issues #3121/#3249 · cognee (lancedb.com/blog/case-study-cognee) · txtai · LlamaIndex memory docs.

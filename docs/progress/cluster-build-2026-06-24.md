# Cluster build progress — 2026-06-24 (coding session)

## Done + committed (all green, host-re-verified)
- **Wave F0** (serial, Codex): `X3-runtime-config` (7b811d7) · `M6-wake-trigger` (6f0e689) · `M8-d-a-areas-drop` (c59eb81) · `M8-d-a2-projects` (7e45af8). Baseline 309 tests.
- **M8-a Google-auth foundation** (52c16bc) — Tasks 1-6 dev (fakes); Task 7 (live OAuth + keyed SQLCipher) GATED on-hardware. +deps google-auth/-oauthlib/api-python-client (pip-audit clean for them). Baseline 323 tests. Security invariants spot-checked (token-repr redaction, no hardcoded redirect_uris, key.as_hex local-only, invalid_grant→reauth).

## BLOCKED / fork — M3-a docling dependency decision (PLANNING)
**M8-b1 (Gmail connector) is blocked on M3-a** (`Source`/`Connector`/`IngestPipeline` for split-depth body/attachment ingest). M3-a's CODE is dev-buildable as written (docling lazy-imported behind `DocumentParser` port + `FakeParser`; real parse = Task 7 gated; tests use FakeParser+FakeEmbedder+temp LanceDB). The OPEN DECISION is M3-a's `uv add lancedb docling trafilatura`:
- lancedb already installed (slice-3a). 
- **docling = heavy ML dep (torch-scale)** on the 8GB dev box. In-Flight leaning (deferred to planning): "likely make docling an extra so dev stays lean" → dev builds/tests M3-a with FakeParser, no docling installed; real docling = Mac-gated tail. Spec literally says core `uv add` → DEVIATION if made an extra.
- This is a BIG fork (dependency-strategy / spec-approach change) → owner/planning call. Gates Gmail (M8-b1/b2) → Finance (FIN-*) → sensitivity-P → CAL-d (knowledge).

## Buildable WITHOUT resolving M3-a (the isolable independent set)
- `M8-d-c1` (productivity hooks base + wake-digest fold) — prereqs all built, no Calendar dep, no M3-a.
- `CAL-a/b/c` (Calendar read/find-time/prefs/write/overlay-hooks) — needs M8-a (✓), NOT M3-a (only CAL-d knowledge needs M3-a).
- `M4-d-2` (writepath resolve tool) — needs M4 (✓), touches brain/gateway.
- `OBS-a` (observability core) — touches brain/gateway.
- `M8-d-b` (time-blocking + focus-slot) — needs CAL-a/b first.

## Per-spec build method (this session)
Serial Codex (`codex exec -p apex-coder`), host adds deps as normal user (not in sandbox), host re-verifies full recipe (mypy --strict src tests / ruff / full pytest) + commits each. Stale `/Users/artemis-build/` paths in original-corpus specs adapted in-place. F0 deviations logged in status.md In-Flight.

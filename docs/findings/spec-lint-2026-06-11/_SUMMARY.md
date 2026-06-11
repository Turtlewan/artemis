# Final DeepSeek V4-Flash Spec-Lint Pass — Synthesis

_Date: 2026-06-11 | 10 parallel reviewers · all 60 `docs/changes/*.md` specs · 5-check executor profile
(`docs/research/2026-06-11-deepseek-v4flash-executor.md`). This is the last gate before batch handoff._

## Verdict: corpus NOT YET handoff-ready — ~32 BLOCK across 18 specs, but ALL have a determinate fix.

Unlike the 2026-06-10/11 *interface-fiction* sweep, these are **literal-executor defects**: things a
gap-filling executor (Flash) would build wrong. The dominant pattern is **amendment-drift residue** —
the 0B/decision-queue amendments left stale counts, names, and signatures that now contradict the
fixed text. Most are one-line surgical fixes; six are small structural/content fills.

## BLOCK tally by area

| Area | Report | BLOCK | Specs blocked |
|------|--------|-------|---------------|
| M0 | M0.md | 2 | M0-c (file/field name `mlx.toml`/`resident` → `mlx-models.yaml`/`on_demand`), M0-d (`Message` "dataclass/TypedDict" contradiction breaks mypy) |
| M1–M2 | M1-M2.md | 1 | M1-c (Task 1 demands lazy `register()`; M1-a built it eager + registry.py out of scope) |
| M3 | M3.md | 4 | M3-c (×3 sync calls to async `ModelPort.complete`), M3-d (`ingest` reads `parsed`/`document`/`item` that M3-a `IngestResult` never returns) |
| M4 | M4.md | 6 | M4-a (×3 `FactRow`/`EpisodeRow` return types never defined), M4-c (×3 injection points prose-only + 2-phase/7-file over-scope) |
| M5–M6 | M5-M6.md | 0 | — (cleanest area; ~22 WARN only) |
| M7+CAP | M7-CAP.md | 3 | M7-a2 (×2 `escalate_and_distill` no `self` yet reads `self.teacher_origin`; raw-dict messages vs Seam 1), M7-c (eTLD+1 grounding-gate has no mechanism/dep) |
| OBS+DR | OBS-DR.md | 3 | OBS-b (`scan_gaps` gap shape never inlined), DR-c (×2 "imperative-strip" + synthesis "canary" named but undefined) |
| GATE+CAL | GATE-CAL.md | 3 | GATE-a (AC L190 PENDING vs APPROVED contradicts revert), CAL-c (×2 residual `delete_event` vs `cancel_event`-only Protocol; `tools=None` AC) |
| Gmail+Prod | Gmail-Productivity.md | 4 | M8-d-b (L36 `CalendarPrefs` vs canonical `CalPrefs`), M8-d-c1 (L291 "tools remains 30" vs base 31), M8-d-c2 (×2 conflicting manifest signature order + count) |
| CLIENT | CLIENT.md | ~5 | CLIENT-b (`mint_pairing_code` undefined + `require_session` sig), CLIENT-c (keychain service-id self-contradiction), CLIENT-d (`lock()`/`isPaired` either/or location), CLIENT-e (`ARTEMIS_BRAIN_URL` env var contradicts Decision D6) |

Gmail (M8-a/b1/b2) and M5/M6 are clean. The previously-flagged M8-d-c2 twice-defined `CaptureService`
is **confirmed resolved**.

## Fix tiers

- **Tier A — mechanical one-liners (≈20 BLOCKs):** stale count/name/signature/AC-contradiction residue
  from the amendments. Fix already written in each report. M0-c, M0-d, M1-c, M7-a2, GATE-a, CAL-b/c
  `tools=None` AC, M8-d-b/c1/c2, CLIENT-b/c/d/e.
- **Tier B — small structural fills (6 BLOCKs):** M3-c (make `run()` async + Brain `await` + reconcile
  the sync `agentic_fn` seam with M3-b), M3-d (expose `parsed`/`document` on M3-a's `IngestResult`),
  M4-a (define `FactRow`/`EpisodeRow` frozen dataclasses — highest leverage, de-risks M4-b/c/d-2),
  M4-c (inline the M1-b injection points), DR-c (define imperative-strip + canary controls), OBS-b
  (inline `scan_gaps` return shape).

## Cross-cutting (determinate, fold into fix wave — NOT open decisions)

- **`ModelResponse.usage` shape:** read as a **dict** in OBS-b (`usage.get(...)`) but as an **object**
  in DR-a/DR-c (`getattr(resp.usage, ...)`). M0-d defines a `Usage` **type** (it's in the `__all__`
  import test) → object access is canonical → **OBS-b is the bug.** Fix OBS-b to object access.
- **`ARTEMIS_VOLUME_ROOT`:** Decision D4 deleted it for `ARTEMIS_DATA_ROOT`; stale refs linger in
  M3-a/M3-b done-when text. Sweep these (WARN, fold opportunistically).

## Fix wave applied 2026-06-11 (9 AFK agents, 1/area; M5-M6 skipped — 0 BLOCK)

Outcome: **all mechanical BLOCKs + the structural ones with a determinate fix are resolved.** Highlights:
M4-a `FactRow`/`EpisodeRow` frozen dataclasses now defined (de-risked M4-b/c/d-2); M3-c made async +
awaited; M3-d `IngestResult` exposes `parsed`/`document`/`item`; OBS-b `usage` → object access + inline
`scan_gaps`/`Gap` shape; DR-c imperative-strip + canary defined; M7-a2 `DistillService` made a class;
M7-c eTLD+1 via `tldextract`; GATE-a AC↔revert reconciled; CAL-c `delete_event`→`cancel_event`;
M8-d-b `CalPrefs`, M8-d-c1/c2 counts (31/32) + manifest signature; CLIENT `require_session` pinned,
`mint_pairing_code` resolved, keychain id, `lock()`/`isPaired` homed in CLIENT-c, `ARTEMIS_BRAIN_URL`
removed (D6). The dominant out-of-scope-file-edit WARN pattern (M1-b config.py, M1-d, M2-c) was swept.

### Residuals deferred by the no-guess rule (NOT fixed — need a call)

**Genuine cross-spec / planning decisions (owner):**
1. **M3-c async seam** — once `agentic.run` is async, the `as_agentic_fn` closure returns a coroutine,
   conflicting with M3-b's *sync* `agentic_fn` port seam. Resolving needs M0-d `Retriever`'s sync/async
   shape + M3-b's port-conformance assertion decided together. Marker at M3-c:47.
2. **M4-c split** — self-declared 2-phase/7-file; over the split rule. Split or accept as flagged
   atomic exception? Planning decision. Marker at M4-c.

**Determinate-but-structural (no decision; just need a focused follow-up with the store signatures):**
3. **CAL-b:353 + CAL-c:245 `tools=None` ACs** — non-runnable as `python -c` one-liners; correct fix is
   a pytest fixture building the manifest with the Task-5 fake stores. Needs CAL-a store constructors.
4. **M8-d-c2 `settings` param** — Task 7 reconciled to the canonical 7-param signature; whether
   `init_capture` also needs `settings` (8th param) vs module-level Settings access is unresolved.

**Authoring deferrals (drafting, low-risk, fold opportunistically):** M4-a KNN vec0+bitemporal SQL
skeleton; M4-b `EXTRACTION_SCHEMA`/`DECISION_SCHEMA` literal dicts; M7-a2 distill template text;
M7-c CuriosityLoop no-teacher staging shape; OBS-b `verified_at` format (blocked on M7-a1 pinning it);
CLIENT-e chat-footer (product) + token-provider `@Sendable`/`@MainActor` (Swift 6 concurrency).

Everything else across all 60 specs is now handoff-clean.

## Post-fix decisions + cascades (2026-06-11 → 06-12)

- **M4-c split (owner):** M4-c → **M4-c-1** (recall + auto-inject) + **M4-c-2** (decay + owner surface). Original deleted; dependency edge M4-c-2→M4-c-1 added. Spec count 60 → 61.
- **M3-c async seam → ADR-015 (owner chose A2, full):** the seam break (async agentic loop vs sync `Retriever.retrieve`) was resolved by making the **network-I/O port surface async**. New rule (ADR-015): network-I/O port methods (`ModelPort.complete`/`embed`, `EmbeddingModel.embed`, `Reranker.rerank`, `Retriever.retrieve`, `MemoryStore.{recall,inject_context,add_fact,update_fact}`) are `async`; local-disk/cached methods (`VectorStore.*`, `EmbeddingModel.dimension`, `MemoryStore.delete_fact`, `Router.route`, voice ports) stay sync. Cascade applied across M0-d, M1-a/b/c, M3-a/b/c/d, M4-a/b/c-1/c-2/d-2, M7-a1 + consumer sweep. contracts.md Seam 1 amended; **ADR-015** written. `pytest-asyncio` + `asyncio_mode="auto"` added to M0-a.

## ⚠️ NEW blocker surfaced by the async cascade — tool-dispatch async (ADR-016 candidate)

ADR-015 made `RecipeStore.write` async. Its caller is a **brain-tool callable** (`suggestion_accept` in M8-d-c2) dispatched via `ToolRegistry` `callable_ref` — and **Seam 2 types `callable_ref: Callable[..., BaseModel]` as SYNC**, with GATE-a's `approve()` calling it synchronously (`result = tool_spec.callable_ref(args)`). This is the same async question one layer up, at the **tool-dispatch surface** — and it's arguably pre-existing (calendar/gmail write tools do Google API network I/O inside the async brain). Resolving it (make `callable_ref` async-capable → cascade GATE-a/b + every spoke's tools + brain dispatch) is a genuine architectural decision with a large blast radius. **Deferred** (LINT-DEFER marker at M8-d-c2; M4-d-2's resolve_entity stays sync and conforms fine because it does no I/O). **This is the last gate to handoff-ready and should get its own focused pass / ADR-016.**

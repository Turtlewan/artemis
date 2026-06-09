---
spec: m7-c-curiosity-loop
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M7-c — Curiosity Loop (idle-trigger + gap scan over telemetry → curriculum → Researcher port (stub) + grounding gate (≥2 external sources) → distill → stage → owner-gated commit via M6 Heartbeat digest; hard per-cycle + weekly token caps)

**Identity:** Implements the idle-triggered self-improvement loop: scan observability telemetry for gaps (escalation clusters · low-confidence answers · recurring topics · staleness), pick the top gap (curriculum), fill it via a `Researcher` port (minimal/stub satisfying the grounding-gate contract), pass the **grounding gate** (≥2 independent EXTERNAL reachable sources, never self-generated), distill to a RAG chunk or a verified recipe, **stage** it, and surface it for **owner-gated commit via the M6 Heartbeat digest** — all under hard per-cycle + weekly token caps.
→ why: see docs/technical/architecture/brain.md § "Self-improvement — the Curiosity Loop" (the full pipeline + caps + "NOT weight fine-tuning / NOT self-code-rewrite") · ADR-003 (rule-growth lifecycle item (1): the Curiosity Loop refines rules, owner-gated).

<!-- TERMINOLOGY: "recipe" not "skill". The Deep-Research engine is a SEPARATE core-adjacent capability; M7-c ships only a minimal/stub `Researcher` port that satisfies the grounding-gate contract. -->

<!-- Split rule: TWO logical phases (1: idle-trigger + gap scan + curriculum; 2: Researcher port + grounding gate + distill + stage + owner-gated-commit + caps). 4 src files + 1 test — exceeds the ≤3-files guideline. Justified atomic exception: the unit is "one Curiosity cycle end-to-end", and every stage is a link in one pipeline that must be tested as a whole (a gap that doesn't reach the grounding gate, or a grounded result that doesn't stage, proves nothing). Each file is a thin single-stage module behind a port; the heavyweight Deep-Research engine is explicitly OUT (a stub Researcher behind a port). Flagged per rules. If review wants leaner: M7-c1 (trigger + gap scan + curriculum) / M7-c2 (Researcher port + grounding gate + distill + stage + caps). -->

## Assumptions
- M7-a1 (`Recipe`/`RecipeStore`, RAG-for-recipes), M7-a2 (`escalate_and_distill`/`apply_recipe`/`task_class_key`; distill-to-recipe write path), and M7-b (`Promoter`/`RecurrenceStore`/`ReviewSurface` — staged results enter the same owner-gated promotion path) are complete. → impact: Stop (M7-c reuses the recipe distill + promotion machinery; a Curiosity-distilled recipe is written as a `CANDIDATE` and flows through M7-b's owner gate, never auto-enabled outside the #8 classifier).
- M1-d Heartbeat (`Heartbeat` with `tick()`/`run_forever()`, silent-success) is the **idle trigger** host: the Curiosity cycle runs as a Heartbeat hook on an idle schedule, NOT a new daemon. M7-c provides a `curiosity_tick()` the Heartbeat invokes; it self-limits via the token caps and runs zero work when caps are exhausted. → impact: Stop (reuse M1-d Heartbeat; do not add a scheduler). RESOLVED (gate 2026-06-08): `curiosity_tick(is_idle: Callable[[], bool], now: datetime)` runs the cycle only when `is_idle()` is True; the caller supplies the idle signal — the Brain/Gateway exposes `last_interaction_at` (a one-line addition wired at composition); if unavailable, the caller passes an `is_idle` defaulting to the SGT off-peak window (00:30–08:30, brain.md deployment).
- **Observability telemetry** is the gap-scan input: escalation events, answer confidence scores, routed task classes, and chunk/recipe staleness timestamps. → impact: Stop. RESOLVED (gate 2026-06-08): M7-c reads telemetry through a `TelemetrySource` Protocol (defined here) — `escalations() -> Sequence[EscalationEvent]`, `low_confidence_answers() -> Sequence[ConfidenceEvent]`, `topic_counts() -> Mapping[str,int]`, `stale_items() -> Sequence[StaleItem]` — buildable + tested against `FakeTelemetry` now. The concrete telemetry store/writer is a **separate pending spec** (the observability/telemetry spec, IG2) drafted after the M0–M7 gate; M7-c's runtime value is inert until it lands.
- The **Deep-Research engine is a SEPARATE capability**, not built here. M7-c ships a `Researcher` Protocol + a minimal stub `StubResearcher` that returns a fixed result shaped to satisfy the grounding gate (so the loop is end-to-end testable). The real engine (spotlighting + CaMeL on untrusted web) swaps in behind the port later. → impact: Stop (do NOT build the research engine; only the port + stub + the grounding-gate contract it must satisfy).
- **Grounding gate** (anti-collapse, brain.md): a research result is accepted ONLY if it cites **≥2 independent EXTERNAL sources** (distinct domains) whose URLs are **reachable**, and the content is **not self-generated** (sources must be external URLs, never an Artemis-internal store or a model). Reachability is an HTTP HEAD/GET check. → impact: Stop (this is the locked anti-collapse invariant; a result failing the gate is discarded, never staged). The reachability check is the only network the gate needs; off-hardware tests inject a `FakeReachability` (no real network).
- **Owner-gated commit via the M6 Heartbeat digest:** a staged Curiosity result is NEVER committed (added to the live RAG index / ENABLED as a recipe) automatically — it is staged and surfaced in the M6 digest for owner approval; on approval it enters the live store (recipe → M7-b promote; RAG chunk → ingest into the live index). → impact: Stop. RESOLVED (gate 2026-06-08, IG1=B): M7-c exposes `staged_for_digest() -> list[StagedItem]` (the data surfaced for owner review) + `commit_staged(item_id)` / `discard_staged(item_id)` (the owner actions). The **action surface is the client-app** (over its M2-authenticated connection); the M6 ntfy digest is informational-only ("a curiosity result is staged"). Until the client-app Review/Staged screen ships, staged items accumulate and are committed via that surface when built.
- **Hard token caps:** a per-cycle cap and a weekly cap on teacher/research tokens; when either is exhausted the cycle is a no-op (silent, like Heartbeat). Token usage is read from `ModelResponse.usage` (M0-d) accumulated in a small persisted `TokenLedger`. → impact: Stop (caps are a locked brain.md guardrail; exceeding them must hard-stop the cycle).

Simplicity check: considered building a real curriculum/research engine — rejected; brain.md scopes the Deep-Research engine as a separate core-adjacent capability and the brief says ship a stub Researcher behind a port. Considered an LLM ranking the gaps — kept minimal: curriculum picks the top gap by a deterministic score (cluster size × recency × staleness) with at most one cheap local call to phrase the research query; the gate + caps + staging are pure code. Considered committing grounded results automatically for the safe class — rejected; brain.md is explicit: stage → owner-gated commit via the digest (always).

## Prerequisites
- Specs that must be complete first: M7-a1 (recipe store/RAG), M7-a2 (distill/apply), M7-b (Promoter/ReviewSurface), M1-d (Heartbeat host for the idle trigger). Dependency to spec separately (consumed via Protocols here, so M7-c builds + tests against fakes now): the **observability/telemetry spec** (concrete `TelemetrySource`) and the **Deep-Research engine spec** (concrete `Researcher`). The staged-item owner-commit surface is the client-app (IG1=B); the M6 digest is informational-only.
- Environment setup required: none beyond the above for the off-hardware suite (fakes for telemetry, researcher, reachability, model). The live research run (real `Researcher` + real reachability) is **GATED on-hardware** and depends on the real Deep-Research engine (a separate capability) — M7-c only proves the loop against the stub.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/curiosity/__init__.py | create | package marker + re-exports (`CuriosityLoop`, `Researcher`, `StubResearcher`, `TelemetrySource`, `grounding_gate`, `TokenLedger`, `StagedItem`) |
| /Users/artemis-build/artemis/src/artemis/curiosity/gaps.py | create | `TelemetrySource` Protocol + event types + `scan_gaps` + `pick_top_gap` (curriculum) |
| /Users/artemis-build/artemis/src/artemis/curiosity/research.py | create | `Researcher` Protocol + `ResearchResult`/`Source` types + `StubResearcher` + `grounding_gate` (≥2 external reachable, not self-generated) |
| /Users/artemis-build/artemis/src/artemis/curiosity/loop.py | create | `TokenLedger` (per-cycle + weekly caps), `StagedItem`/`StagingStore`, `CuriosityLoop.curiosity_tick(...)` end-to-end + `staged_for_digest`/`commit_staged`/`discard_staged` |
| /Users/artemis-build/artemis/tests/test_curiosity_loop.py | create | gap scan, curriculum pick, grounding gate (pass/fail), caps hard-stop, stage→owner-gated-commit — all against fakes |

## Tasks
- [ ] Task 1: Define telemetry types + gap scan + curriculum — files: `/Users/artemis-build/artemis/src/artemis/curiosity/gaps.py` —
  - frozen dataclasses: `EscalationEvent { task_class_key: str, at: datetime }`, `ConfidenceEvent { task_class_key: str, confidence: float, at: datetime }`, `StaleItem { item_id: str, kind: Literal["chunk","recipe"], last_verified_at: datetime }`.
  - `class TelemetrySource(Protocol)`: `def escalations(self) -> Sequence[EscalationEvent]: ...`; `def low_confidence_answers(self) -> Sequence[ConfidenceEvent]: ...`; `def topic_counts(self) -> Mapping[str, int]: ...`; `def stale_items(self) -> Sequence[StaleItem]: ...`.
  - frozen dataclass `Gap { task_class_key: str, kind: Literal["escalation-cluster","low-confidence","recurring-topic","staleness"], score: float, evidence_count: int }`.
  - `def scan_gaps(telemetry: TelemetrySource, *, now: datetime, confidence_floor: float = 0.5, staleness_days: int = 90) -> list[Gap]`: build candidate gaps from the four signals (cluster escalations by `task_class_key` → escalation-cluster gaps; group low-confidence answers below `confidence_floor`; recurring topics from `topic_counts`; items older than `staleness_days` → staleness gaps). Score each deterministically: `score = cluster_size * recency_weight(now, latest) * (1 + staleness_factor)` (document the formula). NO model call.
  - `def pick_top_gap(gaps: Sequence[Gap]) -> Gap | None`: return the highest-`score` gap, or None if empty (the curriculum's single pick per cycle).
  — done when: `uv run mypy --strict src` passes; `scan_gaps` over a `FakeTelemetry` with 3 escalations sharing a key yields an `escalation-cluster` gap with `evidence_count == 3`, and `pick_top_gap` returns the top-scored.

- [ ] Task 2: Define the Researcher port + stub + the grounding gate — files: `/Users/artemis-build/artemis/src/artemis/curiosity/research.py` —
  - frozen dataclass `Source { url: str, domain: str, snippet: str }` (an EXTERNAL source — a URL, never an internal store ref). `ResearchResult { query: str, content: str, sources: list[Source], self_generated: bool }`.
  - `class Researcher(Protocol)`: `async def research(self, query: str, *, token_cap: int) -> ResearchResult: ...` (the full Deep-Research engine implements this later; `token_cap` lets the loop bound spend).
  - `class StubResearcher` implementing `Researcher`: returns a FIXED `ResearchResult` with two distinct-domain external sources + `self_generated=False` (minimal, satisfies the gate; constructor lets tests inject a passing or failing result). Document: this is a stub; the real engine (spotlighting + CaMeL on untrusted web) swaps in behind the port — [FLAG: real `Researcher` is a separate core-adjacent capability, not built in M7-c].
  - `class Reachability(Protocol)`: `def is_reachable(self, url: str) -> bool: ...` (HTTP HEAD/GET; off-hardware tests inject a fake). Provide `class HttpReachability` (real, lazy `httpx`/`urllib` HEAD with a short timeout) used only live.
  - `def grounding_gate(result: ResearchResult, reachability: Reachability) -> bool`: accept iff `result.self_generated is False` AND there are **≥2 sources with distinct registrable domain (eTLD+1** — NOT the raw `domain` string; two subdomains of one publisher are NOT independent) AND **≥2 of those distinct-domain sources are reachable** (a single transient-unreachable source does not discard an otherwise-grounded result). `reachability.is_reachable` counts only `2xx`/`3xx` as reachable (a `403`/`429` is "gated, not grounding-usable") and uses a short FIXED timeout (required — an un-timed HEAD/GET would hang the gate). Reject otherwise (the anti-collapse invariant). Define `GroundingError`. NO model call.
  — done when: `uv run mypy --strict src` passes; `grounding_gate` returns True for a 2-distinct-domain reachable non-self-generated result, and False if `self_generated`, <2 distinct domains, or any source unreachable.

- [ ] Task 3: Implement the token caps ledger + staging store — files: `/Users/artemis-build/artemis/src/artemis/curiosity/loop.py` —
  - `class TokenLedger` constructed with `(path: Path, per_cycle_cap: int, weekly_cap: int)`. `def remaining_this_cycle(self) -> int` / `def remaining_this_week(self, now: datetime) -> int` (week = rolling 7-day window over recorded usage). `def record(self, tokens: int, now: datetime) -> None` (persist atomically). `def can_spend(self, now: datetime) -> bool`: True iff both caps have headroom. — the HARD cap: when False the cycle is a no-op. (Wall-clock; the rolling 7-day window is not clock-skew-hardened — a backward clock jump could let one week exceed the cap; documented accepted risk for a single-box deployment, not a crash path. Same-dir atomic persist.)
  - frozen dataclass `StagedItem { item_id: str, kind: Literal["recipe","chunk"], summary: str, payload: dict[str, object], gap: str, sources: list[str] }`. `class StagingStore` constructed with a `path: Path`: `def stage(self, item: StagedItem) -> None`, `def list(self) -> list[StagedItem]`, `def get(self, item_id) -> StagedItem`, `def remove(self, item_id) -> None` (atomic JSON file; staged items are NEVER live until committed).
  — done when: `uv run mypy --strict src` passes; a `TokenLedger` with `per_cycle_cap=0` returns `can_spend == False`; `StagingStore.stage` then `list` round-trips.

- [ ] Task 4: Implement the end-to-end Curiosity cycle + owner-gated commit — files: `/Users/artemis-build/artemis/src/artemis/curiosity/loop.py` — `class CuriosityLoop` constructed with `(telemetry: TelemetrySource, researcher: Researcher, reachability: Reachability, model: ModelPort, recipe_store: RecipeStore, ledger: TokenLedger, staging: StagingStore)`. 
  - `async def curiosity_tick(self, *, is_idle: Callable[[], bool], now: datetime) -> str`: 
    1. if not `is_idle()` or not `ledger.can_spend(now)` → return `"CURIOSITY_SKIP"` (silent no-op, like Heartbeat silent-success; zero tokens spent).
    2. `gaps = scan_gaps(telemetry, now=now)`; `gap = pick_top_gap(gaps)`; if None → `"CURIOSITY_NO_GAP"`.
    3. phrase a research query for the gap (a deterministic template by DEFAULT — gap data derives from owner telemetry; if a model call is used it MUST be `role="responder"` bound to a LOCAL model only, NEVER a cloud role). **Record its tokens via `ledger.record` — every model call in the cycle is counted, else the hard cap is understated.**
    4. `result = await researcher.research(query, token_cap=ledger.remaining_this_cycle())`; `ledger.record(<tokens from result/usage>, now)`.
    5. `if not grounding_gate(result, reachability): return "CURIOSITY_UNGROUNDED"` (discard — never stage an ungrounded result).
    6. distill: decide RAG-chunk vs recipe (a recurring procedural gap → a recipe via `escalate_and_distill`-style distill writing a CANDIDATE recipe; a factual gap → a RAG chunk). Build a `StagedItem` (do NOT write to the live store).
    7. `staging.stage(item)`; return `"CURIOSITY_STAGED"`.
  - `def staged_for_digest(self) -> list[StagedItem]`: the data the M6 Heartbeat digest renders for owner review (each item carries its gap + external sources). 
  - `def commit_staged(self, item_id: str) -> None`: OWNER ACTION — move a staged item into the live store: a `recipe` item → write the CANDIDATE recipe via `recipe_store.write` (then it flows through M7-b's owner-gated promotion), then remove from staging; a `chunk` item → **raise `NotImplementedError` until the M3 ingest hook is specced** (gate 2026-06-08: the RAG-chunk write must NOT bypass M3's validation/provenance pipeline — when wired it ingests as an owner-private `Document` with provenance `source="curiosity"` + the external source URLs via M3-a's ingest entry point, NOT a raw `VectorStore.add`).
  - `def discard_staged(self, item_id: str) -> None`: OWNER ACTION — drop a staged item (owner declines).
  Keep `curiosity_tick` non-raising (degrade-don't-crash; log + return a typed status on any sub-failure). — done when: `uv run mypy --strict src` passes; against fakes a full `curiosity_tick(is_idle=lambda:True, now=...)` with a gap + a grounded stub result returns `"CURIOSITY_STAGED"` and stages an item NOT present in the live recipe store until `commit_staged`. [FLAG gated: `commit_staged` is the owner-gated commit — nothing reaches the live store without it; `curiosity_tick` NEVER commits.]

- [ ] Task 5: Re-export + wire the Heartbeat hook — files: `/Users/artemis-build/artemis/src/artemis/curiosity/__init__.py` — re-export `CuriosityLoop`, `Researcher`, `StubResearcher`, `Reachability`, `HttpReachability`, `TelemetrySource`, `Gap`, `scan_gaps`, `pick_top_gap`, `grounding_gate`, `TokenLedger`, `StagedItem`, `StagingStore`, with `__all__`. Add a typed helper `make_curiosity_hook(loop: CuriosityLoop, is_idle: Callable[[], bool]) -> HookSpec`-shaped factory (or a plain async callable the M1-d Heartbeat schedules) that runs `curiosity_tick` on the idle schedule — document it as the Heartbeat-mounted entry point (the M1-d Heartbeat or a future daemon spec mounts it). Do NOT modify M1-d's `heartbeat.py` here unless a one-line hook-registration is needed; if so, that edit is additive. — done when: `uv run python -c "from artemis.curiosity import CuriosityLoop, StubResearcher, grounding_gate, TokenLedger"` exits 0.

- [ ] Task 6: Write the Curiosity-loop tests (off-hardware, fakes) — files: `/Users/artemis-build/artemis/tests/test_curiosity_loop.py` — typed pytest with `FakeTelemetry` (returns canned escalation/confidence/topic/stale data), `StubResearcher` (injectable passing/failing result), `FakeReachability` (configurable reachable set), `FakeModelPort` (reuse M7-a fake), a real `RecipeStore`/`StagingStore`/`TokenLedger` over `tmp_path`. Tests:
  - gap scan + curriculum: `scan_gaps` over 3 escalations sharing a key yields an `escalation-cluster` gap; `pick_top_gap` returns the highest-scored gap.
  - grounding gate pass: a 2-distinct-domain, all-reachable, non-self-generated result → `grounding_gate` True.
  - grounding gate cases: `self_generated=True` → False; only 1 distinct registrable domain (eTLD+1) → False; two subdomains of the SAME publisher (e.g. `news.x.com`/`sport.x.com`) → False (not independent); 3 sources where 1 is unreachable but ≥2 distinct-domain reachable remain → True (transient failure tolerated); fewer than 2 reachable → False (each asserted).
  - caps hard-stop: a `TokenLedger(per_cycle_cap=0,...)` → `curiosity_tick` returns `"CURIOSITY_SKIP"` with ZERO researcher/model calls (assert via fake call logs).
  - idle gate: `is_idle=lambda:False` → `"CURIOSITY_SKIP"`, no work.
  - end-to-end stage: idle + budget + a gap + a grounded stub result → `curiosity_tick` returns `"CURIOSITY_STAGED"`; the item is in `staged_for_digest()` but the live `recipe_store.list(status=ENABLED)` is unchanged.
  - ungrounded discard: a stub result failing the gate → `"CURIOSITY_UNGROUNDED"` and nothing staged.
  - owner-gated commit: `commit_staged(item_id)` for a recipe item writes a CANDIDATE recipe to the live store (now visible to M7-b) and removes it from staging; `discard_staged` removes without writing.
  — done when: `uv run pytest -q tests/test_curiosity_loop.py` passes AND `uv run mypy --strict src tests/test_curiosity_loop.py` passes.

- [ ] Task 7 (GATED — on-hardware, live research): End-to-end Curiosity cycle with a real Researcher + real reachability — files: (no repo files; uses the real `Researcher` engine when it exists + `HttpReachability`) — on the Mini, with the real Deep-Research engine available (a SEPARATE capability — this task is blocked until it ships) and `claude`/local models served: run one `curiosity_tick` on a synthetic NON-SENSITIVE gap, confirm the grounding gate accepts a result with ≥2 reachable external sources and the result is STAGED (not committed). Build-time empirical (real web egress under CaMeL/spotlighting; non-sensitive only). — done when: a live cycle stages a grounded result with real external sources; no auto-commit; recorded in handoff. [GATED — live web research egress; depends on the separate Deep-Research engine capability; non-sensitive only.]

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/curiosity/__init__.py, /Users/artemis-build/artemis/src/artemis/curiosity/gaps.py, /Users/artemis-build/artemis/src/artemis/curiosity/research.py, /Users/artemis-build/artemis/src/artemis/curiosity/loop.py, /Users/artemis-build/artemis/tests/test_curiosity_loop.py |
| Modify | /Users/artemis-build/artemis/src/artemis/heartbeat.py (additive one-line Curiosity-hook registration ONLY if needed — see Task 5) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_curiosity_loop.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_curiosity_loop.py` | Test gate (gap scan, curriculum, grounding gate, caps, stage→commit — all fakes) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/curiosity/**, src/artemis/heartbeat.py (if edited), tests/test_curiosity_loop.py |
| `git commit` | "feat: M7-c Curiosity Loop (idle gap-scan → curriculum → Researcher stub + grounding gate → distill → stage → owner-gated commit; token caps)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings → staging/ledger paths + role→endpoint resolution |

### Network
| Action | Purpose |
|--------|---------|
| live HTTP HEAD/GET reachability + real Researcher web egress (GATED, Task 7) | Grounding-gate reachability + live research — non-sensitive only, under CaMeL/spotlighting |

## Specialist Context
### Security
- The **grounding gate** is the anti-collapse / anti-poisoning control: never stage a self-generated result; require ≥2 INDEPENDENT external reachable sources. [FLAG apex-security: the real `Researcher` reads untrusted web content — it MUST run under spotlighting + CaMeL (brain.md dual-LLM); M7-c ships only the stub + the gate, so the security wrapping lands with the real engine. The reachability check makes real outbound HTTP — gated, non-sensitive only.]
- **Owner-gated commit:** `curiosity_tick` NEVER writes to the live store; only `commit_staged` (an owner action via the M6 digest) does. Curiosity-distilled recipes enter as `CANDIDATE` and still pass M7-b's #8 auto-enable-safe-vs-gate boundary. [FLAG gated: confirm no path lets a Curiosity result auto-ENABLE a recipe or auto-ingest a chunk without owner commit.]
- **Token caps** (per-cycle + weekly) hard-stop the loop — protects the subscription quota (brain.md teacher-cost guardrail) and bounds web egress.

### Performance
The cycle is idle-only + silent-no-op when capped/idle-not-met (zero idle tokens, like Heartbeat). Gap scan, curriculum scoring, grounding gate, and caps are all pure code (no model). At most one cheap local-responder call to phrase the research query (preferably a template). NOT weight fine-tuning, NOT self-code-rewrite (brain.md).

### Accessibility
The `staged_for_digest()` items are owner-facing (rendered in the M6 digest); the digest UI is a later spec — [a11y applies to the digest surface when built].

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/curiosity/*.py | Type + docstring all exports; document the cycle stages, the grounding-gate (≥2 external reachable, not self-generated) invariant, the hard token caps, and the stage→owner-gated-commit contract; mark `StubResearcher` as a stub for the separate Deep-Research engine |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_curiosity_loop.py` → verify: exit 0 (incl. `Researcher`/`TelemetrySource`/`Reachability` Protocol conformance).
- [ ] Run `uv run python -c "from artemis.curiosity.research import grounding_gate, ResearchResult, Source; from artemis.curiosity.loop import TokenLedger"` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_curiosity_loop.py` → verify: gap scan clusters escalations; grounding gate rejects self-generated / <2-domain / unreachable and accepts ≥2-reachable-external; caps=0 → `CURIOSITY_SKIP` with zero researcher calls; a full cycle returns `CURIOSITY_STAGED` and the live recipe store is unchanged until `commit_staged`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini, blocked on the Deep-Research engine) One live cycle on a synthetic non-sensitive gap → verify: grounding gate accepts ≥2 reachable external sources, result is STAGED not committed.

## Progress
_(Coding mode writes here — do not edit manually)_

---
spec: obs-b-telemetry-backend
status: ready
token_profile: lean
autonomy_level: L3
---

# Spec: OBS-b — Telemetry backend (SQLCipher event store + `TracingModelPort` token/cost/latency wrapper + tier-aware cost model + concrete `TelemetrySink` + the `TelemetrySource` reader M7-c consumes)

**Identity:** Implements the metrics pillar behind OBS-a's `ObservabilitySink`: an owner-private SQLCipher telemetry store (epoch-ms integer timestamps, `user_version` migration, retention prune), a `TracingModelPort` wrapper that records token/cost/latency + `model_id` on every `ModelPort.complete`, a tier-aware `CostModel` (brain.md flat-rate quota), a concrete `TelemetrySink` that persists route-decision/escalation events, and a concrete `SqliteTelemetrySource` satisfying `artemis.curiosity.gaps.TelemetrySource` that M7-c consumes.
→ why: see docs/technical/adr/ADR-008-observability.md.

<!-- Split rule note: 4 src + 1 test, 0 modifies. Justified atomic grouping: the store, the sink that writes it, the tracer that writes it, and the source that reads it are one cohesive read/write unit behind two Protocols (OBS-a's ObservabilitySink, M7-c's TelemetrySource) and must be tested as a write→read round-trip. No edits to other specs (OBS-a already placed the taps). Flagged per rules. -->

## Assumptions
- OBS-a is complete: `ObservabilitySink` Protocol (`on_route_decision(task_class_key, confidence, path, *, now)`, `on_escalation(task_class_key, *, is_cloud_safe, now)`, `on_error(component, exc, *, now)` — **non-content primitives only**), `NullSink`, `CompositeSink`, `get_logger` exist in `artemis.obs`. The Brain already computes `task_class_key` and passes it; `TelemetrySink` receives the key directly and imports NOTHING from `recipes` for it. → impact: Stop.
- M7-c (`artemis.curiosity.gaps`) defines the read contract: `class TelemetrySource(Protocol)` with `escalations() -> Sequence[EscalationEvent]`, `low_confidence_answers() -> Sequence[ConfidenceEvent]`, `topic_counts() -> Mapping[str, int]`, `stale_items() -> Sequence[StaleItem]`, plus `EscalationEvent{task_class_key, at}`, `ConfidenceEvent{task_class_key, confidence, at}`, `StaleItem{item_id, kind: Literal["chunk","recipe"], last_verified_at}`. This spec imports those types — does NOT redefine them; `mypy --strict` proves conformance via a static `_check: TelemetrySource = SqliteTelemetrySource(...)`. → impact: Stop.
- **Store is SQLCipher, owner-private, opened via M2-c `sqlcipher_open`** (the same keyed-open the M4-a memory store uses), keyed by the owner-private DEK from the M2-b `KeyProvider`. The DB lives at `paths.scope_dir(settings, "owner-private") / "relational" / "telemetry.db"` (reusing M0-a's `relational/` operational-DB subdir). No plaintext telemetry file is ever created. → impact: Stop (resolves the security verdict; `task_class_key` stays identical to M7-a2's value — SQLCipher-at-rest closes the low-entropy preimage threat without a keyed-HMAC fork that would diverge the recipe-clustering key).
- `low_confidence_answers()` returns ALL recorded confidence events (unfiltered); M7-c's `scan_gaps(..., confidence_floor=0.5)` applies the floor. The method name is historical — the source does NOT pre-filter (docstring states this loudly). A rename to `confidence_events()` is a follow-up for the M7-c spec owner (noted in handoff, not done here — M7-c is ready). → impact: Caution (a double-filter would be harmless; documented to prevent a second floor here).
- `ModelPort.complete(role, messages, *, stream, response_schema) -> ModelResponse`; `ModelResponse{text, finish_reason, usage: Mapping[str,int]}` (M0-d). The adapter is responsible for normalising provider usage to OpenAI-shape keys (`prompt_tokens`/`completion_tokens`/`total_tokens`); the tracer reads them defensively (`usage` absent/None → `{}`; missing key → 0; `total_tokens` absent → `prompt+completion`). A fully-zero usage logs a WARNING (a visible tracing gap, e.g. a streaming call that omitted usage), never a crash. Anthropic prompt-cache tokens (if surfaced) are NOT separately subtracted in v1 → subscription token totals are a conservative upper bound (documented). → impact: Caution.
- `RecipeStore.list(*, status=None) -> list[Recipe]` (M7-a1); each `Recipe.provenance` carries a `verified_at` string. `stale_items()` ships **recipe** staleness from this; **chunk** staleness is gated on an M3 per-chunk verified-at capability that does not exist yet → an injected `chunk_stale_reader` defaults to none and recipe staleness ships alone. → impact: Low (one of four signals ships partial; M7-c degrades gracefully).
- `settings.roles[role]` (M0-a) exposes `.adapter` (`openai`|`claude-cli`), `.endpoint`, `.model_id`. → impact: Stop (cost-tier classification + `model_id` tagging read these).

Simplicity check: considered OpenTelemetry spans + a collector — rejected (ADR-008: single-box, no collector). Considered storing per-call rows AND aggregates — rejected; store raw rows, aggregate in read queries. Considered a $-denominated cost model — rejected; brain.md locks flat-rate quota → tier-aware token attribution (local=0, subscription=quota-units, cloud=micros).

## Prerequisites
- Specs complete first: OBS-a (sink Protocol + `get_logger`), M0-a (`config`/`paths`), M0-d (`ModelPort`/`ModelResponse`), M2-b (`KeyProvider`/`SecretKey`/`ScopedConnection`), M2-c (`sqlcipher_open`), M4-a (`open_*_db` keyed-open precedent — pattern reuse), M7-a1 (`RecipeStore`), M7-a2 (`task_class_key` — used by the Brain in OBS-a, not here), M7-c (`artemis.curiosity.gaps`).
- Environment setup required: the SQLCipher binding is already a project dep (M4-a). Off-hardware tests open a keyed SQLCipher DB at `tmp_path` with a fixed test key (mirroring M4-a's golden tests).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/obs/telemetry/__init__.py | create | re-exports (`TelemetryStore`, `open_telemetry_db`, `telemetry_db_path`, `SqliteTelemetrySource`, `TelemetrySink`, `TracingModelPort`, `CostModel`, `Tier`, `tier_for`, `CallTrace`, `UsageRow`) |
| /Users/artemis-build/artemis/src/artemis/obs/telemetry/store.py | create | `TelemetryStore` (schema + `user_version` migrate + insert/query/prune), `CallTrace`, `UsageRow`, `open_telemetry_db`, `telemetry_db_path`, epoch-ms helpers |
| /Users/artemis-build/artemis/src/artemis/obs/telemetry/cost.py | create | `Tier`, `tier_for`, `CostModel` (tier-aware micros) |
| /Users/artemis-build/artemis/src/artemis/obs/telemetry/tracing.py | create | `TracingModelPort` (wraps `ModelPort`, records token/cost/latency/model_id) |
| /Users/artemis-build/artemis/src/artemis/obs/telemetry/source.py | create | `TelemetrySink` (writes the store) + `SqliteTelemetrySource` (reads → M7-c event types) |
| /Users/artemis-build/artemis/tests/test_obs_telemetry.py | create | schema/migrate round-trip, tracer token/cost/latency/model_id + all-zero WARN + no-crash, sink→source projection, TelemetrySource conformance, empty-store degradation, staleness, usage summary, prune |

## Tasks
- [ ] Task 1: The SQLCipher telemetry store — files: `/Users/artemis-build/artemis/src/artemis/obs/telemetry/store.py` —
  - `def telemetry_db_path(s: Settings) -> Path`: `scope_dir(s, "owner-private") / "relational" / "telemetry.db"` (via `from artemis.paths import scope_dir`). Path only; does not create.
  - `def open_telemetry_db(path: Path, key: SecretKey) -> Connection`: ensure parent dir exists; open keyed via M2-c `sqlcipher_open(path, key)` (NOT plain sqlite3 — the store is born encrypted); `PRAGMA journal_mode=WAL`; `PRAGMA synchronous=NORMAL`; row factory rows-as-tuples. (Single factory so the keyed-open is localized.)
  - epoch-ms helpers: `def _to_ms(dt: datetime) -> int` = `int(dt.timestamp() * 1000)`; `def _from_ms(ms: int) -> datetime` = `datetime.fromtimestamp(ms / 1000, UTC)`. **All `at` columns are INTEGER epoch-ms** (range queries are integer comparisons — format-safe).
  - frozen dataclass `CallTrace { role: str, model_id: str | None, prompt_tokens: int, completion_tokens: int, total_tokens: int, latency_ms: int, cost_micros: int, trace_id: str | None, at: datetime }`. frozen dataclass `UsageRow { role: str, calls: int, total_tokens: int, cost_micros: int }`. (`total_tokens`/`cost_micros` are Python `int` — arbitrary precision; sqlite returns 64-bit ints surfaced as Python int; do NOT cast to a fixed width.)
  - `class TelemetryStore` constructed with `(conn: Connection)` (an already-keyed connection from `open_telemetry_db`). `__init__` calls `_migrate()`:
    - `_migrate()` reads `PRAGMA user_version`; if `< 1`, create (all `IF NOT EXISTS`, then set `PRAGMA user_version = 1`): `route_events(id INTEGER PRIMARY KEY, task_class_key TEXT NOT NULL, confidence REAL NOT NULL, path TEXT NOT NULL, trace_id TEXT, at INTEGER NOT NULL)`; `escalations(id INTEGER PRIMARY KEY, task_class_key TEXT NOT NULL, is_cloud_safe INTEGER NOT NULL, trace_id TEXT, at INTEGER NOT NULL)`; `call_traces(id INTEGER PRIMARY KEY, role TEXT NOT NULL, model_id TEXT, prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL, latency_ms INTEGER NOT NULL, cost_micros INTEGER NOT NULL, trace_id TEXT, at INTEGER NOT NULL)`; indexes `route_events(task_class_key)`, `route_events(at)`, `escalations(at)`, `call_traces(at)`, `call_traces(at, role)`. (Future schema changes bump `user_version` + numbered migrations — the versioned path exists from the outset.)
  - write methods (single parameterised INSERTs, `at` stored via `_to_ms`): `record_route(self, task_class_key, confidence, path, *, trace_id=None, at)`; `record_escalation(self, task_class_key, is_cloud_safe, *, trace_id=None, at)`; `record_call(self, trace: CallTrace)`.
  - read methods (`at` read via `_from_ms`): `route_events(self) -> list[tuple[str, float, str, datetime]]`; `escalation_events(self) -> list[tuple[str, datetime]]`; `topic_counts(self) -> dict[str, int]` (`GROUP BY task_class_key`); `usage_summary(self, *, since: datetime) -> list[UsageRow]` (`WHERE at >= ? GROUP BY role`, `since` via `_to_ms`).
  - retention: `def prune(self, *, older_than: datetime) -> int`: `DELETE FROM <each table> WHERE at < ?` (`older_than` via `_to_ms`); returns total rows deleted. (Calling it on a schedule is deferred to a maintenance spec — the primitive exists now so growth is boundable.)
  — done when: `uv run mypy --strict src` passes; constructing `TelemetryStore` twice on the same keyed DB is idempotent (`user_version` already 1); `record_route` then `topic_counts()` → `{key: 1}`; `record_call` then `usage_summary(since=<epoch>)` → one `UsageRow` with the summed tokens; `prune(older_than=<future>)` removes all rows.

- [ ] Task 2: Tier-aware cost model — files: `/Users/artemis-build/artemis/src/artemis/obs/telemetry/cost.py` —
  - `class Tier(StrEnum)`: `LOCAL`, `SUBSCRIPTION`, `CLOUD`.
  - `def tier_for(role: str, settings: Settings) -> Tier`: if `role not in settings.roles` → log `get_logger("obs.cost").warning("unknown_role", extra={"role": role[:64]})` and return `LOCAL` (conservative/unbilled, but now observable). Else read `settings.roles[role]`: adapter `claude-cli` → `SUBSCRIPTION`; adapter `openai` with `deepseek` in the endpoint host → `CLOUD`; else `LOCAL`.
  - `class CostModel` constructed with `(settings: Settings, cloud_micros_per_1k: int = 0, subscription_micros_per_1k: int = 0)`: `def cost_micros(self, role: str, total_tokens: int) -> int` — `LOCAL` → 0; `CLOUD` → `total_tokens * cloud_micros_per_1k // 1000`; `SUBSCRIPTION` → `total_tokens * subscription_micros_per_1k // 1000` (default 0 = flat-rate quota; the token COUNT is the quota signal surfaced via `usage_summary`, not a dollar figure). Docstring: `cost_micros` is an attribution unit, not a billed $; subscription `total_tokens` is a conservative upper bound (cached input tokens, if any, are not subtracted in v1).
  — done when: `uv run mypy --strict src` passes; `tier_for("teacher", s) == SUBSCRIPTION`, `tier_for("responder", s) == LOCAL`, an unknown role → `LOCAL` + a logged WARNING; `CostModel(s).cost_micros("responder", 5000) == 0`; with `cloud_micros_per_1k=200`, a CLOUD role at 5000 tokens → 1000 micros.

- [ ] Task 3: The `TracingModelPort` wrapper — files: `/Users/artemis-build/artemis/src/artemis/obs/telemetry/tracing.py` —
  - `class TracingModelPort` structurally satisfying `artemis.ports.ModelPort` (do NOT subclass; add `# satisfies artemis.ports.ModelPort` + a static `_check: ModelPort = TracingModelPort(...)` in the test). Constructed with `(inner: ModelPort, store: TelemetryStore, cost: CostModel, settings: Settings, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC))`.
  - `complete(self, role, messages, *, stream=False, response_schema=None) -> ModelResponse`: record `t0 = time.perf_counter()`; `resp = inner.complete(role, messages, stream=stream, response_schema=response_schema)`; `latency_ms = int((time.perf_counter() - t0) * 1000)`; `usage = getattr(resp, "usage", None) or {}` (None/absent → `{}`, never crashes); `prompt = int(usage.get("prompt_tokens", 0))`, `completion = int(usage.get("completion_tokens", 0))`, `total = int(usage.get("total_tokens", prompt + completion))`; if `prompt == completion == total == 0` → `get_logger("obs.tracing").warning("empty_usage", extra={"role": role[:64]})` (visible tracing gap, e.g. streaming without usage); `model_id = settings.roles[role].model_id if role in settings.roles else None`; `cost_micros = cost.cost_micros(role, total)`; build `CallTrace(role[:64], model_id, prompt, completion, total, latency_ms, cost_micros, trace_id=None, at=self._clock())`; `store.record_call(trace)` wrapped in try/except → on failure `get_logger("obs.tracing").warning("record_call_failed", extra={"role": role[:64], "error_type": type(exc).__name__})` (NEVER `messages`/`resp.text`/`str(exc)`) and still return `resp`. Return the unchanged `resp`.
  - `embed(self, role, texts) -> list[Vector]`: delegate to `inner.embed` unchanged (embeddings are NOT token-traced in v1 — documented; cloud-tier embedding cost is therefore excluded from `usage_summary`).
  — done when: `uv run mypy --strict src` passes; the static `_check: ModelPort = TracingModelPort(...)` type-checks; one `complete` against a `FakeModelPort` returning `usage={"total_tokens": 42}` writes exactly one `call_traces` row with `total_tokens==42`, `latency_ms >= 0`, and `model_id` from settings; a response with `usage=None` writes a zero-token trace + a WARNING and does NOT raise; a `store` that raises on `record_call` → `complete` still returns the response.

- [ ] Task 4: The concrete sink + source — files: `/Users/artemis-build/artemis/src/artemis/obs/telemetry/source.py` —
  - `class TelemetrySink` implementing `artemis.obs.ObservabilitySink`, constructed with `(store: TelemetryStore)`:
    - `on_route_decision(task_class_key, confidence, path, *, now)`: `store.record_route(task_class_key, confidence, path, at=now)`. **Records ONLY a route row — never a stub escalation row** (the real escalation is recorded solely by `on_escalation`; this removes the duplicate/false-`is_cloud_safe` row three reviewers flagged).
    - `on_escalation(task_class_key, *, is_cloud_safe, now)`: `store.record_escalation(task_class_key, is_cloud_safe, at=now)`.
    - `on_error(component, exc, *, now)`: `pass` (errors are OBS-a's `ErrorCaptureSink`; this sink is metrics-only).
  - `class SqliteTelemetrySource` satisfying `artemis.curiosity.gaps.TelemetrySource`, constructed with `(store: TelemetryStore, recipe_store: RecipeStore, *, staleness_days: int = 90, chunk_stale_reader: Callable[[], Sequence[StaleItem]] | None = None, clock: Callable[[], datetime] = lambda: datetime.now(UTC))`:
    - `escalations()` → `[EscalationEvent(k, at) for k, at in store.escalation_events()]`.
    - `low_confidence_answers()` → `[ConfidenceEvent(k, conf, at) for k, conf, _path, at in store.route_events()]`. **Docstring (loud):** returns ALL confidence events regardless of score; callers MUST apply their own floor (M7-c's `scan_gaps` does) — the name is historical.
    - `topic_counts()` → `store.topic_counts()`.
    - `stale_items()` → for each recipe in `recipe_store.list()`, parse `recipe.provenance["verified_at"]`; if present and `< clock() - staleness_days`, emit `StaleItem(recipe.name, "recipe", verified_at)`; append `chunk_stale_reader()` if provided.
  — done when: `uv run mypy --strict src` passes (static `_check_sink: ObservabilitySink = TelemetrySink(...)` + `_check_src: TelemetrySource = SqliteTelemetrySource(...)`); `on_route_decision` of an escalate-path decision writes ONE route row and ZERO escalation rows; `on_escalation` writes one escalation row; `SqliteTelemetrySource.escalations()` then returns one `EscalationEvent`.

- [ ] Task 5: Package surface — files: `/Users/artemis-build/artemis/src/artemis/obs/telemetry/__init__.py` — re-export `TelemetryStore`, `open_telemetry_db`, `telemetry_db_path`, `CallTrace`, `UsageRow`, `CostModel`, `Tier`, `tier_for`, `TracingModelPort`, `TelemetrySink`, `SqliteTelemetrySource`, with `__all__`. — done when: `uv run python -c "from artemis.obs.telemetry import TelemetryStore, TracingModelPort, TelemetrySink, SqliteTelemetrySource, CostModel"` exits 0.

- [ ] Task 6: Tests — files: `/Users/artemis-build/artemis/tests/test_obs_telemetry.py` — typed pytest over `tmp_path` (a keyed SQLCipher DB via `open_telemetry_db(tmp_path/"t.db", TEST_KEY)` mirroring M4-a), reusing M0/M7 fakes (`FakeModelPort`, a real `RecipeStore`, a fixed test `Settings`):
  - store: `TelemetryStore(conn)` migrate idempotent (construct twice, `user_version==1`); `record_route`+`topic_counts` → `{key:1}`; `record_call`+`usage_summary(since=epoch)` → one `UsageRow` with summed tokens; `prune(older_than=future)` empties all tables.
  - cost: `tier_for` for `teacher`/`responder`/a deepseek-endpoint role + unknown-role WARNING; `CostModel` LOCAL=0, CLOUD micros math.
  - tracer: static `_check: ModelPort = TracingModelPort(...)`; `complete` with `usage={"total_tokens":42}` → one row, `total_tokens==42`, `model_id` from settings; `usage=None` → zero-token row + WARNING + no raise; a store raising on `record_call` → `complete` still returns.
  - sink→source: static `_check_sink`/`_check_src`; `on_route_decision` (escalate path) writes ONE route row and NO escalation row; `on_escalation` then `escalations()` returns the event; `low_confidence_answers()` returns the confidence event; `topic_counts()` reflects the key.
  - empty-store degradation: a fresh `SqliteTelemetrySource` → `escalations()`/`low_confidence_answers()`/`topic_counts()`/`stale_items()` each return an empty collection without raising.
  - staleness: a `RecipeStore` with one recipe whose `provenance.verified_at` is 200 days old → `stale_items()` yields one `StaleItem(kind="recipe")`; a fresh recipe yields none.
  - end-to-end M7-c shape: `scan_gaps(SqliteTelemetrySource(...), now=...)` (from `artemis.curiosity.gaps`) after 3 escalations sharing a key → an `escalation-cluster` gap with `evidence_count == 3`.
  — done when: `uv run pytest -q tests/test_obs_telemetry.py` passes AND `uv run mypy --strict src tests/test_obs_telemetry.py` passes.

- [ ] Task 7 (GATED — on-hardware, live wiring): Compose the real telemetry stack — files: (no repo files; integration note) — on the Mini, at the composition root: open the store via `open_telemetry_db(telemetry_db_path(settings), owner_private_dek)`; wire `CompositeSink([TelemetrySink(store), ErrorCaptureSink(error_store)])` into the `Brain`; wrap the real `ModelPort` adapter in `TracingModelPort(inner, store, CostModel(settings), settings)`. Run one real `respond` + one real `escalate_and_distill` and confirm `route_events`/`escalations`/`call_traces` rows appear and `usage_summary` reports teacher-tier tokens with `model_id` set. — done when: a live interaction writes telemetry rows and `usage_summary` shows the teacher-tier token total with `model_id`; recorded in handoff. [GATED — needs the live brain + real ModelPort adapter + owner-private DEK on the Mini.]

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/obs/telemetry/__init__.py, /Users/artemis-build/artemis/src/artemis/obs/telemetry/store.py, /Users/artemis-build/artemis/src/artemis/obs/telemetry/cost.py, /Users/artemis-build/artemis/src/artemis/obs/telemetry/tracing.py, /Users/artemis-build/artemis/src/artemis/obs/telemetry/source.py, /Users/artemis-build/artemis/tests/test_obs_telemetry.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_obs_telemetry.py` | Type gate (incl. `ModelPort`/`ObservabilitySink`/`TelemetrySource` conformance) |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_obs_telemetry.py` | Test gate (store/migrate/prune, cost, tracer, sink→source, empty-store, staleness, M7-c gap-scan shape) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/obs/telemetry/**, tests/test_obs_telemetry.py |
| `git commit` | "feat: OBS-b telemetry backend (SQLCipher store + TracingModelPort + tier-aware cost + TelemetrySink + SqliteTelemetrySource)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings → `telemetry_db_path` + role→tier/model_id resolution (tests use `tmp_path` + a test Settings + a fixed test key) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | SQLCipher is local; the tracer wraps a port and makes no network call of its own |

## Specialist Context
### Security
- **[RESOLVED — verdict adopted] At-rest encryption:** the store is SQLCipher (owner-private, M2-c `sqlcipher_open`), not plaintext — closing the low-entropy `task_class_key` preimage/enumeration attack the review identified. `task_class_key` is kept identical to M7-a2's value (no keyed-HMAC fork) because SQLCipher-at-rest already closes the threat and divergence would break recipe-clustering.
- **[RESOLVED — was FLAG] No content via the tracer log path:** the WARNING paths log only `role` (≤64 chars) + `error_type`; never `messages`, `resp.text`, or `str(exc)`.
- **[RESOLVED — was FLAG] Unknown-role visibility:** `tier_for` logs a WARNING on an unknown role (no silent unbilled fallthrough); `role` is truncated to 64 chars before INSERT.
- **No egress:** `TracingModelPort` wraps the port and records locally; it adds no network call. The cloud-egress privacy boundary stays M7-a2's responsibility, untouched.
- **Supply chain:** no new third-party dependency — reuses the existing M4-a SQLCipher binding and stdlib. If a binding bump is ever needed, pin it + run `uv run pip-audit`.

### Performance
- The tracer adds one SQLCipher INSERT per model call (already an I/O-bound, multi-hundred-ms op) → negligible; WAL keeps writes non-blocking for reads. Reads are indexed (`at`, `task_class_key`, `(at, role)`). The Curiosity loop reads at idle only. `prune` bounds growth.

### Accessibility
(none — headless backend; the `usage_summary` surface is owner-facing later; a11y applies when that UI is built.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/obs/telemetry/*.py | Type + docstring all exports; document the schema (epoch-ms ints, NOT NULL, `user_version` migration, retention `prune`), the tier-aware cost model (attribution unit not $; subscription tokens = conservative quota signal; cache under-count noted), the `low_confidence_answers` unfiltered contract, `model_id`/`trace_id` columns, and the deferred chunk-staleness + embedding-trace gaps |
| Data model | docs/technical/architecture/data-model.md | Add a one-line note: `route_events`/`escalations`/`call_traces` are INTERNAL telemetry infra tables (not domain entities) — recorded for coherence, excluded from the conceptual model |
| ADR | docs/technical/adr/ADR-008-observability.md | Already written — reference only |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_obs_telemetry.py` → verify: exit 0, incl. static `_check: ModelPort = TracingModelPort(...)`, `_check_sink: ObservabilitySink = TelemetrySink(...)`, `_check_src: TelemetrySource = SqliteTelemetrySource(...)`.
- [ ] Run `uv run python -c "from artemis.obs.telemetry import TelemetryStore, TracingModelPort, TelemetrySink, SqliteTelemetrySource, CostModel"` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_obs_telemetry.py` → verify: migrate idempotent + round-trip + prune; `tier_for`/`CostModel` math + unknown-role WARNING; tracer writes one trace with `total_tokens==42`+`model_id`, survives `usage=None` (zero-token + WARN, no raise) and a store-write failure; sink→source writes ONE route row + ZERO escalation rows on `on_route_decision`, projects escalations/confidence/topics; empty store returns empty collections without raising; a 200-day-old recipe → one `StaleItem`; `scan_gaps` clusters 3 same-key escalations into an `escalation-cluster` gap with `evidence_count==3`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Wire `CompositeSink`+`TracingModelPort` at the composition root over the keyed store, run one live `respond` + `escalate_and_distill` → verify: `route_events`/`escalations`/`call_traces` rows written and `usage_summary` reports teacher-tier tokens with `model_id`.

## Progress
_(Coding mode writes here — do not edit manually)_

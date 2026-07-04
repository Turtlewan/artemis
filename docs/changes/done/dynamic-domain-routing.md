# dynamic-domain-routing — read routing over the live domain list + curated-always-fresh gate (curated machinery, spec 3 of 3)

**Identity:** The read path routes utterances against the **live** domain list (`store.domains()`), not the hardcoded roster — a conversationally-created domain ("workouts") is instantly readable with zero code change; and the per-domain freshness gate treats curated domains (no fetcher, all rows `source="curate"`) as **always fresh** so they never fall through to the slow path. ADR-048 (#2, consequence "always fresh") · ADR-046 (#5 freshness gate, #8 taxonomy) · design note `docs/v2/curated-domains-machinery.md` (part 4). **Consumes spec 2 (treat as EXISTING):** `DataStore.has_foreign_source(domain, *, own_source="curate")`, the `ReadResult.rows` field + rows-returning `read()`, and `curate.py`'s `stash_results`/`stashed_rows` + synced-domain guard (Task 2 amends both). **Build order:** ships after `curate-write-referent`.

_Reviewed rulings folded 2026-07-04: empty-stash clobber fixed via Task 2a (`stash_results` no-ops on an empty row-set); name-squat guard added via Task 2b (static synced roster reserved regardless of row presence); substring match + naive plural accepted as v1._

_Data review, accepted as-is: the curated/synced discriminant stays runtime-only (`source` column, no schema CHECK) — deliberate under domains-are-labels (ADR-046 #7); revisit only if a second writer class ever appears._

## Files to change
| Op | Path |
|----|------|
| modify | `src/artemis/data/read.py` |
| modify | `src/artemis/data/curate.py` |
| modify | `tests/data/test_read.py` |
| modify | `tests/data/test_curate_write.py` |

## Exact changes

### Task 1 — `src/artemis/data/read.py` (modify): dynamic routing, curated-fresh gate, tracking query

**a.** Add module-level constants + helpers. Place `_TRACKING_PREFIX` / `_TRACKING_PATTERNS` / `_is_tracking_query` above the `DomainSpec` class, and `_label_keywords` next to `_render_rows` at the bottom:

```python
# Meta discoverability (ADR-048 consequence): "what are you tracking for me?" answers from the
# live domain list directly -- no domain match, no phrasing call.
_TRACKING_PREFIX = "I'm currently tracking: "
_TRACKING_PATTERNS: tuple[str, ...] = (
    "what are you tracking",
    "what do you track",
    "what are you keeping track of",
    "what are you storing for me",
)


def _is_tracking_query(text: str) -> bool:
    return any(p in text.lower() for p in _TRACKING_PATTERNS)
```

```python
def _label_keywords(label: str) -> tuple[str, ...]:
    """Matchable keywords for a live domain label (ADR-048 #2): the label itself plus a naive
    singular/plural partner (tasks<->task, workouts<->workout). Deterministic -- not a model call.
    Naive: irregular plurals (status, categories) are accepted v1 behavior."""
    label = label.strip().lower()
    variants = {label, label[:-1] if label.endswith("s") else label + "s"}
    return tuple(sorted(v for v in variants if v))
```

**b.** Replace `ReadService.resolve_domain` in full — static registry first (keeps calendar's rich keyword set + freshness config), then the live domain list:

```python
    def resolve_domain(self, text: str) -> DomainSpec | None:
        lowered = text.lower()
        # Static synced-domain registry first (calendar's rich keyword set + freshness config).
        for spec in self._domains:
            if any(kw in lowered for kw in spec.keywords):
                return spec
        # Then the LIVE domain list (ADR-048 #2): any conversationally-created domain is matchable
        # by its own label (+ naive singular/plural) with zero code change. Curated domains use the
        # DomainSpec defaults (limit=50); their freshness gate is bypassed in read() below.
        static = {spec.domain for spec in self._domains}
        for label in self._store.domains():
            if label in static:
                continue
            keywords = _label_keywords(label)
            if any(kw in lowered for kw in keywords):
                return DomainSpec(domain=label, keywords=keywords)
        return None
```

**c.** Replace `ReadService.read` in full — add the tracking-query early return, and make the freshness gate apply ONLY to synced domains (curated bypass). Preserves spec 2's rows-carrying return and the `_phrase` call:

```python
    async def read(self, text: str) -> ReadResult | None:
        """Answer from local data, or None to fall through to the normal ask path.

        None when: no domain keyword matches, the domain is empty, a synced domain is stale, or the
        phrasing call fails. Curated domains (all rows source="curate") have no upstream and are
        never stale (ADR-048). "what are you tracking?" answers from the live domain list."""
        if _is_tracking_query(text):
            labels = self._store.domains()
            if not labels:
                return None  # nothing tracked yet -> fall through to the normal ask path
            return ReadResult(domain="tracking", answer=_TRACKING_PREFIX + ", ".join(labels) + ".")
        spec = self.resolve_domain(text)
        if spec is None:
            return None
        latest = self._store.latest_fetched_at(spec.domain)
        if latest is None:
            return None  # empty domain -> nothing local to answer
        # Synced domains gate on freshness (ADR-046 #5; stale -> live path). Curated domains (no
        # foreign source) have no fetcher/upstream -> never stale -> bypass the gate (ADR-048).
        if self._store.has_foreign_source(spec.domain) and (self._now() - latest) > spec.freshness_s:
            return None
        rows = self._store.query(domain=spec.domain, limit=spec.limit)
        if not rows:
            return None
        answer = await self._phrase(text, rows)
        if answer is None:
            return None
        return ReadResult(domain=spec.domain, answer=answer, rows=tuple(rows))
```

No other change to `read.py`. `DomainSpec`, `ReadResult`, `Record`, and `has_foreign_source` are already available (`ReadResult.rows` from spec 2).

### Task 2 — `src/artemis/data/curate.py` (modify): empty-stash no-op + name-squat guard

**a.** The referent stash holds the last **non-empty** list the owner actually saw — a tracking meta-query (`rows=()`) or an empty-domain read must not clobber a live referent. Replace `stash_results` (spec 2 placed it after the `ReadResults` dataclass):

```python
def stash_results(store: dict[str, ReadResults], session_key: str, rows: Sequence[Record]) -> None:
    """Hold this session's last-read rows for referent resolution (lazy TTL/size eviction).
    NO-OP on an empty row-set: the stash keeps the last NON-EMPTY list the owner actually saw --
    a tracking meta-query (rows=()) must not clobber a live referent. Rows are stashed
    payload-STRIPPED (review FLAG 4): only sanitized_text is ever copied out, so the stash must
    not retain raw payloads at rest either."""
    if not rows:
        return
    evict_expired(store, ttl_seconds=_RESULTS_TTL_SECONDS, max_entries=_RESULTS_MAX_ENTRIES)
    store[session_key] = ReadResults(rows=tuple(replace(r, payload={}) for r in rows))
```

**b.** Name-squat guard: `has_foreign_source` is row-based, so a curated write into a known-synced domain NAME ("calendar") is refused only after the first sync row lands — the static roster must be reserved regardless of row presence. Add the import (dependency-clean: `read.py` imports only `store`/`ports.model`/`types`, never `curate` — no cycle):

```python
from artemis.data.read import DEFAULT_DOMAINS
```

Add above `apply_curate`:

```python
# The static synced roster's names are RESERVED for curated CRUD regardless of row presence --
# has_foreign_source is row-based, so without this a curated save could squat "calendar" on an
# empty store and later commingle with the sync (data review, name-squat FLAG).
_RESERVED_SYNCED_DOMAINS: frozenset[str] = frozenset(spec.domain for spec in DEFAULT_DOMAINS)


def _is_synced_domain(store: DataStore, domain: str) -> bool:
    """True iff curated CRUD must refuse `domain`: on the static synced roster (reserved even
    before the first sync lands) OR holding any foreign-source row (spec-2 guard)."""
    return domain in _RESERVED_SYNCED_DOMAINS or store.has_foreign_source(domain)
```

Then replace both guard call sites with the helper:
- in `apply_curate`: `if store.has_foreign_source(domain):` → `if _is_synced_domain(store, domain):`
- in `_apply_forget` (the referent-resolved re-check): `if store.has_foreign_source(row.domain):` → `if _is_synced_domain(store, row.domain):`

No other change to `curate.py`.

### Task 3 — `tests/data/test_read.py` (modify): dynamic-routing + curated-fresh + tracking tests

Reuse the existing `FakePhraser` / `_seed` idioms. Add a curated-row seeder (curated rows MUST use `source="curate"` so `has_foreign_source` is False):

```python
def _seed_curated(store: DataStore, *, domain: str, text: str, fetched_at: float = 1.0) -> None:
    store.upsert(
        Record(
            domain=domain, kind="note", key=f"{domain}-1", payload={},
            sanitized_text=text, source="curate", fetched_at=fetched_at, owner_fields={},
        )
    )
```

Add these tests (keep every existing test — `test_resolve_domain`, `test_read_stale_data_falls_through` etc. must still pass unchanged, proving static calendar routing + the synced freshness gate are intact):

1. `test_resolve_domain_live_label` — `store = DataStore(); _seed_curated(store, domain="workouts", text="Ran 5k")`; `svc = ReadService(store, phraser=FakePhraser())`; `svc.resolve_domain("what workouts have I logged").domain == "workouts"`. An unseeded label does not match: `svc.resolve_domain("what recipes do I have") is None`.
2. `test_resolve_domain_singular_plural` — `_seed_curated(store, domain="tasks", text="renew passport")`; `svc.resolve_domain("show my task list").domain == "tasks"` (singular "task" matches label "tasks"); also seed `domain="workouts"` and assert `svc.resolve_domain("did I log a workout today").domain == "workouts"` (singular matches plural label).
3. `test_resolve_domain_static_wins_and_survives` — with a live `calendar` row present (`_seed(store)`), `svc.resolve_domain("any meetings tomorrow?").domain == "calendar"` (static keyword set still routes calendar; the live loop skips the already-static label).
4. `test_dynamic_domain_readable_end_to_end` — `_seed_curated(store, domain="workouts", text="Ran 5k on Tuesday")`; `svc = ReadService(store, phraser=FakePhraser(answer="You ran 5k."), now=lambda: 1e9)`; `result = await svc.read("what workouts have I logged")`; `result is not None`, `result.domain == "workouts"`, `result.answer == "You ran 5k."` (a conversationally-created domain is readable with no code change).
5. `test_curated_domain_bypasses_freshness_gate` — `_seed_curated(store, domain="notes", text="buy milk", fetched_at=1.0)`; `svc = ReadService(store, phraser=FakePhraser(answer="You have: buy milk."), now=lambda: 1e9)` (fetched_at is ~1e9s stale, far past the 900s threshold); `result = await svc.read("show my notes")`; `result is not None` (curated → never stale → does NOT fall through). Contrast: a synced calendar row of the same age still falls through (existing `test_read_stale_data_falls_through`).
6. `test_curated_empty_domain_falls_through` — empty store, `svc.read("show my notes") is None` (label unseeded → resolve_domain returns None → fall through).
7. `test_tracking_query_lists_domains` — `_seed_curated(store, domain="notes", text="a"); _seed_curated(store, domain="workouts", text="b")`; `phraser = FakePhraser()`; `svc = ReadService(store, phraser=phraser)`; `result = await svc.read("what are you tracking for me?")`; `result is not None`, `"notes" in result.answer and "workouts" in result.answer`, and `phraser.calls == []` (answered from the domain list, no phrasing call).
8. `test_tracking_query_empty_store_falls_through` — empty store, `await svc.read("what are you tracking for me") is None`.

### Task 4 — `tests/data/test_curate_write.py` (modify): empty-stash no-op + name-squat tests

Reuse the file's existing `_row` helper and `ReadResults`/`stash_results`/`stashed_rows` imports (spec 2). Add:

1. `test_stash_empty_rows_noop` — `state: dict[str, ReadResults] = {}`; `stash_results(state, "dev", (_row(key="a"),))`; then `stash_results(state, "dev", ())`; `stashed_rows(state, "dev")` still has len 1 with `[0].key == "a"` (empty stash did NOT clobber the prior rows). Also `stash_results(state, "fresh", ())` leaves `stashed_rows(state, "fresh") == ()` (no phantom entry created).
2. `test_tracking_result_rows_do_not_clobber_stash` — mirrors the ask-route flow through the data-layer seam: `state = {}`; `stash_results(state, "dev", (_row(key="a"),))` (a prior real read); seed a curated row (`store.upsert(_row(domain="notes", kind="note", key="n1", sanitized_text="buy milk", payload={}, source="curate"))`) and run `result = await ReadService(store, phraser=FakePhraser()).read("what are you tracking for me?")` (reuse/import the `FakePhraser` idiom from `tests/data/test_read.py`); `result is not None and result.rows == ()`; then `stash_results(state, "dev", result.rows)` (exactly what the ask wiring does on every `local_read`); `stashed_rows(state, "dev")[0].key == "a"` (the live referent survives the tracking query).
3. `test_save_into_reserved_synced_name_refused_on_empty_store` — EMPTY store (zero rows anywhere); `apply_curate(CurateDecision(op="save", domain="calendar", content="fake event"), store=store, last_rows=())` → `not outcome.ok`, reply == `"calendar is synced read-only -- I can't change it."`, `store.query(domain="calendar") == []` (the roster name is reserved before any sync row exists).

## Acceptance criteria
1. `resolve_domain` routes an utterance to a live domain by its own label (+ naive singular/plural), with zero code change; an unseeded label does not match. → `test_resolve_domain_live_label`, `test_resolve_domain_singular_plural`
2. The static synced registry (calendar keywords + freshness) still routes and is not shadowed by the live loop. → `test_resolve_domain_static_wins_and_survives`, plus all pre-existing `test_resolve_domain` / `test_read_*` tests unchanged.
3. A conversationally-created curated domain is readable end-to-end with no new code. → `test_dynamic_domain_readable_end_to_end`
4. A curated domain (no foreign source) bypasses the freshness gate — never falls through to the slow path on staleness; a synced domain keeps the ADR-046 #5 gate. → `test_curated_domain_bypasses_freshness_gate` + pre-existing `test_read_stale_data_falls_through`
5. An empty/unseeded domain still falls through (no phantom answer). → `test_curated_empty_domain_falls_through`
6. "what are you tracking for me?" answers from `store.domains()` with no phrasing call; empty store falls through. → `test_tracking_query_lists_domains`, `test_tracking_query_empty_store_falls_through`
7. `stash_results` is a NO-OP on an empty row-set — the referent stash keeps the last non-empty list the owner saw; a tracking query (`rows=()`) routed through the ask wiring does not clobber a live referent. → `test_stash_empty_rows_noop`, `test_tracking_result_rows_do_not_clobber_stash`
8. The static synced roster's names are reserved for curated CRUD regardless of row presence — a save into "calendar" on an EMPTY store is refused with the synced-readonly reply; the spec-2 row-based guard tests still pass unchanged. → `test_save_into_reserved_synced_name_refused_on_empty_store` + pre-existing `test_save_into_synced_domain_refused` / `test_forget_referent_synced_row_refused`
9. Whole-project gates clean (commands below); all new code passes `mypy --strict`.

## Commands to run
```
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q
```

<!-- amended 2026-06-11 per contracts.md (Seam 5) + m5-m6-voice-heartbeat.md BLOCKs B1, F10 -->
---
spec: m6-a-scheduler-tickloop-hookcontract
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M6-a — Heartbeat scheduler + tick loop (replaces M1-d skeleton) + extended hook contract (HookSpec → tier/delivery/payload) + per-module hook registration + Tier gating (Tier-0 always-runs / Tier-1 skipped-and-queued while locked)

**Identity:** Replaces M1-d's no-op Heartbeat skeleton with the real scheduled-tick engine: it extends the M1-a `HookSpec` contract (adds `delivery`, derives `tier` from `data_scope`, makes `check_ref` return a typed hit/no-hit payload), collects every registered module's `proactive_hooks` from the `ToolRegistry`, runs each hook when its interval/cron is due against a fake-able clock, emits the silent-success `HEARTBEAT_OK` (zero idle tokens) when a tick has no hits, and gates execution by tier — Tier-0 hooks always run (even while locked), Tier-1 hooks are skipped-and-queued when the owner session is locked.
→ why: see docs/technical/architecture/brain.md § "Proactive engine (Heartbeat)" (scheduled-tick-dominant, silent-success `HEARTBEAT_OK`, zero idle tokens, per-module `proactive_hooks`) · docs/technical/adr/ADR-006-two-tier-proactivity.md (Tier-0 always-on / Tier-1 queued-for-unlock).

<!-- Split rule: TWO logical phases (1: the extended hook contract + the scheduler/tick/due-evaluation engine that replaces the M1-d skeleton; 2: tier gating + the Tier-1 skip-and-queue path). 1 modify (M1-a manifest.py — extend HookSpec) + 3 create (hook_result types, the scheduler, tests). At the 2-phase / borderline-files limit. Kept together because the scheduler is meaningless without the extended hook contract it dispatches, and the tier gate is the same dispatch loop's branch. Hit-handling (template/LLM/urgency/digest/briefing) is M6-b; ntfy delivery + the durable Tier-1 queue store + policy config is M6-c. If review wants leaner: sub-split into M6-a1 (extend HookSpec + scheduler) and M6-a2 (tier gating). Flagged per rules. -->

## Assumptions
- M1-a complete: `src/artemis/manifest.py` defines `HookSpec` (`name`, `interval_seconds: int | None`, `cron: str | None`, `urgency: Literal["low","normal","high"]`, `needs_llm: bool`, `dedup_key: str | None`, `check_ref: Callable[[], bool]`), `ModuleManifest.proactive_hooks: list[HookSpec]`, `DataScope` (`OWNER_PRIVATE | GUEST_VISIBLE | SHARED`), and `ToolRegistry` with `manifests() -> dict[str, ModuleManifest]`. → impact: Stop (M6-a extends `HookSpec` IN PLACE and reads hooks via `registry.manifests()`; symbol names must match M1-a exactly).
- M1-d complete: `src/artemis/heartbeat.py` defines the skeleton `Heartbeat` (`HEARTBEAT_OK: Final`, `tick()`, `run_forever()`). M6-a **rewrites** this file into the real engine, preserving the public names `Heartbeat`, `HEARTBEAT_OK`, `tick`, `run_forever` (callers/tests from M1-d that import those names keep working). → impact: Stop (rewrite-in-place, names preserved; the M1-d unit test for the skeleton's no-hit behaviour must still pass against the real engine when no hooks are registered).
- M2-b complete: `KeyProvider` Protocol exposes `is_owner_unlocked() -> bool`; `src/artemis/identity/key_provider.py` exports `KeyProvider`, `FakeKeyProvider`. → impact: Stop (the tier gate calls `is_owner_unlocked()`; M6-a injects a `KeyProvider` and uses the fake in tests).
- M2-c complete: `src/artemis/proactive/` package exists (created by M2-c's `tier0_key.py`); the `proactive` pseudo-scope is reserved. M6-a adds modules under `src/artemis/proactive/`. → impact: Low (package already present; M6-a only adds files there).
- A hook's **tier is DERIVED from its module's `data_scope`**, not declared per-hook (ADR-006: "a hook declares its tier (derives from its data_scope)"): a hook whose module `data_scope` is `SHARED` (and which is marked Tier-0-safe — calendar/weather/derived) is **Tier 0**; a hook whose module touches `OWNER_PRIVATE` real sensitive data is **Tier 1**. → impact: Caution. RESOLVED (gate 2026-06-08): explicit `tier: Literal[0,1]` field on `HookSpec`, default `1` (fail-safe to the more-restricted tier); a `ModuleManifest` `model_validator` REQUIRES `tier == 0 ⇒ data_scope != OWNER_PRIVATE` (a Tier-0 hook may not sit on an owner-private module). The explicit `tier=0` opt-in marks the minimised-corpus hooks; the `OWNER_PRIVATE ⇒ Tier 1` guard is enforced at validation. NOT pure auto-derivation — `SHARED` alone does not prove a Tier-0-safe minimised corpus.
- The scheduler uses a **monotonic, injectable clock** (`Callable[[], float]`, defaulting to `time.monotonic`) so due-evaluation and the `run_forever` sleep are deterministically fake-able in tests. Cron parsing uses a small dependency-free recurrence check evaluated against a wall-clock supplier (`Callable[[], datetime]`, defaulting to `datetime.now`) — only the field shapes needed for the M6 hooks (a daily HH:MM "briefing" cron). → impact: Caution. RESOLVED (gate 2026-06-08): minimal `cron` evaluator supporting only `"M H * * *"` (daily HH:MM) — sufficient for the briefing + daily Tier-0 hooks — raising `ValueError` on any unsupported field; a full croniter can replace it behind the `_cron_due(spec, now)` seam later. **Missed-tick semantics:** `_cron_due` fires when `now_wall >= today-at-H:M AND last_fired_date < today` (fire-if-past-and-not-yet-fired), NOT exact-minute equality — so a tick that slips past the scheduled minute (system busy/GC) still fires that day.
- `tick()` is **synchronous and pure-dispatch in M6-a**: it evaluates which hooks are due, runs each due hook's `check_ref` (deterministic, no LLM), collects the resulting hits, and RETURNS them (a `TickResult`) — it does NOT deliver or call the LLM (that is M6-b/M6-c). When zero hits, `tick()` returns a `TickResult` whose `summary == HEARTBEAT_OK` and which carries zero hits (the silent-success path: no LLM call, no delivery — zero idle tokens). → impact: Stop (this is the seam M6-b plugs hit-handling into; M6-a's `tick` must not import any model/ntfy code).
- A hook's `check_ref` returns a typed `HookResult` (hit/no-hit + an optional payload) — NOT a bare `bool`. The M1-a `HookSpec.check_ref: Callable[[], bool]` is widened to `Callable[[], HookResult]`. → impact: Stop (this changes the M1-a contract; the M1-d time tool declares `proactive_hooks=[]` so it is unaffected, but any future hook author follows the new signature).

Simplicity check: considered keeping `check_ref -> bool` and signalling the payload via a side channel — rejected; a hook hit needs to carry data (e.g. "budget 92% used", the dedup key value) for M6-b's template/LLM path, so a typed `HookResult` return is the minimum honest contract. Considered pulling in APScheduler for the scheduler — rejected per brain.md "thin custom orchestrator, no heavyweight framework" and M1-d's same call; an injectable-clock due-loop over `asyncio` is the minimum that ticks + is deterministically testable. Considered a full croniter dependency — rejected for M6; a minimal daily-HH:MM evaluator covers the briefing + daily hooks and stays dependency-free behind a swappable seam.

## Prerequisites
- Specs that must be complete first: **M1-a** (`HookSpec`/`ModuleManifest`/`DataScope`/`ToolRegistry.manifests`), **M1-d** (the `Heartbeat` skeleton this rewrites), **M2-b** (`KeyProvider.is_owner_unlocked` + `FakeKeyProvider`), **M2-c** (`src/artemis/proactive/` package).
- Environment setup required: none beyond M0/M1/M2. Fully deterministic off-hardware — injectable clock + `FakeKeyProvider` + in-test fake hooks; no model, no ntfy, no broker. No on-hardware gate in M6-a (the live scheduled run is M6-c's gated task).
- **Reservation note (architecture-validation 2026-06-23, reservation F — shared durable-exec + idempotency convention; ADR-024 Refinement 2026-06-23):** the heartbeat is one of the three consumers of the **shared checkpoint/replay + idempotency-key convention** (with the Task Executor and recipe-runner). The existing `Hit.dedup_key` is this surface's idempotency key — keep it conformant to the shared convention so a tick that fires the same logical hit twice (overlapping ticks — the named 2026 failure mode) is de-duplicated, and reserve a **per-tick lock** so two overlapping `tick()` runs can't double-advance background work. M6-a builds the dedup_key + tick loop; the durable-replay impl is M9/ADR-024. → impact: Low (dedup_key already exists; this aligns it to the shared convention + reserves the per-tick lock).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/manifest.py | modify | extend `HookSpec`: add `tier: Literal[0,1]`, `delivery` descriptor, widen `check_ref` return to `HookResult`; add the `OWNER_PRIVATE ⇒ tier==1` validator |
| /Users/artemis-build/artemis/src/artemis/proactive/hook_types.py | create | `HookResult` (hit/payload), `Hit` (resolved hook + result + tier + dedup_key), `TickResult` (hits + summary), `DeliverySpec` (channel/priority/tags — shape only; M6-c consumes it) |
| /Users/artemis-build/artemis/src/artemis/heartbeat.py | modify (rewrite) | the real `Heartbeat`: register hooks from the registry, due-evaluation on an injectable clock, `tick() -> TickResult`, `run_forever`, Tier gating (Tier-0 always; Tier-1 skip-and-queue when locked) |
| /Users/artemis-build/artemis/tests/test_heartbeat_scheduler.py | create | due-evaluation, interval + daily-cron firing, silent-success `HEARTBEAT_OK`, tier gating, skip-and-queue, fake clock determinism |

## Tasks
- [ ] Task 1: Extend the `HookSpec` contract — files: `/Users/artemis-build/artemis/src/artemis/manifest.py` (modify) — SURGICAL change to the existing `HookSpec` (M1-a) only; do not touch other models. Changes:
  - Add `tier: Literal[0, 1] = 1` (default the MORE-restricted tier — fail-safe per ADR-006).
  - Widen `check_ref` type from `Callable[[], bool]` to `Callable[[], "HookResult"]` (import `HookResult` from `artemis.proactive.hook_types` under a `TYPE_CHECKING` guard to avoid an import cycle; the field stays `arbitrary_types_allowed`).
  - Add `delivery: "DeliverySpec | None" = None` (the per-hook delivery descriptor; shape defined in `hook_types.py`, consumed by M6-c; `None` ⇒ M6-c applies a tier/urgency default).
  - Keep `name`, `interval_seconds`, `cron`, `urgency`, `needs_llm`, `dedup_key` unchanged.
  - Add a `HookSpec` `model_validator(mode="after")`: exactly one of `interval_seconds`/`cron` must be set (raise `ValueError` "hook needs exactly one of interval_seconds or cron" otherwise).
  - Add a `ModuleManifest` `model_validator(mode="after")`: for every hook in `proactive_hooks`, if `self.data_scope == DataScope.OWNER_PRIVATE` then the hook's `tier` MUST be `1` (raise `ValueError` "Tier-0 hook may not sit on an owner-private module: <hook.name>"). This enforces the ADR-006 derivation guard at the type/validation layer.
  — done when: `uv run mypy --strict src` passes; `HookSpec(name="h", interval_seconds=60, check_ref=<a HookResult-returning callable>)` constructs with `tier == 1`; a `ModuleManifest(data_scope=OWNER_PRIVATE, proactive_hooks=[HookSpec(..., tier=0)])` raises `ValidationError`.

- [ ] Task 2: Define the proactive hook/tick value types — files: `/Users/artemis-build/artemis/src/artemis/proactive/hook_types.py` — pure Pydantic v2 / frozen dataclasses, `mypy --strict`-clean, NO model/ntfy/broker imports:
  - `class HookResult(BaseModel)`: `hit: bool`, `payload: dict[str, object] = {}` (the deterministic check's structured output — e.g. `{"budget_pct": 92}`; empty when no hit), `dedup_value: str | None = None` (the concrete dedup value this run, e.g. the date — combined with the hook's `dedup_key` by M6-b/c). Add a classmethod `HookResult.miss() -> HookResult` returning `HookResult(hit=False)` and `HookResult.of(payload, *, dedup_value=None) -> HookResult` returning a hit.
  - `class DeliverySpec(BaseModel)`: `channel: Literal["ntfy"] = "ntfy"`, `priority: Literal["min","low","default","high","max"] | None = None`, `tags: list[str] = []`, `click_url: str | None = None`, `actions: list[dict[str, str]] = []` (ntfy action-button descriptors; the schema-validated shape M6-c renders — M6-a only carries it).
  - `@dataclass(frozen=True) class Hit`: `module: str`, `hook_name: str`, `tier: Literal[0,1]`, `urgency: Literal["low","normal","high"]`, `needs_llm: bool`, `dedup_key: str | None`, `result: HookResult`, `delivery: DeliverySpec | None`. (One resolved hook firing — everything M6-b/c need without re-reading the manifest. No `queued` field — queue-token `Hit`s are distinguished solely by being passed through the `tier1_sink` path; callers MUST NOT inspect `result` on a queue-token.)
  - `@dataclass(frozen=True) class TickResult`: `hits: tuple[Hit, ...]`, `summary: str`, `tier1_skipped: tuple[str, ...]` (fq `module.hook` names skipped-and-queued because the owner is locked). Add a property `is_silent_success(self) -> bool` = `len(self.hits) == 0`.
  - `HEARTBEAT_OK: Final = "HEARTBEAT_OK"` — re-export from here so M6-b/c import the constant from one home; `heartbeat.py` re-exports it too for M1-d back-compat.
  — done when: `uv run mypy --strict src` passes; `HookResult.miss().hit is False`; `TickResult(hits=(), summary=HEARTBEAT_OK, tier1_skipped=()).is_silent_success is True`.

- [ ] Task 3: Rewrite the Heartbeat engine (scheduler + tick loop + tier gating) — files: `/Users/artemis-build/artemis/src/artemis/heartbeat.py` (rewrite, preserving public names) — `class Heartbeat` constructed with `(registry: ToolRegistry, key_provider: KeyProvider, *, clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], datetime] = lambda: datetime.now(), on_hits: Callable[[TickResult], None] | None = None, tier1_sink: Callable[[Hit], None] | None = None, logger=...)`. Re-export `HEARTBEAT_OK` from `hook_types` (M1-d back-compat). Behaviour:
  - On construction, build the hook table: iterate `registry.manifests().values()`, and for each manifest's `proactive_hooks` build a resolved record `(module, hook, tier, next_due_monotonic)` — initialise `next_due_monotonic` so an interval hook is due on the first tick; record cron hooks with their `"M H * * *"` parse.
  - `def _interval_due(self, rec, now_mono) -> bool`: true when `now_mono >= rec.next_due`; on firing, advance `rec.next_due += hook.interval_seconds`.
  - `def _cron_due(self, rec, now_wall) -> bool`: minimal daily `"M H * * *"` evaluator — **true when `now_wall >= (today at H:M)` AND `rec.last_fired_date < today`** (fire-if-past-and-not-yet-fired, NOT exact-minute equality — a slipped tick still fires that day); on firing set `rec.last_fired_date = now_wall.date()`. Raise `ValueError` on an unsupported cron field.
  - `def tick(self) -> TickResult`: compute `now_mono = clock()`, `now_wall = wall_clock()`; collect due hooks (interval OR cron). For each due hook: **TIER GATE** — if `hook.tier == 1` and `not key_provider.is_owner_unlocked()`: skip running it, append its fq name to `tier1_skipped`, and call `tier1_sink(<a Hit built WITHOUT running check_ref — result=HookResult.miss()>)` if a sink is set (the durable queue is M6-c; the sink is the seam). **The queued `Hit` is a queue-token ONLY — never a hit signal; M6-c's `drain()` MUST ignore its `result` and use only the fresh `check_ref()` return to decide hit/miss.** Tier-0 hooks ALWAYS run regardless of lock state. For a hook that runs: call `result = hook.check_ref()` (deterministic, NO LLM); if `result.hit`, build a `Hit(module, hook.name, tier, hook.urgency, hook.needs_llm, hook.dedup_key, result, hook.delivery)` and collect it. Wrap each `check_ref()` in try/except → log + treat as a miss (degrade-don't-crash; one bad hook never aborts the tick). **A due hook's `next_due` (interval) / `last_fired_date` (cron) advances when it is DISPATCHED — whether `check_ref` returns OR raises** — a hook deemed due has fired (attempted); not advancing on exception would re-fire it every tick = retry storm. Build `TickResult(hits=<collected>, summary=(HEARTBEAT_OK if no hits else f"{n} hit(s)"), tier1_skipped=<...>)`. If `on_hits` is set AND hits exist, call `on_hits(tick_result)` **wrapped in try/except → log + continue** (a raising HitHandler must not kill the tick or `run_forever`) (the M6-b hit-handling seam). On silent success (no hits) log debug "heartbeat tick: silent success" and make NO model/delivery call (zero idle tokens). Return the `TickResult`.
  - **`pre_tick_steps: list[Callable[[], Awaitable[None]]]`** — async pre-flight callables, owned and awaited by this `Heartbeat`'s runner before each `tick()`. The composition root supplies them at construction (default `[]`). **This is the ONE place untrusted text is laundered** (Seam 5 / Decision D3): a pre-flight step (e.g. M8-b2's Gmail urgency hook) runs `QuarantinedReader` and writes laundered safe claims to a shared store; the sync `check_ref` reads only those laundered claims. Add `pre_tick_steps: list[Callable[[], Awaitable[None]]] = []` as a constructor parameter. In `run_forever`, before each `tick()`, await every step in order; any step that raises is caught, logged, and skipped (degrade-don't-crash — a failing pre-step MUST NOT abort the tick or suppress other steps). Import `Callable`, `Awaitable` from `collections.abc`.
  - `async def run_forever(self, *, max_ticks: int | None = None, sleep_seconds: float = 60.0) -> None`: wrap the loop body in `try/finally`; each iteration: (1) `await` each step in `self.pre_tick_steps` in order (degrade-don't-crash per above); (2) run `tick()`; (3) `await asyncio.sleep(sleep_seconds)` (granularity, NOT a hook interval), stopping after `max_ticks`. **Graceful shutdown:** the cancellation point is the `await asyncio.sleep` (between ticks — never mid-`tick()`); on `asyncio.CancelledError` the `finally` logs a clean-shutdown line and re-raises, so no tick is abandoned mid-dispatch. (Granularity sleep + per-hook interval/cron due-checks = the scheduled-tick engine.)
  — done when: `uv run mypy --strict src` passes; with an empty registry `Heartbeat(...).tick().summary == HEARTBEAT_OK` (M1-d back-compat) and `is_silent_success is True`.

- [ ] Task 4: Write the scheduler + tier-gate tests — files: `/Users/artemis-build/artemis/tests/test_heartbeat_scheduler.py` — typed pytest with a **fake clock** (a mutable `[t]` list + a `clock()` closure returning `t[0]`), a fake `wall_clock`, `FakeKeyProvider` (M2-b), and in-test fake hooks (callables returning `HookResult.miss()` or `HookResult.of(...)`), registered via real `ModuleManifest`s on a real `ToolRegistry(FakeEmbedder())`:
  - silent success: a registry with ONE interval hook whose `check_ref` returns `miss()` → `tick().summary == HEARTBEAT_OK`, `is_silent_success is True`, zero hits; an `on_hits` spy was NEVER called.
  - interval due-evaluation: a hook with `interval_seconds=60`; first `tick()` runs it; advance the fake clock by 30s → second `tick()` does NOT run it (not due); advance by another 31s → third `tick()` runs it again (assert via a call-counter on the fake `check_ref`).
  - hit collection: a hook whose `check_ref` returns `HookResult.of({"budget_pct": 92}, dedup_value="2026-06-04")` → `tick().hits` has one `Hit` with `module`/`hook_name`/`urgency`/`needs_llm`/`result.payload["budget_pct"] == 92`; `summary != HEARTBEAT_OK`; the `on_hits` spy received the `TickResult`.
  - daily cron: a hook `cron="30 8 * * *"`; with `wall_clock` returning 08:30 → fires once; a second `tick()` at the same 08:30 minute does NOT re-fire (already fired this day); **a fresh day with `wall_clock` returning 08:31 (tick slipped past the scheduled minute) STILL fires that day** (fire-if-past-and-not-yet-fired); at 08:30 the NEXT day fires again. An unsupported cron (`"*/5 * * * *"`) raises `ValueError` at construction/first-evaluation.
  - tier gating — Tier-0 always runs: a `tier=0` hook on a `SHARED` module runs under `FakeKeyProvider(owner_unlocked=False)` (its `check_ref` IS called).
  - tier gating — Tier-1 skip-and-queue: a `tier=1` hook on an `OWNER_PRIVATE` module under `owner_unlocked=False` → its `check_ref` is NOT called, its fq name is in `tick().tier1_skipped`, and the injected `tier1_sink` spy received a queued `Hit`. Under `owner_unlocked=True` the SAME hook runs normally.
  - degrade: a hook whose `check_ref` raises → `tick()` does not raise; that hook is treated as a miss; other hooks still run.
  - next_due advances on exception: a raising interval hook (`interval_seconds=60`) dispatched on tick 1; advance the fake clock by 30s → tick 2 does NOT re-run it (its `next_due` advanced despite the raise); advance by 31s → tick 3 runs it again (assert the call-counter increments only when due, not every tick — no retry storm).
  - on_hits never kills the tick: an `on_hits` spy that raises → `tick()` still returns its `TickResult` (the raise is logged+swallowed).
  - graceful shutdown: start `run_forever(sleep_seconds=…)` as a task, `task.cancel()` during the inter-tick sleep → awaiting the task raises `CancelledError` (after the `finally` clean-shutdown log); assert no tick was left partially dispatched (a tick in progress completes before the cancel takes effect at the sleep).
  - **pre_tick_steps ordering and degrade**: construct `Heartbeat(..., pre_tick_steps=[async_step])` where `async_step` records it was called → after one tick `async_step` was awaited exactly once BEFORE `tick()` fired (verified via a shared call-log list). A second test: `pre_tick_steps=[raising_step, good_step]` where `raising_step` raises → `tick()` still fires, `good_step` still runs (degrade-don't-crash; no step silences subsequent steps).
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_heartbeat_scheduler.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/proactive/hook_types.py, /Users/artemis-build/artemis/tests/test_heartbeat_scheduler.py |
| Modify | /Users/artemis-build/artemis/src/artemis/manifest.py, /Users/artemis-build/artemis/src/artemis/heartbeat.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_heartbeat_scheduler.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (scheduler, due-eval, tier gating, silent success) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/manifest.py, src/artemis/heartbeat.py, src/artemis/proactive/hook_types.py, tests/test_heartbeat_scheduler.py |
| `git commit` | "feat: M6-a Heartbeat scheduler + tick loop + extended hook contract + Tier-0/Tier-1 gating" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Pure in-process; injected clock + fake KeyProvider in tests |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No new dependencies (stdlib `asyncio`/`time`/`datetime`) |

## Specialist Context
### Security
The tier gate is an ADR-006 wall: a Tier-1 hook's `check_ref` (which touches real owner data) is NEVER invoked while the owner session is locked — it is skipped-and-queued, so no sensitive read happens without an unlocked session. The `OWNER_PRIVATE ⇒ tier==1` manifest validator is a structural guard against a hook author mislabelling a sensitive hook as Tier-0. Tier-0 hooks run always but only over the minimised proactive corpus (the corpus + its key are M2-c/M6-c concerns; M6-a only enforces "Tier-0 may not sit on an owner-private module"). `tick()` makes ZERO model and ZERO network calls — no egress surface in M6-a. [HARD FLAG for the M6-c apex-security note: the actual Tier-1 *durable* queue (where skipped hits persist until unlock) and the Tier-0 corpus access are the scope-creep subjects per ADR-006 — M6-a only provides the `tier1_sink` seam.]

### Performance
Silent success = `tick()` returns `HEARTBEAT_OK` with zero hits → no LLM, no delivery, zero idle tokens (brain.md). Due-evaluation is O(number of hooks) per granularity tick — negligible. The injectable clock makes the whole engine millisecond-fast and deterministic in CI.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/heartbeat.py, src/artemis/proactive/hook_types.py | Type + docstring all exports; document the tick contract (pure dispatch, returns TickResult, no LLM/delivery), the tier-derivation guard, and the `on_hits`/`tier1_sink` seams M6-b/c consume |
| Inline | src/artemis/manifest.py | Document the extended HookSpec fields (tier, delivery, HookResult return) on the changed model only |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_heartbeat_scheduler.py` → verify: exit 0.
- [ ] Run `uv run python -c "from artemis.heartbeat import Heartbeat, HEARTBEAT_OK; from artemis.registry import ToolRegistry; from artemis.identity.key_provider import FakeKeyProvider; from tests_helpers import FakeEmbedder" 2>/dev/null || uv run python -c "from artemis.heartbeat import Heartbeat, HEARTBEAT_OK; print(HEARTBEAT_OK)"` → verify: prints `HEARTBEAT_OK` (engine + constant import).
- [ ] Run `uv run pytest -q tests/test_heartbeat_scheduler.py` → verify: silent-success returns `HEARTBEAT_OK` with no `on_hits` call; interval due-evaluation fires only when due; a hit produces a `Hit` carrying the payload and calls `on_hits`; daily cron fires once per day and rejects unsupported cron; Tier-0 runs while locked; Tier-1 is skipped-and-queued while locked and runs when unlocked; a raising hook degrades to a miss; a `pre_tick_steps` step is awaited before `tick()` fires; a raising pre-step does not suppress subsequent steps or abort the tick.
- [ ] Run `uv run python -c "from artemis.proactive.hook_types import HookResult, TickResult, HEARTBEAT_OK; print(HookResult.miss().hit, TickResult(hits=(), summary=HEARTBEAT_OK, tier1_skipped=()).is_silent_success)"` → verify: prints `False True`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_

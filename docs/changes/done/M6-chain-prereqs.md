---
spec: m6-chain-prereqs
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M6-chain-prereqs — async `on_hits` contract patch (M6-a) + `ntfy_topic_secret` Settings field (M0-a), the two prerequisites that unblock the M6-b → M6-c delivery chain

**Identity:** Two small, independent prerequisite patches that gate the M6 delivery chain. (1) Make the M6-a `Heartbeat.on_hits` seam **async** and move its invocation out of the synchronous `tick()` into the already-async `run_forever` loop, so `M6-b`'s `HitHandler.handle` can `await model.complete(...)` (async `ModelPort` per ADR-015). (2) Add the `ntfy_topic_secret` field to `Settings` so `M6-c` can form a non-guessable ntfy topic. Ratified in planning 2026-06-24.
→ why: see `docs/findings/m6-delivery-chain-blocker.md` (the async/sync collision + the missing Settings field) and ADR-015 (async port surface).

<!-- Split rule: 2 logical phases (async-contract patch · Settings field), 3 files (heartbeat.py + its test file, config.py) — at the limit, not over. Kept in one spec because both are prerequisites of the same M6 delivery chain and each is individually tiny; neither fits cleanly back into its already-built parent spec (M6-a @627dfef, M0-a). -->

## Assumptions
- M6-a is built and committed (627dfef): `src/artemis/heartbeat.py` defines `Heartbeat` with `on_hits: Callable[[TickResult], None] | None` (sync) called synchronously inside `tick()` at the end of the tick; `run_forever` is already `async` and already `await`s each `pre_tick_steps` entry. → impact: Stop (this spec changes that exact seam + call site).
- `tick()` currently returns a `TickResult` but is annotated `-> str` (a pre-existing annotation bug). Because `run_forever` must now read `tick()`'s return to decide whether to fire `on_hits`, the annotation is corrected to `-> TickResult` as a necessitated part of this change (not gratuitous). → impact: Low.
- The on_hits seam currently has THREE direct consumers in `tests/test_heartbeat_scheduler.py` that drive it through `tick()` — the finding's "tests untouched" note was optimistic. Two need rework (see Task 1). → impact: Caution (the test rework is in this spec's scope and file list).
- `src/artemis/config.py` `Settings` has `ntfy_port` but no `ntfy_topic_secret`. The M6-c spec already references `settings.ntfy_topic_secret`; the field simply does not exist yet. → impact: Stop (Task 2 adds it).

Simplicity check: considered amending the already-built M6-a / M0-a specs in place — rejected; they are committed, so a fresh prereq spec keeps the scope-lock honest (the finding's recommendation). Considered making the `deliver` sink async too — rejected; out of scope, `deliver` is a plain HTTP POST, not a `ModelPort` call, and an `async` method may call a sync sink. Considered generating the ntfy secret inside slot-init only — kept slot-init/M0-f as the prod persistence path but gave the field a secure `default_factory` so dev is non-guessable without env wiring.

## Prerequisites
- Specs complete first: **M6-a** (built @627dfef), **M0-a** (`Settings`). No new dependencies.
- Environment: none. Fully off-hardware; `asyncio_mode=auto` (added in M0-a per ADR-015) lets the reworked async tests run without explicit `@pytest.mark.asyncio` where convenient.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/heartbeat.py | modify | `on_hits` → `Callable[[TickResult], Awaitable[None]] | None`; remove its call from `tick()`; `await` it in `run_forever`; fix `tick()` return annotation to `-> TickResult` |
| tests/test_heartbeat_scheduler.py | modify | rework the 3 `on_hits` tests for the relocated async call site |
| src/artemis/config.py | modify | add `ntfy_topic_secret` field (secure default-factory, excluded from serialisation) |

## Tasks
- [x] Task 1: Make `on_hits` async and relocate its call — files: `src/artemis/heartbeat.py`, `tests/test_heartbeat_scheduler.py`
  - Constructor seam (line ~55): change `on_hits: Callable[[TickResult], None] | None = None` → `on_hits: Callable[[TickResult], Awaitable[None]] | None = None`. Ensure `Awaitable` is imported from `collections.abc` (already imported for `pre_tick_steps`).
  - `tick()` (line ~134): change the return annotation `-> str` → `-> TickResult`. REMOVE the on_hits invocation block (lines ~175–181); keep only the silent-success debug log: `if not hits: self._log.debug("heartbeat tick: silent success")`. `tick()` no longer calls `on_hits`; it just returns the `TickResult`.
  - `run_forever` (line ~215): capture the tick result and fire on_hits there, mirroring the existing `pre_tick_steps` await pattern — replace `self.tick()` with:
    ```python
    tr = self.tick()
    if tr.hits and self._on_hits is not None:
        try:
            await self._on_hits(tr)
        except Exception:
            self._log.exception("heartbeat on_hits handler failed")
    ```
  - Test rework in `tests/test_heartbeat_scheduler.py`:
    - `test_silent_success_returns_heartbeat_ok_without_on_hits`: the seam is now async, so a sync `on_hits=on_hits.append` no longer type-checks. Replace with an `async def _record(r: TickResult) -> None: on_hits.append(r)` passed as `on_hits=_record`. Keep the real assertions (`summary == HEARTBEAT_OK`, `is_silent_success`, `hits == ()`, `on_hits == []`) — a no-hit `tick()` still never fires on_hits.
    - `test_hit_collection_preserves_payload_and_calls_on_hits`: split the concern. KEEP the payload assertions driven by `tick()` (drop on_hits from that path). ADD an `async` test (e.g. `test_run_forever_fires_on_hits_on_hit`) that builds the same hitting hook with an `async def` recorder appending to `received`, runs `await heartbeat.run_forever(max_ticks=1, sleep_seconds=0)`, and asserts `received` got one `TickResult` whose `hits` carry the expected payload.
    - `test_on_hits_exception_does_not_kill_tick`: rename to `test_on_hits_exception_does_not_kill_run_forever`; make it `async`; pass an `async def on_hits` that raises; `await heartbeat.run_forever(max_ticks=1, sleep_seconds=0)` must complete without raising (degrade-don't-crash now lives in `run_forever`, not `tick()`).
  - done when: `uv run mypy --strict src tests/test_heartbeat_scheduler.py` passes; `uv run pytest -q tests/test_heartbeat_scheduler.py` passes; a no-hit `tick()` fires no on_hits; one `run_forever(max_ticks=1)` tick WITH a hit awaits on_hits exactly once; a raising async on_hits does not kill `run_forever`.

- [x] Task 2: Add `ntfy_topic_secret` to `Settings` — files: `src/artemis/config.py`
  - Add `import secrets` at the top.
  - Add the field near the other ntfy settings:
    ```python
    # ntfy egress topic secret: the topic IS the publish/subscribe capability and
    # must not be guessable. Prod stability comes from M0-f injecting a persisted
    # ARTEMIS_NTFY_TOPIC_SECRET into the slot .env; absent (dev) → a random per-process hex.
    ntfy_topic_secret: str = Field(default_factory=lambda: secrets.token_hex(16), exclude=True)
    ```
  - The env value (`ARTEMIS_NTFY_TOPIC_SECRET`, injected per-slot by M0-f) takes precedence over the default_factory → stable topic in prod; random hex in dev when unset.
  - done when: `uv run mypy --strict src` passes; `python -c "from artemis.config import Settings; s=Settings(); assert s.ntfy_topic_secret and 'ntfy_topic_secret' not in s.model_dump()"` exits 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | src/artemis/heartbeat.py, tests/test_heartbeat_scheduler.py, src/artemis/config.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_heartbeat_scheduler.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Full suite (no regression in the existing heartbeat tests) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/heartbeat.py, tests/test_heartbeat_scheduler.py, src/artemis/config.py |
| `git commit` | "feat: M6 chain prereqs — async on_hits contract + ntfy_topic_secret Settings field" |

## Specialist Context
### Security
`ntfy_topic_secret` is the egress capability for the proactive engine (anyone who knows the topic can publish/subscribe). The secure `default_factory` (`secrets.token_hex(16)` = 128 bits) prevents the guessable `artemis-dev-owner`-style topic the M6-c spec's F9 fix warns against; `exclude=True` keeps it out of any serialised settings dump. [FLAG apex-security / planning: M0-f's secrets inventory should add `ARTEMIS_NTFY_TOPIC_SECRET` to the Keychain→`.env` inject map so prod has a stable, persisted topic — out of this spec's scope, tracked as a follow-up.]

### Performance
The relocated on_hits call adds zero cost to `tick()` (it now does strictly less) and one `await` in `run_forever` only when a tick has hits — identical to the prior behaviour, just at a site that can legally await.

### Accessibility
(none — no frontend)

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_heartbeat_scheduler.py` → verify: exit 0 (the async seam + `-> TickResult` annotation type-check).
- [ ] Run `uv run pytest -q tests/test_heartbeat_scheduler.py` → verify: silent-success fires no on_hits; a hitting `run_forever(max_ticks=1)` awaits on_hits once with the correct payload; a raising async on_hits does not kill `run_forever`.
- [ ] Run `uv run python -c "from artemis.config import Settings; s=Settings(); assert s.ntfy_topic_secret and 'ntfy_topic_secret' not in s.model_dump()"` → verify: exit 0.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
**✅ DONE 2026-06-24 (Codex gpt-5.5, Opus host verified).** Both tasks complete, all ACs green.
- Task 1: `on_hits` → `Callable[[TickResult], Awaitable[None]] | None`; call relocated from `tick()` to `run_forever` (awaited, exception-degraded); `tick()` annotation `-> str` → `-> TickResult`. 3 tests reworked: silent-success uses async `_record`; `test_hit_collection_preserves_payload` keeps payload asserts (on_hits dropped); new async `test_run_forever_fires_on_hits_on_hit`; `test_on_hits_exception_does_not_kill_tick` → `..._run_forever` (async, raises, `run_forever` survives).
- Task 2: `import secrets` + `ntfy_topic_secret: str` with `default_factory=secrets.token_hex(16)`, `exclude=True`.
- **Deviation (SMALL):** the `tick() -> TickResult` annotation fix made the pre-existing `cast(TickResult, heartbeat.tick())` calls redundant across the test file; Codex removed them + the now-unused `from typing import cast` import (orphan-cleanup from this spec's own change — CLAUDE.md §3). Same file, no approach change.
- Verify (re-run independently by host): `mypy --strict src tests/test_heartbeat_scheduler.py` clean (66 files) · `ruff check` + `ruff format --check` clean · full suite **238 passed** · config AC exits 0.

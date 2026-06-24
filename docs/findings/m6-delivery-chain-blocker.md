# Finding: M6 delivery chain (M6-b → M6-c) is blocked — async `on_hits` contract decision needed

_Surfaced 2026-06-24 during the prereq build (coding mode). Routed to planning per owner decision (pause build, resolve contract in planning)._

## TL;DR

`M6-c` (ntfy delivery) cannot be built because it depends on `M6-b` (hit→message handler), which is **unbuilt**. `M6-b` in turn **cannot be built as written**: its `HitHandler.handle` (the `on_hits` callable) must make an **async** `model.complete()` call, but `M6-a`'s `Heartbeat` invokes `on_hits` **synchronously**. Resolving this requires changing the `M6-a` `on_hits` contract from sync to async — an architecture decision outside `M6-b`'s file scope. Planning must decide the contract; then the build can proceed.

## The async/sync collision (the core blocker)

- `src/artemis/heartbeat.py:134` — `def tick(self) -> str` is **sync**; at line 177 it calls `self._on_hits(tick_result)` **synchronously**.
- `src/artemis/heartbeat.py:55` — the seam is typed `on_hits: Callable[[TickResult], None]` (sync).
- `M6-b` Task 2 — `HitHandler.handle(tick)` is the `on_hits` impl and **must** `await self.model.complete(role="responder", messages=...)` exactly once per tick for the batched-LLM path (`ModelPort.complete` is async per ADR-015).
- A sync function cannot `await`. So `M6-b` is unbuildable against the current `M6-a` contract.

### Proposed resolution (planning to ratify)

Make `on_hits` **async** and **relocate its invocation** out of the sync `tick()` into the already-async `run_forever` loop:

- Change the seam to `on_hits: Callable[[TickResult], Awaitable[None]] | None`.
- In `tick()`: stop calling `on_hits`; return the `TickResult` as today.
- In `run_forever` (heartbeat.py:215, already async): after `tr = self.tick()`, do `if tr.hits and self._on_hits is not None: await self._on_hits(tr)` (try/except, degrade-don't-crash).

**Why this is low-risk / behavior-preserving:** the only existing `on_hits` consumer path is the real `run_forever` loop. Direct `tick()` callers (notably the M1-d tests that compare `tick()` to `HEARTBEAT_OK`) **do not use `on_hits`**, so moving the call out of `tick()` does not change their behavior. The change is small and localized to `heartbeat.py`.

**Why it's a planning call, not a build adaptation:** it modifies a core M6-a contract (the `on_hits` signature + invocation site) in a file outside `M6-b`'s declared scope. Per APEX, build-changing contract judgment is resolved in planning. (Contrast `M4-c-1`'s `SqliteMemoryStore` hole, which the owner approved filling inline — that added a new class within the spec's own file list; this changes an existing cross-spec contract.)

If planning ratifies: `M6-b`'s spec should be amended to (a) note `handle` is wired as an async `on_hits`, and the `M6-a` heartbeat change should be captured as its own tiny spec (or an explicit `M6-b` task) so the scope lock is honest.

## Secondary holes in the chain

1. **`M6-b` is unbuilt** but is a ready spec (`docs/changes/M6-b-hit-handling-batched-llm-urgency-briefing.md`). Its other deps are all satisfied (M6-a `Hit`/`TickResult`/`HookResult`/`DeliverySpec`; `ModelPort`/`ModelResponse`; `ToolRegistry`/`HookSpec`). Only the async-`on_hits` contract blocks it. The build-order pointer in status.md had skipped M6-b (listed M6-c directly) — order correction: **M6-b precedes M6-c**.
2. **`M6-c` needs a `Settings` field** `ntfy_topic_secret` (a per-slot cryptographically-random hex; the ntfy topic is the egress capability and must not be guessable). The current `Settings` (`src/artemis/config.py`) has `ntfy_port` but **no** `ntfy_topic_secret`. The M6-c spec's Files-to-Change does not list `config.py`, so adding the field is out-of-scope as written — planning should either add the field to `M0-a`/`Settings` or amend `M6-c`'s scope.
3. **`M0-b` (ntfy LaunchDaemon)** is unbuilt and Mac-gated; off-hardware M6-c is tested against a fake `http_post` + `ntfy_base_url(settings)`, so M0-b is **not** a hard build dependency for M6-c (only Task 7, the live publish, is on-hardware-gated). No action needed off-hardware beyond the `Settings` field.

## Recommended planning outputs

1. Ratify the async-`on_hits` contract change (above) → amend `M6-a` (tiny) or add `M6-a-async-onhits` spec.
2. Add `ntfy_topic_secret` to `Settings` (in `M0-a` or as an `M6-c` scope amendment).
3. Re-confirm build order: **M6-a (contract patch) → M6-b → M6-c**.

Once (1)–(3) land, the prereq build resumes the M6 chain. Until then it stays parked; the rest of the prereq layer (M7-b, then google-dep M8-a/M8-b1/CAL-a/b, then the deferred docling M3-a/M3-b) is independent of M6 and remains buildable.

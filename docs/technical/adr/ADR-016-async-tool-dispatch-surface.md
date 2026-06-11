# ADR-016 — Uniform async tool-dispatch surface (`ToolSpec.callable_ref`)

- **Status:** Accepted · **Date:** 2026-06-12 · **Deciders:** owner + planning
- **Relates:** ADR-015 (async port surface — the layer below this one) · contracts.md Seam 2 (ToolRegistry / `callable_ref`) · contracts.md Seam 3 (GATE `ActionStagingService.approve`) · M1-a (`ToolSpec` producer) · M1-b (Brain tool dispatch) · GATE-a (approve→`_execute` twin dispatch) · ADR-012 (gated-action staging). Trigger: the ADR-015 async-port cascade surfaced the same sync/async question one layer up at the tool-dispatch surface (final spec-lint pass, 2026-06-11).

## Context

ADR-015 made the network-I/O **port** surface async (`ModelPort`/`EmbeddingModel`/`Reranker`/`Retriever`/`MemoryStore` embed methods). That fixed the ports but pushed the same break up to the **tool-dispatch** surface — the single uniform point where the Brain and GATE invoke a registered tool.

`ToolSpec.callable_ref` was frozen (contracts.md Seam 2) as **sync**: `Callable[[BaseModel], BaseModel]`. Both call sites invoke it synchronously:
- Brain (M1-b `respond`): `spec.callable_ref(args_model)`.
- GATE-a `approve()`: `tool_spec.callable_ref(validated_args)` — the `_execute` twin.

Two collisions with the sync typing:
1. **Can't reach an async dependency (the trigger).** M8-d-c2's `suggestion_accept` brain-tool flows through `accept_with_graduation()` (defined sync) into `RecipeStore.write`, which ADR-015 made **async** (it embeds the recipe for RAG-for-tools). A sync callable can't `await` it — the `asyncio.run`-inside-a-running-loop bridge raises at runtime. (Parked as a `LINT-DEFER` in M8-d-c2.)
2. **Latent event-loop blocking.** Every write-enabled spoke's tool (and its `_execute` twin) performs **network I/O** to Google Calendar/Gmail APIs. A *sync* callable doing that I/O inside the async Brain/GATE event loop blocks the loop — exactly the failure ADR-015 §2 set out to remove.

So `callable_ref` must become async-capable; that part is forced by ADR-015. The genuine decision is *how* — given that every tool funnels through **one uniform dispatch site** in each of two consumers.

Options weighed (2026-06-12):
- **A — Uniform async.** `callable_ref: Callable[..., Awaitable[BaseModel]]`. **Every** tool callable is `async def`; both dispatch sites `await` it. Pure-sync tools (time, `memory.resolve_entity`) become trivial `async def` (zero runtime cost).
- **B — Heterogeneous (mirror ADR-015's per-method port split).** `callable_ref: Callable[..., BaseModel | Awaitable[BaseModel]]`. No-I/O tools stay sync; the dispatch site detects coroutines (`inspect.isawaitable`) and awaits conditionally.

## Decision

1. **Adopt option A — the uniform async tool-dispatch surface.** `ToolSpec.callable_ref` is `Callable[..., Awaitable[BaseModel]]`. **Every** registered tool callable — front-door, `_execute` twin, read-only, and no-I/O alike — is `async def` returning a Pydantic result model. This is the standing rule for all current and future tools.

2. **Why uniform here, not heterogeneous like ADR-015.** ADR-015 split ports per-method because each port has *one* fixed caller and a typed protocol, so a sync/async split is clean and statically checkable. Tool callables are different: they are dispatched through a **single uniform site** in each consumer (Brain `respond`, GATE `approve`). A single socket wants a single plug shape. Option B's union return type forces `inspect.isawaitable` branching that **`mypy --strict` cannot enforce** — reintroducing the silent-missed-`await` class of bug that ADR-015 §Consequences was proud of catching. Wrapping a no-I/O body in `async def` is zero-cost at runtime (it returns immediately without suspending), so uniformity costs nothing and buys static safety.

3. **Concrete cascade — dispatch sites become async-aware:**
   - **M1-a (producer):** `ToolSpec.callable_ref: Callable[..., Awaitable[BaseModel]]`. `get_tool`'s synthetic-`ToolSpec` wrapper for `_execute` twins wraps an **async** callable. Tool-index export is unaffected (`callable_ref` is never serialised). `retrieve_tools`/`retrieve_tools_scored` stay as ADR-015 left them (already async via the embed).
   - **M1-b (Brain):** `await spec.callable_ref(args_model)` inside `respond`. `respond` is already `async`. The degrade-test's "raising callable" becomes an `async def` that raises.
   - **GATE-a (`ActionStagingService.approve`):** becomes **`async def`**; `await tool_spec.callable_ref(validated_args)` for the `_execute` twin dispatch. The conditional `PENDING→EXECUTING→APPROVED/PENDING` state machine (Seam 3) is unchanged — the SQLCipher `set_status_conditional` calls stay **sync** inside the async method (local disk, no I/O). `reject`, `expire_due`, `list_pending` **stay sync** (no dispatch). Test spy callables become `async def`.
   - **GATE-b (route):** `await request.app.state.action_staging.approve(body.id)` in the already-`async def approve_action` route. Swift/ArtemisKit is unaffected (HTTP boundary). The "dispatches synchronously" prose updates to "awaits the async dispatch".
   - **Spoke tools:** every spoke's tool callable and `_execute` twin is `async def`: M1-d (time), M4-d-2 (`memory.resolve_entity` — **flips its 2026-06-12 "stays sync" LINT note**), CAL-a/b/c/d, M8-b1/b2 (Gmail), M8-d-a/b/c1/c2 (Productivity, incl. `accept_with_graduation` → `async def` that `await`s `RecipeStore.write`; removes the M8-d-c2 `LINT-DEFER`).

4. **What stays sync (deliberately).** Inside an `async` tool body, local-only work stays sync: SQLCipher reads/writes, `ActionStagingService.stage`/`set_status_conditional`, `EntityRepository` DB lookups, `Router.route` is async only because ADR-015 made it so. A tool that does *only* such work is still declared `async def` for signature uniformity, but its body contains no `await`.

## Consequences

- **Cascade (mechanical, ~16 specs):** every tool callable → `async def`; every dispatch → `await`; every test fake/spy callable → `async def`. Reaches M1-a, M1-b, GATE-a, GATE-b, M1-d, M4-d-2, CAL-a/b/c/d, M8-b1, M8-b2, M8-d-a, M8-d-b, M8-d-c1, M8-d-c2. contracts.md Seam 2 amended; M1-a is the producer of record.
- **Re-opens a frozen contract.** Like ADR-015, a conscious post-freeze amendment (the freeze stops *drift*, not deliberate decisions). The uniform-async rule is now part of the binding contract; future tools inherit it.
- **Clears the two parked markers:** M8-d-c2's `LINT-DEFER` (RecipeStore.write await) and M4-d-2's "resolve_entity stays sync" LINT note are both resolved by this ADR.
- **Tests:** dispatch tests `await` the callables; `mypy --strict` enforces the coroutine typing end-to-end, so a missed `await` fails the gate rather than silently returning a coroutine — the same safety property ADR-015 secured one layer down.
- **Fixes the latent blocking** at the tool layer: no spoke's network I/O blocks the event loop during a brain turn or an approve dispatch.
- **This is the last gate to batch-handoff-ready.** With the cascade applied, the corpus has no remaining sync/async inconsistency across the port + dispatch surfaces.

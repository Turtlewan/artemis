# Run Model: Draining an In-Process Event Queue
**Research date:** 2026-06-25
**Topic:** Periodic tick-based drain vs dedicated long-lived background worker for an asyncio dispatcher queue
**Phase:** apex-research Phase-2 (Retrieval) — cite-or-drop, no recommendation

---

## Research Question

Should a dispatcher's in-process `asyncio.Queue` be drained via a **periodic heartbeat tick** (calling `drain_once()` each tick interval) or via a **dedicated long-lived background task** that runs `while True: item = await queue.get(); ...` continuously?

---

## 1. Periodic / Batched Tick Drain vs. Continuous Worker Loop

### 1.1 The Continuous Worker Loop — Standard Practice

The canonical asyncio pattern is a long-lived consumer coroutine with a blocking `await queue.get()`:

```python
async def worker(queue):
    while True:
        item = await queue.get()
        await process(item)
        queue.task_done()
```

This is the pattern shown in the official CPython asyncio queue documentation example (gist by Yury Selivanov / `1st1`). Workers are created with `asyncio.create_task()` and run until cancelled.

**Sources:**
- CPython asyncio queue gist: `asyncio.create_task(worker(f'worker-{i}', queue))` — 3-worker pool processes 20 items concurrently [[gist](https://gist.github.com/1st1/f110d5e2ade94e679c4442e9b6d117e1)] [tier: HIGH — official CPython example]
- Python 3 docs — asyncio.Queue: `await queue.get()` blocks until an item is available [[docs.python.org](https://docs.python.org/3/library/asyncio-queue.html)] [tier: HIGH — authoritative]

### 1.2 Tick-Based (Periodic) Drain — Mechanism and Fit

A periodic drain couples the queue consumer to an existing scheduler/heartbeat. Each tick calls something like:

```python
async def drain_once(queue):
    while not queue.empty():
        item = queue.get_nowait()
        await process(item)
```

This is conceptually similar to asyncio's internal `_run_once()` which "puts a timer on a heap of scheduled things to be checked against event loop 'time' on each single event loop iteration." [[Python AsyncIO Event Loop — Lei Mao](https://leimao.github.io/blog/Python-AsyncIO-Event-Loop/)] [tier: MEDIUM — blog, accurate]

**Temporal's Python SDK** uses exactly this model for workflow execution: *"a Temporal workflow is just a triggered 'loop' that executes all ready tasks until all are yielded and then waits to be triggered again."* The custom `asyncio.AbstractEventLoop` runs single iterations triggered by server events rather than spinning continuously. [[temporal.io](https://temporal.io/blog/durable-distributed-asyncio-event-loop)] [tier: HIGH — vendor engineering blog, well-sourced]

### 1.3 Latency Comparison

**Continuous worker:** Items are processed as soon as they arrive — `await queue.get()` yields immediately when an item is present. Latency is bounded only by event loop scheduling.

**Tick drain:** Maximum latency per item = tick interval. If tick is 100 ms, an item enqueued 1 ms after the last tick waits up to 99 ms.

The nullprogram.com asyncio latency study (Chris Wellons, 2020) demonstrated that heartbeat latency is directly coupled to task scheduling: "The 200 tasks got scheduled ahead of the heartbeat, and so it doesn't get scheduled again until each of those tasks either yields (`await`) or completes." In their test, 200 concurrent tasks caused 1.5 s heartbeat latency. [[nullprogram.com](https://nullprogram.com/blog/2020/05/24/)] [tier: HIGH — empirical benchmark, widely cited]

**Implication for tick drain:** If the tick itself is a task competing with other tasks, the tick interval becomes a *floor*, not a ceiling on latency.

### 1.4 When Tick-Based Drain Is Acceptable

Tick-based drains are acceptable when:

1. **Background automations, not request-path** — items in the queue do not gate any user-visible response. A 100–500 ms drain delay is invisible.
2. **Existing heartbeat already ticks at acceptable frequency** — coupling avoids spawning a new long-lived task and its lifecycle management overhead.
3. **Batch semantics desired** — processing all queued items atomically within a single tick is a feature, not a bug (e.g., coalescing rapid events before acting).

The Medium article on event-driven architecture confirms the contrast: "You don't want to poll every 10 seconds. Instead, *listen* for file system events." The article favors reactive/continuous for latency-sensitive paths and periodic for batch/scheduled work. [[The Pythoneers / Medium](https://medium.com/pythoneers/mastering-pythons-event-driven-architecture-building-asynchronous-systems-without-going-insane-5768b6a8cf3d)] [tier: MEDIUM — Medium engineering post]

---

## 2. asyncio Background Task Patterns in Python

### 2.1 Long-Lived Consumer Task — Lifecycle

```python
task = asyncio.create_task(worker(queue))
# ... later, on shutdown:
task.cancel()
try:
    await task
except asyncio.CancelledError:
    pass  # expected
```

Key patterns from the roguelynn.com graceful-shutdown article:

- Use **signal handlers** to trigger shutdown: `loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s, loop)))`
- Collect and cancel all tasks: `[task.cancel() for task in asyncio.all_tasks()]`
- Gather with `return_exceptions=True` to absorb `CancelledError` without masking other exceptions
- Use `try/finally` (not `try/except`) in workers to ensure cleanup propagates cancellation normally

[[roguelynn.com](https://roguelynn.com/words/asyncio-graceful-shutdowns/)] [tier: HIGH — Lynn Root is a core Python contributor]

### 2.2 Task Cancellation Semantics

`task.cancel()` schedules `CancelledError` to be raised at the next `await` point in the coroutine. This means:

- A worker blocked on `await queue.get()` receives `CancelledError` immediately.
- A worker mid-processing (after `get()`, before `task_done()`) receives `CancelledError` at its next `await`.

**Use `try/finally` around the loop body** to mark items done or re-enqueue on cancellation:

```python
async def worker(queue):
    while True:
        item = await queue.get()
        try:
            await process(item)
        finally:
            queue.task_done()
```

[[asyncio cancellation pattern — Rob Blackbourn / Medium](https://rob-blackbourn.medium.com/a-python-asyncio-cancellation-pattern-a808db861b84)] [tier: MEDIUM — Medium engineering post]

### 2.3 Python 3.13 Queue.shutdown()

Python 3.13 adds `asyncio.Queue.shutdown(immediate=False)`:

| Parameter | Behaviour |
|-----------|-----------|
| `immediate=False` | Allows queued items to drain before raising `QueueShutDown` to blocked `get()` callers |
| `immediate=True` | Empties queue immediately, all blocked `get()` callers raise `QueueShutDown` at once |

After `shutdown()`, `put()` and `put_nowait()` raise `QueueShutDown`. This eliminates the sentinel-value pattern.

[[asyncio.Queue.shutdown — runebook.dev](https://runebook.dev/en/docs/python/library/asyncio-queue/asyncio.Queue.shutdown)] [tier: MEDIUM — mirrors official docs] | [[python/asyncio PR #415 — drain proposal history](https://github.com/python/asyncio/pull/415)] [tier: HIGH — primary source, CPython maintainer discussion]

**Historical context:** An earlier `drain()` / `drain_nowait()` / `close()` proposal (PR #415) was rejected by Guido van Rossum as "too complicated" and by Raymond Hettinger as not cleaner than sentinel values. The `shutdown()` method added in 3.13 is the eventual resolution — simpler, covering the main use case. [[github.com/python/asyncio/pull/415](https://github.com/python/asyncio/pull/415)] [tier: HIGH — primary source]

### 2.4 put_nowait — Non-Blocking Emitter Pattern

`put_nowait(item)` enqueues without suspending the caller:

```python
# From CPython source (Lib/asyncio/queues.py):
def put_nowait(self, item):
    if self._is_shutdown: raise QueueShutDown
    if self.full():       raise QueueFull
    self._put(item)
    self._unfinished_tasks += 1
    self._finished.clear()
    self._wakeup_next(self._getters)  # wakes any blocked get() immediately
```

**Critical detail:** `_wakeup_next(self._getters)` immediately schedules the consumer coroutine to resume on the next event loop iteration. This means a continuous worker receives items with minimal latency — effectively one event loop cycle after `put_nowait()`. [[CPython Lib/asyncio/queues.py](https://github.com/python/cpython/blob/main/Lib/asyncio/queues.py)] [tier: HIGH — primary source]

For a tick drain, `put_nowait()` is still safe; the item sits in the deque until the next tick calls `get_nowait()`.

---

## 3. Ordering and Backpressure

### 3.1 FIFO Guarantees with a Single Consumer

`asyncio.Queue` uses `collections.deque` internally: items added with `append()`, removed with `popleft()`. FIFO ordering is guaranteed at the queue level. With a **single consumer**, FIFO delivery is also guaranteed at the processing level — no two consumers can interleave item handling.

[[CPython Lib/asyncio/queues.py — deque usage](https://github.com/python/cpython/blob/main/Lib/asyncio/queues.py)] [tier: HIGH — primary source]

A **tick drain** that calls `get_nowait()` in a loop within a single coroutine also maintains FIFO within that tick batch.

### 3.2 Burst Behavior

**Unbounded queue:** The nullprogram.com study makes a strong empirical claim: *"every unbounded `asyncio.Queue()` is a bug."* Producers can fill memory before consumers run, and adding `asyncio.sleep(0)` yields are fragile workarounds. [[nullprogram.com](https://nullprogram.com/blog/2020/05/24/)] [tier: HIGH]

**Bounded queue with `await put()`:** When `maxsize` is set, `await queue.put(item)` blocks the producer when the queue is full — natural backpressure. The producer's `await put()` suspends until a consumer removes an item. [[tech-champion.com — bounded queues and backpressure](https://tech-champion.com/programming/python-programming/manage-async-i-o-backpressure-using-bounded-queues-and-timeouts/)] [tier: MEDIUM — engineering blog]

**`put_nowait()` + bounded queue:** Raises `QueueFull` immediately rather than blocking. The caller must decide to drop, retry later, or expand capacity. This is the emitter-side pattern when the emitter cannot afford to block.

**Under burst, tick drain risks:**

- Items accumulate between ticks. If the queue is unbounded and bursts are large, memory grows unboundedly until the tick fires.
- If processing one tick's batch takes longer than the tick interval, ticks can "skip" or queue up, compounding the lag.

**Under burst, continuous worker risks:**

- The worker competes with other tasks for event loop time. If the burst consists of many `put_nowait()` calls in a tight loop, the worker may not actually drain items until the producer yields. [tier: derived from nullprogram.com findings]

### 3.3 Drop vs. Block

| Mechanism | Behavior under full queue |
|-----------|--------------------------|
| `await queue.put()` | Blocks producer until space — backpressure propagated upstream |
| `put_nowait()` → catch `QueueFull` → drop | Drops the item; caller controls drop policy |
| `put_nowait()` → catch `QueueFull` → timeout drop | Bounded wait, then drop [[tech-champion.com](https://tech-champion.com/programming/python-programming/manage-async-i-o-backpressure-using-bounded-queues-and-timeouts/)] [tier: MEDIUM] |

For background automation dispatchers (non-blocking emitter): `put_nowait()` with a `QueueFull` handler is the correct choice. The emitter must not await.

---

## 4. Single-Consumer vs. Multi-Consumer Trade-offs

### 4.1 Ordering

**Single consumer:** FIFO processing order guaranteed. No interleaving. Deduplication at the queue level is straightforward — check before enqueue.

**Multi-consumer:** Items leave the queue in FIFO order but are processed concurrently. Two workers can process items out of wall-clock order relative to each other. Deduplication requires cross-worker coordination (e.g., a shared `set` with a lock). The `dataleadsfuture.com` article notes: "have a few cashiers" — each consumer is independent; no consumer sees another's item mid-flight. [[dataleadsfuture.com](https://www.dataleadsfuture.com/unleashing-the-power-of-python-asyncios-queue/)] [tier: MEDIUM]

### 4.2 Resource Use

Multi-consumer scales throughput but each task has a coroutine object cost (small, ~1 KB) plus scheduling overhead. For a dispatcher handling background automations, a single consumer is typically sufficient and eliminates ordering/dedup complexity.

### 4.3 Lost-Update Risk (Inngest Finding)

Inngest's engineering blog identifies a subtle failure mode with state-based (not queue-based) primitives: when state transitions happen within a single event loop tick, consumers using `asyncio.Condition` can "see 'closed', not 'closing'" — intermediate states vanish. Their recommended solution is exactly the per-consumer queue model: buffer `(old, new)` tuples into a queue so no transition is ever lost. [[inngest.com](https://www.inngest.com/blog/no-lost-updates-python-asyncio)] [tier: HIGH — production engineering blog, specific failure mode]

**Implication:** A queue-based drain (continuous or tick) is more robust than a `Condition`/`Event`-based notify-and-poll pattern, precisely because it records transitions rather than just current state.

---

## 5. Coupling a Worker to a Scheduler/Heartbeat vs. Independent Loop

### 5.1 Scheduler-Coupled (Tick Drain)

**Pros:**

- **Lifecycle simplicity:** No extra task to create, cancel, or supervise. Shutdown of the scheduler automatically stops queue draining.
- **Batching semantics:** All items accumulated since the last tick are processed atomically in one call, which can be useful for coalescing or rate-limiting downstream side-effects.
- **Predictable load:** Processing happens at known intervals; easier to reason about throughput and resource usage.
- **Simpler error boundary:** If `drain_once()` throws, the tick handler catches it; no separate task exception to handle.

**Cons:**

- **Latency floor = tick interval.** Items wait up to the full tick interval before processing begins.
- **Tick overrun risk:** If `drain_once()` takes longer than the tick interval, subsequent ticks stack up or items are processed late. Requires guarding against re-entrant calls.
- **Coupling fragility:** If the scheduler is paused, suspended, or delayed (e.g., event loop overload), the drain stalls too. The nullprogram.com study showed heartbeat latency can spike to 1.5 s under load — a tick-coupled drain would spike identically. [[nullprogram.com](https://nullprogram.com/blog/2020/05/24/)] [tier: HIGH]
- **Not reactive:** Items that arrive immediately after a tick wait the full interval.

**The Temporal model** (tick-drain variant) works because Temporal's "ticks" are triggered by external server events (timer completions, activity results), not a fixed wall-clock interval. This makes latency event-driven, not time-driven. [[temporal.io](https://temporal.io/blog/durable-distributed-asyncio-event-loop)] [tier: HIGH]

### 5.2 Independent Long-Lived Task (Continuous Worker)

**Pros:**

- **Minimum latency:** Items processed within one event loop cycle of `put_nowait()` (via `_wakeup_next`). [[CPython queues.py](https://github.com/python/cpython/blob/main/Lib/asyncio/queues.py)] [tier: HIGH]
- **Decoupled lifecycle:** The worker runs independently; the scheduler/heartbeat can pause without affecting queue draining.
- **Standard pattern:** Well-understood by Python async practitioners; easy to test, easy to cancel.
- **Reactive:** `await queue.get()` is a true event-driven wait — no polling, no CPU burn.

**Cons:**

- **Extra task to manage:** Must be created, tracked, and cancelled explicitly on shutdown.
- **Exception handling:** Unhandled exceptions in the worker task are "swallowed" unless the caller `await`s the task or attaches a `done_callback`. Use `task.add_done_callback(handle_exception)`.
- **No batching by default:** Each item is processed as it arrives. Batching requires explicit accumulation logic inside the worker.
- **Lifecycle coupling is the developer's responsibility:** If the host coroutine exits without cancelling the worker, the worker becomes an orphan task (asyncio will log "Task was destroyed but it is pending!").

### 5.3 Hybrid Pattern

A continuous worker can implement tick-like batching by collecting all currently-queued items after `await queue.get()`:

```python
async def worker(queue):
    while True:
        item = await queue.get()          # blocks until at least one item
        batch = [item]
        while not queue.empty():
            batch.append(queue.get_nowait())  # drain remaining without blocking
        await process_batch(batch)
        for _ in batch:
            queue.task_done()
```

This gives reactive wakeup (low latency) with batching semantics, without a fixed tick interval. [tier: derived pattern, consistent with CPython queue API]

---

## 6. Summary Table

| Dimension | Tick Drain (heartbeat-coupled) | Continuous Worker (independent) |
|-----------|-------------------------------|----------------------------------|
| **Latency** | Up to 1 tick interval | ~1 event loop cycle after put_nowait |
| **Simplicity** | Simpler — no extra task | Standard but needs lifecycle management |
| **Shutdown** | Free — scheduler owns lifecycle | Must cancel task explicitly |
| **Batching** | Natural — processes all items per tick | Requires explicit accumulation |
| **Under load** | Tick can be delayed by event loop saturation | Worker competes equally for loop time |
| **Burst behaviour** | Items accumulate between ticks | Worker processes immediately; bounded by queue maxsize |
| **FIFO within batch** | Yes (get_nowait loop in order) | Yes (single consumer) |
| **Coupling risk** | Scheduler pause = drain stalls | Drain runs independently |
| **Background automation fit** | Good — latency tolerance acceptable | Good — but adds complexity |
| **Python version** | Any | Any; shutdown() available 3.13+ |

---

## 7. Sources Index

| Source | Tier | URL |
|--------|------|-----|
| CPython asyncio/queues.py (primary implementation) | HIGH | https://github.com/python/cpython/blob/main/Lib/asyncio/queues.py |
| CPython asyncio queue docs (Python 3 official) | HIGH | https://docs.python.org/3/library/asyncio-queue.html |
| CPython asyncio queue gist — 1st1 (Yury Selivanov) | HIGH | https://gist.github.com/1st1/f110d5e2ade94e679c4442e9b6d117e1 |
| python/asyncio PR #415 — drain proposal, Guido/Hettinger rejection | HIGH | https://github.com/python/asyncio/pull/415 |
| nullprogram.com — Latency in Asynchronous Python (empirical) | HIGH | https://nullprogram.com/blog/2020/05/24/ |
| roguelynn.com — Graceful Shutdowns with asyncio (Lynn Root) | HIGH | https://roguelynn.com/words/asyncio-graceful-shutdowns/ |
| inngest.com — No Lost Updates: asyncio shared state | HIGH | https://www.inngest.com/blog/no-lost-updates-python-asyncio |
| temporal.io — Durable Distributed asyncio Event Loop | HIGH | https://temporal.io/blog/durable-distributed-asyncio-event-loop |
| asyncio.Queue.shutdown — runebook.dev (Python 3.13 docs) | MEDIUM | https://runebook.dev/en/docs/python/library/asyncio-queue/asyncio.Queue.shutdown |
| tech-champion.com — Backpressure bounded queues | MEDIUM | https://tech-champion.com/programming/python-programming/manage-async-i-o-backpressure-using-bounded-queues-and-timeouts/ |
| dataleadsfuture.com — asyncio.Queue consumer patterns | MEDIUM | https://www.dataleadsfuture.com/unleashing-the-power-of-python-asyncios-queue/ |
| rob-blackbourn.medium.com — asyncio cancellation pattern | MEDIUM | https://rob-blackbourn.medium.com/a-python-asyncio-cancellation-pattern-a808db861b84 |
| The Pythoneers / Medium — event-driven architecture asyncio | MEDIUM | https://medium.com/pythoneers/mastering-pythons-event-driven-architecture-building-asynchronous-systems-without-going-insane-5768b6a8cf3d |
| Lei Mao — Python AsyncIO Event Loop | MEDIUM | https://leimao.github.io/blog/Python-AsyncIO-Event-Loop/ |

---

*Research agent: apex-research Phase-2. All claims cite-or-dropped. No recommendation made.*

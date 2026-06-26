# AGENT-inbox — build progress / flags

Built by Codex, host-verified (mypy 276 files clean, 786 passed). Opus cross-model review: CLEAN + 1 FLAG.

## FLAG (review-needed, planning) — deliver-count silent-failure gap
`AskOwnerTool.ask` models the delivery seam as `Deliver = Callable[[list[OutboundMessage]], int]`
and ignores the returned count. The production `NtfyDelivery.__call__` swallows publish exceptions
and returns the number of 2xx publishes (0 on failure) — it does NOT raise. So the spec's
"delivery failure propagates → ask re-raises, row stays pending" FLAG is only honoured when the
injected deliver *raises* (the test's fake does). Wired to the real NtfyDelivery, a silent ntfy
outage returns 0 and `ask(timeout_s=0)` blocks on the waiter.
Mitigations present: owner out-of-band recourse via `pending()`+`resolve()`; any `timeout_s>0`
parks via `asyncio.wait_for`.
ACTION for the composition spec (where AskOwnerTool is wired to the real NtfyDelivery): treat
`count == 0` as a delivery failure (raise / signal so the executor parks rather than blocks).
Faithful to the spec's abstract seam; not a build-blocker.

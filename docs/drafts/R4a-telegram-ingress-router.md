---
spec: R4a-telegram-ingress-router
status: draft
token_profile: lean
autonomy_level: L5
coder_effort: high
---

# Spec: R4a — Telegram ingress → intent router (chat + web-Q)

**Identity:** Add the runner-side inbound loop that consumes `transport.receive()`, classifies each message via `IntentRouter`, executes `plain_ask` + `web_q`, and sends a quarantined reply back out — the first consumer of inbound Telegram.
→ why: see docs/technical/adr/ADR-043-telegram-inbound-and-bless-consent.md (decisions 1, 7, 8)

## Assumptions
- `App.run` (`src/artemis/app.py`) today drives ONLY the scheduler; `transport.receive()` has no consumer, so inbound Telegram is dropped past the allowlist — this spec adds the consumer → impact: Stop
- `IntentRouter.classify` is transport-neutral and already returns `{build, web_q, aggregate, plain_ask}` — reuse as-is, no change → impact: Stop
- The runner builds its own model router (`build_model_router`); it can construct the `IntentRouter` and a `WebTool` (`build_web_tool`) in-process rather than calling the brain over loopback HTTP (avoids a second auth surface). This is the [NEEDS CLARIFICATION resolved: in-process] integration choice → impact: Caution
- The `invoke` branch (route 3) is intentionally NOT wired here — R4b adds it (this spec ships chat + web_q only, so it is independently useful and reviewable). A `build` classification gets a "build on the desktop" reply (ADR-043 decision 1) → impact: Stop
- `aggregate` is treated as `web_q` for now (the aggregation pipeline, ADR-035 #4, is unbuilt) → impact: Low

## Prerequisites
- none (this is the base of the R4 chain). R4b and R4c depend on this.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/ingress.py | create | `InboundRouter`: consume `receive()`, classify, run plain_ask/web_q, send reply |
| src/artemis/app.py | modify | `App` gains an ingress task; `run()` drives scheduler + ingress concurrently; `build_app` wires the `InboundRouter` when a receiving transport is present |
| tests/test_ingress.py | create | unit tests with a fake transport + fake model/web tool |

## Tasks
- [ ] Task 1: Create `InboundRouter` in `src/artemis/ingress.py`. `InboundRouter(intent: IntentRouter, model: ModelPort, web_tool: WebTool, transport: TransportPort, owner_identity: str)`; `async def run()` iterates `async for msg in transport.receive()`; for each: `intent.classify(msg.text)` → dispatch: `plain_ask` → one `model.complete` chat answer; `web_q`/`aggregate` → `web_tool.answer(msg.text)`; `build` → a fixed "I can build capabilities on the desktop — text me a question or ask me to run one instead." reply; each reply sent via `transport.send(OutboundMessage(identity=msg.identity, text=...))`. Exceptions per-message are caught + logged (`ingress_message_degraded reason=%s`) and reply with a safe generic error — one bad message never kills the loop. — files: src/artemis/ingress.py, tests/test_ingress.py — done when: a fake transport yielding one text per route produces the expected reply and the loop survives a raising handler.
- [ ] Task 2: Wire ingress into the runner. In `src/artemis/app.py`: `App` gains an optional `ingress: InboundRouter | None`; `run()` runs the scheduler AND (if ingress present) `ingress.run()` concurrently (`asyncio.gather`, cancel-safe). `build_app` constructs the `InboundRouter` (building `IntentRouter` + `build_web_tool`) only when the transport implements `receive` AND is not the console default — gate on a param `enable_ingress: bool = True`. — files: src/artemis/app.py — done when: `build_app(transport=<receiving>)` returns an `App` whose `run()` drives both loops; console-only path unchanged.
- [ ] Task 3: Tests. `tests/test_ingress.py`: fake transport (async-iterable of `InboundMessage`, records `send`), stub `IntentRouter` (returns a set route), stub model + web tool; assert plain_ask→model text, web_q→web-tool text, build→desktop-notice, and that a handler exception yields the safe error reply and continues. — files: tests/test_ingress.py — done when: all assertions pass, `uv run pytest tests/test_ingress.py -q` green.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/ingress.py, tests/test_ingress.py |
| Modify | src/artemis/app.py |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` · `uv run ruff check src/ tests/` · `uv run pytest -q` | host-verify |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the files above + CHANGELOG.md |
| `git commit` | "feat(ingress): route inbound Telegram to chat + web-Q" |

## Specialist Context
### Security
No new credential/egress flow in R4a (no invoke). Standard: inbound text is untrusted owner input classified by an existing model call; `web_q` output already flows through `WebTool`'s quarantine. The `invoke` branch (the credential-touching one) is deferred to R4b, which carries the dispatched apex-security review.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Added — inbound Telegram routed to chat + web-Q |
| ADR | docs/technical/adr/ADR-043-... | cross-reference |

## Acceptance Criteria
- [ ] Fake transport yields a `plain_ask` message → reply is the model's chat completion text.
- [ ] Fake transport yields a `web_q` message → reply is `web_tool.answer(...)` output.
- [ ] Fake transport yields a `build` message → reply is the fixed "build on the desktop" notice; no capability is authored.
- [ ] A handler that raises on one message → that message gets a safe generic error reply AND the loop continues to the next message.
- [ ] `build_app(transport=console)` unchanged (no ingress); `App.run()` drives scheduler + ingress when a receiving transport is wired.
- [ ] `uv run mypy` / `ruff` clean; `uv run pytest -q` green.

## Progress
_(Coding mode writes here — do not edit manually)_

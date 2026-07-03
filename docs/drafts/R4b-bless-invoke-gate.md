---
spec: R4b-bless-invoke-gate
status: draft
autonomy_level: L5
coder_effort: high
cross_model_review: true
---

# Spec: R4b — bless consent + Telegram invoke gate

**Identity:** Add the version-scoped bless store, the Telegram invoke gate (blessed → run; un-blessed → inline-button confirm), `callback_query` handling, and the `/blessed` revoke command — reusing the existing invoke + quarantine path.
→ why: see docs/technical/adr/ADR-043-telegram-inbound-and-bless-consent.md (decisions 2–8)

## Assumptions
- The invoke path (`invoke.build_invoke_proposal` → `invoke.confirm_invoke`: secret resolve → `FetchSandbox.run` → `_quarantine_output`) is REUSED, not reimplemented — the gate only decides *whether/when* to confirm and routes the confirm through Telegram → impact: Stop
- Bless keys to `(capability_name, Skill.version)`; because `promote` bumps `version`, an update auto-invalidates the old bless (version-scoped, ADR-043 decision 6) — no explicit reset logic needed beyond matching on version → impact: Stop
- Bless state is a shared JSON store under `ARTEMIS_DATA_DIR` (mirrors `LayoutStore`) so the brain process (desktop routes, R4c) and the runner process (this gate) see the same state; the gate reads fresh at decision time → impact: Stop
- `TelegramTransport` is text-only today; inline-keyboard send + `callback_query` receive are NEW (this spec adds them to `telegram.py`) → impact: Stop
- The confirm message NEVER includes secret VALUES — only secret NAMES + egress domains (the existing quarantine/no-secret-in-output invariants hold) → impact: Stop

## Prerequisites
- `R4a-telegram-ingress-router` (this spec adds the `invoke` branch into `ingress.py`, which R4a creates — hard dependency; NOT file-disjoint from R4a, so build strictly after it).
- No file overlap with `verify-auth-unverified-mark` (that spec touches store.py/types.py/skill_md.py/capability_routes.py/invoke.py; this spec touches bless.py[new]/telegram.py/ingress.py and does NOT edit invoke.py — it imports it).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/bless.py | create | `BlessStore`: JSON-backed, `is_blessed(name, version)`, `bless(name, version)`, `unbless(name)`, `list_blessed()`; atomic writes |
| src/artemis/transport/telegram.py | modify | inline-keyboard send (`send_prompt` with buttons) + `callback_query` in `receive()` (yield a typed callback event); answer callback |
| src/artemis/ingress.py | modify | `invoke` branch: selector → proposal → blessed? auto-`confirm_invoke` : send button-card; handle callback (Run once / Always allow / Cancel); `/blessed` command → list + unbless |
| tests/capabilities/test_bless.py | create | version-scoping + revoke |
| tests/test_ingress_invoke.py | create | gate behavior (blessed auto-run, unblessed confirm, callback → run/bless/cancel) |
| tests/transport/test_telegram_callbacks.py | create | inline-keyboard payload + callback_query parse |

## Tasks
- [ ] Task 1: `BlessStore` (`src/artemis/capabilities/bless.py`). JSON file `{ "<name>": <version:int> }`. `is_blessed(name, version)` = stored version == version; `bless(name, version)` writes; `unbless(name)` deletes; `list_blessed()` returns `[(name, version)]`. Atomic write (temp + replace), mirror `LayoutStore`. — files: src/artemis/capabilities/bless.py, tests/capabilities/test_bless.py — done when: a bless at v2 is NOT blessed after the stored entry is v1 (version-scope), unbless removes it, list reflects both.
- [ ] Task 2: Telegram inline-keyboard + callback plumbing (`src/artemis/transport/telegram.py`). Add `send_prompt(identity, text, buttons)` posting `reply_markup.inline_keyboard`; extend `receive()` to also surface `callback_query` updates as a typed inbound event (e.g. `InboundCallback(identity, data, callback_id)`), still allowlist-gated; add `answer_callback(callback_id)` (Bot API `answerCallbackQuery`) so the client stops the spinner. Keep text messages working unchanged. — files: src/artemis/transport/telegram.py, tests/transport/test_telegram_callbacks.py — done when: `send_prompt` emits the correct inline_keyboard JSON and a `callback_query` update parses to an allowlisted `InboundCallback`.
- [ ] Task 3: Invoke gate in `ingress.py`. On route `invoke`: run the capability selector → if a confident match, `build_invoke_proposal`; read `BlessStore.is_blessed(name, version)`; **blessed** → `confirm_invoke(...)` immediately, reply the quarantined output; **un-blessed** → `send_prompt` with the consent body (capability + description + `egress_domains` + secret NAMES + inputs) and buttons `[Run once]`/`[Always allow]`/`[Cancel]` carrying the `invoke_id`. Handle the callback: `Run once` → `confirm_invoke`; `Always allow` → `BlessStore.bless(name, version)` then `confirm_invoke`; `Cancel` → drop the proposal. Missing-secret → reply "add the key on the desktop" (deep-link text), do not run. — files: src/artemis/ingress.py, tests/test_ingress_invoke.py — done when: blessed capability auto-runs; un-blessed sends the button-card and does NOT run until a callback; Always-allow persists a bless and runs.
- [ ] Task 4: `/blessed` revoke command in `ingress.py`. A message `/blessed` → reply the `list_blessed()` names as tap-to-unbless buttons; the callback unblesses and confirms. — files: src/artemis/ingress.py, tests/test_ingress_invoke.py — done when: `/blessed` lists blessed capabilities and a tap removes one from the store.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3] | Wave 3: [Task 4]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/capabilities/bless.py, tests/capabilities/test_bless.py, tests/test_ingress_invoke.py, tests/transport/test_telegram_callbacks.py |
| Modify | src/artemis/transport/telegram.py, src/artemis/ingress.py |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` · `uv run ruff check src/ tests/` · `uv run pytest -q` | host-verify |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the files above + CHANGELOG.md |
| `git commit` | "feat(ingress): bless-gated Telegram capability invoke + /blessed" |

### Network
| Action | Purpose |
|--------|---------|
| (none) | reuses the existing Telegram Bot API client; no new packages |

## Specialist Context
### Security
**BLOCKER: dispatched apex-security review pending — do NOT mark this spec `ready` until it runs.** `cross_model_review: true` is set (bless is a standing authorization). Review focus: (a) bless is genuinely version-scoped (a rebuilt capability cannot inherit a stale grant); (b) the confirm message never leaks secret VALUES (names + egress only); (c) callback data is integrity-checked/allowlisted so a forged/replayed `callback_query` cannot run or bless a capability the owner didn't approve (the `invoke_id` must be server-minted, single-use, owner-chat-bound — reuse the invoke path's pop-first-claim at-most-once); (d) the shared on-disk bless store is read-fresh at gate time and written atomically (no TOCTOU between two processes); (e) an un-blessed invoke NEVER auto-runs (fail-closed to confirm). Reuses ADR-009/037 quarantine + the invoke path's secret handling unchanged.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Added — bless-gated Telegram invoke + /blessed revoke |
| ADR | docs/technical/adr/ADR-043-... | cross-reference |

## Acceptance Criteria
- [ ] `BlessStore` blessed at `(gmail-reader, 2)` → `is_blessed("gmail-reader", 2)` true, `is_blessed("gmail-reader", 3)` false (version-scope); `unbless` removes it.
- [ ] Un-blessed invoke over Telegram → a `send_prompt` with egress domains + secret NAMES (never values) + `[Run once]/[Always allow]/[Cancel]`; the capability does NOT run before a callback.
- [ ] `[Run once]` callback → runs via `confirm_invoke`, replies quarantined output, no bless written.
- [ ] `[Always allow]` callback → writes a bless at the current version AND runs.
- [ ] A second forged/replayed callback for the same `invoke_id` does not run again (at-most-once).
- [ ] `/blessed` → lists blessed capabilities as unbless buttons; a tap removes one.
- [ ] A blessed capability texted again → runs with NO confirm prompt.
- [ ] `uv run mypy` / `ruff` clean; `uv run pytest -q` green.

## Progress
_(Coding mode writes here — do not edit manually)_

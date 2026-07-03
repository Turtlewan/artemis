---
spec: R4b-bless-invoke-gate
status: ready
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
- [ ] Task 1: `BlessStore` (`src/artemis/capabilities/bless.py`). JSON file `{ "<name>": <version:int> }`. `is_blessed(name, version)` = stored version == version; `bless(name, version)` writes; `unbless(name)` deletes; `list_blessed()` returns `[(name, version)]`. Atomic write (temp + replace), mirror `LayoutStore`. **FAIL-CLOSED reads (apex-security BLOCK 2):** `is_blessed`/`list_blessed` catch ANY read error (missing file, permission error, torn/partial write, invalid JSON) and treat it as NOT blessed — `is_blessed` returns `False`, `list_blessed` returns `[]` — never raise out of the store and never default to a permissive/blessed state. **FRESH reads (apex-security FLAG 3):** `is_blessed`/`list_blessed` re-read the file from disk on EVERY call — no persistent in-process cache — so a bless/revoke written by the other process (desktop routes / R4c) or by `/blessed` takes effect immediately. — files: src/artemis/capabilities/bless.py, tests/capabilities/test_bless.py — done when: a bless at v2 is NOT blessed after the stored entry is v1 (version-scope); unbless removes it; list reflects both; **a corrupt/unreadable `bless.json` makes `is_blessed` return `False` (not raise, not True); and a revoke written to disk is visible to the very next `is_blessed` call (no cache).**
- [ ] Task 2: Telegram inline-keyboard + callback plumbing (`src/artemis/transport/telegram.py`). Add `send_prompt(identity, text, buttons)` posting `reply_markup.inline_keyboard`; extend `receive()` to also surface `callback_query` updates as a typed inbound event (e.g. `InboundCallback(identity, data, callback_id)`); add `answer_callback(callback_id)` (Bot API `answerCallbackQuery`) so the client stops the spinner. Keep text messages working unchanged. **Callback allowlist (apex-security FLAG 2):** gate `callback_query` on `callback_query.message.chat.id` against `allowed_chat_ids` — the SAME field + strength as the existing text-path check (`message.chat.id`) — and drop any callback whose chat id is not allowlisted before it reaches the gate. (Document that `callback_query.from.id` is the tapping user and `message.chat.id` is the chat; we gate on the chat id to match the text path.) **Consent-card rendering (apex-security note):** send the confirm card as PLAIN text with NO `parse_mode` (or escape for the chosen mode) so egress domains / secret names / inputs always render literally and can't be visually hidden by formatting-significant characters. — files: src/artemis/transport/telegram.py, tests/transport/test_telegram_callbacks.py — done when: `send_prompt` emits the correct inline_keyboard JSON; a `callback_query` from an allowlisted chat parses to an `InboundCallback`; a `callback_query` from a non-allowlisted chat is dropped.
- [ ] Task 3: Invoke gate in `ingress.py`. On route `invoke`: run the capability selector → if a confident match, `build_invoke_proposal`; capture the **shown skill `version`** alongside the held proposal (keyed by the server-minted, single-use, owner-chat-bound `invoke_id`); read `BlessStore.is_blessed(name, version)`; **blessed** → `confirm_invoke(...)` immediately, reply the quarantined output; **un-blessed** → `send_prompt` with the consent body (capability + description + `egress_domains` + secret NAMES + inputs) and buttons `[Run once]`/`[Always allow]`/`[Cancel]` carrying the `invoke_id`.
  **Callback handling — atomic pop-first-claim (apex-security FLAG 1):** the handler must ATOMICALLY pop the held proposal for `invoke_id` from the in-memory store BEFORE doing anything else (mirror `ask_routes.py`'s `invokes.pop(invoke_id, None)`); a second/forged/replayed callback for the same `invoke_id` finds nothing and is a guaranteed no-op (at-most-once). Then:
  **Stale-version re-check (apex-security BLOCK 1):** before running, re-read the capability's CURRENT `version` and compare to the shown version captured at card time. On MISMATCH → do NOT run and do NOT bless; reply "this capability changed since you were asked — here's a fresh confirmation" and re-send a fresh consent card for the current version. On match: `Run once` → `confirm_invoke`; `Always allow` → `confirm_invoke` first, then on a successful run `BlessStore.bless(name, current_version)` (bless only a run that actually succeeded); `Cancel` → already popped, done.
  **Generic, non-leaking replies (apex-security FLAG 4):** map `confirm_invoke` outcomes to safe owner-facing text — `missing_secrets` → "add the key on the desktop" (deep-link text, do not run); `not_found` → "that capability is no longer available"; `error`/sandbox exception → "that capability couldn't be run — check the desktop for details". NEVER echo an exception message, stack trace, secret value, or raw capability output into the Telegram reply (only the quarantined output on success). — files: src/artemis/ingress.py, tests/test_ingress_invoke.py — done when: blessed capability auto-runs; un-blessed sends the button-card and does NOT run until a callback; a callback for a rebuilt/version-changed capability re-cards instead of running; a replayed callback is a no-op; Always-allow persists a bless only after a successful run; error/not_found replies carry no internal detail.
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
**Dispatched apex-security review DONE (2026-07-03) — 2 BLOCKs + 4 FLAGs, all folded into the Tasks/Acceptance Criteria above.** `cross_model_review: true` (bless is a standing authorization). Resolved:
- **BLOCK 1 (stale-version execution):** the async confirm can sit until the invoke TTL; a rebuild in that window would run new code against the old card. FIXED — Task 3 captures the shown version and re-checks it at callback; mismatch → re-card, no run/bless.
- **BLOCK 2 (bless-store read error):** FIXED — Task 1 `is_blessed`/`list_blessed` fail closed (missing/corrupt/unreadable ⇒ not-blessed, never raise, never permissive).
- **FLAG 1 (pop-first-claim):** FIXED — Task 3 atomically pops the proposal before executing (at-most-once vs redelivery/double-tap/replay).
- **FLAG 2 (callback allowlist field):** FIXED — Task 2 gates `callback_query.message.chat.id` against `allowed_chat_ids`, matching the text path.
- **FLAG 3 (fresh read for immediate revoke):** FIXED — Task 1 re-reads from disk every call, no cache.
- **FLAG 4 (generic error replies):** FIXED — Task 3 maps not_found/error to safe text; never leaks exceptions/secrets/raw output.

**At build time, a dual-pass apex-security wave review runs on the changed `bless.py`/`ingress.py`/`telegram.py` (the code, not the spec) before commit** — the filenames don't match the mechanical wave-review triggers, so the host dispatches it explicitly (as done for the chrome-sandbox isolate change). Standing invariants: reuses ADR-009/037 quarantine + the invoke path's secret handling unchanged; confirm card carries secret NAMES + egress only, never values; un-blessed invoke fail-closes to confirm.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Added — bless-gated Telegram invoke + /blessed revoke |
| ADR | docs/technical/adr/ADR-043-... | cross-reference |

## Acceptance Criteria
- [ ] `BlessStore` blessed at `(gmail-reader, 2)` → `is_blessed("gmail-reader", 2)` true, `is_blessed("gmail-reader", 3)` false (version-scope); `unbless` removes it.
- [ ] **Fail-closed (BLOCK 2):** a corrupt/unreadable/missing `bless.json` → `is_blessed(...)` returns `False` (does not raise, never `True`); `list_blessed()` returns `[]`.
- [ ] **Fresh-read (FLAG 3):** an `unbless` written to disk is reflected by the very next `is_blessed` call in the same process (no cache).
- [ ] Un-blessed invoke over Telegram → a `send_prompt` with egress domains + secret NAMES (never values) + `[Run once]/[Always allow]/[Cancel]`; the capability does NOT run before a callback.
- [ ] `[Run once]` callback → runs via `confirm_invoke`, replies quarantined output, no bless written.
- [ ] `[Always allow]` callback → runs, and writes a bless at the current version ONLY after the run succeeds.
- [ ] **Stale-version (BLOCK 1):** a callback whose captured shown-version ≠ the capability's current version does NOT run and does NOT bless — it re-sends a fresh consent card for the current version.
- [ ] **At-most-once (FLAG 1):** a second/forged/replayed callback for the same `invoke_id` finds the proposal already popped and is a no-op (no second run, no bless).
- [ ] **Callback allowlist (FLAG 2):** a `callback_query` from a non-allowlisted chat id is dropped before the gate.
- [ ] **No-leak (FLAG 4):** `not_found`/`error` outcomes reply generic text with no exception message, stack trace, secret value, or raw capability output.
- [ ] `/blessed` → lists blessed capabilities as unbless buttons; a tap removes one.
- [ ] A blessed capability texted again → runs with NO confirm prompt.
- [ ] `uv run mypy` / `ruff` clean; `uv run pytest -q` green.

## Progress
_(Coding mode writes here — do not edit manually)_

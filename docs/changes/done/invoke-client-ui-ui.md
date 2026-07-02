---
spec: invoke-client-ui-ui
status: done
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: medium
---

# Spec: Invoke confirm — askStore state machine + AskPopup confirm card (CLIENT side, layer 2/2)

**Identity:** Extends `askStore`'s intent→propose→gate→build state machine with an
invoke_confirm/invoke_clarify branch, and adds the Ask-popup confirm card (mirroring the existing
build `PlanCard`) with Run/Cancel and a missing-secrets → keys-panel deep-link. Second of two client
specs for the capability invoke/reuse path (#5b of 5); depends on `invoke-client-ui-gateway` (layer 1)
for `gateway.invokeConfirm` and the extended `AskResponse` DTO.
→ why: see docs/technical/adr/ADR-039-capability-invoke-reuse.md decisions 1, 2, 5, 6.

## Assumptions
- **[Load-bearing — flagged for confirmation before build]** The brain's `invoke_confirm`/
  `invoke_clarify` structured fields (`invoke_id`, `capability`, `egress_domains`, `secrets`, `args`,
  `missing`) are returned ONLY by the non-streaming `POST /app/ask` endpoint. Confirmed by direct read
  of `src/artemis/api/ask_routes.py`'s `ask_stream` handler (lines 215-237): it calls the identical
  `_invoke_or_routed_answer(...)` as `/app/ask`, but only ever yields
  `_sse_event(response.text)` + `"data: [DONE]\n\n"` — the SSE payload carries no `path`/`invoke_id`/
  etc. at all. `client/src-tauri/src/gateway.rs::parse_stream_frame` corroborates this on the client
  side: its own `[DONE]` handling is hardcoded `StreamEvent::Done { path: None, tool_used: None,
  escalated: false }`, with a code comment stating "the non-stream `/app/ask` response remains the
  source for those answer tags until the wire format changes." `askStore.send()` today calls ONLY
  `gateway.askStream()` (the SSE path) for ordinary chat text — `gateway.ask()` (the non-streaming
  wrapper, already fully wired end-to-end: Rust `app_ask` command registered, TS `ask()` export) is
  currently called nowhere in application code (only in `gateway.test.ts`). **Resolution taken by this
  spec:** `askStore.send()` is changed to call `gateway.ask()` (non-streaming) instead of
  `gateway.askStream()` for its single request, branching on `response.path`. This is a one-shot
  Promise either way today — the brain's `_answer()`/`ask_stream` implementation is not real token
  streaming; it computes the full answer once and sends it as one SSE chunk — so this is not a UX
  regression for plain-text answers, and it fixes a latent bug where `path`/`tool_used`/`escalated`
  were always lost over SSE (engine tag silently stuck on `"local"`). **Alternative considered and
  rejected:** keep `askStream()` untouched and add a SEPARATE non-streaming `gateway.ask()` pre-check
  call before every send — this avoids touching existing streaming tests but permanently DOUBLES the
  brain-side cost/latency of every single chat message (the selector-first step plus, for `plain_ask`/
  `web_q`, a real model or Tavily call, run twice). Rejected as a standing performance/cost tax → impact:
  **Stop** — confirm this transport-switch direction before merging; if wrong, `askStore.send()`'s
  entire body (Task 1) needs a different shape.
- This transport switch makes `gateway.askStream()` (TS), `gateway::ask_stream`/`app_ask_stream`
  (Rust), and the `AskSnapshot.streaming` field's producer (the `update({ streaming: ... })` calls
  inside `send()`) unused BY THIS CALL SITE. Per surgical-scope discipline this spec does **not**
  delete them — `askVoice`/`app_ask_voice` still uses the same `streamCommand`/`StreamEvent` Rust
  types independently, and ripping out a whole Tauri command + its route is a bigger, separate cleanup
  decision. `AskPopup.tsx`'s `snapshot.streaming` read (line ~437) is left in place; it simply never
  receives a non-empty value from the text-send path after this change (voice does not populate it
  either, today) → impact: Caution (dead code left in place, flagged not fixed; a follow-up cleanup
  spec should decide whether to remove `app_ask_stream`/`askStream`/the `streaming` field, or keep
  them for a future real-streaming upgrade).
- Unlike the build `PlanCard` (which carries `missing_secrets` computed at PROPOSE time by the brain),
  the invoke confirm payload has NO pre-known missing-secrets list — `AskResponse`'s `invoke_confirm`
  branch only ever sets `secrets` (declared names). The missing-key guard runs at CONFIRM (Run) time
  server-side (`InvokeConfirmResponse.status == "missing_secrets"`), confirmed by
  `src/artemis/api/ask_routes.py` lines 169-178 vs. `confirm_invoke`'s guard. So the confirm card's
  `missingSecrets` starts empty and is populated only after a failed Run — this spec updates the SAME
  card in place (not a separate post-hoc "pending credentials" card like the build flow's
  `pendingCredentialPlans`, since there is exactly one card per invoke and the locked flow says "keep
  the card so the owner can re-Run") → impact: Low.
- `openKeys(secretName)` (client/src/settings/keysStore.ts) takes an optional `pendingKey` string and
  opens the keys panel — reused as-is, no changes needed there → impact: Low.

Simplicity check: considered keeping `askStream()` for the general chat path and adding invoke
detection as a bolt-on secondary call — rejected above (double brain cost). Considered giving the
invoke confirm card its own `AskMessage` subtype file — rejected; `AskMessage`'s existing
discriminated-by-`kind` shape (`plan`/`status`/`result`/`installed`) already accommodates one more
`kind: "invoke_confirm"` with an `invoke?: AskInvokeConfirm` field, no new abstraction needed.

## Prerequisites
- Specs that must be complete first: `invoke-client-ui-gateway` (provides `gateway.invokeConfirm` and
  the extended `AskResponse`/`InvokeConfirmResponse` DTOs this spec imports).
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| client/src/ask/askStore.ts | modify | `AskInvokeConfirm` type, `invoke_confirm` message kind, `send()` rewired to `gateway.ask()`, new `confirmInvoke`/`cancelInvoke` methods |
| client/src/ask/AskPopup.tsx | modify | invoke confirm card (mirrors plan card), Run/Cancel buttons, missing-secrets Add-key deep-link |
| client/src/ask/askStore.test.ts | modify | update streaming tests to mock `gateway.ask`; add invoke_confirm/invoke_clarify/confirmInvoke/cancelInvoke tests |
| client/src/ask/AskPopup.test.tsx | modify | render + interaction tests for the confirm card |

## Tasks
- [ ] Task 1: askStore state machine — files: client/src/ask/askStore.ts — done when: (a) new
  exported type `export interface AskInvokeConfirm { invokeId: string; capability: string;
  egressDomains: string[]; secrets: string[]; args: Record<string, unknown>; missingSecrets: string[]; }`;
  (b) `AskMessageKind` gains `"invoke_confirm"`; `AskMessage` gains `invoke?: AskInvokeConfirm`; (c)
  `send()` is rewired per the Assumptions resolution: replaces the `gateway.askStream(...)` loop with
  `const response = await gateway.ask({ text: trimmed, speak: !snapshot.muted });` inside the existing
  try/catch (vault-locked handling unchanged, catching the same error shape); (d) if
  `response.path === "invoke_confirm"` and `response.invoke_id !== undefined`: appends one assistant
  message with `kind: "invoke_confirm"`, `text: ""`, and `invoke: { invokeId: response.invoke_id,
  capability: response.capability ?? "", egressDomains: response.egress_domains ?? [], secrets:
  response.secrets ?? [], args: response.args ?? {}, missingSecrets: [] }`, then returns (no
  `askStream` call, no plain-text message); (e) if `response.path === "invoke_clarify"`: appends one
  assistant message with `text: response.text` (kind left `undefined`/plain), then returns; (f)
  otherwise: appends one assistant message with `text: response.text`, `engine:
  deriveEngine(response.path, response.escalated)`, `path: response.path`, `tool:
  response.tool_used ?? undefined`, calls `markEngine(engine)` and `publishPolite(response.text,
  true)` — this replaces the previous per-chunk `appendTextToMessage`/`replaceMessage` streaming
  dance with a single `appendMessage` call (no placeholder assistant message is created before the
  await); (g) `update({ sending: true, ... })` before the call and `update({ sending: false })` in a
  `finally`, matching the existing try/finally shape; (h) new method `async confirmInvoke(messageId:
  string): Promise<void>`: finds the message by id, returns silently if not found or
  `message.invoke === undefined`; sets `sending: true`; calls `const result = await
  gateway.invokeConfirm(message.invoke.invokeId)`; on `result.status === "ok"` replaces the message
  with `{ id: messageId, role: "assistant", text: result.text ?? "" }` (plain text, card gone); on
  `"missing_secrets"` replaces the message keeping `kind: "invoke_confirm"` with `invoke: {
  ...message.invoke, missingSecrets: result.missing_secrets }` (card stays, Run/Cancel stay usable);
  on `"not_found"` replaces the message with a plain assistant text `"That request has expired — ask
  again."`; on `"error"` replaces the message with a plain assistant text `"Something went wrong
  running that."`; sets `sending: false` in a `finally`; (i) new method `cancelInvoke(messageId:
  string): void` — identical shape to the existing `cancelBuild`: filters the message out of
  `snapshot.messages` (no `buildMode` field to clear); (j) `npm run typecheck` (from `client/`) is
  clean.
- [ ] Task 2: AskPopup confirm card — files: client/src/ask/AskPopup.tsx — done when: (a) in the
  `messages.map` render loop, a new branch `if (message.kind === "invoke_confirm" && message.invoke
  !== undefined)` renders a `.ask-card` (same classes as the existing plan-card block) with:
  `.ask-card__title` = `message.invoke.capability`; a "Network access" `.ask-card__meta` +
  `.ask-card__list` of `message.invoke.egressDomains` (or "No network access" meta if empty, mirroring
  the plan card's exact conditional); a `.ask-card__meta` listing `message.invoke.secrets` (comma-
  joined names, only rendered if non-empty, mirroring the plan card's secrets line but WITHOUT the
  `(missing)` inline flag — invoke has no pre-known missing set, see Assumptions); a `.ask-card__meta`
  listing extracted args as `key: value` pairs (`Object.entries(message.invoke.args)`, only rendered
  if the object has entries); if `message.invoke.missingSecrets.length > 0`: a `.ask-card__meta`
  "Missing secrets: {joined}" line PLUS one `.ask-cardbtn` "Add key" per missing secret with
  `onClick={() => openKeys(secret)}` (mirrors the existing `pendingCredentialPlans` block's Add-key
  button shape exactly, `aria-label={"Add key " + secret}`); `.ask-card__actions` with two buttons:
  `.ask-cardbtn` "Run" `onClick={() => void askStore.confirmInvoke(message.id)}` `disabled={
  snapshot.sending}`, and `.ask-cardbtn ask-cardbtn--ghost` "Cancel"
  `onClick={() => askStore.cancelInvoke(message.id)}`; (b) `openKeys` import (already present from
  `../settings/keysStore`) is reused, no new import; (c) no changes to the existing plan/status/result/
  pendingCredentialPlans branches; (d) `npm run typecheck` and `npm run lint` (from `client/`) are
  clean.
- [ ] Task 3: askStore tests — files: client/src/ask/askStore.test.ts — done when: (a) the
  `vi.mock("../api/gateway", ...)` hoisted mock adds `ask: vi.fn()` alongside the existing
  `capabilityPropose`/`capabilityBuild`/`capabilityPromote` (keep `askStream` mock present but unused
  by these tests, since it's still imported by the module — or remove it from the mock object if
  `askStore.ts` no longer imports it; check the actual import list after Task 1 and mock exactly what's
  imported); (b) the two existing tests that mocked `askStream` returning multi-chunk generators
  ("streams text into one assistant message and finalizes engine metadata from done", "sends speak
  false after mute is toggled...") are rewritten to mock `mocks.ask.mockResolvedValueOnce({ text:
  "Hello there.", path: "cloud", tool_used: undefined, escalated: false })` (etc.) and assert
  `mocks.ask` was called with `{ text: ..., speak: ... }`, with the same resulting message/engine/
  announcement assertions; (c) "keeps normal non-build messages on askStream" is renamed/rewritten to
  assert `mocks.ask` (not `mocks.capabilityPropose`) was called for a non-build message; (d) new test:
  a `response.path === "invoke_confirm"` result from `mocks.ask` produces one assistant message with
  `kind: "invoke_confirm"` and `invoke.invokeId`/`invoke.capability`/`invoke.missingSecrets` (`[]`)
  matching the response; (e) new test: `response.path === "invoke_clarify"` produces one plain
  assistant message whose `text` equals `response.text` and no `invoke_confirm`-kind message is
  appended; (f) new test: `confirmInvoke` with a fake `gateway.invokeConfirm` resolving
  `{ status: "ok", text: "Ran it.", invoke_id: "inv-1", missing_secrets: [] }` replaces the card
  message with a plain assistant text message `"Ran it."`; (g) new test: `confirmInvoke` resolving
  `{ status: "missing_secrets", missing_secrets: ["TAVILY_API_KEY"], invoke_id: "inv-1", text: null }`
  keeps `kind: "invoke_confirm"` on the same message id and sets
  `invoke.missingSecrets == ["TAVILY_API_KEY"]`; (h) new test: `confirmInvoke` resolving
  `{ status: "not_found", ... }` and separately `{ status: "error", ... }` each replace the card with a
  plain assistant error text message; (i) new test: `cancelInvoke` removes the confirm-card message
  from `snapshot.messages`; (j) `npm run test -- askStore.test.ts` passes (HOST-run — see gateway spec
  note, vitest cannot run in the Codex sandbox).
- [ ] Task 4: AskPopup tests — files: client/src/ask/AskPopup.test.tsx — done when: (a) the hoisted
  `gatewayMocks` object adds `ask: vi.fn()` (mirroring Task 3's askStore mock update; keep/drop
  `askStream` per what `AskPopup`'s transitive import of `askStore` actually needs mocked); (b) new
  test: seeding `askStore` with a `mocks.ask` resolution whose `path === "invoke_confirm"` and
  submitting via the textbox renders a card containing the capability name, egress domain(s), and
  secret name(s); (c) new test: clicking the "Run" button calls the mocked `gateway.invokeConfirm`
  with the message's `invokeId`; (d) new test: with `gateway.invokeConfirm` resolving
  `status: "missing_secrets"`, after clicking Run the card still renders with a "Missing secrets" line
  and an "Add key" button; clicking that button calls `keysMocks.openKeys` with the secret name
  (mirrors the existing pending-credentials "Add key" test); (e) new test: clicking "Cancel" removes
  the card from the thread; (f) `npm run test -- AskPopup.test.tsx` passes (host-run).

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3, Task 4]
<!-- Task 1 (askStore.ts) and Task 2 (AskPopup.tsx) are file-disjoint. Task 3 depends on Task 1's
     store shape; Task 4 depends on Task 2's rendered markup; Tasks 3/4 are file-disjoint from each
     other and can run in parallel in Wave 2. -->

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | client/src/ask/askStore.ts, client/src/ask/AskPopup.tsx, client/src/ask/askStore.test.ts, client/src/ask/AskPopup.test.tsx |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `npm run typecheck` (from client/) | tsc |
| `npm run lint` (from client/) | eslint --max-warnings 0 |
| `npm run test -- askStore.test.ts AskPopup.test.tsx` (from client/) | vitest — **HOST-RUN ONLY**: cannot run inside the Codex sandbox (esbuild `../..` block); the coder runs typecheck/lint in-sandbox, the HOST runs `npm run test` as final verification |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | client/src/ask/askStore.ts client/src/ask/AskPopup.tsx client/src/ask/askStore.test.ts client/src/ask/AskPopup.test.tsx |
| `git commit` | "feat: invoke confirm-card UI — askStore state machine + AskPopup card (invoke-client-ui-ui)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | no new env vars |

### Network
| Action | Purpose |
|--------|---------|
| (none) | all calls go through the mocked `gateway` module in tests; no real network |

## Specialist Context
### Security
- No secret VALUES ever reach this layer — `AskInvokeConfirm.secrets`/`missingSecrets` are names only
  (mirrors `BuildPlanCard.secrets`/`missing_secrets`, unchanged pattern). The session token stays in
  Rust (`gateway.invokeConfirm` → `app_invoke_confirm` → bearer-authed request), never touches the
  webview, mirroring `capabilityPromote`.
- Run is never automatic — `confirmInvoke` only fires on an explicit owner click of "Run"
  (`AskPopup`'s button `onClick`), matching ADR-039 decision 6 and the locked flow's "NEVER auto-run."

### Performance
(none beyond the Assumptions-flagged transport-switch trade-off, already reasoned through above)

### Accessibility
- Run/Cancel/Add-key buttons are real `<button type="button">` elements with visible text or
  `aria-label` (mirrors the existing plan-card and pending-credentials buttons — no new pattern).
- The confirm card's missing-secrets state change (Run → still-a-card-with-a-new-line) is a DOM
  update inside the existing `.ask-thread[aria-label="Conversation"]` region; no new live-region
  needed beyond the existing `politeAnnouncement`/`assertiveAnnouncement` mechanism (this spec does
  not add a new announcement for the invoke card — matches the plan/status/result cards, none of
  which announce beyond the thread itself today).

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Add entry under Unreleased: Ask-popup confirm card for running a promoted capability (invoke/reuse path, client UI complete — ADR-039 all 5 specs shipped) |

## Acceptance Criteria
- [ ] Plain chat messages still work after the transport switch → verify: `npm run test -- askStore.test.ts`
  passes the rewritten streaming-replacement tests (engine tag, announcement, message text all match
  today's behavior, now sourced from `gateway.ask()`).
- [ ] Build-intent messages are unaffected → verify: the existing `isBuildIntent` tests (routes to
  `capabilityPropose`, never calls `gateway.ask`) still pass unmodified.
- [ ] `invoke_confirm` path renders a confirm card, never auto-runs → verify: `AskPopup.test.tsx`'s new
  test asserts the card renders with capability/egress/secrets and that `gateway.invokeConfirm` is
  NOT called until "Run" is clicked.
- [ ] `invoke_clarify` path shows a plain message, no card → verify: `askStore.test.ts`'s new test
  asserts no `kind: "invoke_confirm"` message exists and the plain text matches `response.text`.
- [ ] Run → ok replaces the card with the result text → verify: `askStore.test.ts`/`AskPopup.test.tsx`
  new tests.
- [ ] Run → missing_secrets keeps the card and deep-links to the keys panel → verify:
  `AskPopup.test.tsx`'s new test asserts `openKeys` is called with the missing secret name after
  clicking "Add key", and the card is still present with Run/Cancel.
- [ ] Run → error/not_found shows an error message, no crash → verify: `askStore.test.ts`'s new tests.
- [ ] Cancel removes the card → verify: `askStore.test.ts`/`AskPopup.test.tsx` new tests.
- [ ] Whole-client verification recipe is green → verify: `npm run typecheck`, `npm run lint` clean
  (coder, in-sandbox); `npm run test` clean (host, after handoff).

## Progress
_(Coding mode writes here — do not edit manually)_

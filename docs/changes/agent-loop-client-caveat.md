---
spec: agent-loop-client-caveat
status: ready
token_profile: balanced
autonomy_level: L3
coder_effort: medium
---

# Spec: agent-loop-client-caveat — AL-4c — client carries + renders the loop's verdict / caveat signals

**Identity:** Carry the three optional AL-4a `/app/ask` fields (`verdict`, `verdict_reason`,
`answered_from`) plus the now-set `escalated` bool through the Tauri gateway + TS DTO + Ask store into
the Ask popup, and render a DELIVER + VISIBLE-CAVEAT line under each bot answer bubble. Rendering only —
no brain change, no flag flip.
→ why: docs/technical/adr/ADR-047-agentic-assistant-loop.md (AL-4 arc; AL-4c = client render of AL-4a's DTO fields).

<!-- SCOPE FENCE (ADR-047 arc). AL-4c RENDERS the AL-4a DTO signals on the NON-STREAM Ask path ONLY.
Explicitly EXCLUDED (do NOT build here): any brain-side change (AL-4a owns the contract; consumed as
frozen); stream/voice caveat rendering (the brain's SSE [DONE] carries no verdict metadata today — see
the stream-done decision below; AL-6 changes the wire); the go-live flip of ARTEMIS_AGENT_LOOP (owner
step, gated on the eval cluster); step-trace rendering (AL-6). The loop itself is never touched. -->

## Assumptions
<!-- Format: assumption → impact if wrong (Stop | Caution | Low) -->
- The AL-4a contract (`docs/changes/agent-loop-wiring.md`) adds exactly three optional string fields to
  `AskResponse` — `verdict` ("passed"/"flagged"/"unjudged"|null), `verdict_reason` (str|null),
  `answered_from` ("local_data"/"general_knowledge"|null) — and starts SETTING the pre-existing
  `escalated` bool; loop responses carry `path="loop"`, `tool_used=None`. This is the frozen shape AL-4c
  anchors on → impact: Stop (a wrong field name/semantic renders the wrong caveat or silently drops it).
- `escalated` ALREADY exists on both DTO layers: `client/src-tauri/src/gateway.rs` `AskResponse.escalated:
  bool` (L241) and `client/src/api/dto.ts` `AskResponse.escalated: boolean` (L57). AL-4c only ADDS the
  three new fields; it does not touch `escalated` on the DTO (it newly READS it for the caveat line) →
  impact: Low.
- The serde silent-drop gotcha (memory `tauri-gateway-serde-silent-drop`): a brain JSON field with no
  matching Rust struct field is DROPPED before it reaches the webview. The three new fields MUST be added
  to `gateway.rs::AskResponse` or they never reach TS, no matter what dto.ts declares → impact: Stop.
- serde derive treats a `Option<T>` struct field as implicitly `None` when the key is absent (no
  `#[serde(default)]` needed) — proven by the existing `invoke_id`/`capability`/… `Option` fields, which
  the brain-contract test (`connect_and_ask_use_brain_app_contract`, L1449) deserializes from a body that
  omits them. So the three new `Option<String>` fields need no `#[serde(default)]`; missing → `None` →
  impact: Caution (a wrong attribute would fail deserialization on the common no-loop response).
- Adding three `Option<String>` fields makes serde SERIALIZE three extra `null` keys on every serialized
  `AskResponse`. The ONE Rust exact-JSON assertion — `connect_and_ask_use_brain_app_contract`
  (L1521-1536) — must gain `"verdict": null, "verdict_reason": null, "answered_from": null` or it fails.
  This mirrors AL-4a's Python exact-dict edit on the client side. All other gateway tests assert typed
  fields and are unaffected → impact: Stop (the exact-dict test fails otherwise).
- The Ask popup's PRIMARY text path is NON-STREAM: `askStore.send` → `gateway.ask` (POST `/app/ask`) →
  `AskResponse`, appended as one assistant message (askStore.ts L228-239). The loop's verdict fields
  arrive HERE. The stream/voice paths (`ask_stream`/`ask_voice`) carry only text chunks + a metadata-less
  `[DONE]` (gateway.rs `parse_stream_frame` L874-882 hardcodes `Done{path:None, tool_used:None,
  escalated:false}`), so verdict signals are NOT available on the stream path in AL-4a → impact: Stop
  (drives the stream-done decision: leave `StreamEvent`/`Done` untouched; caveats render only on the
  non-stream response — see Simplicity check).
- `deriveEngine(path, escalated)` (askStore.ts L99-103) maps `escalated===true → "review"`, else any
  non-local/non-direct/non-empty path → "codex", else "local". Path `"loop"` currently falls through to
  "codex" (a silent mislabel). AL-4c makes the loop's engine chip honest (see Simplicity check for the
  chosen mapping) → impact: Caution (leaving it as "codex" is a minor honesty regression AL-4c exists to
  remove; it does not crash).
- The `AskEngine` union is defined in `client/src/ask/EngineTag.tsx` (L1: `"local" | "codex" | "review"`)
  and imported by `askStore.ts` and `ResultRow.tsx`. Screens use a SEPARATE engine type
  (`EngineTagText` in `DomainDetailShell.tsx` L49 takes its own `"local"|"codex"|"review"` literal; the
  `dtos.ts` `EngineTag` type is screens-local). No exhaustive `switch` over `AskEngine` exists (grepped).
  So widening `AskEngine` with `"loop"` is additive and does NOT ripple into screens → impact: Caution
  (a hidden exhaustive switch would break the build; none found).
- `verdict_reason` is judge free text derived from analysis of untrusted ingested content. It MUST be
  rendered as a plain React text node (a `{expression}` child), never via `dangerouslySetInnerHTML` or
  any markdown renderer → impact: Stop (HTML/markdown rendering is a stored-XSS vector; hard rule folded
  from AL-4a's security review).

Simplicity check:
- **Split-or-not → ONE spec.** Non-test files = 5 (`gateway.rs`, `dto.ts`, `askStore.ts`,
  `EngineTag.tsx`, `AskPopup.tsx`) — over the ≤3/justified-4 line. Kept as ONE spec because the five are
  a single thin vertical slice with no logical phase boundary: Rust DTO → TS DTO → store model+engine →
  engine label → render. Two of the five are trivial type-declaration touches (`EngineTag.tsx` = a
  one-line union widening; `dto.ts` = three optional fields). Splitting into AL-4c-data / AL-4c-render
  would (a) leave a store carrying fields nothing renders (dead intermediate state), and (b) force the
  render spec to re-establish the same field contract — coordination cost with no risk reduction. The
  build is still waved (Rust vs TS-DTO are file-disjoint; render depends on the DTO/store).
- **Engine-chip mapping for `path="loop"` → its own `"loop"` label** (frozen decision #4's preferred
  example). Chosen over reusing "codex": AL-4c's whole purpose is honest provenance, and the loop's
  driver is not guaranteed to be codex-family, so a "codex" chip would be a silent mislabel. The
  `escalated===true → "review"` precedence is LEFT INTACT (surgical): an escalated loop shows the
  "review" chip + the "retried under a stronger model" caveat; a non-escalated loop shows "loop". The
  widening costs one line in `EngineTag.tsx` plus additive `loop` keys in `AskEngineStatus` /
  `initialSnapshot` so `markEngine("loop")` type-checks — all trivial. (Reviewer may override to the
  no-widening "leave as codex" treatment; stated as a decision, not a blocker.)
- Baseline CSS only — two new classes pinned to the Ask popup's existing pinned palette (`--a` accent
  for the warn caveat, `--muted` for subtle notes). Owner refines visuals in the later UI-overhaul
  session.

## Prerequisites
- **AL-4a (`agent-loop-wiring`)** must land first — it defines the `verdict`/`verdict_reason`/
  `answered_from` fields and sets `escalated` and `path="loop"`. AL-4c is a pure consumer of that frozen
  contract. Until AL-4a ships, the fields are always `null` and AL-4c renders exactly today's UI (a safe
  no-op), so AL-4c can be BUILT and MERGED before the flag is ever flipped.
- Client-only; shares no brain files. Environment: none beyond an existing client toolchain
  (`npm`, `cargo`). No new dependencies.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `client/src-tauri/src/gateway.rs` | modify | Add `verdict`/`verdict_reason`/`answered_from` as `Option<String>` to `AskResponse`; update the one exact-JSON test; add a loop-response round-trip test. |
| `client/src/api/dto.ts` | modify | Add the three optional fields to the `AskResponse` TS interface. |
| `client/src/ask/EngineTag.tsx` | modify | Widen `AskEngine` union with `"loop"`. |
| `client/src/ask/askStore.ts` | modify | Add fields to `AskMessage` + `AskEngineStatus`; `deriveEngine` loop branch; carry the fields onto the assistant message in `send`. |
| `client/src/ask/AskPopup.tsx` | modify | Render the caveat/note lines under the bot answer bubble; add two baseline CSS classes. |
| `client/src/ask/askStore.test.ts` | modify | Cases: loop response carries fields; engine=="loop"/"review"; null → undefined. |
| `client/src/ask/AskPopup.test.tsx` | modify | Cases: each caveat renders; passed/all-null render nothing; `verdict_reason` renders as literal text (no HTML injection). |

Non-test files touched: 5 (`gateway.rs`, `dto.ts`, `EngineTag.tsx`, `askStore.ts`, `AskPopup.tsx`) —
over the ≤3 rule; justified as one thin vertical slice with two trivial type-declaration touches (see
Simplicity check). ⚠

## Tasks
- [ ] Task 1: Rust gateway DTO — add the three `Option<String>` fields to `AskResponse`; update the
  exact-JSON assertion; add a loop round-trip test — files: `client/src-tauri/src/gateway.rs` — done
  when: `cargo test` (in `client/src-tauri`) is green including the updated exact-dict test and the new
  loop test; a body carrying `verdict`/`verdict_reason`/`answered_from` deserializes them (not dropped).
- [ ] Task 2: TS DTO + store carry + engine label — add the three optional fields to `dto.ts`
  `AskResponse`; widen `AskEngine` with `"loop"`; add `AskMessage`/`AskEngineStatus` fields,
  `initialSnapshot` `loop:false`, the `deriveEngine` loop branch, and carry the fields onto the assistant
  message in `send` — files: `client/src/api/dto.ts`, `client/src/ask/EngineTag.tsx`,
  `client/src/ask/askStore.ts`, `client/src/ask/askStore.test.ts` — done when: `npm run -w client
  typecheck` + `npm run -w client lint` clean; new askStore vitest cases pass (loop response →
  `engine==="loop"`, non-escalated; `escalated` → `"review"`; fields carried; null → undefined).
- [ ] Task 3: Render caveats in the Ask popup — add the caveat/note JSX under the bot answer bubble and
  two baseline CSS classes; `verdict_reason` as a plain text node only — files:
  `client/src/ask/AskPopup.tsx`, `client/src/ask/AskPopup.test.tsx` — done when: `npm run -w client test`
  passes the new cases (flagged caveat + reason; unjudged+loop note; general_knowledge note; escalated
  note; passed → nothing; all-null → nothing; `verdict_reason` with `<b>`/markdown renders as literal
  text, no element created); `typecheck`/`lint` clean.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]
<!-- Task 1 (Rust, client/src-tauri) and Task 2 (TS, client/src) are file-disjoint — different toolchains,
no shared import. Task 3 renders the fields Task 2 puts on the message model, so it runs after. -->

## Exact changes

### Task 1 — `client/src-tauri/src/gateway.rs` (modify)

**Edit A — three fields on `AskResponse`.** Append after `missing: Option<Vec<String>>,` (L247):

```rust
    // AL-4c: agent-loop verdict/answered_from signals (AL-4a contract). Option<String> so a
    // non-loop response (fields absent) deserializes to None and serializes back as null.
    // Without these fields serde SILENTLY DROPS them before the webview (tauri-gateway-serde-silent-drop).
    verdict: Option<String>,
    verdict_reason: Option<String>,
    answered_from: Option<String>,
```

**Edit B — update the one exact-JSON assertion.** In `connect_and_ask_use_brain_app_contract`, the
expected map (L1523-1535) must include the three new null keys (the mock body at L1503-1508 does NOT send
them, proving missing → None → serialized null):

```rust
        assert_eq!(
            encoded,
            json!({
                "text": "answer",
                "path": "direct",
                "tool_used": null,
                "escalated": false,
                "invoke_id": null,
                "capability": null,
                "egress_domains": null,
                "secrets": null,
                "args": null,
                "missing": null,
                "verdict": null,
                "verdict_reason": null,
                "answered_from": null
            })
        );
```

**Edit C — new loop round-trip test.** Add beside the other gateway tests (mirrors the existing mock
pattern) proving a loop-shaped body carries the fields through (not dropped):

```rust
    #[tokio::test]
    async fn ask_carries_loop_verdict_fields() {
        let server = MockServer::start().await;
        let state = state_with_server(&server);
        state.set_token("session-token".to_string());
        Mock::given(method("POST"))
            .and(path("/app/ask"))
            .and(header("authorization", "Bearer session-token"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "text": "you have lunch at noon",
                "path": "loop",
                "tool_used": null,
                "escalated": true,
                "verdict": "flagged",
                "verdict_reason": "no calendar record matched",
                "answered_from": "general_knowledge"
            })))
            .expect(1)
            .mount(&server)
            .await;

        let response = ask(&state, AskRequest { text: "when is lunch".to_string() })
            .await
            .unwrap();

        assert_eq!(response.path, "loop");
        assert!(response.escalated);
        assert_eq!(response.verdict.as_deref(), Some("flagged"));
        assert_eq!(response.verdict_reason.as_deref(), Some("no calendar record matched"));
        assert_eq!(response.answered_from.as_deref(), Some("general_knowledge"));
    }
```
<!-- NOTE for the coder: `AskResponse` derives Deserialize; the fields are private but the test is in the
same module (`mod tests` under `use super::*`), so field access compiles. -->

### Task 2 — TS DTO + store

**Edit A — `client/src/api/dto.ts` (modify).** Append to the `AskResponse` interface after
`missing?: string[];` (L63):

```ts
  // AL-4c: agent-loop verdict/answered_from signals (AL-4a contract). Null/absent on non-loop paths.
  verdict?: "passed" | "flagged" | "unjudged" | null;
  verdict_reason?: string | null;
  answered_from?: "local_data" | "general_knowledge" | null;
```

**Edit B — `client/src/ask/EngineTag.tsx` (modify).** Widen the union (L1):

```ts
export type AskEngine = "local" | "codex" | "review" | "loop";
```
<!-- Additive; the component renders `{engine}` + `ask-engine-tag--loop` (no CSS needed — text is the
contract). ResultRow imports AskEngine and passes it through unchanged — no ResultRow edit. -->

**Edit C — `client/src/ask/askStore.ts` (modify).**

1. `AskMessage` (after `path?: string;` L37 / `tool?: string;` L38, before `failedLocked`):

```ts
  verdict?: "passed" | "flagged" | "unjudged";
  verdictReason?: string;
  answeredFrom?: "local_data" | "general_knowledge";
  escalated?: boolean;
```

2. `AskEngineStatus` (L42-46) gains a `loop` key so `markEngine("loop")` type-checks:

```ts
export interface AskEngineStatus {
  local: boolean;
  codex: boolean;
  review: boolean;
  loop: boolean;
}
```

3. `initialSnapshot` engineStatus (L68):

```ts
  engineStatus: { local: true, codex: false, review: false, loop: false },
```

4. `deriveEngine` (L99-103) — add the loop branch AFTER the escalated check (escalated precedence kept):

```ts
const deriveEngine = (path?: string, escalated?: boolean): AskEngine => {
  if (escalated === true) return "review";
  if (path === "loop") return "loop";
  if (path !== undefined && path !== "" && path !== "local" && path !== "direct") return "codex";
  return "local";
};
```

5. In `send`, carry the fields onto the finalized assistant message (the append at L230-237):

```ts
      appendMessage({
        id: id(),
        role: "assistant",
        text: response.text,
        engine,
        path: response.path,
        tool: response.tool_used ?? undefined,
        verdict: response.verdict ?? undefined,
        verdictReason: response.verdict_reason ?? undefined,
        answeredFrom: response.answered_from ?? undefined,
        escalated: response.escalated,
      });
```

**Edit D — `client/src/ask/askStore.test.ts` (modify).** Add cases (mirror the existing
`mocks.ask.mockResolvedValueOnce({...})` + `connectionStore.onPaired()/onConnected()` pattern from the
first `send` test at L57):

1. **loop response carries the fields + engine "loop" (non-escalated)** → mock `ask` resolves
   `{ text: "you have lunch", path: "loop", tool_used: null, escalated: false, verdict: "passed",
   verdict_reason: "grounded in calendar", answered_from: "local_data" }`; after `send("when is lunch")`
   the last assistant message has `engine === "loop"`, `verdict === "passed"`,
   `verdictReason === "grounded in calendar"`, `answeredFrom === "local_data"`, `escalated === false`.
2. **escalated loop → engine "review", escalated carried** → same but `escalated: true`,
   `verdict: "unjudged"`, `verdict_reason: ""`, `answered_from: "general_knowledge"`; assert
   `engine === "review"`, `escalated === true`, `answeredFrom === "general_knowledge"`,
   `verdictReason === undefined` (empty string → undefined via `?? undefined`).
3. **non-loop response → all new fields undefined (today's behavior)** → mock resolves a plain
   `{ text: "hi", path: "direct", tool_used: null, escalated: false }` (no new keys); assert the message
   has `verdict === undefined`, `answeredFrom === undefined`, `escalated === false`, `engine === "local"`.

### Task 3 — `client/src/ask/AskPopup.tsx` (modify)

**Edit A — caveat/note lines under the bot answer bubble.** In the final fallthrough bot-text return
(L644-654), add the caveat block after the `.ask-msg__body` div. `verdict_reason` is rendered inside a
`{...}` text child — a plain React text node, NEVER `dangerouslySetInnerHTML`/markdown:

```tsx
                  return (
                    <div
                      key={message.id}
                      className={`ask-msg ${isUser ? "ask-msg--user" : "ask-msg--bot"}`}
                    >
                      <span className="ask-msg__who">{isUser ? "You" : "Artemis"}</span>
                      <div className="ask-msg__body">
                        {message.failedLocked ? "Vault locked." : body}
                      </div>
                      {!isUser && !message.failedLocked && message.verdict === "flagged" ? (
                        <div className="ask-msg__caveat">
                          ⚠ unverified — couldn&apos;t be grounded in your data
                          {message.verdictReason !== undefined && message.verdictReason !== ""
                            ? ` — ${message.verdictReason}`
                            : ""}
                        </div>
                      ) : null}
                      {!isUser &&
                      !message.failedLocked &&
                      message.verdict === "unjudged" &&
                      message.path === "loop" ? (
                        <div className="ask-msg__note">unverified (checker unavailable)</div>
                      ) : null}
                      {!isUser &&
                      !message.failedLocked &&
                      message.answeredFrom === "general_knowledge" ? (
                        <div className="ask-msg__note">
                          answered from general knowledge — not from your data
                        </div>
                      ) : null}
                      {!isUser && !message.failedLocked && message.escalated === true ? (
                        <div className="ask-msg__note">retried under a stronger model</div>
                      ) : null}
                    </div>
                  );
```
<!-- verdict==="passed" → no caveat (frozen decision #1; the optional subtle ✓ is intentionally omitted
to keep it minimal). All fields undefined (non-loop) → none of the branches fire → exactly today's UI. -->

**Edit B — two baseline CSS classes.** Add to the `styles` template string, after `.ask-msg__body`'s
rules (near L168), pinned to the popup's existing palette:

```css
.ask-msg__caveat {
  font-size: 12px;
  color: var(--a);
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.ask-msg__note {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
}
```

**Edit C — `client/src/ask/AskPopup.test.tsx` (modify).** Add render cases. To exercise a specific bot
message, resolve `gatewayMocks.ask` with the shaped `AskResponse` and drive `askStore.send(...)` (the
file already mounts `AskPopup` and mocks the gateway). Cases:

1. **flagged → caveat + reason as literal text** → `ask` resolves `{ text: "…", path: "loop",
   tool_used: null, escalated: false, verdict: "flagged", verdict_reason: "no record matched",
   answered_from: "general_knowledge" }`; after send, the popup contains the text "unverified" and the
   literal substring "no record matched" AND "answered from general knowledge".
2. **XSS guard: `verdict_reason` is plain text** → resolve `verdict_reason:
   "<img src=x onerror=alert(1)>"` with `verdict: "flagged"`; assert the rendered `.ask-msg__caveat`
   `textContent` CONTAINS the literal string `"<img src=x onerror=alert(1)>"` and that
   `container.querySelector("img")` is `null` (no element parsed from the reason).
3. **unjudged + loop → checker-unavailable note** → `verdict: "unjudged", path: "loop"`; assert
   "unverified (checker unavailable)" present.
4. **passed → no caveat** → `verdict: "passed", answered_from: "local_data", escalated: false`; assert
   NEITHER "unverified" NOR "general knowledge" NOR "stronger model" appears.
5. **escalated → stronger-model note** → `escalated: true`; assert "retried under a stronger model".
6. **non-loop / all-null → today's UI unchanged** → resolve a plain `{ text: "hi", path: "direct",
   tool_used: null, escalated: false }`; assert no `.ask-msg__caveat` / `.ask-msg__note` element exists.

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | `client/src-tauri/src/gateway.rs`, `client/src/api/dto.ts`, `client/src/ask/EngineTag.tsx`, `client/src/ask/askStore.ts`, `client/src/ask/AskPopup.tsx`, `client/src/ask/askStore.test.ts`, `client/src/ask/AskPopup.test.tsx`, `CHANGELOG.md` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `npm run -w client typecheck` | TypeScript type check (`tsc --noEmit`). |
| `npm run -w client lint` | ESLint (`--max-warnings 0`). |
| `npm run -w client test` | vitest (`vitest run`) — askStore + AskPopup suites. |
| `cargo test` (run in `client/src-tauri`) | Rust gateway struct/round-trip + exact-dict tests. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the seven client files above + `CHANGELOG.md` |
| `git commit` | "feat(client): render agent-loop verdict/caveat signals in Ask popup (AL-4c)" |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No network. vitest mocks the gateway; `cargo test` uses an in-process `wiremock` MockServer. |

## Specialist Context

### Security
- **Hard rule (folded from AL-4a's security review): `verdict_reason` is untrusted judge free text —
  render as PLAIN TEXT ONLY.** In AskPopup it is a `{message.verdictReason}` text child; NEVER
  `dangerouslySetInnerHTML`, and never passed through a markdown/HTML renderer. Task 3 case 2 is the
  regression test (an `<img onerror>` payload must render as literal characters, produce no `<img>`
  element).
- No new network surface, no secrets, no token handling. The session token stays in Rust (the gateway
  pattern is unchanged). The three new fields are display-only strings.
- The serde silent-drop rule (memory `tauri-gateway-serde-silent-drop`) is honored: the fields are added
  to the Rust struct (Task 1) as the source of truth, not just to dto.ts.
- **Review FLAG (folded, variant analysis):** Task 3 adds a one-time verification step — grep/read
  AskPopup.tsx's full render path and confirm NO brain-sourced field (answer body, tool text, card
  fields) passes through `dangerouslySetInnerHTML` or a markdown/HTML renderer; record the result in
  the build notes. If any case is found, file it as a follow-up — do not fix out-of-scope here.
- **Review note (accepted, cited upstream):** `verdict_reason` length-bounding is owned upstream —
  AL-2's `VerifyJudge.evaluate` caps it at 300 chars at parse time (`_MAX_REASON_CHARS`), so the
  client renders a bounded string; `overflow-wrap` handles display. No client-side truncation added.

### Accessibility
- The caveat/note lines are static text under the answer bubble, inside the existing `Conversation`
  thread region — no new interactive elements, no focus changes.
- **Review BLOCK (folded): announced, not just visible.** The caveat/note nodes MUST land inside the
  popup's existing SR live-region announcement scope. Task 3 gains an explicit test: render a flagged
  loop message and assert the caveat text is within the `aria-live` container (query the live region,
  assert `textContent` includes "unverified"); same assertion style for the general-knowledge note.
  If the thread region is NOT the live region in the as-built, the caveat text must additionally be
  appended to whatever live announcement the popup already emits per message — the test defines done.
- **Review BLOCK (folded → owner-step): manual screen-reader pass.** Automated checks catch a
  minority of SR issues. A manual NVDA pass (Windows dev box) confirming all four caveat/note strings
  + the "loop" chip are announced is a REQUIRED item on the AL-4 go-live checklist (alongside the
  eval gates) — executed by the owner at the live smoke, not by the coder. Recorded in Acceptance
  Criteria as an owner-step checkbox.
- **Review FLAG (folded): contrast floor is a hard requirement NOW, not UI-overhaul polish.** Both
  new classes must meet ≥4.5:1 against the popup's pinned background (`#060c14`) at their 11-12px
  size: `--a` (`#fff0d8`) computes ≈ 17:1 — passes. `--muted` must be COMPUTED by the coder against
  `#060c14`; if it falls below 4.5:1, use `--text` (or bump the color within these two classes only)
  instead of `--muted`. Only spacing/visual styling defers to the UI-overhaul session.
- **Review FLAG (folded): the "loop" chip carries disambiguating context.** Match the existing chips'
  accessible-name convention (verify how `local`/`codex`/`review` are exposed — e.g. an `aria-label`
  of "engine: <value>" or visible label text); the new `loop` value must not be the only bare,
  context-free chip. If the existing chips are bare too, add `aria-label={"engine: " + engine}` to
  the shared EngineTag element (one attribute, applies to all values uniformly).

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `client/src-tauri/src/gateway.rs`, `client/src/api/dto.ts` | One-line comments on the new fields (as written above). |
| Changelog | `CHANGELOG.md` | Add under Unreleased: "Ask popup now renders agent-loop verdict/caveat signals (AL-4c) — an unverified/flagged caveat, an ‘answered from general knowledge’ note, and a ‘retried under a stronger model’ note; verdict_reason rendered as plain text." |
| ADR | (none) | ADR-047 (AL-4 arc) already covers the decision. |

## Acceptance Criteria
- [ ] The three fields reach the webview (serde) → verify: `cargo test -p` (in `client/src-tauri`)
  `ask_carries_loop_verdict_fields` green — a loop body's `verdict`/`verdict_reason`/`answered_from`
  deserialize (not dropped).
- [ ] Non-loop response unchanged on the wire → verify: `connect_and_ask_use_brain_app_contract` green
  with the three null keys added to the expected map.
- [ ] Store carries the fields + honest engine label → verify: `npm run -w client test` — askStore cases
  (loop → `engine==="loop"`; escalated → `"review"`; fields carried; empty reason/absent → undefined).
- [ ] Each caveat renders per the frozen rules → verify: `npm run -w client test` — AskPopup cases
  (flagged+reason; unjudged+loop; general_knowledge; escalated; passed→nothing; non-loop→nothing).
- [ ] `verdict_reason` cannot inject markup → verify: the XSS-guard case (rendered as literal text; no
  `<img>` element created).
- [ ] Caveats are ANNOUNCED, not just visible → verify: the live-region test (flagged message → the
  popup's `aria-live` container's `textContent` includes "unverified"; general-knowledge note likewise).
- [ ] Contrast floor met → verify: build notes record the computed ratios of the two caveat classes'
  colors vs `#060c14`; both ≥ 4.5:1 (swap `--muted` → `--text`/adjusted color if it fails).
- [ ] Variant analysis recorded → verify: build notes state the grep/read result — no brain-sourced
  field in AskPopup's render path uses `dangerouslySetInnerHTML`/markdown rendering.
- [ ] **OWNER STEP (go-live checklist, not build-blocking):** manual NVDA pass — all four caveat/note
  strings + the "loop" chip announced. Executed at the AL-4 live smoke; carried on the eval-gate
  spec's go-live checklist.
- [ ] Stream path untouched → verify: `git diff` shows NO change to `StreamEvent`/`Done`/
  `parse_stream_frame` in `gateway.rs`.
- [ ] Type + lint clean → verify: `npm run -w client typecheck` and `npm run -w client lint` clean.
- [ ] Surgical → verify: `git diff --stat` shows only the seven files above (+ `CHANGELOG.md`).

## Commands to run
```bash
# from repo root
npm run -w client typecheck
npm run -w client lint
npm run -w client test
# from client/src-tauri
cargo test
```

## Progress
_(Coding mode writes here — do not edit manually)_
</content>
</invoke>

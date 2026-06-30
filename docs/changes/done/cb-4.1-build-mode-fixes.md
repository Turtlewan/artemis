---
slice: capability-build
status: ready
coder_effort: low
depends_on: cb-4-build-mode-ui
surface: client (React/TS)
---

# CB-4.1 — Build mode UX fixes (Adjust/Discard + honest success)

**Identity:** Polish fixup for CB-4, from the first live run. Two real bugs: (1) `Adjust`/`Discard` are visual no-ops (`cancelBuild()` only flips the chip; the plan/result card stays), and (2) the promote success message claims *"It's now a node on your map"* — false until CB-5b renders capability nodes, which is why a successful build "felt" like it failed. Client only; no backend change (the build/promote loop works — verified live, `email-extractor-store` built + promoted end-to-end).

**Root cause (verified):** `askStore.cancelBuild()` sets `buildMode: false` only — it never removes the card it was invoked from. And `promoteBuild` hardcodes the map-node claim. Backend is correct; this is purely the Ask-popup feedback layer.

## Files to change

1. `src/ask/askStore.ts` — **modify**: `cancelBuild(messageId)` removes the dismissed card; honest installed message.
2. `src/ask/AskPopup.tsx` — **modify**: pass the card's `message.id` to `cancelBuild`; refocus the input after dismiss.
3. `src/ask/askStore.test.ts` — **modify**: update `cancelBuild` tests + the installed-message assertion.
4. `src/ask/AskPopup.test.tsx` — **modify**: Adjust removes the plan card.

## Exact changes

### 1. `src/ask/askStore.ts`

**a. `cancelBuild`** — take the dismissed card's message id and remove it (so `Adjust`/`Discard` visibly clear the card), then exit build mode:
```ts
  cancelBuild(messageId: string): void {
    update({
      messages: snapshot.messages.filter((message) => message.id !== messageId),
      buildMode: false,
    });
  },
```

**b. Honest installed message** — in `promoteBuild`, drop the map-node claim (CB-5b doesn't exist yet) and confirm clearly with the version:
```ts
        text: `Added "${installed.name}" (v${installed.version}) — built & verified.`,
```
(Replaces the `… It's now a node on your map.` text. `InstalledCard.version` already exists.)

### 2. `src/ask/AskPopup.tsx`

Both dismiss buttons currently call `askStore.cancelBuild()` with no argument — pass the card's `message.id`, and refocus the input so the user can retype:
- Plan card **`Adjust`**: `onClick={() => { askStore.cancelBuild(message.id); inputRef.current?.focus(); }}`
- Result card **`Discard`**: `onClick={() => { askStore.cancelBuild(message.id); inputRef.current?.focus(); }}`

(`inputRef` already exists in the component. If a lint rule objects to a multi-statement arrow, extract a small `const dismiss = (mid: string) => { askStore.cancelBuild(mid); inputRef.current?.focus(); };` near the other handlers and call it.)

### 3. `src/ask/askStore.test.ts`

- Update existing `cancelBuild` usages to pass a message id.
- Add: after a plan card is appended, `cancelBuild(planMessageId)` removes that message from `snapshot.messages` and sets `buildMode: false`.
- Update the `promoteBuild` test to assert the installed message text contains `built & verified` and does **not** contain `map`.

### 4. `src/ask/AskPopup.test.tsx`

- Update the Adjust test: clicking `Adjust` calls `askStore.cancelBuild` with the plan message's id (and, if the test renders from real store state, the plan card is removed from the thread afterward).

## Acceptance criteria

1. `cancelBuild(messageId)` removes that message and clears `buildMode` → askStore test.
2. The installed message reads "built & verified" with the version and makes **no** map-node claim → askStore test.
3. Clicking `Adjust` dismisses the plan card (calls `cancelBuild` with its id) → AskPopup test.
4. Whole client green: `npm run typecheck`, `npm run lint`, `npm run test`.

## Commands to run

```bash
# from client/
npm run typecheck
npm run lint
npm run test
```

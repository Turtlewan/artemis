---
slice: capability-build
status: ready
coder_effort: medium
depends_on: cb-3-client-gateway
surface: client (React/TS)
---

# CB-4 — Visible build mode in the Ask popup

**Identity:** Fourth spec of the capability-build slice — the **visible build mode**. Extends `askStore` with a build state-machine (intent heuristic → propose → plan gate → build → result gate → promote) over CB-3's gateway wrappers, and renders tagged message kinds as cards in `AskPopup` (plan card with `Build it`/`Adjust`, live status line, result card with `Add`/`Discard`) plus a "Building capability" header chip. After this, the owner types a build request in the Ask box and watches Artemis build itself a capability. Depends on CB-3 (`gateway.capabilityPropose/capabilityBuild/capabilityPromote`). No map node (CB-5).

**Design authority (co-editing):** this spec defines **structure + behavior**; CSS here is baseline-functional only (reuse the existing `--p/--a/--text/--muted/--hair` palette vars already in `AskPopup`'s `styles`). The owner does visual refinement (spacing/colour) by hand — do not over-style.

**Defaults locked here (so the build doesn't stall on them):**
- **Intent heuristic** = a conservative regex (imperative build verb near the start + a capability noun). False positives are low-cost (the user gets a plan card they can `Adjust`/dismiss). Model-based intent is a deferred upgrade.
- **Blocked plan** (network/secret capability): the plan card renders the `block_reason` and the `Build it` button is **disabled** (not hidden) — the user sees *why* it can't build yet.
- **No clarify round** (deferred): `propose` runs straight from the goal; `Adjust` = dismiss and retype.

## Files to change

1. `src/ask/askStore.ts` — **modify**: build state (`buildMode`), message `kind` + payloads, intent heuristic, `startBuild`/`confirmBuild`/`promoteBuild`/`cancelBuild`.
2. `src/ask/AskPopup.tsx` — **modify**: render the `plan`/`status`/`result`/`installed` message kinds + their buttons; the header chip.
3. `src/ask/askStore.test.ts` — **modify**: build-flow tests (intent routing, propose→plan, build→result, promote→installed, blocked).
4. `src/ask/AskPopup.test.tsx` — **modify**: plan card renders + buttons wire to the store; chip shows in build mode.

One cohesive UI surface (the Ask popup build flow) → one phase.

## Exact changes

### 1. `src/ask/askStore.ts`

**a. Imports** — add the gateway build types:
```ts
import type { BuildPlanCard } from "../api/dto";
```
(`* as gateway` is already imported; `capabilityPropose/capabilityBuild/capabilityPromote` come from there.)

**b. Message kinds + payloads** — extend `AskMessage`:
```ts
export type AskMessageKind = "text" | "plan" | "status" | "result" | "installed";

export interface AskBuildResult {
  passed: boolean;
  blocked: boolean;
  output: string;
}

export interface AskMessage {
  id: string;
  role: AskRole;
  text: string;
  kind?: AskMessageKind; // undefined = "text"
  plan?: BuildPlanCard; // kind === "plan"
  result?: AskBuildResult; // kind === "result"
  buildId?: string; // plan | status | result — which build the buttons act on
  engine?: AskEngine;
  path?: string;
  tool?: string;
  failedLocked?: boolean;
}
```

**c. Snapshot flag** — add `buildMode: boolean` to `AskSnapshot` and `initialSnapshot()` (`buildMode: false`).

**d. Intent heuristic** (module-level):
```ts
// Conservative build-intent match: an imperative build verb near the start + a capability noun.
// Model-based intent classification is a later upgrade; a false positive only yields a dismissable plan card.
const BUILD_INTENT = /^\s*(?:please\s+)?(?:build|create|make|write)\b.*\b(capabilit(?:y|ies)|module|tool|skill|recipe|util(?:ity)?|function)\b/i;
const isBuildIntent = (text: string): boolean => BUILD_INTENT.test(text);
```

**e. Connection guard helper** — factor the existing check in `send()` so `startBuild` reuses it:
```ts
const isConnected = (): boolean => {
  const state = connectionStore.getSnapshot().state;
  return state === "connectedLocked" || state === "unlocked";
};
```
(Use it in `send()` in place of the inline check; behavior unchanged.)

**f. Route build intent** — at the very top of `send()`, after the empty-trim guard:
```ts
    if (isBuildIntent(trimmed)) {
      await this.startBuild(trimmed);
      return;
    }
```

**g. The build flow methods** — add to the `askStore` object:
```ts
  async startBuild(goal: string): Promise<void> {
    const trimmed = goal.trim();
    if (trimmed === "") return;
    if (!isConnected()) {
      unlockPrompt();
      update({ assertiveAnnouncement: "Not connected - re-authentication required" });
      return;
    }
    appendMessage({ id: id(), role: "user", text: trimmed });
    update({ buildMode: true, sending: true, assertiveAnnouncement: "" });
    try {
      const plan = await gateway.capabilityPropose(trimmed);
      appendMessage({
        id: id(),
        role: "assistant",
        text: "",
        kind: "plan",
        plan,
        buildId: plan.build_id,
      });
    } finally {
      update({ sending: false });
    }
  },

  async confirmBuild(buildId: string): Promise<void> {
    const statusId = id();
    appendMessage({ id: statusId, role: "assistant", text: "Starting…", kind: "status", buildId });
    update({ sending: true });
    let result: AskBuildResult | null = null;
    try {
      for await (const event of gateway.capabilityBuild(buildId)) {
        if (event.type === "build_status") {
          appendTextToMessage(statusId, event.text);
        } else if (event.type === "build_result") {
          result = { passed: event.passed, blocked: event.blocked, output: event.output };
        } else if (event.type === "error") {
          appendTextToMessage(statusId, "Build error.");
        }
      }
      if (result !== null) {
        appendMessage({
          id: id(),
          role: "assistant",
          text: "",
          kind: "result",
          result,
          buildId,
        });
      }
    } finally {
      update({ sending: false });
    }
  },

  async promoteBuild(buildId: string): Promise<void> {
    update({ sending: true });
    try {
      const installed = await gateway.capabilityPromote(buildId);
      appendMessage({
        id: id(),
        role: "assistant",
        text: `Added "${installed.name}". It's now a node on your map.`,
        kind: "installed",
      });
    } finally {
      update({ sending: false, buildMode: false });
    }
  },

  cancelBuild(): void {
    update({ buildMode: false });
  },
```
(Keep `resetForTest` resetting `buildMode` via `initialSnapshot()`.)

### 2. `src/ask/AskPopup.tsx`

**a. Header chip** — when `snapshot.buildMode`, render a chip in the header (before or after `ask-engine`):
```tsx
{snapshot.buildMode ? <span className="ask-chip">Building capability</span> : null}
```

**b. Render message kinds** — in the `messages.map(...)`, branch on `message.kind` before the default text bubble:
- `"plan"`: a card showing `message.plan.name`, `message.plan.summary`, and `secrets` (if any); if `message.plan.blocked`, show `block_reason`. Buttons: `Build it` (`disabled={message.plan.blocked}`, `onClick={() => void askStore.confirmBuild(message.buildId!)}`) and `Adjust` (`onClick={() => askStore.cancelBuild()}`).
- `"status"`: a single status line rendering `message.text` (live-updated).
- `"result"`: a card. If `message.result.passed`: "✓ Verified" + buttons `Add to my capabilities` (`onClick={() => void askStore.promoteBuild(message.buildId!)}`) and `Discard` (`onClick={() => askStore.cancelBuild()}`). Else: show blocked/failed state + the `output` snippet (no Add).
- `"installed"`: a plain assistant bubble with `message.text`.
- default (text/undefined): the existing bubble.

Keep it structurally simple (a `div.ask-card` with a title row, body, and an `ask-card__actions` button row). Reuse `ask-msg--bot` alignment.

**c. Baseline CSS** — append minimal rules to the `styles` string (functional only; owner refines):
```css
.ask-chip { font-size: 11px; color: var(--a); border: 1px solid var(--hair); border-radius: 999px; padding: 4px 9px; text-transform: uppercase; letter-spacing: 0.06em; }
.ask-card { align-self: flex-start; max-width: 88%; border: 1px solid var(--hair); border-radius: 14px; padding: 12px 15px; background: color-mix(in srgb, var(--bg) 70%, #12253a 30%); display: flex; flex-direction: column; gap: 8px; }
.ask-card__title { font-weight: 600; font-size: 14px; }
.ask-card__meta { font-size: 12px; color: var(--muted); }
.ask-card__actions { display: flex; gap: 8px; margin-top: 4px; }
.ask-cardbtn { border: 1px solid var(--hair); border-radius: 10px; padding: 8px 14px; font-size: 13px; cursor: pointer; background: var(--p); color: var(--bg); font-weight: 600; }
.ask-cardbtn--ghost { background: transparent; color: var(--text); }
.ask-cardbtn:disabled { opacity: 0.5; cursor: not-allowed; }
```

Note: `message.plan.summary` may contain the literal `…`/non-ASCII — render as-is (UTF-8 webview, no transform).

### 3. `src/ask/askStore.test.ts`

Mirror the existing gateway-mock pattern (the file already mocks `../api/gateway`). Add:
- A build-intent message ("build me a date utility module") routes to `capabilityPropose` (mocked → a `BuildPlanCard`), appends a `kind:"plan"` message, and sets `buildMode: true`.
- `confirmBuild(buildId)` consuming a mocked `capabilityBuild` async-iterable (`build_status` then `build_result{passed:true}` then `done`) appends a `kind:"result"` message with `result.passed === true`.
- `promoteBuild(buildId)` (mocked `capabilityPromote` → `InstalledCard`) appends a `kind:"installed"` message and clears `buildMode`.
- A blocked `BuildPlanCard` (`blocked:true`) yields a `kind:"plan"` message whose `plan.blocked` is true.
- A normal (non-build) message still routes to `askStream` (existing behavior unchanged).
- Reset state with `askStore.resetForTest()` between cases.

### 4. `src/ask/AskPopup.test.tsx`

Mirror the existing render tests. Add:
- Seeding the store (via `askStore.startBuild` with mocked gateway, or by asserting after a build-intent `send`) renders a plan card with the capability name and a `Build it` button; the header shows the "Building capability" chip.
- Clicking `Build it` calls `askStore.confirmBuild` (spy) with the plan's `build_id`.
- A blocked plan renders the `block_reason` and a disabled `Build it`.

## Acceptance criteria

1. A build-intent message routes to `capabilityPropose` and renders a plan card; a normal message still streams a chat answer → askStore tests.
2. `confirmBuild` streams status then appends a result card; `promoteBuild` appends the installed confirmation and clears build mode → askStore tests.
3. A blocked plan disables `Build it` and shows the reason → AskPopup test.
4. The "Building capability" chip shows while `buildMode` is true → AskPopup test.
5. Whole client green: `npm run typecheck`, `npm run lint`, `npm run test` all pass.

## Commands to run

```bash
# from client/
npm run typecheck
npm run lint
npm run test
```

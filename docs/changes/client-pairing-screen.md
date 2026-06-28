---
status: ready
weight: light
cross_model_review: false
coder_effort: medium
---

# client-pairing-screen — pre-connect pairing gateway for the Tauri client

## Identity
New `PairingScreen` pre-connect gateway that fills the `!connected` branch in `App.tsx:131`
(today returns `null` → blank window): pairing-code input → `pairDevice()`, the four
`PairingError` mappings, a recovery-passphrase sub-field → `recoverWithPassphrase()`, and the
in-flight/disconnected affordances. Frontend-only; all Tauri commands already registered.
Design: `docs/findings/client-pairing-ui-design-brief.md`.

## Files to change
- `client/src/auth/PairingScreen.tsx` — create (component + inline `const styles` block; reuses
  `.glass`/`.grid-mask`/`.glow-primary`/`.caret-primary`/`.screen-status` tokens).
- `client/src/App.tsx` — modify (one line at `:131`).
- `client/src/auth/PairingScreen.test.tsx` — create (vitest + Testing Library, mocked `invoke`).

> Three files; wiring merged into the App.tsx one-liner. No Rust, no CSS file, no new store —
> `connection.ts` transitions are already driven by `pairDevice()`.

## Exact changes

### Task 1 — `client/src/auth/PairingScreen.tsx` (create)
Default-export-free named component. Props from the App.tsx branch:

```tsx
import { useId, useRef, useState } from "react";
import type { ConnectionState } from "../api/dto";
import { pairDevice, type PairingError } from "./pairing";
import { recoverWithPassphrase } from "./recovery";

interface PairingScreenProps {
  state: ConnectionState; // "unpaired" | "disconnected" (the !connected states)
}

type Phase = "idle" | "submitting";

export function PairingScreen({ state }: PairingScreenProps): JSX.Element { … }
```

Behaviour:
- **Local state:** `code` (controlled input, default ""), `phase: Phase`, `error: PairingError | null`,
  `recoverOpen: boolean`, `passphrase` (controlled), plus a status string for the `aria-live` region.
- **Layout** (single centred panel, NOT the map):
  - Root `<div className="pair-gate">` (full-viewport flex-centre; transparent — `AmbientProvider`
    + `PhotoBackground` already mount behind it from `App`). `<span className="grid-mask" aria-hidden>`
    optional tactical grid.
  - Panel `<section className="glass pair-panel">` with `<span className="glass-sheen" aria-hidden />`.
  - **Brand mark:** inline `<svg className="pair-mark glow-primary">` — arc-reactor ringed circle
    `stroke="var(--p)"`, no fill (per `docs/technical/architecture/design-brief.md`); add
    `pair-mark--pulse` class while `phase === "submitting"` (a calm opacity pulse, gated by
    `prefers-reduced-motion`).
  - Title `<h1 className="pair-title">Pair this device</h1>` (Space Grotesk via inline style, matching
    `.screen-shell__title`); when `state === "disconnected"` title reads `Reconnect`.
- **Pairing form** (`state === "unpaired"`):
  - `<form onSubmit={onSubmit}>` with a labelled `<input>`:
    `id={useId()}`, `value={code}`, `autoFocus`, `autoComplete="off"`, `spellCheck={false}`,
    `inputMode="text"`, monospace, `className="caret-primary"` focus glow via `.glow-primary` on focus;
    `disabled={phase === "submitting"}`. Do NOT restrict to digits (code is URL-safe base64 ~12 chars).
  - Hint `<p className="screen-status">`: `Get a code on your brain: POST /app/admin/pair-code
    (valid 10 min)` with the curl one-liner in a `<code>` element. Never render a submitted code back.
  - Submit button `Pair` (`type="submit"`, `disabled={phase === "submitting" || code.trim() === ""}`);
    label switches to `Connecting…` while submitting.
- **`onSubmit`** (preventDefault):
  ```tsx
  setPhase("submitting"); setError(null); setStatus("Connecting…");
  try {
    await pairDevice(code.trim());          // drives store → unlocked → App remounts WorldShell
    // success: component unmounts via the connection store flip; no local navigation
  } catch (e) {
    setError(e as PairingError);            // pairDevice re-throws a PairingError; store stays unpaired
    setPhase("idle");
    setStatus(errorMessage(e as PairingError));
  }
  ```
  (Do not reset `phase` on success — leave the disabled/submitting state; the store transition
  unmounts the gateway. Tests assert via the store snapshot, not a phase reset.)
- **Error mapping** — pure `errorMessage(err: PairingError): string`:
  - `wrongOrExpiredCode` → `"That code didn't work or has expired. Mint a new one and try again."`
  - `offTunnel` → `"Can't reach your brain. Check the tunnel/connection."`
  - `biometricCancelled` → `"Biometric check was cancelled. Try again."`
  - `network` → `"Something went wrong reaching your brain. Try again."`
- **`aria-live` region:** `<p role="alert" aria-live="assertive" className="screen-status pair-error">`
  rendering `errorMessage(error)` when `error !== null`; otherwise a `role="status" aria-live="polite"`
  region carries the `Connecting…` text (mirror the `screen-status` pattern in
  `client/src/screens/DomainDetailShell.tsx`).
- **Recovery sub-field** (secondary affordance, collapsed by default):
  - `<button type="button" className="pair-link" onClick={() => setRecoverOpen(v => !v)}>Recover with
    passphrase</button>` with `aria-expanded={recoverOpen}`.
  - When open: a labelled `<input type="password">` (`value={passphrase}`, `autoComplete="off"`) + a
    `Recover` button → `await recoverWithPassphrase(passphrase)`; clear `passphrase` to "" in a `finally`.
  - Static note under the field: `On this device, recovery is not yet available (Mac-gated).` —
    `auth_recover` is a Windows no-op stub (broker escrow Mac-gated per `auth.rs` DEV-WALL); keep the
    path wired but set expectations. Treat a thrown error the same as the pairing error region.
  - Never echo the passphrase elsewhere; keep input controlled and reset on unmount.
- **Disconnected affordance** (`state === "disconnected"`, optional for v1): show a `Connect` button.
  v1 may reuse the same pairing form (re-pair path); if a no-re-pair reconnect is wanted, a `Connect`
  button calls a thin helper that runs `auth_connect → auth_unlock` only. Keep minimal — do not add a
  new store method.
- **Styles:** a `const styles = \`…\`` template string rendered via `<style>{styles}</style>` (project
  convention — see `DomainDetailShell.tsx`). Define `.pair-gate` (fixed inset-0, grid/flex centre,
  z-index above `.photo-bg`), `.pair-panel` (max-width ~420px, padding, `.glass` already supplies the
  surface), `.pair-mark`, `.pair-title`, `.pair-error`, `.pair-link`. Use `--p`/`--text`/`--muted`/
  `--hair` tokens ONLY — do NOT hard-code colours. Gate any pulse animation behind
  `@media (prefers-reduced-motion: reduce)`.

### Task 2 — `client/src/App.tsx` (modify, one line)
At line 131 replace:
```tsx
if (!connected) return null;
```
with:
```tsx
if (!connected) return <PairingScreen state={connection.state} />;
```
Add the import: `import { PairingScreen } from "./auth/PairingScreen";`. Leave `AmbientProvider` /
`PhotoBackground` where they are (in `App`, above `WorldShell`) so the gateway inherits ambient +
photo with no extra wiring. No other changes.

### Task 3 — `client/src/auth/PairingScreen.test.tsx` (create)
Vitest + `@testing-library/react`, mock `@tauri-apps/api/core` `invoke` (same pattern as
`client/src/auth/pairing.test.ts`). `beforeEach`: `connectionStore.resetForTest()`,
`mockedInvoke.mockReset()`.

## Acceptance criteria
1. **Renders the gateway in `unpaired`** — `render(<PairingScreen state="unpaired" />)`; the code
   input (by label) and a `Pair` button are present. → `npx vitest run src/auth/PairingScreen.test.tsx`
2. **Submit calls `pairDevice` and drives the store** — type a code, submit; `invoke` called with
   `"auth_pair", { pairingCode }` then `"auth_connect"` then `"auth_unlock"` (mock resolves `{}`);
   `connectionStore.getSnapshot().state === "unlocked"`. → vitest
3. **Each PairingError maps to its plain-English message in the alert region** — for each of
   `wrongOrExpiredCode` / `offTunnel` / `biometricCancelled` / `network`, mock the first `invoke` to
   reject with the matching error shape; assert the `role="alert"` text equals the mapped string and
   the form re-enables (store stays `unpaired`). → vitest
4. **Connecting state disables the form** — while the `auth_pair` promise is pending, the input and
   `Pair` button are `disabled` and the button reads `Connecting…`. → vitest
5. **Recovery sub-field** — clicking `Recover with passphrase` reveals the password input
   (`aria-expanded` flips true); entering a value + `Recover` calls `invoke("auth_recover",
   { passphrase })`; the input is cleared afterward. → vitest
6. **App.tsx branch** — typecheck passes and the `!connected` branch returns `<PairingScreen>` (not
   `null`). → `npx tsc --noEmit` + a render assertion that `App` mounts the code input when the store
   is `unpaired`.

## Commands to run
```bash
cd client
npm run test -- --run src/auth/PairingScreen.test.tsx   # or: npx vitest run src/auth/PairingScreen.test.tsx
npx tsc --noEmit
npm run test -- --run                                    # full vitest suite (was 60–66 green)
```
No `cargo` needed — this spec touches no Rust (all `auth_*` commands already registered in
`client/src-tauri/src/lib.rs`).

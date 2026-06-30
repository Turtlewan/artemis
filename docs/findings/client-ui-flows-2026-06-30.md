# Artemis Tauri Client — User-Facing Feature Flow Map

_Mapped 2026-06-30 from `client/src/` on branch `v2-rebuild`._

The client is a Tauri desktop app. The React/TS frontend talks to the Rust "brain" **exclusively
through Tauri `invoke(command, args)` calls and `Channel<StreamEvent>` streams** — there are no
direct HTTP fetches in this layer. The "gateway" (`api/gateway.ts`) is a thin typed facade over
`invoke`. "Endpoint" below = a Tauri command name, not a REST path.

---

## 0. App shell & top-level routing — `main.tsx`, `App.tsx`

- **`main.tsx`** picks the root by Tauri window label: label `"ask"` → renders `AskWindow` (the
  dedicated voice popup window); otherwise → `App`. Wraps in `StrictMode` + `RootErrorBoundary`
  (full-viewport crash screen).
- **`App.tsx`** wraps everything in `AmbientProvider` → `PhotoBackground` → `WorldShell`.
  `WorldShell` reads `useConnection()` and gates on `ConnectionState`:
  - `connected = state === "connectedLocked" || state === "unlocked"`.
  - **Not connected** (`unpaired` / `disconnected`) → renders `<PairingScreen state={...} />`.
  - **Connected** → renders the full spatial world: topbar (brand, breadcrumb `Home / {domain}`,
    a **"Vault unlocked" / "Vault locked"** indicator, and **Ask / Home / Reset layout** buttons),
    `AskPopup`, `WorldPlane`, `Dock`, `Minimap`, an `aria-live` SR region, and `DetailOverlay`.

**Three top-level UI states:** pairing/unlock (`PairingScreen`) → world-locked (`connectedLocked`,
"Vault locked") → world-unlocked (`unlocked`, "Vault unlocked"). Both connected states render the
same world shell; only the status text and the per-domain re-unlock gate differ.

**Connection state machine** (`state/connection.ts`, `useSyncExternalStore`):
`ConnectionState = "unpaired" | "disconnected" | "connectedLocked" | "unlocked"`. Transitions:
`onPaired` (unpaired→disconnected), `onConnected` (→connectedLocked), `onUnlocked`
(connectedLocked→unlocked), `onLocked` (unlocked→connectedLocked), `onDisconnected`, `onRevoked`
(→unpaired). Initial `unpaired`.

---

## FLOW 1 — Pairing / first-run & unlock (`auth/`)

**What the user does:** On first run the world is gated behind `PairingScreen` (z-index overlay,
glass panel, animated concentric-circle mark). The user mints a pairing code on the brain
(hint line literally renders `POST /app/admin/pair-code`, valid 10 min), types it in, and submits.
Heading/labels are state-driven: `disconnected` → "Reconnect" / "Connect"; else "Pair this device"
/ "Pair". A "Recover with passphrase" disclosure offers passphrase recovery (currently noted
**"recovery is not yet available (Mac-gated)"**).

**Gateway/IPC calls:**
- `pairDevice(code)` (`auth/pairing.ts`) runs a **three-invoke sequence**, advancing the connection
  store after each: `invoke("auth_pair", { pairingCode })` → `onPaired()`; `invoke("auth_connect")`
  → `onConnected()`; `invoke("auth_unlock")` → `onUnlocked()`. One success walks
  unpaired→disconnected→connectedLocked→unlocked.
- `recoverWithPassphrase(value)` (`auth/recovery.ts`) → `invoke("auth_recover", { passphrase })`,
  scrubs the passphrase from memory in `finally`.

**Errors:** `toPairingError` maps to `PairingError = { kind: "wrongOrExpiredCode" | "offTunnel" |
"biometricCancelled" | "network" }`, each with user copy in `PairingScreen.errorMessage`. Auth
error kinds `biometricCancelled` / `pairingRejected` / `hardwareUnavailable` map through; HTTP
[400,401,403,404,410] → wrongOrExpiredCode; network → offTunnel.

**DTOs (handshake, snake_case wire, mostly Rust-side behind invoke):** `PairRequest`
(`device_id`, `public_key_b64`, `pairing_code`, `code_signature_b64`), `SessionBegin/Complete*`
(signed-nonce + `counter` challenge/response → `session_token`, `expires_at`), `UnlockBegin/Complete*`
(`nonce_b64`, `counter`, `signature_b64`), `StatusResponse` (`connected`, `vault_unlocked`,
`device_id`). The signed-nonce+counter shape implies a hardware/biometric signature handshake.

**Unlock (re-unlock while connected):** there is no separate unlock screen. Once `connectedLocked`,
the world renders but each domain detail screen swaps to a **re-unlock gate** (see Flow 5). Locking
is user-driven from `StatusDetail` (`gateway.lock` → `onLocked`).

---

## FLOW 2 — Travel-zoom spatial map (`world/`)

**What the user does:** The world is a single fixed plane (`WORLD = 2600×1760`, "brain core" at
center) panned/zoomed by one CSS `translate()...scale()` transform — no scrolling.
- **Pan:** left-drag on the stage background (drags that land on a `.world-card` are ignored so
  cards stay clickable). Live rubber-band overshoot during drag, clamp-to-bounds on release. When
  zoomed out so the plane is smaller than the viewport, the axis locks centered.
- **Zoom:** mouse wheel, cursor-anchored and inertial (eases actual scale toward a target),
  clamped to `minScale 0.42 .. maxScale 2.4`.
- **Keyboard:** arrows pan by 72px; `Home`/`Escape` fly to overview.
- **Travel:** `Dock` buttons (and card opens) trigger `travelTo` — a cinematic fly with a
  **mid-flight zoom-out "dip"** for long distances, eased, ~640–1150ms; respects
  `prefers-reduced-motion` (instant jump).

**Camera model** (`world/camera.ts`): `Camera { tx, ty, scale }` + `transform-origin: 0 0`.
`HOME_SCALE 0.72`, `FOCUS_SCALE 1.05`. Helpers: `worldToScreen`/`screenToWorld`, `pan`,
`zoomToward` (focal zoom), `cameraForCenter`, `home`, `clampCamera` (hard), `clampRubberband`
(soft). `useCamera({viewportW, viewportH, onArrive})` owns the camera state + all handlers and
exposes `travelTo`, `home`, `transform`, `isMoving`.

**Render** (`world/WorldPlane.tsx`): one `.world-plane` element carries `camera.transform`; behind
it `NeuralWeb` draws the domain/relationship web tracking the same transform; `.world-core` is a
decorative orb; each placement → a `CardSlot`.

**Placement & clustering** (`world/clusters.ts`): `CARD 250×150`; `defaultPlacements()` seeds all
11 domains at hand-tuned offsets from core, grouped around four cluster poles (Comms / Planning /
Knowledge / Self). `CardPlacement { id, domain, cluster, x, y, w, h }`.

**Card slot** (`world/CardSlot.tsx`): a native `<button class="world-card glass">`, `aria-label` =
domain label, `onClick → onOpen(domain)`. Sets `dataset.cardSlot = domain` (the morph-origin
lookup). Repositionable: drag the grip handle (translate by `Δ/scale`), or keyboard Move-mode
(Enter to enter, arrows to nudge by 48px, Enter commit / Escape revert). `onMove(placement,
persist)` — `false` = live preview, `true` = save.

**Dock** (`world/Dock.tsx`): canonical keyboard-reachable nav; 2-letter buttons per domain,
`aria-current` on active, click → `travelTo`. **Minimap** (`world/Minimap.tsx`): decorative
(`aria-hidden`/`inert`) overview with dots + a viewport rectangle.

**Layout persistence** (`world/layoutBridge.ts` + `state/layout.ts`): `useLayoutBridge` seeds from
the brain-synced `layoutStore` (else `defaultPlacements()`), calls `loadOnConnect()`, and persists
moves via debounced `saveAfterDragEnd` → `gateway.layoutPut` (`app_layout_put`). LWW by
`updated_at`; stale PUT responses discarded. `resetToDefault` restores the seed and saves
immediately.

---

## FLOW 3 — Glance cards (`card/` glance face)

**What the user sees:** each placement hosts a `GlanceHost(domainId)` glance face. Two fixed,
non-scrolling variants (`card/types.ts` `GlanceContent`): `{ kind: "count", value, label }` (big
number + label) and `{ kind: "tiles", tiles: {value,label}[] }` (2-col grid). Rendered by
`GlanceFace` with ellipsis truncation so faces never content-scroll.

**Data a glance needs:** only `DomainGlanceProps { domainId }` for content (the component
self-sources its domain data) plus the `CardPlacement` for geometry/identity.

**Current state — important:** **no glance components are registered anywhere in app code** (only a
test registers one). So **all 11 domains currently render the `GlanceHost` placeholder
`{ kind:"count", value:"—", label: domainLabel }` face.** The glance machinery is fully wired but
CLIENT-screens has not yet supplied real glance content — this is the obvious next build seam for
the brain to feed per-domain summary numbers.

---

## FLOW 4 — Card → DetailOverlay morph (`card/` overlay)

**What the user does:** clicking a card (or its Dock entry) opens that domain's detail. Two separate
mechanisms: the **camera** flies to the card (`travelTo`), and the **card→dialog FLIP morph**
expands the overlay out of the exact card rect.

**Mechanism** (`card/useCardOverlay.ts`, `card/morph.ts`, `card/DetailOverlay.tsx`):
`useCardOverlay` holds `openId: DomainId | null` + `originRef` (the originating CardSlot, for FLIP +
focus return). `morph.ts` does FLIP math (`firstLastInvert(fromRect, toRect)` → transform/opacity-
only keyframes). `DetailOverlay` is a top-most, focus-trapped (`aria-modal`) dialog that WAAPI-
animates from the card rect to the dialog (220ms open / 190ms close-reverse), respects reduced
motion, and returns focus to the card. Body renders `getDomainDetail(renderedId)` or a
"Detail coming" fallback.

---

## FLOW 5 — Per-domain detail screens (`screens/`)

**Routing/registry:** `screens/registry.ts` registers detail components into the card registry at
module load. **6 bespoke** panels + **5 generic**:

| Domain | Detail component | Read command | Engine tag |
|---|---|---|---|
| review | `ReviewDetail` | (fans out, see below) | review |
| schedule | `CalendarDetail` | `app_calendar_read` | review |
| tasks | `TasksDetail` | `app_tasks_read` | local |
| projects | `ProjectsDetail` | `app_projects_read` | local |
| email | `GmailDetail` | `app_gmail_read` | codex |
| finance | `FinanceDetail` | `app_finance_read` | local |
| people | `GenericDomainDetail` | `app_people_read` | local |
| travel | `GenericDomainDetail` | `app_travel_read` | local |
| memory | `GenericDomainDetail` | `app_memory_read` | local |
| knowledge | `GenericDomainDetail` | `app_knowledge_read` | local |
| health | `GenericDomainDetail` | `app_health_read` | local |

(`StatusDetail` is exported separately as `statusDetail` — connection chrome, not a registered
domain; works while locked.)

**Shared read path** (`screens/useDomainRead.ts`): `useDomainRead(domainId, reader?)` calls
`invoke(ROUTE[domainId])` and yields `{ data, loading, error, locked }`. A `vaultLocked` error sets
`locked:true`; any other error → `"Data not yet available for this domain."`.

**Shared scaffold** (`screens/DomainDetailShell.tsx`): injects all `screen-*` CSS, computes
`locked = LOCK_TIER[domainId]==="unlocked" && connection.state==="connectedLocked"` and renders an
**"Unlock required" re-unlock gate** (button → `onClose`) when locked. Render priority:
locked → loading → error → empty → children. (`domainRoutes.ts` tags every domain `LOCK_TIER:
"unlocked"` = owner-private, needs unlocked vault.)

**Per-screen highlights:**
- **CalendarDetail** (`schedule`): month/week day-strip + selected-day panel; events (tentative-held
  styling), tasks-due, RSVP → `stage("calendar.external_effect", …)` via `app_stage_pending_action`.
- **TasksDetail** (`tasks`): Due/Overdue/Upcoming lists with complete/reschedule (`action("tasks.{kind}",
  {task_id})`); time-block disabled; right pane = captured suggestions with Accept/Reject via
  `acceptSuggestion`/`rejectSuggestion` (`task_suggestion_accept/reject`).
- **ProjectsDetail** (`projects`): read-only list — name, status pill, target, open-tasks count.
- **GmailDetail** (`email`): Needs-you + Signal lists, subject search, reader pane, "Open in Gmail"
  external link.
- **FinanceDetail** (`finance`): week/MTD totals, daily-spend list, bills (local mark-paid),
  category donut SVG, transactions, and Unusual/Duplicate/Confirm insight cards (all local-only edits).
- **ReviewDetail** (`review`): bypasses `useDomainRead`; fans out `Promise.all([actionsPending,
  reviewPending, reviewAutoEnabled])`. Two sections — **Pending actions** (Approve/Reject via
  `app_actions_approve/reject`) and **Recipe review** (Approve/Reject via `app_review_approve/reject`).
  Optimistic removal with restore-on-error; `vaultLocked` → `onLocked()` + re-auth message.
- **GenericDomainDetail** (people/travel/memory/knowledge/health): `{count} items` + item list;
  always shows "Data not yet available for this domain." (placeholder until the brain supplies data).
- **StatusDetail**: connection chrome (works while locked) — Lock now (`gateway.lock` → `onLocked`),
  Disconnect/Sign out (`gateway.logout` → `onRevoked`), Close.

---

## FLOW 6 — Ask-Artemis popup: voice + text + SSE streaming (`ask/`)

**How it opens:** `useAskHotkey` listens for a backend Tauri event **`ask:summon`** (the real global
hotkey lives in Rust) and toggles `isOpen`; also exposes `askButtonProps` so the topbar **Ask**
button opens it. The dedicated **`AskWindow`** (window label `"ask"`) renders `AskPopup` always-open
and "closes" by hiding the OS window (`getCurrentWebviewWindow().hide()`).

**What the user does** (`ask/AskPopup.tsx`, `role="dialog"` `aria-modal`, manual focus trap):
- **Text:** type and submit → `askStore.send(text)` (input clears immediately).
- **Voice:** mic button → `onVoiceTrigger({ speak: !muted })` (delegated to App, which calls
  `gateway.askVoice`). A **mute toggle** controls whether the brain speaks answers (`aria-pressed`).
- A **mode chip** renders `snapshot.modeHint` (`TASK` / `DIGEST` / `WIND-DOWN`); footer shows a
  "Speaking" chip + per-engine ready/idle chips.

**SSE streaming** (`ask/askStore.ts` + `api/gateway.ts`):
- `askStore.send(text)` guards on connection (if not connected/unlocked → `unlockPrompt()` dispatches
  `artemis:reunlock-required` + assertive "Not connected" announcement). Appends a user msg + empty
  assistant msg, then streams via `gateway.askStream({ text, speak: !muted })` → Tauri command
  **`app_ask_stream`** with a `Channel<StreamEvent>`.
- `StreamEvent` union (`dto.ts`): `{ type:"text", text }` (append + polite live-region on sentence
  boundary), `{ type:"vault_locked" }` (mark row `failedLocked`, assertive re-auth msg),
  `{ type:"done", path?, tool_used?, escalated? }` (finalize; `deriveEngine(path, escalated)` →
  `review` if escalated / `codex` if non-local path / else `local`).
- Voice path: `gateway.askVoice(speak)` → command **`app_ask_voice`** (same Channel mechanism). A
  non-stream `ask()` → `app_ask` also exists (`AskResponse { text, path, tool_used?, escalated }`).

**Rendering:** assistant messages → `ResultRow` (title "Answer"/"Vault locked", subtitle = answer
text, plus `EngineTag`). `EngineTag` renders the literal engine word `local` / `codex` / `review`
("the visible word is the contract"; review = accent-styled = escalated).

---

## Domain list (`domains.ts`) — 11 domains, 4 clusters

`domains.ts` holds **only id, label, and cluster** (no color/coordinate metadata — colors live in
DTO data like `FinanceCategory.color`; coordinates in `CardPlacement`/`clusters.ts`).

| DomainId | Label | Cluster |
|---|---|---|
| email | Email | Comms |
| people | People | Comms |
| schedule | Schedule | Planning |
| tasks | Tasks | Planning |
| projects | Projects | Planning |
| travel | Travel | Planning |
| memory | Memory | Knowledge |
| knowledge | Knowledge | Knowledge |
| review | Review | Knowledge |
| health | Health | Self |
| finance | Finance | Self |

`DomainCluster = "Comms" | "Planning" | "Knowledge" | "Self"`. Exports `domainLabel(id)`,
`domainCluster(id)`.

**What each glance card needs from the brain** (currently unwired — all show "—"): a per-domain
summary number/tiles. The natural source per domain is its detail read command (`app_*_read`), e.g.
email = needs-you count, schedule = today's event count, tasks = due count, finance = week total,
review = pending count. This is the key open gap for the brain to fill.

---

## DTO inventory (the data the UI renders)

**Spatial / layout:**
- `CardPlacement` — `id, domain, cluster, x, y, w, h` (geometry + identity per card).
- `LayoutDTO` — `version, updated_at, cards: CardPlacement[]` (LWW-persisted layout).

**Ask / streaming:**
- `StreamEvent` — `{type:"text",text} | {type:"vault_locked"} | {type:"done", path?, tool_used?, escalated?}`.
- `AskRequest` — `text, speak?`. `AskResponse` — `text, path, tool_used?, escalated`.
- `AskMessage` / `AskSnapshot` / `AskEngineStatus` (store-side); `AskEngine = "local"|"codex"|"review"`;
  `AskModeHint = "TASK"|"DIGEST"|"WIND-DOWN"`.

**Per-domain reads** (note: `api/dto.ts` and `screens/dtos.ts` define overlapping but slightly
different shapes — `screens/dtos.ts` is the richer one the detail screens render):
- `CalendarRead` — `events[]` (`id,title,start,end,kind,attendees?,rsvp?`), `tasksDueByDay`/`tasks_due_by_day`.
- `TasksRead` — `overdue[]`, `today[]`, `upcoming[]`, `suggestions[]` (each task `{title, due?, task_id}`).
- `ProjectsRead` — `projects[]` (`id, name, status, target?, openTasks`).
- `GmailRead` — `needsYou[]`/`needs_you` (`id,sender,subject,why`), `signal[]` (`…,ts`).
- `FinanceRead` — `week_total, mtd_total, daily[], categories[] (…,color), transactions[], bills[],
  unusual?, duplicate?, ambiguous?`.
- `GenericRead` — `count, items[] {title, subtitle?, engine?}`.
- `ReviewItem` — `name, description, status, action_class, safety, explanation`.
- `PendingAction` — `id, module, tool, summary, action_class, status, created_at, expires_at, result`.
- `ScreenDTO` = union of the six `*Read` types (`PendingAction`/`ReviewItem` read separately by ReviewDetail).

**Auth / session:** `PairRequest`, `SessionBegin/Complete*`, `UnlockBegin/Complete*`, `StatusResponse`.
**Errors:** `ApiError = {kind:"unauthenticated"} | {kind:"vaultLocked"} | {kind:"http",status} |
{kind:"network"}` (401→unauthenticated, 423→vaultLocked); `PairingError` (4 kinds).
**Misc:** `OkResponse {ok}`, `ConnectionState`.

---

## Test coverage (vitest) — what's already specified behaviorally

- **api/gateway.test.ts** — gateway facade: status/ask/layout round-trips, error mapping, suggestion
  accept/reject, layout stale-PUT discard.
- **api/gateway.voice.test.ts** — voice ask streams via `app_ask_voice`.
- **auth/pairing.test.ts** — `pairDevice` connect→unlock order, wrong/expired/tunnel/biometric errors,
  passphrase not retained.
- **auth/PairingScreen.test.tsx** — pairing UI: render, submit drives store, connecting disables form,
  recovery clears passphrase, App mounts code input while unpaired.
- **ask/askStore.test.ts** — stream→single assistant msg + engine metadata, mute persistence,
  disconnected-send block, vault-lock failed/assertive.
- **ask/AskWindow.test.tsx** — renders AskPopup open; hides OS window on close.
- **ask/AskPopup.test.tsx** — dialog/textbox/engine-tag, mic voice trigger, mute aria-pressed,
  speaking announcement, focus-trap, Escape/click-away close + focus restore.
- **world/world.test.tsx** — shell gating to connected states, dock travel, CardSlot button a11y,
  decorative minimap, layout persistence/reset, Home/Escape target, reduced-motion.
- **world/clusters.test.ts** — default placements seed all 11 domains, four clusters, in-bounds.
- **world/camera.test.ts** — pan, cursor-anchored zoom, rubber-band/clamp, screen↔world round-trip,
  centre/home framing.
- **world/appVoice.test.tsx** — App passes a voice trigger to AskPopup calling `askVoice` with speak flag.
- **card/morph.test.ts** — FLIP inverse + transform/opacity-only keyframes.
- **card/card.test.tsx** — registry (independent detail/glance), glance faces (count/tiles,
  non-scrolling), CardSlot name, aria-modal overlay, fallback heading, reduced-motion.
- **screens/screens.test.tsx** — every domain mapped to a read route, all 11 detail components
  registered, shell title/scroll/engine/status states + re-unlock prompt, rich DTO shapes.
- **screens/StatusDetail.test.tsx** — lock + logout state transitions.
- **screens/ReviewDetail.test.tsx** — pending actions render + keep recipe section, optimistic
  approve removal, restore on 409/404, re-lock on vault lock (approve & reject), empty state.
- **screens/TasksDetail.test.tsx** — accept suggestions w/ due date, reject via owner commands,
  external time-block disabled/uninvoked.
- **state/connection.test.ts** — state machine paths (paired→unlocked, lock/disconnect/revoke,
  ignore unlock when not connectedLocked).
- **theme/ambient.test.ts** — ambient resolver (season/time mapping, night boundary, palette
  coverage, CSS-var write, never returns draft/failing cells) + contrast gate.

---

## Theme — ambient color system (`theme/`)

Decorative, not a user "flow", but it drives the whole look: `palettes.ts` (4×4 Season×TimeState
matrix of 16 vetted palette cells), `contrast.ts` (WCAG gate deciding which cells go live),
`ambient.ts` (time→cell resolver, writes `--bg/--p/--a` CSS vars), `AmbientProvider.tsx` (re-resolves
every minute, honors reduced-motion), `relationships.ts` (11 spokes + 15 domain-pair edges for the
neural web), `PhotoBackground.tsx` (per-cell photo or gradient fallback), `NeuralWeb.tsx` (animated
SVG spokes/edges behind the plane).

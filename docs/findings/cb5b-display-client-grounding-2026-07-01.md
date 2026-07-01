# CB-5b Client Grounding — 2026-07-01

Read-only survey of the client codebase to ground CB-5b implementation.
All line numbers reference the state at commit `1d7ecf8` (branch `v2-rebuild`).

---

## 1. Map Component — WorldPlane

**File:** `client/src/world/WorldPlane.tsx`

The pannable/zoomable map is implemented with **pure CSS transforms** — no external library (no react-flow, d3, framer, etc.).

### Structure

```
div.world-stage          ← overflow-hidden, touch-action:none, pointer events land here
  NeuralWeb (SVG)        ← background neural-web lines, receives camera.transform directly
  div.world-plane        ← position:absolute; transform-origin:0 0; SIZE: 2600×1760px
    div.world-core       ← the central orb, position:absolute at CORE(1300,880)
    {placements.map → CardSlot}
```

### Pan / Zoom

`WorldPlane.tsx:86-93` — the `.world-stage` div receives:
- `onPointerDown` → starts panning
- `onWheel` → zooms
- `onKeyDown` → arrows/Home/Escape

All handlers come from `CameraController` (returned by `useCamera`).

Camera state lives in `useCamera.ts`. The single transform expression, `camera.transform`, is:
```
`translate(${cam.tx}px, ${cam.ty}px) scale(${cam.scale})`
```
(`useCamera.ts:248`) applied to `.world-plane`.

### Camera State (`client/src/world/camera.ts`, `useCamera.ts`)

```typescript
interface Camera { tx: number; ty: number; scale: number; }
```

Constants:
- `WORLD_WIDTH = 2600`, `WORLD_HEIGHT = 1760` (`camera.ts:22-23`)
- `CORE = { x: 1300, y: 880 }` (`camera.ts:24`)
- `HOME_SCALE = 0.72`, `FOCUS_SCALE = 1.05` (`camera.ts:25-26`)
- `minScale = 0.42`, `maxScale = 2.4` (`camera.ts:51-52`)

Event flow:
- **Drag pan**: `onPointerDown` captures pointerId → `window.pointermove` → `pan()` + `clampRubberband()` → `onPointerUp` → `clampCamera()` (`useCamera.ts:150-179`)
- **Wheel zoom**: exponential scale from `deltaY * 0.0011`, RAF-smoothed with `zoomToward()` (`useCamera.ts:181-219`)
- **Keyboard**: arrows pan 72px, Home/Escape call `home()` (`useCamera.ts:221-241`)
- **Programmatic travel**: `travelTo(target)` animates with `easeInOutCubic` + optional scale-dip arc (`useCamera.ts:98-146`)

---

## 2. Node Component — CardSlot

**File:** `client/src/world/CardSlot.tsx`

### Props

```typescript
interface CardSlotProps {
  placement: CardPlacement;   // { id, domain, cluster, x, y, w, h }
  scale: number;              // current camera scale (for drag coord conversion)
  onMove: (placement: CardPlacement, persist: boolean) => void;
  onOpen: (domain: DomainId) => void;
  children?: ReactNode;       // GlanceHost renders here
}
```

### Rendering

Each node is an absolutely-positioned `<button>`:
```typescript
// CardSlot.tsx:103-118
<button
  className={`world-card glass${moving ? " world-card--moving" : ""}`}
  style={{
    left: `${active.x}px`,
    top: `${active.y}px`,
    width: `${active.w}px`,
    height: `${active.h}px`,
  }}
  aria-label={domainLabel(domain)}
  onClick={() => onOpen(domain)}
>
```

Layout:
- `.world-card__chrome` — title from `domainLabel(domain)` + drag grip
- `.world-card__body` — children (GlanceHost) OR cluster name as placeholder
- Default card size: `CARD_WIDTH = 250`, `CARD_HEIGHT = 150` (`clusters.ts:6-7`)

### CRITICAL TYPE CONSTRAINT

`CardSlot.tsx:26` calls `const domain = asDomain(placement.domain)` (a cast to `DomainId`), then:
- `CardSlot.tsx:117`: `aria-label={domainLabel(domain)}` — `domainLabel` does a `Record<DomainId, string>` lookup (`domains.ts:44`). If `domain` is NOT a key in that record, the lookup returns `undefined`.
- `CardSlot.tsx:118`: `onOpen(domain)` — typed as `(domain: DomainId) => void`.

`GlanceFace.tsx:57-61` — `GlanceHost` takes `domainId: DomainId` and passes it to the registry and `domainLabel`. Same constraint.

`DomainId` is a CLOSED union (`domains.ts:1-12`) of exactly 11 values. Capability names are not in it.

**Consequence for CB-5b**: capability nodes cannot reuse `CardSlot`/`GlanceHost` as-is without either:
a) Adding an optional `label?: string` override to `CardSlot` and passing `children` instead of `GlanceHost`, OR
b) Writing a new `CapabilitySlot` component (duplicates drag logic), OR
c) Making `domainLabel()` return the raw string if not found (one-liner change, handles unknown domain IDs gracefully)

Option (c) is the least invasive: change `domains.ts:44` from a strict Record lookup to a fallback:
```typescript
export const domainLabel = (id: DomainId): string => labels[id] ?? id;
// also widen CardSlot.onOpen signature to accept string
```

---

## 3. Hardcoded Domain Positions

**File:** `client/src/world/clusters.ts`

The 11 seed positions (`clusters.ts:23-35`) are hardcoded relative to `CORE`:
```typescript
const seedCenters = {
  email:    { x: CORE.x - 680, y: CORE.y - 290 },
  people:   { x: CORE.x - 510, y: CORE.y - 45 },
  schedule: { x: CORE.x - 155, y: CORE.y - 525 },
  tasks:    { x: CORE.x + 165, y: CORE.y - 500 },
  projects: { x: CORE.x + 455, y: CORE.y - 340 },
  travel:   { x: CORE.x + 680, y: CORE.y - 95 },
  memory:   { x: CORE.x - 420, y: CORE.y + 380 },
  knowledge:{ x: CORE.x - 60,  y: CORE.y + 500 },
  review:   { x: CORE.x + 305, y: CORE.y + 390 },
  health:   { x: CORE.x + 615, y: CORE.y + 240 },
  finance:  { x: CORE.x + 695, y: CORE.y + 485 },
};
```

`defaultPlacements()` (`clusters.ts:58`) builds `CardPlacement[]` from these. BUT:

**`layoutBridge.ts:18-20` (comment + code):**
```typescript
// v2: the brain's capability-backed layout is the ONLY source of map nodes; no hardcoded
// client-side domain seed. An empty layout means an empty map (nothing has been built yet).
const validCards = (layout: LayoutDTO): CardPlacement[] => layout.cards;
```

`validCards` returns `layout.cards` directly — no merge with `defaultPlacements()`. The seed exists but is NOT used in the current v2 render path. The map only renders what the brain's layout returns.

---

## 4. Data Flow — Layout (Current)

```
App.tsx:53
  useLayoutBridge(connected)
    layoutStore.loadOnConnect()
      layoutGet()                         ← client/src/api/gateway.ts:79
        invoke("app_layout_get")          ← Tauri IPC
          gateway::app_layout_get         ← client/src-tauri/src/gateway.rs:814
            gateway::layout_get()         ← gateway.rs:523
              GET /app/layout             ← brain HTTP
```

Response: `LayoutDTO { version, updated_at, cards: CardPlacement[] }`

`layoutStore` (`state/layout.ts`) is a singleton pub/sub store. `useLayoutBridge` subscribes and returns `placements: CardPlacement[]` to `App.tsx`, which passes to `WorldPlane`, which maps to `CardSlot`.

---

## 5. CB-3 Pattern — Capability Commands (Existing)

For reference, the existing capability command pattern:

**Rust gateway fn** (`gateway.rs:481-493`):
```rust
pub(crate) async fn capability_propose(state: &AppState, goal: String) -> Result<PlanCard, GatewayError> {
    request_json(state, Method::POST, "/app/capabilities/propose", Some(&CapabilityProposeRequest { goal }), true).await
}
```

**Tauri command** (`gateway.rs:779-784`):
```rust
#[tauri::command]
pub(crate) async fn app_capability_propose(state: State<'_, AppState>, goal: String) -> Result<PlanCard, GatewayError> {
    capability_propose(&state, goal).await
}
```

**Registration** (`lib.rs:62`):
```rust
gateway::app_capability_propose,
```

**TS wrapper** (`gateway.ts:141-142`):
```typescript
export const capabilityPropose = (goal: string): Promise<BuildPlanCard> =>
  call("app_capability_propose", { goal });
```

---

## 6. CapabilitySummary Schema (Brain)

**File:** `src/artemis/api/capability_routes.py:52-61`

```python
class CapabilitySummary(BaseModel):
    name: str
    description: str
    version: int
    uses: list[str]      # tool/module names this capability uses
    secrets: list[str]   # env var names required

class CapabilitiesList(BaseModel):
    capabilities: list[CapabilitySummary]
```

Endpoint: `GET /app/capabilities` (session-gated, returns `CapabilitiesList`)

No `x/y/w/h` — no position data in the brain response.

---

## 7. What CB-5b Must Add (Concrete File List)

### File 1: `client/src-tauri/src/gateway.rs`

Add Rust structs (after `InstalledCard`, ~line 102):
```rust
#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct CapabilitySummaryItem {
    name: String,
    description: String,
    version: i64,
    uses: Vec<String>,
    secrets: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct CapabilitiesListResponse {
    capabilities: Vec<CapabilitySummaryItem>,
}
```

Add gateway fn (after `layout_put`, ~line 532):
```rust
pub(crate) async fn capabilities_list(state: &AppState) -> Result<CapabilitiesListResponse, GatewayError> {
    request_json::<CapabilitiesListResponse, ()>(state, Method::GET, "/app/capabilities", None, true).await
}
```

Add Tauri command (after `app_layout_put`, ~line 824):
```rust
#[tauri::command]
pub(crate) async fn app_capabilities_list(state: State<'_, AppState>) -> Result<CapabilitiesListResponse, GatewayError> {
    capabilities_list(&state).await
}
```

### File 2: `client/src-tauri/src/lib.rs`

Add to `invoke_handler!` list at line 47-73 (after `gateway::app_layout_put`):
```rust
gateway::app_capabilities_list,
```

### File 3: `client/src/api/dto.ts`

Add after `InstalledCard` (~line 197):
```typescript
export interface CapabilitySummary {
  name: string;
  description: string;
  version: number;
  uses: string[];
  secrets: string[];
}

export interface CapabilitiesList {
  capabilities: CapabilitySummary[];
}
```

### File 4: `client/src/api/gateway.ts`

Add after `capabilityPromote` (~line 145):
```typescript
/** Return all promoted capabilities. */
export const capabilitiesList = (): Promise<CapabilitiesList> =>
  call("app_capabilities_list");
```

### File 5: Node visual (DESIGN DECISION NEEDED)

The capability node must be rendered on the map. The design decision is: **what does a capability node look like, and where is it positioned?**

**Position**: The brain's `GET /app/capabilities` returns no x/y. Options:
- A) Compute positions client-side from capability index (e.g., polar ring around CORE). Deterministic from name hash or list index.
- B) Store positions in the brain's layout (`/app/layout`) — requires either the promote flow to auto-add layout entries (brain change) or CB-5b to call `layoutPut` after fetching capabilities.
- C) Hybrid: fetch capabilities to know what to show; fetch layout for stored positions; compute fallback positions for new capabilities not yet in layout.

**Rendering**: Use `CardSlot` with label fallback (minimal change) OR a new `CapabilityNode` component.

If using `CardSlot`:
- `domains.ts:44` — change `domainLabel` to `labels[id] ?? id` (fallback to raw string)
- `CardSlot.tsx:22` — change `onOpen: (domain: DomainId)` to `(domain: string)` or drop the cast
- `WorldPlane.tsx:125` — pass `null` instead of `<GlanceHost>`, or add a capability-specific child (shows description as placeholder text)

---

## 8. Integration Constraints Summary

| Constraint | Impact |
|---|---|
| `DomainId` is a closed union of 11 strings | `domainLabel(capabilityName)` returns `undefined` — need 1-line fallback or new label path |
| `GlanceHost` takes `DomainId` | Can't pass capability name; must pass `null` children or skip `GlanceHost` |
| `CardPlacement` has no `label` field | Title comes from `domainLabel(domain)` via `placement.domain`; capability name = `domain` field value |
| No position data in `GET /app/capabilities` | Must compute/store positions; no layout engine |
| Brain's `/app/layout` is current source of `placements` | Either: capability cards must be in layout (brain change) or client fetches both and merges |
| `world-plane` is 2600×1760 with CORE at 1300×880 | Plenty of room for 5-20 capability nodes in a ring |
| No library (react-flow etc.) | Custom position seeding required |

---

## Tauri Version

`client/src-tauri/Cargo.toml`:
- `tauri = { version = "2", features = ["test"] }`
- `tauri-build = { version = "2" }`

---

## No Existing Usage

Searched for `app_capabilities_list` and `capabilitiesList` — **zero hits** in client code. CB-5b starts fresh on the Tauri command + TS wrapper side.

# Client live bring-up gaps — first real end-to-end UI run (2026-06-29)

Surfaced while the owner drove the first genuine client↔brain end-to-end session on the enrolled
Windows box (brain via `uv run artemis-brain`, client via `npm run tauri dev`). Pairing → connect →
unlock **succeeded** (the live connect-in that previously died at `session/complete 401` now works).
These are the gaps found past that point. For tomorrow's planning session.

## Summary table

| # | Gap | Severity | Status |
|---|-----|----------|--------|
| 1 | `NeuralWeb` crashes on unplaced domains | was crash-on-startup | ✅ FIXED `c6a8e57` |
| 2 | Auth rate limit = exactly one handshake → reconnect lockout + misleading error | high (blocks reconnect) | dev-unblocked (loopback exempt); needs real design |
| 3 | Brain `default_layout()` ≠ client taxonomy + coordinate space | high (empty map) | workaround (Reset layout btn); needs contract reconcile |
| 4 | Ask hotkey `Alt+Space` collides with Windows OS window-menu | medium | fix staged (→ Ctrl+Alt+Space); Ask button works now |
| 5 | Per-domain live read commands unbuilt for 10/11 domains | high (the main gap) | needs build (the "live-mapping pass") |

## Finding 1 — NeuralWeb crash (FIXED)
`NeuralWeb` drew a spoke for every `SPOKE_DOMAINS` entry + every relationship edge, but `layout` is
keyed only by placed domains. Empty/partial placements (right after connect, before `/app/layout`
resolves) → `layout[id]` undefined → `curvePath` reads `from.x` on undefined → crash.
**Fix:** `client/src/theme/NeuralWeb.tsx` now skips any spoke/edge whose endpoint isn't placed
(also correct behavior: no card → no spoke). Committed `c6a8e57`; tsc/eslint/84 vitest green.

## Finding 2 — Auth rate limiter is one-handshake-sized
`RATE_LIMIT_ATTEMPTS = 5`, `RATE_LIMIT_WINDOW_SECONDS = 900` (`src/artemis/api_app.py`). A single
pair→connect→unlock handshake makes **exactly 5** rate-limited requests (`/app/pair`,
`/app/session/begin`, `/app/session/complete`, `/app/unlock/begin`, `/app/unlock/complete`). So one
successful login exhausts the 15-minute budget, and any reconnect within 15 min returns **429** —
which the Rust client maps (any status ∉ {400,401,403,404,410}) to `network` → `offTunnel` →
"Can't reach your brain. Check the tunnel/connection." (misleading; the brain is up).
- The per-IP limiter was already flagged "architecturally N/A for single-owner loopback" (status 2026-06-28).
- **Dev-unblock applied:** `rate_limited()` now exempts loopback peers (127.0.0.1/::1/localhost); the
  limiter still protects any remote (tailnet/prod) peer. Marked for planning review.
- **Planning options to decide:** per-endpoint budgets vs. a much higher global budget vs. count the
  whole handshake as one attempt vs. keep the loopback exemption as the canonical answer. Also: the
  Rust client should map 429 to a distinct "rate limited / try again shortly" error, not `offTunnel`.

## Finding 3 — Brain default layout vs client taxonomy + coordinate space
`app_layout_store.default_layout()` seeds 11 cards on a small grid (`x∈{0,2,4,6}`, `y∈0..6`, `w=h=2`)
with domain ids `calendar, tasks, email, messages, projects, notes, recipes, finance, health, home,
travel`. The client (`client/src/domains.ts`, `client/src/world/clusters.ts`) uses world-pixel
coordinates around `CORE=(1300,880)` and a **different** 11-domain set: `email, people, schedule,
tasks, projects, travel, memory, knowledge, review, health, finance`.
- Two mismatches: (a) **coordinates** — brain's `0..6` grid units land all cards in the extreme
  top-left, ~900px off-screen from the camera-centered core → "empty map"; (b) **taxonomy** — 5 brain
  ids (`calendar, messages, notes, recipes, home`) aren't client `DomainId`s (and 5 client ids have no
  brain card). Only 6 overlap.
- The client does NOT filter unknown-domain cards (`layoutBridge.validCards`), so it would place the
  brain's cards verbatim — but off-screen.
- **Workaround (no code):** the client's **Reset layout** top-bar button calls the client's own
  `defaultPlacements()` (correct coords + valid domains) and persists it to the brain.
- **Planning to decide:** which side owns the default layout + domain taxonomy. Recommended: the
  **client** owns world geometry/taxonomy; the brain's `default_layout()` should either be removed in
  favor of a client-seeded PUT, or rewritten to the client's domain ids + a coordinate contract.
  This is the previously-flagged "live-mapping pass."

## Finding 4 — Ask hotkey collides with Windows
`client/src-tauri/src/lib.rs` registered the global Ask shortcut as `Alt+Space`, which is the Windows
OS window-menu accelerator — Windows swallows it, so the popup never summons via hotkey.
- A visible **"Ask" button** exists in the top bar (`App.tsx:157`), so the popup is reachable.
- **Dev-unblock staged (not yet applied):** change the global shortcut to **Ctrl+Alt+Space**. Held
  because editing `lib.rs` forces a `tauri dev` rebuild mid-poke; apply at the next client restart.
- **Planning to decide:** the canonical cross-platform Ask chord (and whether it should be
  user-configurable). Runbook (`docs/technical/setup/live-bring-up-runbook.md`) still says ⌥Space/Alt+Space — update when the chord is finalized.

## Finding 5 — Per-domain live reads unbuilt for 10/11 domains (the main gap)
Each detail screen reads via `useDomainRead` → `invoke(ROUTE[domain])` (`client/src/screens/`).
`ROUTE` names Rust commands `app_finance_read`, `app_tasks_read`, `app_gmail_read`,
`app_calendar_read`, `app_projects_read`, `app_people_read`, `app_memory_read`, `app_knowledge_read`,
`app_travel_read`, `app_health_read`, `app_review_pending`. In the Rust `invoke_handler`
(`lib.rs`), **only `app_review_pending` is registered** — the other ten commands don't exist. So
every card except **Review** rejects at `invoke` → `useDomainRead` catch → "Data not yet available
for this domain."
- The detail **screens themselves are built and registered** for all 11 domains
  (`client/src/screens/registry.ts`): bespoke for `email/schedule/tasks/projects/finance/review`,
  `GenericDomainDetail` placeholder for `people/travel/memory/knowledge/health`.
- `useDomainRead.defaultReader` carries a code comment confirming the live wiring is deferred:
  "CLIENT-b live shapes are currently simpler than the locked screen DTOs. The real wire-to-screen
  mapping is deferred."
- **No `glance:` components registered** — the on-map card faces are placeholder "count" tiles
  (`GlanceFace.tsx`); rich UI is in the detail view (open a card).
- **Planning to scope:** (a) the 10 missing Rust read commands, (b) the matching brain read endpoints
  (`/app/{domain}` — `calendar`, `tasks`, `projects` exist; finance/gmail/people/memory/knowledge/
  travel/health need checking), (c) the brain-DTO → locked-screen-DTO mapping, (d) optionally the
  glance-face content. This is the bulk of the remaining client work.

## Finding 6 — Scope clarifications surfaced while poking (not bugs)
- **No theme selector (by design, but no dev override).** Theming is ambient/automatic
  (`AmbientProvider` → `resolveCell(new Date())`, season × time-of-day, re-checked each minute;
  `src/theme/ambient.ts` + `palettes.ts`). `resolveCell` gates to **verified** palette cells and skips
  draft ones, so several season/time combos fall back. There is no manual override/preview UI — you
  can't see other palettes without changing the system clock. **Planning:** consider a dev-only theme
  override/preview toggle for testing the ~16-cell grid; finalize which draft palettes get verified.
- **Card iconography unbuilt.** No per-domain icons/glyphs exist. Only the **Dock** shows 2-letter text
  abbreviations (`domainLabel(...).slice(0,2)`); map cards show placeholder count tiles
  (`GlanceFace`). Same deferred bucket as the glance-content half of Finding 5. **Planning:** spec the
  per-domain symbol/icon set alongside the glance-face content.

## Finding 7 — Visual polish + "launch & demo cleanly" workstream (owner, live session)
Surfaced rapid-fire while poking. Two were fixed live; the rest are a coherent demo-readiness pass
for planning (several are BIG forks — auth/packaging — so not hot-patched).

Fixed live (committed):
- **Neural-web pulses misaligned** — comet keyframes had `translateX(-18→18px)` drift riding the
  pulse off the static curve. Removed; clip-path reveal alone travels along the line. `ab0f19b`.
- **No card hover emphasis** — `.world-card` had no `:hover` rule (designed, never built). Added an
  on-brand hover/focus emphasis (border + glow + lift), reduced-motion safe. `ab0f19b`. (Reconcile the
  exact feel against the mockup/design-brief in planning.)

For planning (the demo-readiness pass — recommend specc'ing as one milestone):
- **Dev demo mode / dummy data.** Detail screens were built against fake DTOs (`screens.test.tsx`);
  the live reads are unbuilt (Finding 5). A runtime "demo mode" that injects fake DTOs into
  `useDomainRead` would let all 11 modules be seen populated. Small build; high evaluation value.
- **Single-click launch (no 2 terminals).** Today = brain (Terminal A, needs a real console for the
  Hello prompt) + client (Terminal B). Owner wants one `.exe`. Tauri-sidecar bundling was REJECTED
  (would silence proactivity, ADR-033 §Refinement). Real path = brain as a background service the
  client launches/supervises; the Windows Hello-needs-a-console constraint must be solved (service
  account vs. a first-run unlock window). Packaging + runtime design.
- **Default / auto pairing code.** Owner wants to skip mint-and-copy each launch. Options: a fixed
  dev pairing code (auth change, dev-slot only), auto-mint+prefill the pairing field, or persist the
  paired session so reconnect skips pairing entirely. Auth-side; pairs with the Finding 2 rate-limit
  and the reconnect UX.
- **Theme edit/preview.** No in-app picker (ambient by design); palettes in `src/theme/palettes.ts`.
  A dev-only override/preview to step through the ~16 cells would help (Finding 6).

## Dev-unblockers applied this session (mark for ratification, not the real fixes)
- Loopback exemption in `rate_limited()` (Finding 2) — `src/artemis/api_app.py` (applied; effect on brain restart).
- Ask hotkey → Ctrl+Alt+Space (Finding 4) — `client/src-tauri/src/lib.rs` (STAGED; apply at next client restart).
- NeuralWeb crash fix (Finding 1) — already a proper fix, committed `c6a8e57`.

Findings 3 and 5 were NOT hot-patched (real contract/build work → planning).

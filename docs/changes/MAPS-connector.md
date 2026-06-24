---
spec: maps-connector
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave R · NEW · de-park Maps (ADR-021 dependency #4; C3/I-3). Maps/travel-time connector for
     airport-timing blocks. CRITICAL dev/Mac split: real API key is owner-present on the Mac; on the
     8GB dev box it is FAKED (FakeMapsConnector) so build/test never needs a key (R3 mitigation).
     Degrades to a fixed-buffer guess (intl 3h / domestic 1.5h, from X3) without the connector. -->

# Spec: MAPS-connector — travel-time connector (Distance Matrix) for airport-timing blocks, dev-faked / Mac-real

**Identity:** A thin travel-time connector behind a `MapsConnector` protocol: `GoogleMapsConnector` (real Distance Matrix, Mac-gated, owner-present key) and `FakeMapsConnector` (dev — deterministic fixed durations), with a `FixedBufferFallback` that yields the X3-configured intl/domestic buffer when no connector is available — so airport-leave blocks degrade gracefully and the dev box never needs a real key.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (dependency #4 — de-park Maps) · docs/findings/cluster-decisions/DECISIONS-LOG.md (C3 location+optional buffer; I-3 Maps faked on dev, real on Mac) · docs/findings/cluster-spec-roadmap.md Risk R3.

## Assumptions

- **X3-runtime-config** complete: `get_runtime_config().reaction.maps_intl_buffer_minutes` (180) and `.maps_domestic_buffer_minutes` (90) are the fixed-buffer fallbacks. → impact: Stop (the fallback reads these; no hardcoded buffer constants).
- **Dev/Mac split is load-bearing (R3):** the real Distance Matrix API key is owner-present on the Mac ONLY. On the dev box, the connector is the `FakeMapsConnector` — build + tests run fully without any key or network. The composition root selects the implementation (real vs fake vs fallback); MAPS-connector NEVER hard-requires a key at import or test time. → impact: Stop (a test that needs a real key is a build-breaker on the 8GB box — forbidden).
- **The connector is a pure travel-time lookup** — `travel_time(origin, dest, *, mode, depart_at=None) -> Duration`. It does NOT own the airport-block creation (that is the Wave-R planning recipe, which calls this connector then `calendar.schedule_task`/`create_from_extract`). MAPS-connector is the data source + its fallback. → impact: Caution (keep it a connector; the block-creation reaction consumes it).
- **Graceful degrade chain:** real connector available → use it; else fixed-buffer fallback (intl vs domestic chosen by the route classification the caller passes). A connector failure (network/quota) at call time also falls back to the fixed buffer — never raises to the caller (an airport block is better with a guessed buffer than not at all). → impact: Stop.
- **The API key (Mac) is read from the environment / secrets layer (`inject_env.py`), NOT from `Settings` or `policy.json`** — it's a secret, so it follows the M0-a no-secrets-in-Settings rule (same as `BRAVE_API_KEY`). The `GoogleMapsConnector` reads `MAPS_API_KEY` from env at construction; absence → the composition root does not build it (uses the fallback). → impact: Stop (no secret in `policy.json`).
- Off-hardware: `FakeMapsConnector` returns deterministic durations; `FixedBufferFallback` reads X3. → impact: Low.

Simplicity check: considered building the airport-block reaction here too — rejected; that's a planning recipe (Wave R) that *uses* this connector. Considered caching travel-time results — rejected; airport blocks are infrequent and the route is time-dependent (a stale cache is wrong), so a per-call lookup with a fallback is the minimum. No new heavy dep — Distance Matrix is one HTTPS GET via the existing httpx client.

## Prerequisites

- Specs complete: **X3-runtime-config** (buffer fallbacks). **M0-d** (the httpx/port conventions for the real connector). **M0-f** (`inject_env` secret handling — for the Mac key).
- Environment: no new PyPI deps (httpx already present); the real connector is Mac-gated.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/travel/__init__.py` | create | package marker + re-exports (`MapsConnector`, `GoogleMapsConnector`, `FakeMapsConnector`, `FixedBufferFallback`, `Duration`, `travel_time_or_buffer`) |
| `/Users/artemis-build/artemis/src/artemis/modules/travel/maps.py` | create | `MapsConnector` protocol + `GoogleMapsConnector` (Mac) + `FakeMapsConnector` (dev) + `FixedBufferFallback` + `travel_time_or_buffer` degrade helper |
| `/Users/artemis-build/artemis/tests/test_maps_connector.py` | create | fake-connector duration; fixed-buffer fallback intl/domestic from X3; degrade-on-failure; no-key path uses fallback |

All paths under `/Users/artemis-build/artemis/`.

(Note: `src/artemis/modules/travel/` is shared with TRIP-entity's optional travel home; if TRIP-entity placed Trip under `memory/`, the `travel/` package here is new — confirm no collision; both can coexist, Trip in memory, Maps in travel.)

## Tasks

- [ ] **Task 1: `MapsConnector` protocol + `Duration` + the connectors** — files: `/Users/artemis-build/artemis/src/artemis/modules/travel/maps.py` —

  ```python
  @dataclass(frozen=True)
  class Duration:
      minutes: int
      source: Literal["maps", "fixed_buffer"]   # provenance — the caller surfaces "estimated" when fixed

  class RouteClass(StrEnum):
      INTERNATIONAL = "international"
      DOMESTIC = "domestic"

  class MapsConnector(Protocol):
      async def travel_time(self, origin: str, dest: str, *, mode: str = "driving",
                            depart_at: str | None = None) -> Duration: ...
  ```

  `class GoogleMapsConnector` (Mac-gated): constructed with `(api_key: str, *, client: httpx.AsyncClient | None = None)`. `async def travel_time(...)`: one Distance Matrix HTTPS GET (`https://maps.googleapis.com/maps/api/distancematrix/json`), parse the duration → `Duration(minutes=..., source="maps")`. On any HTTP/parse error raise `MapsConnectorError` (the degrade helper catches it). Binds only to the Google host. NEVER logs the API key.

  `class FakeMapsConnector` (dev/test): constructed with `(fixed_minutes: int = 35)`. `async def travel_time(...)` returns `Duration(minutes=self.fixed_minutes, source="maps")` deterministically — no network, no key.

  — done when: `uv run mypy --strict src` passes; `await FakeMapsConnector(fixed_minutes=40).travel_time("home","airport")` returns `Duration(40, "maps")`; `_check: MapsConnector = GoogleMapsConnector("k")` type-checks; importing the module performs no network and needs no key.

- [ ] **Task 2: `FixedBufferFallback` + `travel_time_or_buffer` degrade helper** — files: `/Users/artemis-build/artemis/src/artemis/modules/travel/maps.py` —

  ```python
  class FixedBufferFallback:
      """Yields the X3-configured airport buffer when no Maps connector is available or it fails."""
      def buffer(self, route_class: RouteClass) -> Duration:
          cfg = get_runtime_config().reaction
          minutes = (cfg.maps_intl_buffer_minutes if route_class is RouteClass.INTERNATIONAL
                     else cfg.maps_domestic_buffer_minutes)
          return Duration(minutes=minutes, source="fixed_buffer")

  async def travel_time_or_buffer(
      connector: MapsConnector | None,
      origin: str,
      dest: str,
      *,
      route_class: RouteClass,
      mode: str = "driving",
      depart_at: str | None = None,
  ) -> Duration:
      """Degrade chain: connector present → try it; on None or any failure → fixed buffer (never raises)."""
      fallback = FixedBufferFallback()
      if connector is None:
          return fallback.buffer(route_class)
      try:
          return await connector.travel_time(origin, dest, mode=mode, depart_at=depart_at)
      except Exception:
          logging.getLogger("travel.maps").warning("Maps lookup failed — using fixed buffer (%s)", route_class.value)
          return fallback.buffer(route_class)
  ```

  — done when: `uv run mypy --strict src` passes; `await travel_time_or_buffer(None, "a","b", route_class=INTERNATIONAL)` returns `Duration(180, "fixed_buffer")` (from X3 default); with a `FakeMapsConnector` returns the fake's `Duration(..., "maps")`; with a connector whose `travel_time` raises → falls back to the buffer without raising.

- [ ] **Task 3: Tests** — files: `/Users/artemis-build/artemis/tests/test_maps_connector.py` — typed pytest (async tests under the project's async convention).

  - **Fake duration:** `await FakeMapsConnector(fixed_minutes=42).travel_time("h","a")` → `Duration(42, "maps")`.
  - **Fallback intl/domestic from X3:** with a `Settings(data_root=tmp_path)` + monkeypatched `get_runtime_config` returning defaults → `FixedBufferFallback().buffer(INTERNATIONAL).minutes == 180`, `...DOMESTIC...minutes == 90`; both `source == "fixed_buffer"`.
  - **No-connector path:** `await travel_time_or_buffer(None, ...)` → the fixed buffer (asserts the dev box needs no key).
  - **Connector-success path:** `await travel_time_or_buffer(FakeMapsConnector(30), ...)` → `Duration(30, "maps")`.
  - **Degrade-on-failure:** a stub connector whose `travel_time` raises → `travel_time_or_buffer` returns the fixed buffer, does not raise; one warning logged (no key in the log).
  - **Custom buffer via X3 override:** monkeypatch `get_runtime_config` to return `maps_intl_buffer_minutes=200` → the intl buffer is 200 (proves X3-tunable).

  — done when: `uv run pytest -q tests/test_maps_connector.py` passes AND `uv run mypy --strict src tests/test_maps_connector.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 4 (GATED — on-hardware, owner-present, Mac):** With `MAPS_API_KEY` injected on the Mac, `GoogleMapsConnector(key).travel_time("<home>","<Changi T1>", mode="driving")` returns a real `Duration(source="maps")`; removing the key → the composition root builds no connector and the airport-block reaction uses the fixed buffer. Confirm the key never appears in logs. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/modules/travel/__init__.py` |
| Create | `/Users/artemis-build/artemis/src/artemis/modules/travel/maps.py` |
| Create | `/Users/artemis-build/artemis/tests/test_maps_connector.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_maps_connector.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_maps_connector.py` | Test gate (fakes only; no key, no network) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/travel/__init__.py`, `src/artemis/modules/travel/maps.py`, `tests/test_maps_connector.py` |
| `git commit` | `"feat: MAPS-connector — travel-time connector (dev-faked / Mac-real) + fixed-buffer degrade"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `MAPS_API_KEY` | Distance Matrix key — Mac-gated, owner-present; absent off-hardware (fallback used) |
| `ARTEMIS_ENV_FILE` | Settings (for X3 buffer config resolution) |

### Network
| Action | Purpose |
|--------|---------|
| HTTPS to `maps.googleapis.com` (GATED, Mac only) | Distance Matrix travel-time lookup |
| (none off-hardware) | Dev tests use the fake; no network |

## Specialist Context

### Security

- The Maps API key is a **secret** — read from the environment via the M0-f `inject_env` path, NEVER from `Settings` or `policy.json` (M0-a no-secrets-in-Settings rule). `GoogleMapsConnector` holds it only as an instance field; it is never logged. Absence of the key → no connector built → fixed-buffer fallback (no failure).
- The connector makes an **external network call** to Google with origin/destination strings — these are owner location data. On the Mac the owner is present; on dev the fake makes no call. The degrade helper never sends data when no connector is configured. [apex-security note: confirm origin/dest are not logged at info; confirm the key is not in any error string or log.]
- No owned data is written by this spec (it's a read-only connector) — `cross_model_review` not required.

### Performance

- One HTTPS GET per airport-block computation (infrequent — only when assembling a travel reaction). The fallback is a constant lookup. No caching (route times are time-dependent; a stale cache would mislead).

### Accessibility

(none — no frontend)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/travel/maps.py` | Document the dev-faked / Mac-real split, the degrade chain (connector → fixed buffer, never raises), the X3 buffer source, and the secret-from-env key rule |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_maps_connector.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_maps_connector.py` → verify: fake duration; fixed-buffer intl=180/domestic=90 from X3; no-connector → fallback; connector-success → maps source; degrade-on-failure → fallback without raising; X3 override changes the buffer. Tests need NO key and NO network.
- [ ] `uv run python -c "from artemis.modules.travel import FakeMapsConnector, FixedBufferFallback, travel_time_or_buffer; print('ok')"` → verify: prints `ok`.
- [ ] (GATED, Mac, owner-present) real Distance Matrix lookup; key absent → fallback; key never logged → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

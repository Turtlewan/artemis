---
spec: cb5b-3-refresh-backend
status: draft
token_profile: lean
autonomy_level: L5
coder_effort: high
cross_model_review: true
---

# Spec: Proactive pending-count refresh subsystem (CB-5b Phase 2, brain)

**Identity:** A consent-gated background-refresh subsystem: a capability opted into refresh is run on an interval by the existing Scheduler, emits a structured `{count, items}`, and its latest count+items are cached brain-side for the map node + overlay to read.
→ why: see docs/technical/adr/ADR-045-capability-map-nodes.md (decisions 5–6)

## Assumptions
- Reuse the existing `Scheduler` (src/artemis/ports/scheduler.py) + its heartbeat — register one recurring `ScheduledJob` per opted-in capability; do NOT build a new scheduler → impact: Stop
- The refresh dispatch runs the capability through the SAME invoke/sandbox path (FetchSandbox, secret injection) as a normal invoke — a refresh IS a credentialed run, so it is consent-gated (opt-in), never automatic → impact: Stop
- The refresh-output contract is a small JSON `{"count": int, "items": [{"title": str, "detail": str}]}` on the tool's stdout; parsed fail-soft (unparseable/absent → count 0, keep last-known) → impact: Stop
- Refresh output is UNTRUSTED external content — it is cached as data and rendered as data; it never re-enters a model/tool context without the existing quarantine → impact: Stop

Simplicity check: considered a bespoke poller — rejected; the durable Scheduler already fires recurring jobs and survives restart.

## Prerequisites
- `cb5b-1-capability-metadata` (capabilities DTO exists). Invoke path (`invoke.py`, ADR-039) present. **Overlaps `capability_routes.py`/`invoke.py` with verify-auth/oauth — sequence after those or fold into the consolidated metadata spec for the DTO field.**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/refresh.py | create | the refresh runner: invoke a capability → parse `{count,items}` fail-soft → write cache |
| src/artemis/capabilities/refresh_cache.py | create | per-capability `{count, items, refreshed_at}` cache (atomic JSON under ARTEMIS_DATA_DIR; fresh-read, fail-closed to count 0 on read error) |
| src/artemis/capabilities/refresh_optin.py | create | the consent opt-in store (which capabilities+versions are opted into refresh + interval); version-scoped like bless |
| src/artemis/api/refresh_routes.py | create | `POST /app/capabilities/{name}/refresh-optin` (enable/disable+interval), and expose `pending_count`+items on the capabilities/overlay DTO |
| src/artemis/api/app.py | modify | wire the refresh runner + optin store + register scheduled jobs on the Scheduler at startup |
| tests/capabilities/test_refresh.py, test_refresh_cache.py, tests/api/test_refresh_routes.py | create | contract-parse fail-soft, cache fresh-read/fail-closed, optin version-scope, route gating |

## Tasks
- [ ] Task 1: Refresh cache (`refresh_cache.py`) — per-capability `{count:int, items:list, refreshed_at:str}` in an atomic JSON store under ARTEMIS_DATA_DIR; `get(name)->entry|None` (fresh-read each call; unreadable/corrupt → return None = count 0, never raise); `put(name, count, items)`. — files: src/artemis/capabilities/refresh_cache.py, tests/capabilities/test_refresh_cache.py — done when: put/get round-trips; a corrupt file reads back None (fail-soft), never raises.
- [ ] Task 2: Refresh opt-in store (`refresh_optin.py`) — version-scoped opt-in (name→{version, interval_s}); `is_opted_in(name, version)`, `set/clear`. Mirror the bless version-scoping (a rebuild drops the opt-in). Fail-closed: read error → not opted in. — files: src/artemis/capabilities/refresh_optin.py, tests/capabilities/test_refresh.py — done when: opt-in for (name,v1) is not honored after the capability rebuilds to v2; read error → not opted in.
- [ ] Task 3: Refresh runner (`refresh.py`) — given a capability name: if opted-in, run it through the invoke/FetchSandbox path (resolving its secrets exactly as invoke does; fail-closed on missing secrets — skip + log, no crash), read stdout, parse `{count,items}` fail-soft, `refresh_cache.put`. Return a small result; NEVER push to transport (unlike ProactiveWorker) and NEVER log item content or secrets. — files: src/artemis/capabilities/refresh.py, tests/capabilities/test_refresh.py — done when: a stubbed sandbox returning `{"count":3,"items":[…]}` caches count 3; malformed output caches count 0 keeping last-known; missing-secret capability is skipped without raising.
- [ ] Task 4: Routes + scheduler wiring — `refresh_routes.py`: `POST /app/capabilities/{name}/refresh-optin {enabled, interval_s}` (session-gated); expose `pending_count` (from cache, 0 if none) + an items endpoint on the capabilities/overlay DTO. `app.py`: at startup, for each opted-in capability register a recurring `ScheduledJob` whose dispatch calls the refresh runner; re-register on opt-in change. — files: src/artemis/api/refresh_routes.py, src/artemis/api/app.py, tests/api/test_refresh_routes.py — done when: opting a capability in registers a scheduled refresh; `GET /app/capabilities` shows its `pending_count` from cache; opting out cancels the job.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3] | Wave 3: [Task 4]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/capabilities/refresh.py, refresh_cache.py, refresh_optin.py, src/artemis/api/refresh_routes.py, tests/capabilities/test_refresh.py, test_refresh_cache.py, tests/api/test_refresh_routes.py |
| Modify | src/artemis/api/app.py |
### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` / `uv run ruff check src/ tests/` / `uv run pytest -q` | full gate |
### Git Operations
| Operation | Scope |
|-----------|-------|
| `git commit` | "feat(capabilities): consent-gated proactive refresh for map pending-counts (CB-5b)" |

## Specialist Context
### Security
**BLOCKER: apex-security review pending — do not mark ready until run.** This runs credentialed capabilities on a timer. Invariants: refresh runs ONLY for capabilities the owner opted in (version-scoped; a rebuild drops the opt-in); it reuses the existing sandbox + secret injection (no new credential path); refresh output is untrusted (cached as data, quarantined before any model use); missing-secret refresh fails closed (skip, no crash, no partial run); the cache/opt-in stores fail-closed on read error (count 0 / not opted-in); never log item content or secret values. `cross_model_review: true`.

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Changelog | CHANGELOG.md | Unreleased/Added — proactive pending-count refresh |
| ADR | docs/technical/adr/ADR-045-capability-map-nodes.md | written at planning |

## Acceptance Criteria
- [ ] Stubbed sandbox returns `{"count":3,"items":[{"title":"a","detail":"b"}]}` → cache holds count 3; `GET /app/capabilities` shows `pending_count==3`.
- [ ] Malformed/empty refresh output → cached count 0, last-known items retained; no exception.
- [ ] A capability NOT opted in is never scheduled/run; opting in registers a Scheduler job; opting out cancels it.
- [ ] Opt-in for (name, v1) is not honored after rebuild to v2 (version-scoped).
- [ ] Missing-secret capability refresh is skipped (fail-closed), not run, no crash; no secret/item content in logs.
- [ ] Corrupt cache/opt-in file → count 0 / not-opted-in (fail-closed), never raises.
- [ ] `uv run mypy`/`ruff`/`pytest -q` green.

## Progress
_(Coding mode writes here)_

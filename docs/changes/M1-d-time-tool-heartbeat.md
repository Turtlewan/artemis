---
spec: m1-d-time-tool-heartbeat
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M1-d — `get_current_time` trivial tool (manifest-contract proof) + Heartbeat skeleton + end-to-end brain acceptance test

**Identity:** Implements the one trivial tool `get_current_time` as a full instance of the M1-a manifest contract (typed args/return + callable + manifest factory) to validate manifest → registry → router → typed dispatch → response end-to-end, plus the Heartbeat skeleton (a scheduler that ticks, silent-success `HEARTBEAT_OK`, no real hooks), and the milestone end-to-end acceptance test wiring the whole brain.
→ why: see docs/technical/architecture/brain.md § "Tool registry" (the manifest contract a module implements) + § "Proactive engine (Heartbeat)" (scheduled-tick, silent-success `HEARTBEAT_OK`, zero idle tokens).

<!-- Split rule: TWO logical phases (1: the time tool/module; 2: the Heartbeat skeleton) + the milestone end-to-end test (which proves Phase 1, per the brief: the e2e test belongs with the spec whose task it proves — the time tool IS the end-to-end proof). 3 new src files + 1 test. At the 2-phase / file limit; kept together because both are the smallest "module-shaped" pieces and the time tool is the tool the Heartbeat-adjacent loop and the e2e test both exercise. If review wants leaner: sub-split into M1-d1 (time tool + e2e test) and M1-d2 (heartbeat skeleton). Flagged per rules. -->

## Assumptions
- M0-a (config), M0-d (ports), M1-a (`ModuleManifest`/`ToolSpec`/`ActionRisk`/`DataScope`/`Permissions`, `ToolRegistry`), M1-b (`SemanticRouter`, `Brain`), M1-c (`compose_brain`/`Gateway`) complete. → impact: Stop (the tool implements M1-a's contract and is consumed by M1-b/M1-c; the e2e test wires all of them).
- `get_current_time` is **pure, no data, no auth**: `action_risk = ActionRisk.NO_DATA`, `data_scope = DataScope.SHARED`, `permissions` owner+guest both allowed. It returns the current local time; its only input is an optional IANA timezone string. → impact: Low (it exists solely to validate the pipeline; trivially safe).
- M1-c's `compose_brain` imports this module's manifest factory by the name `artemis.tools.time_tool.manifest`. → impact: Stop (the factory name + module path are the contract M1-c's try/except-ImportError expects; must match exactly: module `src/artemis/tools/time_tool.py`, function `manifest() -> ModuleManifest`).
- The Heartbeat skeleton ticks on a fixed interval, runs zero real hooks in M1, and on every tick produces the silent-success signal `HEARTBEAT_OK` (logged, not delivered — ntfy delivery is a later milestone). → impact: Low (skeleton-only per the brief; no real proactive_hooks).
- The Heartbeat scheduler uses `asyncio` (an `async` tick loop with `asyncio.sleep`), runnable standalone and cancellable; it is NOT wired into the launchd daemon in M1 (a future spec adds the daemon hook). → impact: Caution. Decision: M1 ships the Heartbeat as a standalone importable `Heartbeat` class with `run_forever()` + `tick()`, NOT wired into the brain process or launchd in M1 (a future spec mounts it). M1 only proves `tick()` emits `HEARTBEAT_OK`.

Simplicity check: considered making `get_current_time` take rich args (format strings, locales) — rejected; brain.md/the brief want the *minimum* tool that proves the contract end-to-end. One optional `tz` arg is enough. Considered a real scheduler library (APScheduler) for the Heartbeat — rejected for M1; an `asyncio` tick loop is the minimum skeleton that "ticks + silent-success" without a dependency. Considered putting the e2e test in M1-b — placed here because the brief says the e2e test belongs with the spec whose task it proves, and the time tool is the artifact that makes the whole pipeline real.

## Prerequisites
- Specs that must be complete first: M0-a, M0-d, M1-a, M1-b, M1-c (the e2e test exercises the composed brain from M1-c).
- Environment setup required: none beyond M0/M1-a/b/c. The tool + heartbeat are pure Python; the e2e test runs against fake model/embedder adapters (deterministic) — no on-hardware gate. (The live-model end-to-end run is M1-b's gated Task 5.)

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/tools/__init__.py | create | tools package marker |
| /Users/artemis-build/artemis/src/artemis/tools/time_tool.py | create | `get_current_time` callable + args/return Pydantic models + `manifest() -> ModuleManifest` |
| /Users/artemis-build/artemis/src/artemis/heartbeat.py | create | `Heartbeat` skeleton: `tick()` → `HEARTBEAT_OK`; `run_forever()` async loop |
| /Users/artemis-build/artemis/tests/test_time_tool_heartbeat.py | create | unit tests for the tool + heartbeat |
| /Users/artemis-build/artemis/tests/test_e2e_brain.py | create | milestone end-to-end: manifest→registry→router→dispatch→response |

## Tasks
- [ ] Task 1: Implement the `get_current_time` tool as a manifest-contract instance — files: `/Users/artemis-build/artemis/src/artemis/tools/__init__.py`, `/Users/artemis-build/artemis/src/artemis/tools/time_tool.py` — in `time_tool.py`:
  - `class TimeArgs(BaseModel)`: `tz: str | None = Field(default=None, description="IANA timezone name, e.g. 'Asia/Singapore'; None → system local time")`.
  - `class TimeResult(BaseModel)`: `iso: str` (ISO-8601 timestamp), `tz: str` (the resolved zone name).
  - `def get_current_time(args: TimeArgs) -> TimeResult`: resolve the zone via `zoneinfo.ZoneInfo(args.tz)` when given (catch `ZoneInfoNotFoundError` → raise `ValueError`), else system local; return `TimeResult(iso=now.isoformat(), tz=<resolved name>)`. Pure except reading the clock; no data, no auth, no I/O beyond the clock.
  - `def manifest() -> ModuleManifest`: return a `ModuleManifest(name="time", version="0.1.0", description="Time utilities: current time in any timezone.", data_scope=DataScope.SHARED, permissions=Permissions(owner=True, guest=True), tools=[ToolSpec(name="get_current_time", description="Get the current date and time, optionally in a specific timezone.", args_schema=TimeArgs, return_schema=TimeResult, callable_ref=get_current_time, action_risk=ActionRisk.NO_DATA)], proactive_hooks=[], ui=UiSurface())`.
  — done when: `uv run mypy --strict src` passes and `manifest().tools[0].callable_ref(TimeArgs()).iso` is a parseable ISO timestamp.

- [ ] Task 2: Implement the Heartbeat skeleton — files: `/Users/artemis-build/artemis/src/artemis/heartbeat.py` — `class Heartbeat` constructed with `interval_seconds: float = 60.0` and an optional injected logger. `def tick(self) -> str`: run zero hooks (M1 has none), return the constant `HEARTBEAT_OK` (define `HEARTBEAT_OK: Final = "HEARTBEAT_OK"`); log at debug "heartbeat tick: silent success" (zero idle tokens — no LLM call). `async def run_forever(self, *, max_ticks: int | None = None) -> None`: loop calling `tick()` then `await asyncio.sleep(self.interval_seconds)`, stopping after `max_ticks` ticks if given (so tests don't run forever), cancellable via `asyncio.CancelledError`. NO real `proactive_hooks` execution, NO ntfy, NO LLM. — done when: `uv run mypy --strict src` passes and `Heartbeat().tick() == "HEARTBEAT_OK"`.

- [ ] Task 3: Write the tool + heartbeat unit tests — files: `/Users/artemis-build/artemis/tests/test_time_tool_heartbeat.py` — typed pytest:
  - time tool: `get_current_time(TimeArgs())` returns a `TimeResult` whose `iso` parses via `datetime.fromisoformat`; `get_current_time(TimeArgs(tz="Asia/Singapore")).tz == "Asia/Singapore"`; an invalid tz (`TimeArgs(tz="Not/AZone")`) raises `ValueError`.
  - manifest contract: `manifest().name == "time"`; the single tool's `action_risk is ActionRisk.NO_DATA`; `args_schema is TimeArgs`; `callable(manifest().tools[0].callable_ref)`.
  - heartbeat: `Heartbeat().tick() == "HEARTBEAT_OK"`; `asyncio.run(Heartbeat(interval_seconds=0.0).run_forever(max_ticks=3))` completes (no exception) and the loop ran exactly 3 ticks (assert via a counter/spy or the logger).
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_time_tool_heartbeat.py` passes.

- [ ] Task 4: Write the milestone end-to-end brain test — files: `/Users/artemis-build/artemis/tests/test_e2e_brain.py` — typed pytest proving the full M1 pipeline with deterministic fakes (`FakeEmbedder` + `FakeModelPort` from the M1-a/M1-b test patterns — the `FakeModelPort.complete` returns, for the time tool's `args_schema`, a JSON `{"tz": null}` valid for `TimeArgs`):
  - build a real `ToolRegistry(FakeEmbedder())`, `registry.register(time_tool.manifest())` (the REAL manifest + REAL callable, not a stub).
  - build a real `SemanticRouter(registry, FakeEmbedder())` and a real `Brain(router, registry, FakeModelPort())`.
  - `r = await brain.respond("what time is it", "owner-private")` → assert `r.tool_used == "time.get_current_time"`, `r.escalated is False`, and `r.text` contains a parseable ISO timestamp produced by the REAL `get_current_time` callable (proving manifest→registry→router→typed-dispatch→response works end to end with the real tool).
  - also drive it through `Gateway` (M1-c): `await Gateway(brain).handle_text("what time is it")` returns the same tool result with `OWNER_SCOPE` attached.
  - negative: `await brain.respond("xyzzy nonsense token", "owner-private")` → `r.escalated is True`, `r.text == "ESCALATION_NOT_AVAILABLE"`.
  — done when: `uv run pytest -q tests/test_e2e_brain.py` passes AND `uv run mypy --strict tests/test_e2e_brain.py` passes — this is the M1 "smallest end-to-end brain" acceptance proof (typed question → think → answer, surfaces + tool included, model faked).

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/tools/__init__.py, /Users/artemis-build/artemis/src/artemis/tools/time_tool.py, /Users/artemis-build/artemis/src/artemis/heartbeat.py, /Users/artemis-build/artemis/tests/test_time_tool_heartbeat.py, /Users/artemis-build/artemis/tests/test_e2e_brain.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_time_tool_heartbeat.py tests/test_e2e_brain.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (tool, heartbeat, end-to-end) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/tools/**, src/artemis/heartbeat.py, tests/test_time_tool_heartbeat.py, tests/test_e2e_brain.py |
| `git commit` | "feat: M1-d get_current_time tool (manifest-contract proof) + heartbeat skeleton + e2e brain test" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Pure in-process; the clock is the only external read |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No new dependencies (stdlib `zoneinfo`/`asyncio`) |

## Specialist Context
### Security
`get_current_time` is `action_risk = NO_DATA`, `data_scope = SHARED`, owner+guest permitted — the safest possible tool, chosen precisely so the pipeline proof carries no scope/risk concerns. The Heartbeat skeleton makes ZERO LLM calls and ZERO deliveries (silent-success only) — no egress surface in M1. [FLAG apex-security at the heartbeat-hooks milestone: real `proactive_hooks` + ntfy delivery introduce an egress + injection surface to threat-model then.]

### Performance
Heartbeat silent-success = `HEARTBEAT_OK` with zero idle tokens (brain.md). The e2e test uses fakes so it is millisecond-fast and gate-able in CI; the live-model timing is M1-b's gated task.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/tools/time_tool.py, src/artemis/heartbeat.py | Type + docstring all exports; document time_tool as the canonical manifest-contract example a future module copies |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_time_tool_heartbeat.py tests/test_e2e_brain.py` → verify: exit 0.
- [ ] Run `uv run python -c "from artemis.tools.time_tool import manifest, TimeArgs; m=manifest(); print(m.name, m.tools[0].action_risk.value, m.tools[0].callable_ref(TimeArgs()).tz)"` → verify: prints `time no-data <a zone name>`.
- [ ] Run `uv run python -c "from artemis.heartbeat import Heartbeat; print(Heartbeat().tick())"` → verify: prints `HEARTBEAT_OK`.
- [ ] Run `uv run pytest -q tests/test_e2e_brain.py` → verify: the end-to-end test passes — `respond("what time is it")` fires `time.get_current_time` (real callable) and returns a real ISO timestamp; the nonsense query returns `ESCALATION_NOT_AVAILABLE`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_

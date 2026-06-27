---
status: done
weight: light
cross_model_review: false
coder_effort: medium
---

> **BUILT 2026-06-27** (Codex `gpt-5.5`, host-verified). Full `uv run mypy` clean (331 files),
> full `uv run pytest -q` green (893 passed / 6 skipped). All 4 tasks implemented; surgical scope
> (exactly the 6 listed files). Minor notes for review: (a) the lifespan reaches `brain._registry`
> / `brain._model` (private attrs — no public accessor exists; faithful to "don't invent params");
> (b) one full-suite run emitted a benign, non-reproducing faulthandler all-threads dump at teardown
> (heartbeat-task teardown race — cosmetic, suite green both runs); (c) Task 1's live
> `uv run artemis-brain` → `/healthz` 200 check is owner on-box (real win32 lifespan Hello-unlocks);
> import resolves and the launcher binds 127.0.0.1:brain_port as specified.

# win-brain-runtime — runnable brain on Windows + proactive heartbeat in startup (⑤a)

## Intent
Make the brain a runnable service on Windows and turn proactivity on. Today the brain is a
FastAPI app (`artemis.main:app`) with **no Windows launch mechanism** (only the Mac `launchd`
M0-b) and its **proactive heartbeat is never started** (not wired into `main.py` lifespan), so
even a running brain does nothing on its own. This adds a dev-process launcher and starts the
heartbeat as a managed background task — the brain-side half of ⑤ "full compose." Pure Python;
runs on Mac verbatim.

## Key decisions
- **Launch = dev process (uvicorn), NOT a Tauri sidecar.** The proactive heartbeat must keep
  running when the app window is closed (it delivers via ntfy). A sidecar ties the brain's life to
  the app window and would silence proactivity. Dev-process is ADR-033's "lighter interim"; the
  end-state is a **background service** (Windows service ≈ Mac `launchd`/M0-b). Recorded as
  **ADR-033 §Refinement 2026-06-27**. Sidecar rejected.
- **Heartbeat = a cancellable background `asyncio` task** started in the FastAPI lifespan (never
  awaited inline — `run_forever` is an infinite loop), cancelled + awaited on shutdown.
- **Gated + degrade-don't-crash:** `Settings.heartbeat_enabled` (default True) governs whether it
  starts; if the proactive chain can't compose in a bare dev env (no ntfy/model), log a WARNING and
  start the brain anyway — a missing notifier must never block startup.

## Gotchas / edge cases
- The lifespan was just changed by m2-win-b (win32 key-provider branch). The heartbeat starts
  **after** the brain/key_provider setup and **before** `yield`; the cancel+await goes in the
  `finally` after `yield`. Don't disturb the m2-win-b platform branch.
- **Tests that enter the real lifespan must not spin the loop.** `tests/test_gateway_surfaces.py`
  (and any future TestClient-with-lifespan) must run with `heartbeat_enabled=False`, else the
  background task runs during tests. Set it off in their settings.
- `compose_proactive(...)` + `attach_to_heartbeat` build the chain; wire per their actual
  signatures (don't invent params). If they need a notifier/model the bare dev env lacks, the
  degrade-don't-crash guard covers it.
- `run_brain.py` binds **127.0.0.1** only (never `0.0.0.0`) — the brain is loopback-local; the
  client reaches it over localhost (matches the no-network-grant client posture).

## Tasks
1. `scripts/run_brain.py` + `[project.scripts] artemis-brain` — launch `uvicorn artemis.main:app`
   on `host=127.0.0.1`, `port=settings.brain_port`, reload off. — done when: `uv run artemis-brain`
   serves `GET http://127.0.0.1:8030/healthz` → 200.
2. `Settings.heartbeat_enabled: bool = True` in `config.py` (comment: gates the proactive loop;
   off in tests/bare dev). — done when: field present, default True.
3. Wire the heartbeat into `main.py` lifespan: when `heartbeat_enabled`, compose the proactive
   chain (`compose_proactive` + `attach_to_heartbeat`) and start `Heartbeat.run_forever` via
   `asyncio.create_task`; store the task on `app.state.heartbeat_task`; in the post-`yield`
   `finally`, cancel it and `await` (suppressing `CancelledError`). Wrap the compose in a
   try/except that WARN-logs and skips the task on failure (degrade-don't-crash). — done when: with
   `heartbeat_enabled=True` the app logs the heartbeat starting and a unit test asserts the task is
   created on startup and cancelled cleanly on shutdown; with it False (or compose failing) startup
   still completes and serves `/healthz`.
4. Make the lifespan-entering tests heartbeat-safe — set `heartbeat_enabled=False` in
   `tests/test_gateway_surfaces.py`'s `client` fixture settings (the same fixture m2-win-b touched).
   — done when: those 8 tests stay green with no background loop running.

## Files to touch
- `scripts/run_brain.py` — create (uvicorn launcher, 127.0.0.1:brain_port)
- `pyproject.toml` — modify (`[project.scripts] artemis-brain = "artemis.scripts.run_brain:main"` — or a top-level `scripts/` entry consistent with existing console scripts)
- `src/artemis/config.py` — modify (`Settings.heartbeat_enabled`)
- `src/artemis/main.py` — modify (lifespan: start/stop the heartbeat task) — **critical file (production startup); confirm at build**
- `tests/test_brain_runtime.py` — create (heartbeat task starts-when-enabled + cancels-cleanly; degrade-don't-crash on compose failure)
- `tests/test_gateway_surfaces.py` — modify (heartbeat off in the lifespan fixture)

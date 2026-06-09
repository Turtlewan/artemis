---
spec: obs-a-observability-core
status: ready
token_profile: lean
autonomy_level: L3
---

# Spec: OBS-a — Observability core (structured JSON logging + no-PII redaction + `ObservabilitySink` Protocol + error capture + the Brain/distill capture taps)

**Identity:** Builds the local observability foundation: a stdlib-logging JSON setup with a no-PII redaction filter (+ a standalone `redact()`), the `ObservabilitySink` Protocol (`NullSink`/`CompositeSink`) carrying only non-content primitives, an error-capture pillar (`ErrorRecord`/`ErrorStore`/`ErrorCaptureSink`) that redacts before persisting, and the additive default-`NullSink` capture taps in `brain.py` (route decision + degrade-don't-crash sites) and `recipes/distill.py` (escalation + typed errors). Single writer of the brain/distill seam.
→ why: see docs/technical/adr/ADR-008-observability.md.

<!-- Split rule note: 5 creates + 2 additive modifies. Justified atomic grouping: this spec is the single owner of all brain.py/distill.py observability edits (one-writer-per-file) plus the shared substrate (logging + the sink Protocol) every pillar logs through. The telemetry backend that *persists* sink events is a separate spec (OBS-b). Each file is thin and single-concern. Flagged per rules. -->

## Assumptions
- M1-b (`Brain` constructed with `(Router, ToolRegistry, ModelPort)`; `async respond`/`respond_stream`/`pre_route`; `decision = router.route(request_text, scope)` with `decision.path`/`decision.confidence`/`decision.candidate_tools`) and M7-a2 (`async escalate_and_distill(req: EscalationRequest, model, store, *, sandbox=None)`; `EscalationRequest{request_text, scope, task_class_key, is_cloud_safe}`; raises `CloudEgressForbiddenError`/`RecipeReplayError`; exports `task_class_key(decision, request_text) -> str`) are complete and their signatures match exactly. → impact: Stop (the taps are additive edits to these exact signatures).
- The taps are **additive and default to a no-op** (`obs: ObservabilitySink = NullSink()` keyword arg) so every existing M1-b/M7-a2 test that constructs `Brain`/calls `escalate_and_distill` without an `obs` argument still passes unchanged. → impact: Stop (backward-compatibility is the contract that lets us edit two ready specs safely).
- **No content in the Protocol (structural, not by-convention):** `ObservabilitySink` methods carry only non-content primitives — `task_class_key: str`, `confidence: float`, `path: str`, and the exception object. The Brain computes `task_class_key(decision, request_text)` (imported from `artemis.recipes.distill`) BEFORE the tap and passes the resulting key; `request_text` is never passed to a sink. `task_class_key` is already non-reversible (a tool-candidate id, or `sha256(normalise(text))` for no-match). → impact: Stop (this makes the no-content invariant impossible for any future sink to violate; resolves the security BLOCK). `brain.py` importing `task_class_key` from `recipes.distill` is acyclic (`recipes.distill` imports the `ObservabilitySink` Protocol but never `brain`).
- Structured logs go to **stdout as one JSON object per line**; launchd captures stdout to the per-slot `logs/` dir (M0-b deployment). No file handler is opened here. → impact: Low.
- **No-PII rule (absolute, all levels):** logs and error records NEVER carry message content (`request_text`, model output, `Fact` text), credentials, keys, or file paths under a `keys/` dir — at ANY log level (no DEBUG carve-out). Content-named extras are dropped regardless of level; secret-shaped values are redacted. → impact: Stop (privacy invariant enforced by the redaction filter + the no-content Protocol).
- The error pillar is **local-only** (no external SaaS): `ErrorCaptureSink.on_error` writes a structured ERROR log line + appends a redacted `ErrorRecord` to a local append-only JSONL store. → impact: Low.

Simplicity check: considered `structlog` — rejected for lean profile; stdlib `logging` + a `logging.Formatter` subclass emitting JSON + a `logging.Filter` for redaction is dependency-free and sufficient. Considered one combined sink doing both telemetry and errors — rejected; the Protocol + a `CompositeSink` fan-out lets the telemetry concrete (OBS-b) and the error concrete (here) stay single-responsibility and be wired together at composition.

## Prerequisites
- Specs complete first: M0-a (`config`/`paths`), M0-d (`ports` — `RouteDecision`, `ModelResponse`, `Scope`), M1-b (`brain.py`), M7-a2 (`recipes/distill.py` incl. `task_class_key`).
- Environment setup required: none (off-hardware; stdlib only).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/obs/__init__.py | create | package marker + re-exports (`ObservabilitySink`, `NullSink`, `CompositeSink`, `ErrorRecord`, `ErrorStore`, `ErrorCaptureSink`, `configure_logging`, `get_logger`, `RedactionFilter`, `redact`, `JsonFormatter`, `obs_dir`) |
| /Users/artemis-build/artemis/src/artemis/obs/logging.py | create | `configure_logging`, `JsonFormatter`, `RedactionFilter`, `redact`, `get_logger`, `obs_dir` |
| /Users/artemis-build/artemis/src/artemis/obs/sink.py | create | `ObservabilitySink` Protocol + `NullSink` + `CompositeSink` |
| /Users/artemis-build/artemis/src/artemis/obs/errors.py | create | `ErrorRecord` + `ErrorStore` (append-only JSONL) + `ErrorCaptureSink` |
| /Users/artemis-build/artemis/tests/test_obs_core.py | create | logging JSON shape + redaction (incl. error-message redaction + blob boundary), sink no-op/fan-out, error store round-trip, tap wiring against a spy sink |
| /Users/artemis-build/artemis/src/artemis/brain.py | modify | additive `obs` param + route-decision tap (Brain computes the key) + error taps (see Task 5) |
| /Users/artemis-build/artemis/src/artemis/recipes/distill.py | modify | additive `obs` param + escalation tap + typed-error taps (see Task 6) |

## Tasks
- [ ] Task 1: Structured JSON logging + redaction — files: `/Users/artemis-build/artemis/src/artemis/obs/logging.py` —
  - `def obs_dir(s: Settings) -> Path`: `slot_root(s) / "obs"` (compute locally via `from artemis.paths import slot_root`; do NOT edit `paths.py`). Returns a path only; does not create it.
  - `_SECRET_KEY_NAMES`: case-insensitive set of substrings flagging a secret VALUE by its key name — `key`, `token`, `secret`, `password`, `authorization`, `bearer`, `dek`, `ref`, `handle`, `credential`. `_CONTENT_KEY_NAMES`: exact extra-field names always dropped — `content`, `request_text`, `text`, `prompt`, `messages`, `response`.
  - `def redact(value: object) -> object` (standalone, reused by the error store): if `value` is a `str` or `bytes`, return `"***REDACTED***"` when it looks secret — a `bytes` value, OR a `str` of length ≥20 that is entirely base64/hex chars (defence-in-depth, NOT the primary control); else return it unchanged. For a `dict`/`list`, recurse, applying key-name rules to dict items (a dict key whose name matches `_SECRET_KEY_NAMES` → value replaced with `"***REDACTED***"`; a key in `_CONTENT_KEY_NAMES` → item dropped). Primitive non-str scalars pass through.
  - `class JsonFormatter(logging.Formatter)`: `format(record)` returns a single-line JSON object with keys `ts` (ISO-8601 UTC), `level`, `logger`, `msg`, and JSON-serialisable extras under `extra` (non-serialisable → `repr`). On `record.exc_info`, add a single `error` field = `f"{exc_type}: {redact(str(exc))[:200]}"` — NEVER the full traceback.
  - `class RedactionFilter(logging.Filter)`: `filter(record)` runs the record's `msg` and every `extra` value through `redact(...)` (recursing nested dicts/lists), drops `_CONTENT_KEY_NAMES` extras at ALL levels, and always returns `True` (mutates, never filters out).
  - `def configure_logging(level: int = logging.INFO) -> None`: idempotent root-logger setup — one `StreamHandler(sys.stdout)` with `JsonFormatter` + `RedactionFilter`; module-flag guard so repeat calls don't stack handlers.
  - `def get_logger(name: str) -> logging.Logger`: `logging.getLogger(f"artemis.{name}")`.
  — done when: `uv run mypy --strict src` passes; after `configure_logging()`, `get_logger("t").info("hi", extra={"token": "A"*24, "content": "secret msg", "n": 3})` emits one valid-JSON line where `extra.token == "***REDACTED***"`, no `content` key is present, and `extra.n == 3`; `redact("A"*19)` is unchanged and `redact("A"*20)` is `"***REDACTED***"` (asserted in Task 7).

- [ ] Task 2: The `ObservabilitySink` Protocol + null/composite — files: `/Users/artemis-build/artemis/src/artemis/obs/sink.py` — imports only stdlib + `from artemis.obs.logging import get_logger` (NO `ports`/`recipes`/`brain` import — the Protocol carries only primitives).
  - `class ObservabilitySink(Protocol)`:
    - `def on_route_decision(self, task_class_key: str, confidence: float, path: str, *, now: datetime) -> None: ...`
    - `def on_escalation(self, task_class_key: str, *, is_cloud_safe: bool, now: datetime) -> None: ...`
    - `def on_error(self, component: str, exc: BaseException, *, now: datetime) -> None: ...`
  - `class NullSink`: implements all three as `pass` (the default injected everywhere).
  - `class CompositeSink`: constructed with `(sinks: Sequence[ObservabilitySink])`; each method fans out to every child wrapped in `try/except`, **never raising** — on a child failure log exactly `get_logger("obs").warning("sink_child_failed", extra={"sink": type(child).__name__, "error_type": type(exc).__name__})` (NEVER `exc_info=True`, NEVER `str(exc)`, NEVER the call arguments).
  — done when: `uv run mypy --strict src` passes; a `CompositeSink([SpyA, SpyB])` forwards one `on_error` to both, and a child that raises does not propagate and logs no exception message (asserted in Task 7).

- [ ] Task 3: The error pillar — files: `/Users/artemis-build/artemis/src/artemis/obs/errors.py` —
  - frozen dataclass `ErrorRecord { component: str, error_type: str, message: str, at: datetime }` (NO traceback, NO raw content — `message` is already-redacted).
  - `class ErrorStore` constructed with `(path: Path)`: `def append(self, rec: ErrorRecord) -> None` — append-only: create the parent dir on first call, `open(path, "a", encoding="utf-8")`, write one JSON line, `flush()` + `os.fsync()` (single-writer POSIX append; mandated approach — do NOT use a whole-file rewrite). `def list(self) -> list[ErrorRecord]` (read all lines, tolerate a trailing partial line).
  - `class ErrorCaptureSink` implementing `ObservabilitySink`: constructed with `(store: ErrorStore)`. `on_error(component, exc, *, now)` → `msg = str(redact(str(exc)))[:500]` (redact BEFORE truncate+store — resolves the security BLOCK), build `ErrorRecord(component, type(exc).__name__, msg, now)`, `store.append(rec)`, and emit `get_logger(component).error("captured", extra={"error_type": type(exc).__name__})` (no message string in the log extra). `on_route_decision`/`on_escalation` → `pass` (errors pillar only).
  — done when: `uv run mypy --strict src` passes; `ErrorStore.append` then `list` round-trips; `ErrorCaptureSink.on_error("brain", ValueError("token: " + "A"*32), now=...)` writes one record with `error_type=="ValueError"`, `message` containing `"***REDACTED***"` and NOT the raw 32-char string, and no traceback field (asserted in Task 7).

- [ ] Task 4: Package surface — files: `/Users/artemis-build/artemis/src/artemis/obs/__init__.py` — explicit re-exports of `ObservabilitySink`, `NullSink`, `CompositeSink`, `ErrorRecord`, `ErrorStore`, `ErrorCaptureSink`, `configure_logging`, `get_logger`, `RedactionFilter`, `redact`, `JsonFormatter`, `obs_dir`, with `__all__` (OBS-b's telemetry subpackage imports separately). — done when: `uv run python -c "from artemis.obs import ObservabilitySink, NullSink, CompositeSink, ErrorCaptureSink, configure_logging, get_logger, redact"` exits 0.

- [ ] Task 5: Add the Brain capture taps (additive) — files: `/Users/artemis-build/artemis/src/artemis/brain.py` —
  - Add keyword arg `obs: ObservabilitySink = NullSink()` (import from `artemis.obs`); store as `self._obs`. All existing positional constructions still type-check.
  - Import `from artemis.recipes.distill import task_class_key`. In `respond`, immediately after `decision = self._router.route(request_text, scope)`: `key = task_class_key(decision, request_text)` then `self._obs.on_route_decision(key, decision.confidence, decision.path, now=datetime.now(UTC))`. `request_text` is used ONLY to derive `key`; it is never passed to the sink. Do NOT write any escalation event here (the M1 escalate path is a stub; the real escalation is recorded in `escalate_and_distill`, Task 6).
  - In the existing degrade-don't-crash `except` block(s) of `respond` (returns `TOOL_ERROR`/keeps the loop total) and `respond_stream`'s failure path, call `self._obs.on_error("brain", exc, now=datetime.now(UTC))` before returning the typed fallback. Keep the methods non-raising (sink errors are swallowed by `CompositeSink`; never let a sink change control flow).
  — done when: `uv run mypy --strict src` passes; constructing `Brain(router, registry, model)` with no `obs` still works (default `NullSink`); `Brain(..., obs=spy).respond(...)` records exactly one `on_route_decision` (with a non-empty `task_class_key`) per call and one `on_error("brain", ...)` when the tool callable raises; no `request_text` value is ever passed to the sink (asserted in Task 7).

- [ ] Task 6: Add the distill capture taps (additive) — files: `/Users/artemis-build/artemis/src/artemis/recipes/distill.py` —
  - Add keyword arg `obs: ObservabilitySink = NullSink()` to `escalate_and_distill` (import from `artemis.obs`). At function entry, call `obs.on_escalation(req.task_class_key, is_cloud_safe=req.is_cloud_safe, now=datetime.now(UTC))`. (`req.task_class_key` is the safe category key M7-a2 already populated — a tool-candidate id or `sha256(normalise(text))`, never raw content.)
  - Wrap the existing raise sites for `CloudEgressForbiddenError` and `RecipeReplayError` so that immediately before re-raising, `obs.on_error("distill", err, now=datetime.now(UTC))` is called (record then raise — do not swallow).
  - No other behavioural change; the cloud-egress guard and instance-free distill template are untouched.
  — done when: `uv run mypy --strict src` passes; `escalate_and_distill(req, FakeTeacher(), store)` with no `obs` behaves exactly as before; with `obs=spy`, one `on_escalation(req.task_class_key, ...)` is recorded, and a forced `CloudEgressForbiddenError` records one `on_error("distill", ...)` then propagates (asserted in Task 7).

- [ ] Task 7: Tests — files: `/Users/artemis-build/artemis/tests/test_obs_core.py` — typed pytest:
  - logging: `configure_logging()` + capture stdout; `get_logger("t").info("hi", extra={"token": "A"*24, "content": "x", "nested": {"password": "p"*8}, "n": 3})` → assert valid JSON, `extra.token == "***REDACTED***"`, no `content` key, `extra.nested.password == "***REDACTED***"`, `extra.n == 3`.
  - redact boundaries: `redact("A"*19)` unchanged; `redact("A"*20) == "***REDACTED***"`; `redact(b"\xab\xcd")` redacted; `redact({"handle": "h", "ok": 3}) == {"handle": "***REDACTED***", "ok": 3}`.
  - sink: a `SpySink`; `CompositeSink([SpySink(), raising_sink])` forwards `on_error` to the spy, does not raise, and the WARNING line contains no exception message.
  - errors: `ErrorStore(tmp_path/"e.jsonl")` append+list round-trip; `ErrorCaptureSink.on_error("brain", ValueError("token: " + "A"*32), now=...)` → one record, `error_type=="ValueError"`, `message` contains `"***REDACTED***"` and NOT the raw 32-char run, no traceback field.
  - brain tap: `Brain(router, registry, FakeModelPort, obs=spy)`; `await respond("what time is it", scope)` → spy has one `on_route_decision` with a non-empty key and NO argument equal to the raw `request_text`; a raising tool callable → one `on_error("brain", ...)`; constructing with no `obs` → `respond` still returns.
  - distill tap: `escalate_and_distill(req, FakeTeacher(), store, obs=spy)` → one `on_escalation(req.task_class_key, ...)`; a cloud-unsafe req routed to a cloud adapter → one `on_error("distill", ...)` then raises `CloudEgressForbiddenError`.
  — done when: `uv run pytest -q tests/test_obs_core.py` passes AND `uv run mypy --strict src tests/test_obs_core.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/obs/__init__.py, /Users/artemis-build/artemis/src/artemis/obs/logging.py, /Users/artemis-build/artemis/src/artemis/obs/sink.py, /Users/artemis-build/artemis/src/artemis/obs/errors.py, /Users/artemis-build/artemis/tests/test_obs_core.py |
| Modify | /Users/artemis-build/artemis/src/artemis/brain.py, /Users/artemis-build/artemis/src/artemis/recipes/distill.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_obs_core.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_obs_core.py` | Test gate (logging/redaction, error-message redaction, sink fan-out, brain+distill taps) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/obs/**, src/artemis/brain.py, src/artemis/recipes/distill.py, tests/test_obs_core.py |
| `git commit` | "feat: OBS-a observability core (JSON logging + redaction + ObservabilitySink + error capture + brain/distill taps)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings → `obs_dir` path resolution (only when a real store path is needed; tests use `tmp_path`) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No network; logging is stdout, error store is local file |

## Specialist Context
### Security
- **[RESOLVED — was BLOCK] Error-message leak:** `ErrorCaptureSink` now runs `redact(str(exc))` BEFORE truncation/storage; `ErrorRecord` stores only the exception class + a redacted ≤500-char message, no traceback. Test asserts a credential-bearing exception is redacted in the stored record.
- **[RESOLVED — was BLOCK] Content in Protocol:** the `ObservabilitySink` Protocol carries only non-content primitives; the Brain computes `task_class_key` and never passes `request_text` to a sink. No sink can structurally persist message content.
- **[RESOLVED — was FLAG] Redaction coverage:** `redact()` handles `bytes`, recurses nested dict/list, and blocks secret-shaped key names (`key`/`token`/`secret`/`password`/`authorization`/`bearer`/`dek`/`ref`/`handle`/`credential`); the base64/hex length match is defence-in-depth behind key-name matching.
- **[RESOLVED — was FLAG] CompositeSink WARNING:** logs only `sink` class + `error_type`, never `exc_info`/`str(exc)`/arguments.
- **[RESOLVED — was FLAG] DEBUG carve-out:** removed — content-named extras are dropped at ALL levels.

### Performance
- Taps are one method call on the route-decision path wrapped in a fan-out with per-child try/except; `NullSink` is a no-op. Logging is stdout-buffered. `task_class_key` is a hash/lookup already computed in the escalation path elsewhere. No measurable budget impact.

### Accessibility
(none — headless foundation; no UI surface.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/obs/*.py | Type + docstring all exports; document the no-PII contract, the exact `redact()` coverage (and its defence-in-depth limits), the sink fan-out non-raising guarantee, and that taps default to `NullSink` (additive/backward-compatible) |
| ADR | docs/technical/adr/ADR-008-observability.md | Already written — reference only |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_obs_core.py` → verify: exit 0 (incl. `ObservabilitySink` Protocol conformance of `NullSink`/`CompositeSink`/`ErrorCaptureSink`).
- [ ] Run `uv run python -c "from artemis.obs import ObservabilitySink, NullSink, CompositeSink, ErrorCaptureSink, configure_logging, get_logger, redact"` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_obs_core.py` → verify: a secret-shaped extra is `***REDACTED***`, a `content` extra is dropped, nested secrets are redacted, the 19/20-char blob boundary holds; a credential-bearing exception is redacted in the stored `ErrorRecord` with no traceback; `CompositeSink` fan-out survives a raising child without logging its message; `Brain(..., obs=spy).respond(...)` records one `on_route_decision` (no raw `request_text` reaches the sink) + one `on_error` on a raising tool; `escalate_and_distill(..., obs=spy)` records `on_escalation` and `on_error`-then-raises on cloud-egress.
- [ ] Construct `Brain` and call `escalate_and_distill` with NO `obs` arg → verify: both succeed with the default `NullSink` (backward-compatible).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_

---
spec: flagged-injection-coverage
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave S · SECURITY · centralized defense-in-depth across all Extract consumers.
     Blanks flagged content at the reader, adds Extract.usable, fixes 3 consumer sites,
     emits OBS telemetry on detection. cross_model_review: true (untrusted-content security). -->

# Spec: flagged-injection-coverage — centralized injection defense across Extract consumers

**Identity:** Blank flagged content at `QuarantinedReader.read` (fail-safe), add `Extract.usable`, gate the 3 gap consumers (`gmail/ingest`, `calendar/untrusted`+`calendar/memory`, `gmail/urgency`) on `.usable`, add `ObservabilitySink.on_injection_flagged`, emit on detection.
→ why: see `docs/findings/flagged-injection-coverage-decision.md` · ADR-009 (untrusted content security).

## Files to Change

| File | Operation |
|------|-----------|
| `src/artemis/untrusted/quarantine.py` | modify — blank-on-flag in `QuarantinedReader.read`; add `Extract.usable` property; thread optional `ObservabilitySink` into `QuarantinedReader.__init__`; emit `on_injection_flagged` |
| `src/artemis/obs/sink.py` | modify — add `on_injection_flagged` to `ObservabilitySink`, `NullSink`, `CompositeSink` |
| `src/artemis/obs/__init__.py` | modify — re-export `on_injection_flagged` if needed (no-op if Protocol methods don't need re-export) |
| `src/artemis/modules/gmail/ingest.py` | modify — `GmailMemoryExtractor.extract`: `parse_failed` guard → `.usable` |
| `src/artemis/modules/calendar/untrusted.py` | modify — `quarantine_event_text`: fix flagged path to return `parse_failed=False, flagged_injection=True` with blank summary/claims (already handled by reader after Task 1); gate `CalendarExtract` construction on usable |
| `src/artemis/modules/calendar/memory.py` | modify — `CalendarMemoryExtractor.extract`: `parse_failed` guard → `.usable` on `CalendarExtract` |
| `src/artemis/modules/gmail/urgency.py` | modify — `fetch_extracts`: `not extract.parse_failed` guard → `extract.usable` |
| `tests/test_untrusted.py` | modify — add blank-on-flag, `usable` property, and OBS emit tests |
| `tests/test_flagged_injection_coverage.py` | create — regression tests for all 3 consumer sites |

## Tasks

- [ ] **Task 1: `ObservabilitySink.on_injection_flagged` + `NullSink` + `CompositeSink`** — files: `src/artemis/obs/sink.py`

  Add to `ObservabilitySink` Protocol:
  ```python
  def on_injection_flagged(self, source_domain: str, *, now: datetime) -> None:
      """Record an injection-attempt detection; carries only the trust-level domain, not content."""
      ...
  ```

  Add the same no-op to `NullSink`:
  ```python
  def on_injection_flagged(self, source_domain: str, *, now: datetime) -> None:
      pass
  ```

  Add fan-out to `CompositeSink`:
  ```python
  def on_injection_flagged(self, source_domain: str, *, now: datetime) -> None:
      for sink in self._sinks:
          try:
              sink.on_injection_flagged(source_domain, now=now)
          except Exception as exc:
              self._log_child_failure(sink, exc)
  ```

  `datetime` is already imported in `sink.py`. `source_domain` carries only the caller-supplied trusted string (e.g. `"mail.google.com"`, `"calendar.google.com"`) — never model output, never raw content.

  — done when: `uv run mypy src/artemis/obs/sink.py` → exit 0; `NullSink().on_injection_flagged("x", now=datetime.now())` runs without error.

- [ ] **Task 2: `Extract.usable` property + blank-on-flag in `QuarantinedReader.read` + OBS emit** — files: `src/artemis/untrusted/quarantine.py`

  2a. Add `usable` property to the `Extract` dataclass (after the existing fields):
  ```python
  @property
  def usable(self) -> bool:
      """True only when the extract is neither parse-failed nor injection-flagged."""
      return not self.parse_failed and not self.flagged_injection
  ```
  Note: `Extract` is `frozen=True` — a `@property` is fine on a frozen dataclass.

  2b. Thread an optional sink into `QuarantinedReader.__init__`:
  ```python
  from artemis.obs.sink import NullSink, ObservabilitySink

  def __init__(self, model: ModelPort, role: str, *, sink: ObservabilitySink | None = None) -> None:
      ...existing checks...
      self._sink: ObservabilitySink = sink if sink is not None else NullSink()
  ```
  Default `NullSink()` preserves all existing callers with no change.

  2c. In `QuarantinedReader.read`, after the successful parse block, before constructing the return `Extract`, when `flagged_injection` is `True`:
  - Blank `summary` to `""` and `claims` to `()` (keeping `flagged_injection=True`)
  - Emit the OBS event

  Replace the final return block (lines ~144–152 in the current file):
  ```python
  if flagged_injection:
      from datetime import datetime
      self._sink.on_injection_flagged(source_domain, now=datetime.now(tz=datetime.now().astimezone().tzinfo))
      logger.warning(
          "Injection attempt flagged from %s; summary and claims blanked", source_domain
      )
      summary = ""
      claims = ()

  return Extract(
      source_url=source_url,
      source_domain=source_domain,
      summary=summary,
      claims=claims,
      flagged_injection=flagged_injection,
      parse_failed=False,
      tokens_used=tokens_used,
  )
  ```

  Use `datetime.now(UTC)` — import `from datetime import datetime, timezone` at top of file and use `datetime.now(tz=timezone.utc)`.

  — done when: `uv run mypy src/artemis/untrusted/quarantine.py` → exit 0; a flagged extract has `summary=""`, `claims=()`, `flagged_injection=True`, `usable=False`; a clean extract has `usable=True`; a parse-failed extract has `usable=False`.

- [ ] **Task 3: Fix `gmail/ingest.py` — gate on `.usable`** — files: `src/artemis/modules/gmail/ingest.py`

  In `GmailMemoryExtractor.extract` (line ~183), change:
  ```python
  if extract.parse_failed:
      return False
  ```
  to:
  ```python
  if not extract.usable:
      return False
  ```

  The existing `if not text: return False` guard at line ~194 already short-circuits on blank summary (which is now guaranteed by Task 2 for flagged extracts), but the `.usable` gate at line 183 is the explicit contract gate — it runs before any content access.

  — done when: `uv run mypy src/artemis/modules/gmail/ingest.py` → exit 0.

- [ ] **Task 4: Fix `calendar/untrusted.py` — return flagged content blanked** — files: `src/artemis/modules/calendar/untrusted.py`

  The current code (lines ~68–76) logs `flagged_injection` but passes `extract.summary`/`extract.claims` through (with `flagged_injection=True` on the `CalendarExtract`). After Task 2, `summary` and `claims` are already blanked by the reader, so the values passed through will be `""` / `()`. However the existing `if extract.parse_failed` branch (lines ~59–67) hardcodes `flagged_injection=False` on the returned `CalendarExtract` — that is correct (parse failures are not injection flags). No structural change needed to that branch.

  The remaining issue: the second return (lines ~70–76) passes `extract.flagged_injection` to `CalendarExtract.flagged_injection` already. With Task 2 blanking at the reader, the content is now safe. The log at line ~69 remains valid and useful. No code changes needed to `calendar/untrusted.py` beyond verifying the behaviour — **BUT** the `CalendarExtract` docstring should be updated to note that `flagged_injection=True` implies blank `summary`/`claims` (reader contract).

  Update docstring on `CalendarExtract`:
  ```python
  @dataclass(frozen=True)
  class CalendarExtract:
      """Calendar-domain wrapper around a sanitized DR-a extract.

      When ``flagged_injection=True``, ``summary`` and ``claims`` are guaranteed blank
      (the QuarantinedReader blanks content on flag — callers need not re-check the flag
      to avoid using flagged content, but ``parse_failed`` and ``flagged_injection`` are
      preserved for telemetry and routing).
      """
  ```

  — done when: `uv run mypy src/artemis/modules/calendar/untrusted.py` → exit 0.

- [ ] **Task 5: Fix `calendar/memory.py` — gate on `.usable`** — files: `src/artemis/modules/calendar/memory.py`

  In `CalendarMemoryExtractor.extract` (line ~52), change:
  ```python
  if extract.parse_failed:
  ```
  to:
  ```python
  if not (not extract.parse_failed and not extract.flagged_injection):
  ```

  Cleaner — add a `usable` property to `CalendarExtract` mirroring `Extract.usable`:
  ```python
  @property
  def usable(self) -> bool:
      return not self.parse_failed and not self.flagged_injection
  ```
  (Add to `CalendarExtract` dataclass in `calendar/untrusted.py`.)

  Then in `calendar/memory.py` line ~52:
  ```python
  if not extract.usable:
      logger.warning(
          "calendar memory extraction skipped unusable event %s (parse_failed=%s, flagged=%s)",
          event.event_id, extract.parse_failed, extract.flagged_injection,
      )
      return
  ```

  Also remove the now-redundant whitespace text issue: `text = extract.summary + "\n" + "\n".join(extract.claims)` will produce `"\n"` for a blank flagged extract. Add a guard:
  ```python
  text = (extract.summary + "\n" + "\n".join(extract.claims)).strip()
  if not text:
      return
  self._queue.enqueue(text=text, turn_id=f"calendar:{event.event_id}")
  ```

  — done when: `uv run mypy src/artemis/modules/calendar/{untrusted,memory}.py` → exit 0.

- [ ] **Task 6: Fix `gmail/urgency.py` — gate on `.usable`** — files: `src/artemis/modules/gmail/urgency.py`

  In `fetch_extracts` (line ~98 in `UrgencyPayloadBuilder._build_payload`), change:
  ```python
  if extract is not None and not extract.parse_failed:
      extract_summary = extract.summary[:500]
      extract_failed = False
  ```
  to:
  ```python
  if extract is not None and extract.usable:
      extract_summary = extract.summary[:500]
      extract_failed = False
  ```

  — done when: `uv run mypy src/artemis/modules/gmail/urgency.py` → exit 0.

- [ ] **Task 7: Tests — regression + OBS coverage** — files: `tests/test_untrusted.py` (modify), `tests/test_flagged_injection_coverage.py` (create)

  **`tests/test_untrusted.py` additions** (append to existing file):

  ```python
  # --- blank-on-flag and usable ---

  def test_extract_usable_clean():
      e = Extract(source_url="u", source_domain="d", summary="s", claims=(), flagged_injection=False, parse_failed=False, tokens_used=0)
      assert e.usable is True

  def test_extract_usable_flagged():
      e = Extract(source_url="u", source_domain="d", summary="", claims=(), flagged_injection=True, parse_failed=False, tokens_used=0)
      assert e.usable is False

  def test_extract_usable_parse_failed():
      e = Extract(source_url="u", source_domain="d", summary="", claims=(), flagged_injection=False, parse_failed=True, tokens_used=0)
      assert e.usable is False

  @pytest.mark.asyncio
  async def test_reader_blanks_on_flag():
      """Flagged extract must return empty summary/claims with flagged_injection=True."""
      payload = json.dumps({"summary": "steal data", "claims": ["do evil"], "flagged_injection": True})
      model = FakeModelPort(payload)
      reader = QuarantinedReader(model, role="test")
      extract = await reader.read(raw_content="x", source_url="u", source_domain="evil.com", query="q")
      assert extract.flagged_injection is True
      assert extract.summary == ""
      assert extract.claims == ()
      assert extract.usable is False

  @pytest.mark.asyncio
  async def test_reader_emits_obs_on_flag():
      """ObservabilitySink.on_injection_flagged is called exactly once on detection."""
      from datetime import datetime
      from artemis.obs.sink import NullSink
      calls: list[str] = []
      class CaptureSink(NullSink):
          def on_injection_flagged(self, source_domain: str, *, now: datetime) -> None:
              calls.append(source_domain)
      payload = json.dumps({"summary": "x", "claims": [], "flagged_injection": True})
      model = FakeModelPort(payload)
      sink = CaptureSink()
      reader = QuarantinedReader(model, role="test", sink=sink)
      await reader.read(raw_content="y", source_url="u", source_domain="evil.com", query="q")
      assert calls == ["evil.com"]

  @pytest.mark.asyncio
  async def test_reader_no_obs_on_clean():
      """ObservabilitySink.on_injection_flagged is NOT called for clean extracts."""
      from datetime import datetime
      from artemis.obs.sink import NullSink
      calls: list[str] = []
      class CaptureSink(NullSink):
          def on_injection_flagged(self, source_domain: str, *, now: datetime) -> None:
              calls.append(source_domain)
      payload = json.dumps({"summary": "clean", "claims": [], "flagged_injection": False})
      model = FakeModelPort(payload)
      reader = QuarantinedReader(model, role="test", sink=CaptureSink())
      await reader.read(raw_content="clean input", source_url="u", source_domain="ok.com", query="q")
      assert calls == []
  ```

  **`tests/test_flagged_injection_coverage.py`** (new file — regression: flagged content never reaches memory or urgency payload):

  ```python
  """Regression: injection-flagged Extract content must never reach memory or urgency payload."""
  from __future__ import annotations
  import pytest
  from artemis.untrusted.quarantine import Extract

  def _flagged(domain: str = "evil.com") -> Extract:
      return Extract(source_url="u", source_domain=domain, summary="", claims=(), flagged_injection=True, parse_failed=False, tokens_used=0)

  def _clean() -> Extract:
      return Extract(source_url="u", source_domain="ok.com", summary="meeting at 3pm", claims=("call Alice",), flagged_injection=False, parse_failed=False, tokens_used=0)

  # --- gmail/ingest ---
  @pytest.mark.asyncio
  async def test_gmail_ingest_rejects_flagged(fake_gmail_ingest):
      """GmailMemoryExtractor.extract must return False for a flagged extract — nothing enqueued."""
      result = await fake_gmail_ingest.extract_with(extract=_flagged())
      assert result is False
      assert fake_gmail_ingest.enqueued == []

  @pytest.mark.asyncio
  async def test_gmail_ingest_accepts_clean(fake_gmail_ingest):
      """GmailMemoryExtractor.extract must enqueue clean extract content."""
      result = await fake_gmail_ingest.extract_with(extract=_clean())
      assert result is True
      assert fake_gmail_ingest.enqueued != []

  # --- calendar/memory ---
  @pytest.mark.asyncio
  async def test_calendar_memory_rejects_flagged(fake_calendar_memory):
      """CalendarMemoryExtractor.extract must skip flagged events — nothing enqueued."""
      await fake_calendar_memory.extract_with_extract(flagged=True)
      assert fake_calendar_memory.enqueued == []

  @pytest.mark.asyncio
  async def test_calendar_memory_accepts_clean(fake_calendar_memory):
      """CalendarMemoryExtractor.extract must enqueue clean event text."""
      await fake_calendar_memory.extract_with_extract(flagged=False)
      assert fake_calendar_memory.enqueued != []

  # --- gmail/urgency ---
  def test_urgency_payload_excludes_flagged(fake_urgency_builder):
      """Urgency payload must use extract_failed=True for a flagged extract."""
      candidate = fake_urgency_builder.build_with_extract(_flagged())
      assert candidate["extract_failed"] is True
      assert candidate["extract_summary"] == ""

  def test_urgency_payload_includes_clean(fake_urgency_builder):
      """Urgency payload must include summary for a usable extract."""
      candidate = fake_urgency_builder.build_with_extract(_clean())
      assert candidate["extract_failed"] is False
      assert "meeting" in candidate["extract_summary"]
  ```

  Fake fixtures (`fake_gmail_ingest`, `fake_calendar_memory`, `fake_urgency_builder`) implemented as `conftest.py` additions or inline in the test file using `FakeQuarantinedReader` (canned extract), `FakeMemoryQueue` (list append), and `FakeGmailApi`. Pattern follows `test_gmail_urgency_hook.py` and `test_untrusted.py` existing fakes.

  — done when: `uv run pytest -q tests/test_untrusted.py tests/test_flagged_injection_coverage.py` → all pass; `uv run mypy tests/test_flagged_injection_coverage.py` → exit 0.

## Acceptance Criteria

- [ ] `uv run mypy src` → exit 0 (full project, not file-scoped).
- [ ] `uv run pytest -q` → exit 0 (full suite, not file-scoped).
- [ ] Regression: a `flagged_injection=True` Extract returned by a `QuarantinedReader` has `summary=""`, `claims=()`, `usable=False`.
- [ ] Regression: `GmailMemoryExtractor.extract` returns `False` and enqueues nothing for a flagged extract.
- [ ] Regression: `CalendarMemoryExtractor.extract` enqueues nothing for a flagged event.
- [ ] Regression: urgency payload sets `extract_failed=True` and `extract_summary=""` for a flagged extract.
- [ ] OBS: `ObservabilitySink.on_injection_flagged` is called exactly once per flagged detection (source_domain only — no content).
- [ ] OBS: `ObservabilitySink.on_injection_flagged` is NOT called for clean or parse-failed extracts.
- [ ] All existing callers of `QuarantinedReader(model, role)` (no `sink` arg) continue to work unchanged (`NullSink` default).

## Commands to Run

```
uv run mypy src
uv run pytest -q tests/test_untrusted.py tests/test_flagged_injection_coverage.py
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

## Permissions

### File Operations
| Action | Path |
|--------|------|
| Modify | `src/artemis/untrusted/quarantine.py` |
| Modify | `src/artemis/obs/sink.py` |
| Modify | `src/artemis/obs/__init__.py` |
| Modify | `src/artemis/modules/gmail/ingest.py` |
| Modify | `src/artemis/modules/calendar/untrusted.py` |
| Modify | `src/artemis/modules/calendar/memory.py` |
| Modify | `src/artemis/modules/gmail/urgency.py` |
| Modify | `tests/test_untrusted.py` |
| Create | `tests/test_flagged_injection_coverage.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy src` | Full-project type gate |
| `uv run pytest -q` | Full test suite gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The 9 files above |
| `git commit` | `"feat: flagged-injection coverage — blank-on-flag, Extract.usable, consumer gates, OBS telemetry"` |

## Specialist Context

### Security

- **Blank-on-flag at the reader (Task 2):** carelessness in any consumer now fails safe — flagged content is `""` / `()` before it leaves the quarantine boundary. `flagged_injection=True` is preserved for telemetry routing but carries no content. This is the "powerless by construction" design per ADR-009.
- **`Extract.usable` (Task 2):** single gate replaces the dual `not parse_failed and not flagged_injection` check. Consumers that forget the old check now get an empty string (safe); consumers that use `.usable` get the explicit contract.
- **OBS event carries no content:** `on_injection_flagged(source_domain, now=...)` is the caller-supplied trusted string only. Never model output, never raw body, never summary.
- **`CalendarExtract.usable`:** mirrors `Extract.usable` at the calendar wrapper layer so `calendar/memory.py` doesn't reach through to the inner `Extract`.

[apex-security review: confirm blank-on-flag is unconditional; confirm OBS event carries no content; confirm all 3 consumer site guards use `.usable`, not bare `parse_failed`.]

# Progress: flagged-injection-coverage — COMPLETE

Built by Codex; host-verified + cross-model (Opus) reviewed. Committed (see git log).

## Outcome
Host-verified: full mypy clean (235 files), ruff clean, 641 passed / 2 skipped.

## Security invariants — cross-model review CLEAN
Blank-on-flag unconditional at QuarantinedReader.read (summary="", claims=() before the single
return); Extract.usable + CalendarExtract.usable correct; all 3 consumers (gmail/ingest,
calendar/memory, gmail/urgency) gate on .usable; OBS event carries only the trusted source_domain
(no content); NullSink default preserves all existing callers; CompositeSink swallows child errors.

## Cross-model review BLOCK findings — FIXED inline (Opus)
Codex hid `on_injection_flagged` behind `if not TYPE_CHECKING:` on the ObservabilitySink Protocol
+ a separate `InjectionFlaggedSink` Protocol + `cast(...)` workarounds, to avoid touching the other
sink implementors. That left the method invisible to mypy and a latent AttributeError on the
injection path (ErrorCaptureSink lacked it). Proper fix (completes spec Task 1):
- `obs/sink.py`: declared `on_injection_flagged` unconditionally on ObservabilitySink; removed the
  `InjectionFlaggedSink` Protocol + the `cast` in CompositeSink.
- `untrusted/quarantine.py`: removed the `cast`/`InjectionFlaggedSink` import; calls
  `self._sink.on_injection_flagged(...)` directly.
- Added no-op `on_injection_flagged` to every concrete implementor mypy/runtime needs:
  `obs/telemetry/source.py` TelemetrySink, `obs/errors.py` ErrorCaptureSink, and the
  `tests/test_obs_core.py` SpySink spy.

### DEVIATION (for planning review)
Scope expanded by 3 files beyond the spec's Files-table (`obs/errors.py`,
`obs/telemetry/source.py`, `tests/test_obs_core.py`) — mechanical no-ops completing the Protocol
addition Task 1 specified. No approach/contract change. Same intent-preserving under-enumeration
pattern owner approved for sensitivity-ground-rules Task 6 this session.

### Low-sev notes (no action)
- Spec Task 2c pseudocode showed a misleading `datetime.now(tz=datetime.now().astimezone().tzinfo)`
  draft form; implementation correctly uses `datetime.now(tz=timezone.utc)`.
- Implementation adds `test_reader_no_obs_on_parse_failed` beyond spec (positive).

# Progress: CAL-create-from-extract — COMPLETE

Built by Codex; host-verified + independent Opus cross-model review. Host: mypy clean (248 files),
ruff clean, 681 passed (full suite, pre-guard-fix) + the targeted file 10 passed post-fix.

## Cross-model review — no BLOCK; security boundary CLEAN
No direct Google write (approve routes through CAL-b write_tools.create_event → classifier → GATE
staging); attendee-gating wall holds; UNIQUE idx_held_raw_ref gives idempotency; EventExtract has
no raw email body field.

### Applied (MEDIUM, in-scope safety fix)
- **discard_held_event status guard:** added an `if held.status is not HELD: return held` guard
  (mirrors approve_held_event). Without it, discarding an already-APPROVED event silently
  overwrote status→DISCARDED and nulled the google_event_id/pending_action_id audit trail. + added
  `test_discard_after_approve_is_noop`.

### FLAGGED for planning (low-sev, no action)
- `list_held_events` accepts an unvalidated `status: str` → invalid value yields a silent empty list
  (parameterised, no injection). Consider a `Literal['held','approved','discarded']`.
- Held-event tools register only when `held_event_store` is provided (silent opt-in) — consistent
  with overlay/schedule_task convention; consider a composition-root warning.

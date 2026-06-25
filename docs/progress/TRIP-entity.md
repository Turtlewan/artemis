# Progress: TRIP-entity — COMPLETE

Built by Codex; host-verified + independent Opus cross-model review. Host: mypy clean (241 files),
ruff clean, 666 passed / 2 skipped.

## Cross-model review — no BLOCK; 2 MEDIUM flagged for planning (NOT changed)
Changing either alters the trip data-contract / "revise in place" semantics → planning decision,
not an autonomous coding call:
1. **Leg revise semantics (MEDIUM):** `add_leg` uses `INSERT ... ON CONFLICT(raw_ref) DO NOTHING`,
   so re-ingesting a leg with the same raw_ref but corrected title/dates/origin is a no-op (only
   the trip-level span recomputes). Spec says "revises in place" — ambiguous whether leg fields
   should update (DO UPDATE) or stay idempotent (DO NOTHING). Current = idempotent no-op (safe).
2. **Origin PLACE consistency (MEDIUM):** on the revise (raw_ref-hit) path `origin_id` is hardcoded
   None, so origin PLACE-entity creation only happens on the new-leg path. Resolve origin
   unconditionally if origin PLACE consistency across paths is required.

### Low-sev (advisory, no action)
- `list_trips` N+1 (benign at personal scale); `_recompute_span` relies on caller's open txn
  (safe today, add a guard if refactored); `_windows_overlap` open-start (start_dt=None) collapse
  undocumented; missing test for "new raw_ref on a COMPLETED trip opens a new trip".
- (Reviewer finding #4 `__all__` missing trip_entity_ref was INACCURATE — it is present at L130.)

Codex self-corrected 2 idempotency edge cases during its build (same-raw_ref replay after
stable-key miss; missing-window same-destination merge).

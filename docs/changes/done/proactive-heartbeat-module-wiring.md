---
spec: proactive-heartbeat-module-wiring
status: ready
risk: high
coder: codex
coder_effort: high
cross_model_review: true
autonomy_level: L5
origin: system-check 2026-06-28 (decision B), grounded 2026-06-28. Build scoped to FINANCE registration; calendar deferred (Google-spoke-gated).
---

# Spec: Wire finance proactive hooks into the live heartbeat (writes excluded)

**Identity:** Make proactivity actually fire. The heartbeat enumerates `proactive_hooks` from the
*registered* manifests; today only `time` + `tasks_manifest` are registered, so the 3 productivity
hooks already fire but the 4 finance hooks are dark. This spec registers the finance manifest —
**hooks + read tools ONLY, write tools EXCLUDED** — so finance alerts (unusual-spend, bill-due,
renewal, new-recurring) go live. Read-and-notify only; payloads are ID/count-only (verified). Calendar
hooks are deferred (need the Google calendar spoke + heavier construction — see § Deferred).
→ why: system-check 2026-06-28 finding #3; grounding report 2026-06-28.

## Grounding facts (verified 2026-06-28)
- Hooks fire via the heartbeat enumerating `registry.manifests()[module].proactive_hooks` during
  `tick()` (`heartbeat.py run_forever`); hooks read via **injected stores**, not the tool registry.
  So the lever is **manifest registration**, NOT `pre_tick_steps` (flush/drain are already wired).
- **Productivity (3 hooks) already live** — `tasks_manifest` was registered by the agency build; its
  `include_write_surface=False` filters TOOLS only, `proactive_hooks` are unaffected. No change here.
- **Finance (4 hooks)** — `finance_manifest(store)` builds `build_finance_hooks(store)` but the
  manifest is **not registered** in `_register_modules`. Payloads are ID/count/scalar-total only
  (finance/hooks.py header verified — no transaction text). Finance is owner-private LOCAL (no bank
  link) — but its WRITE tools (add/edit/delete txn) still must NOT be model-reachable reactively
  (minimal-surface principle, same as agency).
- `_register_modules` (`gateway.py:500`) constructs the tasks store gated on `key_provider` and
  registers `tasks_manifest(store, include_write_surface=False)` — mirror this for finance.

## Invariants (hard rules — same security boundary as the agency build)
1. **No write tool reachable reactively.** The finance manifest is registered with its write surface
   EXCLUDED — only the finance READ tools + the 4 `proactive_hooks` go live. NO finance write tool
   (add/update/delete transaction, etc.) appears in the registry `brain.py:266` selects from.
2. **No external effect.** Finance is owner-private local; nothing here calls an external system. No
   GATE needed (nothing external-effect is exposed).
3. **Owner-private / Hello-unlock.** Finance store gated on unlock like tasks/memory; a locked vault →
   the finance manifest is absent / hooks no-op, not a crash.
4. **Notify payloads stay ID/count-only** (already true in the hooks; a test pins it).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/modules/finance/manifest.py` | modify | Add `include_write_surface: bool = False` to `finance_manifest` (mirror `tasks_manifest`). When False: expose ONLY finance read tools + `build_finance_hooks(store)` hooks; EXCLUDE all finance write tools. `True` preserves the current full set (back-compat). |
| `src/artemis/gateway.py` | modify | In `_register_modules`, construct the `FinanceStore` gated on `key_provider`/unlock (mirror the tasks-store construction) and `registry.register(finance_manifest(store, include_write_surface=False))`. |
| `tests/test_*` (finance + gateway registry) | create/modify | Per Acceptance Criteria. |

## Tasks
- [ ] Task 1: `include_write_surface=False` on `finance_manifest` — files: `src/artemis/modules/finance/manifest.py` — done when: with the default (False), the manifest's tool list has the finance READ tools but NONE of the finance write tools, and `proactive_hooks` has the 4 finance hooks; `True` preserves the prior full tool set. `uv run --no-sync mypy` clean.
- [ ] Task 2: Register finance in `_register_modules` — files: `src/artemis/gateway.py` — done when: `_register_modules` constructs the FinanceStore gated on unlock and registers `finance_manifest(store, include_write_surface=False)`; a locked-vault path leaves finance absent/no-op (mirror the tasks gating). `uv run --no-sync mypy` clean.
- [ ] Task 3: Tests / invariants — files: `tests/test_finance_*.py` (+ a gateway registry test) — done when: a test asserts the live registry from `_register_modules` exposes the finance hooks (proactive_hooks non-empty for finance) + finance read tools but NO finance WRITE tool (Invariant 1); a heartbeat tick over the populated registry evaluates the finance + productivity hooks (not an empty scan); locked vault → finance no-op (Invariant 3); a finance hook's emitted payload contains no transaction text (Invariant 4). Full `uv run --no-sync pytest -q` green.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Acceptance Criteria
- [ ] Live registry from `_register_modules` exposes finance `proactive_hooks` (4) + finance read tools, and NO finance write tool. (Invariant 1 — assert on registered tool names + hook names.)
- [ ] A heartbeat tick over the populated registry evaluates finance + productivity hooks (the registry is not the time-only empty scan).
- [ ] Locked vault → finance manifest absent / hooks no-op, no crash. (Invariant 3.)
- [ ] A finance hook payload carries IDs/counts only — no transaction text. (Invariant 4.)
- [ ] `include_write_surface=True` preserves the full prior finance tool set (back-compat).
- [ ] Host re-verify: full `uv run --no-sync mypy` + `uv run --no-sync pytest -q` green.

## Deferred (not this build)
- **Calendar hooks (7).** Registering the calendar manifest needs constructing `sync_engine`,
  `cache_store`, `overlay_store`, `owner_email`, `calendar_ids` — which depend on the **Google
  calendar spoke being live (OAuth)**. Until go-live the calendar cache is empty and the hooks would
  no-op anyway. Defer calendar registration to a follow-up gated on the Google spoke. (Same
  write-surface-exclusion invariant will apply to the calendar manifest then — its `calendar.create`
  etc. are EXTERNAL-effect and must stay off the reactive path.)
- `pre_tick_steps` for any calendar overlay launderers — travels with the deferred calendar work.

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Modify | `src/artemis/modules/finance/manifest.py`, `src/artemis/gateway.py` |
| Create | finance + gateway-registry tests under `tests/` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run --no-sync mypy` / `uv run --no-sync pytest -q` | Host verify (a live brain may hold artemis-brain.exe → `--no-sync`). |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` (by name) + `git commit` | "feat(proactivity): wire finance hooks into the live heartbeat (writes excluded)" |

## Security Context
The single hard invariant is Invariant 1 — registering a manifest registers its tools, so the finance
write surface must be excluded (mirrors the agency `include_write_surface=False`). Finance is local
(no external effect), so no GATE is needed; the exclusion is minimal-surface discipline (the model
should not edit the owner's ledger un-prompted). Calendar deferral keeps the genuinely external-effect
write surface (`calendar.create`) entirely out of scope this build.

## Progress
_(Coding mode writes here — do not edit manually)_

### 2026-06-29 — built by Codex (gpt-5.5, high), host-verified + Codex-ensemble reviewed
- [x] Task 1 — `finance_manifest(include_write_surface=False)` filters `_finance_tool_specs` to `ActionRisk.READ` only (10 read tools survive; 12 write/effect tools excluded incl. `transaction_add/update/recategorize`, `csv_import`, `fin_suggestion_accept/reject`, `recurring_scan`, `reconcile_run`, `finance_knowledge_push`); the 4 finance `proactive_hooks` retained. `True` preserves the full set.
- [x] Task 2 — `_register_modules` constructs the FinanceStore + registers `finance_manifest(store, include_write_surface=False)` only when owner-unlocked; locked vault → finance absent/no-op.
- [x] Task 3 — `tests/test_finance_gateway_registry.py` (new) asserts, against the REAL `_register_modules`/`ToolRegistry`/`Heartbeat`: exact read-tool set + exact write-tool absence, non-empty finance hooks, heartbeat tick evaluates finance + productivity hooks, locked-vault no-op, ID/count-only payloads.

**Side effect noted:** the 3 productivity hooks went live with the agency build (`tasks_manifest` registered); this completes finance. Calendar (7 hooks) deferred — needs the Google calendar spoke live (see § Deferred).

**Host verify:** full mypy clean (344) · Codex targeted 63 · full pytest **944 passed, 6 skipped**.
**Codex ensemble review (off-Max):** security lens CLEAN (enumerated 10 read survive / 12 writes excluded; unlock-gated; ID-only payloads) · correctness lens CLEAN (filter-by-READ correct, back-compat preserved, tests assert real exact behavior). No findings to adjudicate.

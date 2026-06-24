# BUILD-ORDER — the "build specs" manifest

**Trigger (coding mode):** when the owner says **"build specs"**, build the `status: ready` specs in `docs/changes/` in the dependency-ordered waves below, via the Codex build flow (`docs/bring-up/CODEX-BUILD-RUNBOOK.md` / apex-code). **Verify each wave's acceptance criteria before starting the next** — do not build a later wave on top of an unverified earlier one. Everything here is dev-box-buildable; Mac-gated tasks (flagged per spec) are stubbed/skipped until the Mac.

Per-spec detail (prereqs, dev/Mac flags, decision-IDs): `docs/findings/cluster-spec-roadmap.md`. Locked decisions: `docs/findings/cluster-decisions/DECISIONS-LOG.md`.

## Already built — do NOT rebuild
M0/M1 spine · M4-a bitemporal core · M4-d-1 entities · LanceDBVectorStore · model/routing adapters (Codex batch). See `docs/status.md` In-Flight.

## Prereq layer (the cluster sits on these — build/verify first)
M2 wall **(STUB on dev** — `KeyProvider`/`ScopedStore` fakes, slice-2a pattern) · M8-a Google auth · DR-a quarantine · M3-a ingest · M3-b retriever · M4-b write-path · M4-c-1 recall · M7-a1/M7-b recipe system. (Existing `ready` specs.)

## Build waves (in order)

| Wave | Specs | Status |
|------|-------|--------|
| **F0 — Foundation** | runtime-config-layer (new) · M6-wake-trigger (amend) · M8-d-a split + Areas-drop (amend) · projects-module (new) | ✅ drafted (ready) |
| **F1 — Cluster amendments** (parallel) | M8-b2 urgency-widen · CalPrefs working_days/focus_window · M8-d-b focus-slot-pick · M8-d-c1 wake-digest | ✅ drafted (ready) |
| **P — Sensitivity gate (ADR-029)** | producer tags M3-a/M8-b1/M4-b → carrier M3-b/M4-c-1 → RAG-compose enforcer (new) | ✅ drafted (ready) |
| **S — Finance (FIN-\*)** (serial) | FIN-a ledger+CSV → FIN-b extraction → FIN-c recurring/reconciliation → FIN-d knowledge | ✅ ready (FIN-c emit seam conformed to canonical `DomainEvent`) |
| **R — Reaction layer (ADR-021)** | infra ×4 (emit/rule-store/dispatcher/reconciler) · Trip entity · Maps connector · calendar.create_from_extract · recipes ×3 | ✅ ready (TRIP-entity + recipes ×3 conformed to canonical `ReactionRule`/`Reconciler`/`assemble`; `EventType` registry extended) |
| **U — UI Tauri client (ADR-028)** | core/auth/world/card/ask/screens/theme | **HELD — pending UI design** |

**Concurrency:** F0 → F1 first; then **P, S, and R-infra may run concurrently**. U builds last (and only after its screen designs finalise).

## Drafting status (planning side)
F0–R = **all 28 cluster specs drafted `status: ready`** (2026-06-23 AFK pass). U = held. A spec is only eligible for "build specs" once `status: ready`.

**Cross-spec build-time coordination (RESOLVED 2026-06-23):** the `EventType` registry in `RXN-emit` is the single source of truth and now carries every event the cluster produces/consumes. Conformance pass appended `TRIP_ASSEMBLED="trip-assembled"` (producer: TRIP-entity) and `BILL_PAID="bill-paid"` (producer: RXN-recipes-self A1/A9) with producer + payload contracts. The drafters' `commitment-detected`/`flight-email-detected`/`meeting-email-detected`/`gift-signal-detected` are NOT event types — they are scalar payload flags on the registered `EMAIL_INGESTED` event (each recipe callable guards on its flag). A1 settlement binds to the existing `PAYMENT_RECORDED` (no `statement-recorded`). FIN-c's `txn-recorded`/`bill-recorded`/`subscription-detected` were already registered. All RXN-recipes now use the canonical `ReactionRule` (str `reaction_ref` + `dedup_key_fields`, no `Callable`/`idempotency_key_fn`) and the canonical `Reconciler.match(target, candidates)` + `TripAssembler.assemble(extract)` signatures.

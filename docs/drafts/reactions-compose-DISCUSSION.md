# Reactions runtime composition — discussion prep (for the next planning session)

**Design locked + recorded:** ADR-032 (reactions runtime composition + go-live posture).
**Four Deep-Details drafts queued in `docs/drafts/`** (NOT yet gate-passed → not in `docs/changes/`):
`R1-reactions-compose.md` · `R2-reactions-emit-seams.md` · `R3-linked-task-ref.md` ·
`R4-memory-module-fact-gift.md`.

Decisions already made (ADR-032): heartbeat-drain run model · all four emit seams · observe-first
`reactions_mode` flag (default observe) · gift facts `sensitivity="general"` · `linked_task_ref`
propagated via an injected lookup.

---

## ⛔ KEY OPEN QUESTION — the `EMAIL_INGESTED` payload contract (3-way mismatch)

The comms reactions are already BUILT and consume `EMAIL_INGESTED`, but the new emit seam (R2) and
the gift reaction (R4) disagree with them on what the event carries. All three must be reconciled
before R2/R4 can pass the readiness gate's *sufficiency-audit* (does the emit actually produce what
the consumer needs?).

**What each side currently assumes:**
- **Built comms (A4/A5/A7), `recipes/comms.py`:** reads SANITIZED EXTRACT FIELDS from the payload —
  `extract_summary`, a `commitment` bool, `event_kind`, `start_datetime`/`end_dt`, `location`,
  `attendee_emails`, plus trip fields (`origin`/`destination`/`confirmation_ref`/`co_travellers`).
  Comment: *"The live Gmail pre-flight stores only sanitized extract fields on the event."* → expects
  emit to happen AFTER the quarantined extraction, payload carrying the laundered fields.
- **R2 draft (emit seam):** `EMAIL_INGESTED` = scalar-only `{message_id, source_ref}`, emitted at
  INGEST time in `GmailIngestor.ingest_message` (before/without the quarantined Extract). R2 explicitly
  rejected emitting from `GmailMemoryExtractor.extract` because that path is best-effort/skippable.
- **R4 draft (gift reaction):** reads `gift_signal_detected` / `gift_item` from the payload (gift
  detection assumed pre-computed upstream).

**The fork to decide:**
- **Option A — emit post-extraction, payload carries sanitized extract fields.** Matches the built
  comms reactions with zero rework; gift detection + commitment/event detection are upstream (gmail
  extraction). Cost: emit lives on the best-effort extraction path (skippable → some emails never
  emit), and the event payload grows (still sanitized/scalar text, no raw body — Seam 7 OK since the
  quarantined summary is laundered).
- **Option B — emit at ingest (`{message_id, source_ref}`), reactions FETCH the extract.** Generic
  `EMAIL_INGESTED` (one event, every reaction does its own detection over the fetched quarantined
  extract via an injected lookup). Cost: rework the BUILT comms reactions (A4/A5/A7) from
  read-from-payload to fetch-via-ref, plus R4 runs its own gift detection. More work, cleaner contract,
  fires on every email regardless of extraction success.

**Recommendation to weigh:** Option B is the architecturally cleaner end-state (generic event +
per-reaction detection over the laundered extract, matching ADR-021 Seam 7 "event carries the ref,
not the content"), but it reworks already-shipped comms code. Option A is lower-churn but couples the
emit to the skippable extraction path and bakes detection upstream. Decide this first — it reshapes
R2, R4, and the built `recipes/comms.py`.

## Secondary couplings (smaller, resolve after the contract)
- **R1 → R2 wiring boundary:** R1 keeps `compose_reactions` a thin wiring root and DEFERS passing
  `bus.emit` into producers to R2; R2 wires it at each construction site (no app-root exists yet).
  Confirm that split.
- **No production app-root/daemon exists** — nothing calls `compose_proactive`/`compose_reactions`
  together; reactions become integration-testable + observable, but a daemon mount is a separate
  bring-up step. (Not blocking R1–R4; flag for the bring-up plan.)
- **R3:** adds a surgical `get_bill(id)` finance read + injects `get_linked_task_ref_fn` into A1/A9
  (mark_bill_paid returns None today). Independent; low-risk.
- **R4 naming:** `TIER_A_BUILTINS` already has a `gift_signal` rule on `FACT_ADDED→memory.note_gift_signal`
  (downstream); R4 adds a DISTINCT `EMAIL_INGESTED` comms rule. Keep both, don't collide names.

## Next-session flow
1. Resolve the `EMAIL_INGESTED` contract fork (A vs B) → patch R2 + R4 (+ `recipes/comms.py` if B).
2. Dispatch security/data domain reviews on R1/R2/R4 (go-live + memory-contract + untrusted-email).
3. Run the readiness gate on all four; move to `docs/changes/`.
4. Build order: R1 → R2 ∥ (R3, R4 independent).

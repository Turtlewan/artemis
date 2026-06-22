# Cross-Module Reaction Wiring Audit (surface 7)

_Generated 2026-06-20. Audits every **accepted** reaction in `docs/owner-rules/7-cross-module-reactions.md`
against the 6 wiring dimensions (emit · entity-join · GATE · quarantine · task⇄cal · idempotency/link-integrity),
using `contracts.md` seams, the module design docs, ADR-012/013, and the I/O map. Read-only analysis._

## The standing premise (applies to every 🆕 row)
The I/O map's key finding holds: **there is no reaction infrastructure today** — no emit points, no rule
store, no dispatcher. So every 🆕 reaction is "accounted" only **given the 3 new pieces get built** (emit
events · rule store · reaction dispatcher). The ✅ rows already exist as **time-polled heartbeat pushes**
(they poll, they don't subscribe); the layer makes them uniform/observable/learnable. Status below is judged
*assuming the 3 pieces + the agreed link-integrity reconciler are built* — so PARTIAL/GAP means a gap
**beyond** that baseline (a missing module capability, an unspecced entity, or a conflict with a locked decision).

**Two join types** (don't conflate): (a) **entity-backbone join** — person/place/goal via `person_fact_key`
/ `EntityRef` + `memory.resolve_entity` (Seam 6); (b) **domain link-field join** — `transaction.raw_ref`↔msg-id,
`bill.linked_task`/`linked_event`, `task.calendar_event_id`. B/charge/bill/task↔event use (b), NOT the entity backbone.

## Per-reaction table
Status: **ACCOUNTED** (covered by existing seams + the 3 pieces) · **PARTIAL** (needs a not-yet-agreed
capability) · **GAP** (missing piece beyond the 3, or conflicts with a locked decision).

| # | Reaction | Emit event | Entity/link join | GATE? | Quarantine? | task⇄cal? | Idempotency / reverse-link | Status | Note |
|---|----------|-----------|------------------|-------|-------------|-----------|----------------------------|--------|------|
| A1 | CC-bill-pay email → settlement (not spend) | Gmail email-ingested | raw_ref→msg-id; type=settlement | no (ledger write) | yes (QuarantinedReader) | n/a | raw_ref key; L1 dedup | ACCOUNTED | finance.md transfers/settlements rule covers it |
| A3a | card-payment email → txn + instrument + dedup | Gmail email-ingested | raw_ref; **instrument field** | no | yes | n/a | raw_ref + economic-event key | PARTIAL | `transaction.instrument` not yet in finance.md data model |
| A3b | PayLah!/PayNow email → classify spend/transfer/settlement | Gmail email-ingested | raw_ref; instrument | no | yes | n/a | raw_ref key | PARTIAL | needs instrument field + the purchase/transfer/settlement classifier (designed, not specced) |
| A4 | commitment email → suggestion task | Gmail commitment-extracted | — (suggestion inert) | no (suggestion) | yes | on accept → task⇄cal | suggestion-inbox idempotent | ACCOUNTED | suggestion-inbox (productivity §G) exists |
| A5 | flight itinerary → branching travel playbook | Gmail email-ingested | traveler→PERSON (Seam 6); **Trip entity** | no (self-only cal + reminders) | yes | yes (packing/airport blocks) | Trip-assembly stateful/revisable (idempotent on booking-ref) | PARTIAL | needs **Trip aggregation entity** (not in corpus) + **Maps connector** (PARKED) for airport timing |
| A6 | bill email → record bill + remind | Gmail email-ingested | bill.linked_task/event | no | yes | yes (pay task + marker) | bill state open→paid; raw_ref | ACCOUNTED | |
| A7 | interview email → prep playbook | Gmail email-ingested | company/person→entity | no (self-only cal) | yes | yes (prep task block) | event/task by msg-id | PARTIAL | in-person logistics block needs Maps; rest accounted |
| A8 | Ashley email → partner-CRM playbook | Gmail email-ingested | Ashley PERSON (person_fact_key) | no (suggest/nudge) | yes | yes (act task) | per-date-trigger idempotent | PARTIAL | needs **gift-signal memory category** + **"share/clip to Artemis" channel** (unspecced) + date-approach trigger |
| A9 | payment matches open bill → mark paid + complete task | Finance txn-recorded | bill↔payment (payee+amt+window); bill.linked_task | no | (upstream) | yes (completes task→clears block) | stateful matcher; reconciler | ACCOUNTED | finance.md bill-reconciliation loop; relies on the agreed reconciler |
| B1 | bill due → "pay X" task | Finance bill-due hook | bill.linked_task | no | n/a | yes | bill id | ACCOUNTED | ✅ specced hook |
| B2 | renewal soon → calendar marker + notify | Finance renewal hook | subscription.linked_event | no | n/a | marker | subscription id | ACCOUNTED | ✅ specced hook |
| B3 | new recurring charge → memory + price history | Finance new-sub hook | subscription entity | no | n/a | n/a | merchant key | ACCOUNTED | ✅; uses module→memory push (see X-cut #3) |
| B4 | unusual spend → notify | Finance unusual-spend hook | — | no | n/a | n/a | charge id | ACCOUNTED | ✅ specced hook |
| B8 | finance facts/patterns → memory + knowledge | Finance | finance facts | no | n/a | n/a | fact key | ACCOUNTED | ✅; module→memory push (X-cut #3) |
| B2b | renewal/price-increase → decide task + cal | Finance renewal hook | subscription.linked_task/event | no | n/a | yes (deadline=renewal) | subscription id | ACCOUNTED | new task+cal wiring over existing emit |
| B4b | unusual spend → dispute task + cal | Finance unusual-spend hook | charge.linked_task | no | n/a | yes (deadline=dispute window) | charge id | ACCOUNTED | |
| B4c | any charge → find receipt email; no match → fraud | **Finance txn-recorded (NEW emit)** | txn↔email (raw_ref/economic-event) | no | (reads quarantined email) | n/a | economic-event key; **reverse: no-match flag** | PARTIAL | matcher exists (dedup L1) but **reverse direction (charge w/o email → fraud)** + Finance→Gmail read is new; deep-dive pending |
| B5 | purchase matches "buy X" task → complete | Finance txn-recorded | purchase↔intent-task (fuzzy) | no | n/a | yes (clears block) | needs **intent-match key** | PARTIAL | purchase↔"buy X" task matcher is new + fuzzier than economic-event; precision-first |
| B6 | travel-booking purchase → A5 playbook + complete booking task | Finance txn-recorded | txn→Trip; booking task | no | n/a | yes | fan-out (2 reactions, 1 hop each) | PARTIAL | inherits A5 (Trip/Maps) + B5 (matcher) deps |
| C1 | task scheduled → focus block | Tasks task-scheduled | task.calendar_event_id | no (self-only) | n/a | yes | task id | ACCOUNTED | ✅ M8-d-b seam |
| C2 | pay-bill task done → mark bill paid | Tasks task-completed | bill.linked_task (reverse A9) | no | n/a | n/a | task id | ACCOUNTED | ✅ |
| C3 | project completed → knowledge + memory | Tasks project-completed | project/GOAL entity | no | n/a | n/a | project id | ACCOUNTED | ✅; module→memory push (X-cut #3) |
| C4 | task completed → clear focus block | Tasks task-completed | task.calendar_event_id | no | n/a | yes (clears) | task id | ACCOUNTED | ✅ |
| C5 | task overdue → notify | Tasks overdue hook | — | no | n/a | n/a | task id | ACCOUNTED | ✅ |
| C6 | commitment captured → recipe graduation | Tasks capture | — | no | (upstream) | n/a | M7 promotion | ACCOUNTED | ✅ M8-d-c2 |
| C3b | project completed → archive child tasks | Tasks project-completed | parent/child task ids | no | n/a | n/a | project id | ACCOUNTED | internal Tasks |
| C3c | task/project done linked to Goal → update Goal progress | Tasks completed | GOAL entity (Seam 6 D3) | no | n/a | n/a | goal:project_id | PARTIAL | GOAL entity exists eagerly, but **Goals sub-domain (progress model) is DEFERRED** |
| C4b | task completed → memory accomplishment note | Tasks task-completed | — | no | n/a | n/a | task id | PARTIAL | module→memory push not yet wired (X-cut #3) |
| C5b | task overdue → propose reschedule into found time | Tasks overdue hook | task.calendar_event_id | no (propose) | n/a | yes (task⇄cal) | task id | ACCOUNTED | overdue hook + `propose_reschedule` + `find_time` all exist |
| C5c | repeated overdue → escalate / flag stuck | Tasks overdue hook | — | no | n/a | n/a | task id + overdue-count state | ACCOUNTED | needs small overdue-count state |
| C6b | commitment captured → memory fact | Tasks capture | — | no | (upstream) | n/a | suggestion id | PARTIAL | module→memory push not yet wired (X-cut #3) |
| C7 | GOAL entity created → surface in week-ahead | Tasks project-create (eager GOAL) | GOAL entity | no | n/a | n/a | goal:project_id | PARTIAL | entity exists; week-ahead surfacing rides Productivity weekly hook but Goals deferred |
| D1 | meeting w/ external attendee → prep task | Calendar change-detection/new-invite | attendee→PERSON | no (prep task self) | yes (external event text) | yes (prep block) | event id | ACCOUNTED | |
| D2 | meeting cancelled → cancel block / re-plan | Calendar change-detection (show_deleted) | task.calendar_event_id | no | n/a | yes (lifecycle-sync) | event id | ACCOUNTED | M8-d-b auto-cancel precedent |
| D3 | free gap → propose scheduling a pending task | Calendar free-gap hook | task↔proposed block | no (propose) | n/a | yes | — | **GAP** | **conflicts w/ locked 2026-06-09 Productivity opt-out of the gap-fill hook**; Calendar free-gap hook emits "focus-protect", not "schedule pending task" |
| E1 | any module mentions person/place/goal → resolve+link | (all modules) | **entity backbone** `resolve_entity` | no | varies | n/a | entity id; unsure→ask | ACCOUNTED | foundational join (Seam 6) |
| E2 | booking/receipt email → knowledge | Gmail email-ingested | — | no | yes | n/a | msg-id | ACCOUNTED | ✅ |
| E3 | entity info change → propagate via refs | Memory entity-changed | EntityRef (live, no copies) | no | n/a | n/a | lifecycle-sync | ACCOUNTED | ✅ Seam 6 |
| E4 | key date learned → calendar + advance nudge | Memory fact-added (date) | person entity | no (nudge) | n/a | yes (nudge task) | date key | PARTIAL | calendar marker fine; gift/plan nudge inherits A8 deps |
| E5 | document ingested → memory facts | Knowledge doc-ingested | doc→entities | no | yes (untrusted doc) | n/a | chunk id | PARTIAL | module→memory push (X-cut #3) + **cross-store provenance open question** (fact→source chunk) |
| E5b | statement/receipt OCR → finance txn | Knowledge doc-ingested (visual) | raw_ref→doc | no | yes | n/a | doc/line key | PARTIAL | needs M3 visual-OCR → Finance extraction wiring; pairs w/ B4c |
| E5c | document ingested → link entities | Knowledge doc-ingested | resolve_entity | no | yes | n/a | doc id | ACCOUNTED | rides E1 resolver |
| E6 | memory fact that is a date → calendar marker | Memory fact-added | — | no | n/a | n/a | fact id | PARTIAL | needs a **new emit on Memory writes** (Memory currently emits only resolve_entity) |
| E6b | gift-signal fact → wishlist | Memory fact-added (gift flag) | person wishlist | no | n/a | n/a | fact id | PARTIAL | depends on A8 gift-signal category |
| E7 | before meeting a person → person briefing (=D4) | Calendar upcoming-event | person entity + recall | no | n/a | n/a | event id | ACCOUNTED | Seam 6 + memory recall + calendar; merges D4 |
| E8 | "what's due this week" → synthesize Finance+Tasks+Calendar | — (owner asks / scheduled) | hub query-time | no | n/a | n/a | — | **GAP (reclassify)** | finance.md says this is **hub-level brain synthesis at query time, NOT a reaction** — has no emit/dispatch |

## Gaps & open wiring questions
1. **D3 conflicts with a LOCKED decision.** Productivity §C/§E explicitly opted OUT of the gap-fill hook
   (owner 2026-06-09). Calendar's free-gap hook emits a *focus-protect* suggestion, not "schedule a pending
   task." Accepting D3 (propose-not-auto) **revives a deselected behavior** → owner must either reaffirm D3
   as a reaction-layer override (productivity.md + calendar.md amendment) or drop it.
2. **E8 is not a reaction.** Per finance.md §Cross-module, "what's due this week" is brain query-time
   synthesis (no emit, no dispatcher). Reclassify it as a **hub/read view**, not a reaction-layer rule. (Still
   valuable — it's the consumer side of the same links — but it belongs in the brain/hub spec, not the rule store.)
3. **Module→Memory fact-push is "structurally possible, not yet wired"** (I/O map). Blocks every
   "…→ memory fact" reaction: B3, B8, C3, C4b, C6b, E5, A8-memory. M4-b (A.U.D.N. write path) is currently
   Brain-turn-driven; a **module-initiated `MemoryStore.add_fact` path** must be specced (the spoke contract
   assumes it). → M4-b amendment.
4. **A5/B6 depend on two non-existent things:** a **"Trip" aggregation entity** (TripIt-style; not in corpus)
   and the **Maps/travel-time connector** (PARKED). Without Maps, airport-timing blocks degrade to fixed-buffer
   guesses. → likely a small **Travel** capability + de-park Maps before A5 ships.
5. **A8/E4/E6b depend on unspecced capabilities:** a **gift-signal memory category** (extends M4 extraction)
   and the **"share/clip to Artemis" iOS channel** (CLIENT addition; email fallback exists). → M4 extraction
   amendment + a CLIENT spec.
6. **`transaction.instrument`/`account` field missing** from finance.md data model (it has `type`, not
   `instrument`). Blocks A3a/A3b "which card/PayLah/PayNow." → finance.md amendment (already noted in workbook §Finance deltas).
7. **B4c reverse-direction + Finance→Gmail read is new.** Dedup L1 gives charge↔email matching; the *reverse*
   (charge with NO email → fraud signal) and Finance querying Gmail cross-module are new wiring. Deep-dive pending.
8. **C3c/C7 Goal-progress:** the GOAL *entity* exists (Seam 6 D3, created eagerly by Productivity), but the
   Goals *sub-domain* (progress model) is DEFERRED — so these are correctly Goal-gated, build when Goals land.
9. **E6 needs a new Memory emit.** Memory today emits only `resolve_entity` results; "fact-added (is a date)"
   and "fact-added (gift-signal)" require Memory to emit fact-write events. → M4 emit point.
10. **Cross-store provenance (E5)** — open question already in status.md: does a document-sourced fact carry a
    pointer back to its M3 chunk, or bottom out at a turn id? Affects E5's link-integrity.

## Cross-cutting findings
- **One matcher, reused.** A9 (payment↔bill), B4c (charge↔receipt), B5/B6 (purchase↔task), Finance dedup L1,
  and the link-integrity reconciler are **the same fuzzy-match primitive** (stable key + amount/date-window +
  precision-first → owner-review). Build it once as a shared reconciler service; every loop binds to it.
- **GATE is rarely triggered** by the accepted set — almost all reactions are internal/reversible (ledger
  writes, memory facts, self-only focus blocks, suggestions/nudges). No accepted reaction auto-sends external
  comms (gift/dinner = suggestion; check-in = reminder). The dispatcher must still route external-effect
  reactions through GATE, but the *current* accepted rows mostly won't hit it. Matches the internal-reversible autonomy boundary.
- **Two reactions are really hub views, not reactions:** E8 ("what's due this week") and arguably E7/D4
  (person briefing on demand). These are **query-time synthesis** — the *read* side of the same links the
  reactions *write*. Keep them out of the rule store; spec them in the brain/hub layer.
- **Memory is under-instrumented as an emitter.** It's the join fabric but emits almost nothing (only
  resolve_entity). E3/E4/E6/E6b all want "memory changed" events → Memory needs a fact-write emit point.
- **Stateful/multi-event reactions are a first-class requirement** (A5 trip-assembly, A9 bill reconciliation,
  C5c overdue-count) — the rule store + dispatcher must support accumulate-over-window + revisable state, not
  just fire-once-per-event. A5 is the proof case.
- **D4 correctly merges into E7** (one person-briefing reaction, calendar-triggered). No wiring issue.

## Bottom line
27 ACCOUNTED · 17 PARTIAL · 2 GAP (of 46). No reaction is structurally impossible; the PARTIALs cluster on
**5 missing capabilities** (module→memory push · Trip entity · Maps connector · gift-signal+share-channel ·
transaction.instrument) + **Goals deferred**. The 2 GAPs are a **locked-decision conflict (D3)** and a
**miscategorization (E8 = hub view)** — both owner calls, not build problems.

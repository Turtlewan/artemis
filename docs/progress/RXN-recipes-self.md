# Progress: RXN-recipes-self — COMPLETE

Built by Codex; host-verified + independent Opus cross-model review (finance/fraud reactions).
Host: mypy clean (258 files), ruff clean, 732 passed / 2 skipped.

## Built
A1 (statement→settlement), A6, A9 (payment reconcile), B4c (high-value no-receipt fraud confirm),
bill lifecycle, bill_paid_event (scalar-only BILL_PAID emit), register_self_reactions.

## Cross-model review — no BLOCK; fraud path CONFIRMED notification-only
B4c over-threshold routes to fraud_notify_fn only (no card_block, no auto-action); below-threshold
gate + X3-threshold-read + receipt-clears tests present.

### Applied (financial-safety test strengthening)
- **B4c over-threshold test bumped 500.00→600.00:** the original amount equaled the default
  ~S$500 threshold, so with strict `<` it proved only "at threshold (inclusive)", not "over". Now
  proves the over-threshold fraud-signal path unambiguously.

### FLAGGED for planning (NOT changed — cross-spec contract / known follow-up)
- **⚠ HIGH: react_bill_paid_lifecycle is dead-in-production.** It reads `linked_task_ref` from the
  BILL_PAID event payload, but `bill_paid_event()` (the builder A1/A9 call) never emits that field —
  so in production the lifecycle always returns "skipped" (the test passes only via a hand-built
  fixture). Fix is a cross-spec contract decision: where `linked_task_ref` is sourced at emit
  (depends on the FIN-c mark-paid return + FIN-a bill record). Pairs with the already-known
  "txn-recorded emit not wired into FIN-b" follow-up — resolve the RXN↔FIN emit wiring together.
- **A1/A9 emit gated on changed=True** (MEDIUM): BILL_PAID/complete are skipped when the FIN-c tool
  reports changed=False — reasonable idempotency but a spec divergence (spec says emit on first
  fire). Document or always-emit-and-let-the-dedup-ledger-suppress.
- **B4c threshold inclusive vs exclusive** (DECISIONS-LOG I-3 says "above"): code is inclusive
  (`amount < threshold → below`, so exactly-threshold → fraud). Confirm intended boundary.
- low: stateful two-fire receipt-clear not tested; ADR-011 source-guard string check is weak;
  `_register_tool` mutates ToolRegistry privates (`_tools`/`_pending`/`_manifests`) — registry owner
  should expose a public `register_tool`.

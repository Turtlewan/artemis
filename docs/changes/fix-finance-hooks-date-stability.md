---
spec: fix-finance-hooks-date-stability
status: ready
token_profile: lean
autonomy_level: L2
---

## Intent
Make `tests/test_finance_hooks.py` date-stable. `make_renewal_check` / `make_bill_due_check`
(`src/artemis/modules/finance/hooks.py`) filter `today <= date <= today+window` where
`today = datetime.datetime.now(UTC).date()` (the real clock). The test hardcodes
`today = "2026-06-25"` and seeds `next_renewal` / `due_date` from it, so once the wall-clock
rolls past that date the seeded dates fall out of the window and `test_hooks_hit_with_count_id_scalar_payloads`
fails (observed 2026-06-26). This is the single red test in an otherwise-green suite; it is a
test-data brittleness bug, not a product bug — the hook logic is correct.

## Key decisions
- Fix the **test**, not the hook. The hook's `now()`-relative window is correct behaviour
  (real renewals are relative to today). Do NOT inject a clock into the production hook for this.
- Derive the test's `today` from the real current date (`datetime.date.today()` /
  `datetime.datetime.now(datetime.UTC).date()`) instead of a hardcoded literal, so every seeded
  subscription/bill/transaction date is always positioned relative to "now" and the hooks fire
  deterministically on any run date.
- Keep the relative offsets the test already encodes (e.g. transactions on consecutive days, the
  bill/renewal due "today") — only the anchor changes from a literal to `date.today()`.

## Gotchas / edge cases
- Any OTHER hardcoded date in the same test that feeds a windowed hook must move to the same
  relative anchor (scan the whole test function — `next_renewal`, `due_date`, `last_seen_date`,
  the five `txn_date` rows, and the `spending_summary` 7-day window which also uses `_today()`).
- The `spending_summary` check uses `today - 7d <= txn_date <= today + 1d`; the seeded
  transaction dates must land inside that window relative to the new anchor.
- Use UTC (`datetime.datetime.now(datetime.UTC).date()`) to match the hook's `_today()` exactly,
  avoiding a midnight-local-vs-UTC edge.

## Tasks
1. In `tests/test_finance_hooks.py`, replace the hardcoded `today = "2026-06-25"` anchor in
   `test_hooks_hit_with_count_id_scalar_payloads` (and any sibling test with the same pattern)
   with a real-date anchor (`datetime.datetime.now(datetime.UTC).date()`), and re-express every
   seeded `next_renewal` / `due_date` / `last_seen_date` / `txn_date` as an offset from that anchor
   so all four hook checks (`renewal`, `new_recurring`, `bill_due`, `spending_summary`) fire.
   — done when: `uv run pytest -q tests/test_finance_hooks.py` passes on today's date AND would
   still pass if the system clock advanced (offsets are relative, no absolute literals feeding a
   windowed hook).

## Files to touch
- `tests/test_finance_hooks.py` — anchor the test's dates to the real current date (relative offsets).

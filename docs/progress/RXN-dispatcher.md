# Progress: RXN-dispatcher — COMPLETE

Built by Codex; host-verified + independent Opus cross-model review (security keystone).
Host: mypy clean (249 files), ruff clean, 692 passed / 2 skipped.

## Cross-model review — no BLOCK; core security invariants CLEAN
Non-stateful dedup uses atomic try_claim (INSERT OR IGNORE); external-effect reactions only stage;
A4 path inert (CaptureService.suggest_from_text, no direct write); scalar-only event payloads.

### Applied (security-invariant hardening, in-scope dispatcher.py)
- **A4 routing made authoritative:** check `reaction_ref == email_to_task` BEFORE `external_effect`,
  so an A4 reaction is ALWAYS inert even if misconfigured external_effect=True (review: spec-invariant
  risk).
- **run_forever degrade-don't-crash symmetry:** guarded `rules_for` with the same try/except
  drain_once has (a rule-store exception no longer kills the loop).

### FLAGGED for planning (NOT changed)
- **Stateful-rule dedup atomicity (review HIGH) — NOT reachable in the current design.** The drain is
  single-consumer sequential (drain_once / run_forever await _fire one event at a time), so the
  read-compare-then-write on state_hash has no concurrent racer; sequential re-delivery is safe
  (first fires + record_refire writes the hash, next read returns). The TOCTOU only bites under a
  future MULTI-consumer drain — at which point the stateful path should adopt a try_claim first-fire
  guard or a BEGIN IMMEDIATE read+write txn. Documented, not changed (would alter stateful semantics).
- **record_refire inside the effect try/except (MEDIUM):** a ledger-write failure right after a
  successful effect is swallowed → re-fire window on next delivery. Low-impact (local sqlite ledger,
  single owner); consider a dedicated guard/higher-severity log.
- A4 path emits no notice_sink (I-10 passive-notice posture) — advisory.
- Test white-box helpers (_ledger_rows uses ledger._connect; one test uses plain sqlite3 off-hardware).

Codex used lazy `__getattr__` exports in reactions/__init__.py to avoid an emit->memory->reactions
import cycle (standard idiom; reviewer flagged a doc-comment nicety only).

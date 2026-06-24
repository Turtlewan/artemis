---
spec: rxn-reconciler
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave R · reaction infra piece (iv) — Decision 4 + 6. The ONE shared fuzzy-match reconciler primitive
     (stable-key + amount/date-window + precision-first → owner-review on uncertainty) serving A9/B4c/B5/B6/
     finance-dedup-L1/link-integrity. Plus the nightly link-integrity sweep (I-7=A). Reads windows from X3. -->

# Spec: RXN-reconciler — shared fuzzy-match reconciler + nightly link-integrity sweep

**Identity:** The single reconciliation primitive every Finance/reaction loop binds to — `Reconciler.match(candidates, target, …)` returns matched / ambiguous / unmatched on a `stable-key + amount/date-window + normalized-merchant` basis, auto-merging only high-confidence exact matches and surfacing everything below the bar as an inert "possible duplicate?" / needs-review suggestion. Plus the periodic **link-integrity sweep** that finds half-wired cross-module links, auto-repairs deterministic halves, and flags fuzzy ones to a needs-review lane.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (Decision 4 one shared reconciler · Decision 6 link-integrity = contract + reconciler · I-7=A nightly sweep) · docs/technical/modules/finance.md (L0–L4 ladder).

<!-- ONE logical phase: the match primitive + the link-integrity sweep that is an instance of it. 1 src file
     + 1 test. Depends on RXN-dispatcher (the sweep runs as a nightly reaction / heartbeat hook) + the
     spoke stores it reconciles over (Finance, Tasks, Calendar — accessed via their tools, never direct joins). -->

## Assumptions

- **RXN-dispatcher** complete: the nightly link-integrity sweep runs as a scheduled reaction / M6 hook; the reconciler's match primitive is called by the Finance dedup loop (FIN-c) and the A9/B4c/B5/B6 reaction recipes (RXN-recipes-*). → impact: Stop (the reconciler is a library; its callers are the dispatcher loops + FIN-c).
- **X3 runtime-config** complete: `get_runtime_config().finance.{reconcile_date_window_days, reconcile_amount_exact}` and `.reaction.reconciler_nightly_time` supply the match windows + the sweep cadence. The reconciler reads these at construction (composition-time). → impact: Stop (tight tunable defaults: date ±1d, exact amount; nightly 03:00 — all from X3).
- **Precision-first (load-bearing, ADR-021 posture):** auto-merge ONLY a high-confidence exact match (exact amount when `reconcile_amount_exact`, within the date window, normalized-merchant equal). Anything below that bar → an INERT suggestion (owner confirms) — NEVER a silent merge. This is the L3 "ambiguous → owner, not silent" rule. → impact: Stop (the match result classes + the auto-merge gate are the correctness core).
- **Cross-module access is tool-mediated (ADR-013 D2 / ADR-011):** the link-integrity sweep reads each spoke's state through its READ tools / repository accessors — NEVER a cross-store SQL join. A half-link is detected by comparing logical refs (`{module, id}`) across spokes via their tools. → impact: Stop (no cross-scope DB join; the sweep is a logical-ref consistency check).
- **The reconciler holds no domain state** (I-8=C): it is a pure-ish matcher + a sweep that calls spoke tools to repair/flag; the needs-review lane is the existing suggestion/Review surface (M8-d-c2 `suggestions` / GATE Review) — not a new store. → impact: Stop.
- Off-hardware: pure-function match tests + a sweep test over `FakeFinanceStore`/`FakeTasksStore`/`FakeCalendarClient` with seeded half-links. Deterministic, no model. → impact: Low.

Simplicity check: ADR-021 Decision 4 is explicit — ONE reconciler, not per-loop matchers. The match primitive is a pure function over candidate/target records + a config window; the link-integrity sweep is the SAME primitive applied to cross-module link pairs. No fuzzy-ML matcher (precision-first + deterministic windows + normalized-string equality is the bar; a learned matcher is the L4 recipe-graduation path, not this primitive). The minimum is: a `match()` function returning typed result classes + a `sweep_link_integrity()` that calls it over link pairs.

## Prerequisites

- Specs complete: **RXN-dispatcher** (the sweep runs as a nightly reaction), **X3-runtime-config** (windows + cadence), and the spoke read surfaces it reconciles (FIN-a `FinanceRepository`, M8-d-a `ProductivityStore`, CAL-a `CalendarClient` read tools).
- Environment: no new PyPI deps (stdlib).

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/reactions/reconciler.py` | create | `MatchResult`, `Reconciler.match`, `normalize_merchant`, `sweep_link_integrity`, `LinkIntegrityReport` |
| `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` | modify | re-export `Reconciler`, `MatchResult`, `LinkIntegrityReport` |
| `/Users/artemis-build/artemis/tests/test_reactions_reconciler.py` | create | exact-match auto-merge, ambiguous→suggestion, no-match, date/amount-window edges, merchant normalization, link-integrity sweep repair + flag |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Define the match result types + `normalize_merchant`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/reconciler.py` —

  ```python
  class MatchOutcome(StrEnum):
      EXACT = "exact"            # high-confidence → auto-merge allowed
      AMBIGUOUS = "ambiguous"    # below bar → inert suggestion, owner confirms
      NONE = "none"              # no candidate within window

  @dataclass(frozen=True)
  class MatchResult:
      outcome: MatchOutcome
      target_id: str
      matched_id: str | None             # the candidate id when EXACT/AMBIGUOUS, else None
      score: float                       # 0..1 confidence
      reason: str                        # deterministic explanation for the suggestion/audit

  def normalize_merchant(raw: str) -> str:
      """Lowercase, strip punctuation/whitespace, drop common suffixes (PTE LTD, store numbers,
      trailing digits) → a stable comparison key. Deterministic, no model."""
  ```

  — done when: `uv run mypy --strict src` passes; `normalize_merchant("NTUC FairPrice #123  PTE LTD") == normalize_merchant("ntuc fairprice")` (or an agreed canonical form); `MatchResult` constructs frozen.

- [ ] **Task 2: Implement `Reconciler.match`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/reconciler.py` —

  ```python
  class Reconciler:
      def __init__(self, *, date_window_days: int, amount_exact: bool, amount_tol: Decimal = Decimal("0")) -> None: ...
      # constructed from X3: date_window_days=cfg.finance.reconcile_date_window_days,
      #                      amount_exact=cfg.finance.reconcile_amount_exact

      def match(self, target: "ReconcileRecord", candidates: Sequence["ReconcileRecord"]) -> MatchResult:
          """Precision-first fuzzy match on amount + date-window + normalized merchant.
          EXACT (auto-merge) only when: amount equal (or within amount_tol if not amount_exact) AND
          |date(target) - date(candidate)| <= date_window_days AND normalize_merchant equal.
          A single near-but-not-exact candidate → AMBIGUOUS (inert suggestion). No candidate in window → NONE.
          Multiple EXACT candidates → AMBIGUOUS (precision-first: never auto-pick among ties)."""
  ```
  `ReconcileRecord` = a frozen `{id: str, amount: Decimal, currency: str, date: str, merchant: str}` (the common shape A9/B4c/B5/B6/finance-dedup map their domain rows into — the ONE shape the ONE matcher takes).

  Match algorithm (deterministic, precision-first):
  1. Filter candidates to those within `date_window_days` AND same currency.
  2. Among those, find exact-amount + normalized-merchant-equal candidates.
  3. Exactly ONE such → `EXACT` (auto-merge eligible), `score=1.0`.
  4. More than one such (tie) → `AMBIGUOUS` (never auto-pick).
  5. Zero exact but ≥1 within-window candidate with partial match (amount within `amount_tol` if `not amount_exact`, OR merchant equal but amount differs) → `AMBIGUOUS` (inert suggestion), `score` from the partial overlap.
  6. No within-window candidate → `NONE`.

  — done when: `uv run mypy --strict src` passes; an exact amount+date+merchant single candidate → `EXACT`; two exact candidates → `AMBIGUOUS` (tie, no auto-pick); a same-merchant different-amount candidate → `AMBIGUOUS`; an out-of-window candidate → `NONE`; a same-month recurring charge (different month, outside window) → `NONE` (the finance.md "subscription monthly charge is NOT a duplicate" invariant).

- [ ] **Task 3: Implement `sweep_link_integrity`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/reconciler.py` —

  ```python
  @dataclass(frozen=True)
  class LinkIntegrityReport:
      repaired: tuple[str, ...]       # link descriptors auto-repaired (deterministic half-links)
      flagged: tuple[str, ...]        # link descriptors sent to the needs-review lane (fuzzy)
      checked: int

  def sweep_link_integrity(
      *, link_pairs: Sequence["LinkPair"], repair_fn: Callable[["LinkPair"], None],
      flag_fn: Callable[["LinkPair"], None],
  ) -> LinkIntegrityReport:
      """I-7=A: for each cross-module link pair (e.g. bill↔task, task↔calendar-block, payment↔bill),
      check both halves resolve. A deterministic half-link (one side has the ref, the other lost it, and
      the missing side is unambiguously reconstructable) → repair_fn (auto-repair). A fuzzy/ambiguous
      half-link → flag_fn (needs-review lane). Returns the report. Runs nightly + on-demand from the hub."""
  ```
  `LinkPair` = a frozen `{kind: str, left_ref: EntityRef | str, right_ref: EntityRef | str | None, deterministic: bool}` — the per-recipe specs build these from spoke tool reads (NEVER a cross-store join). `deterministic=True` ⇒ the missing half is unambiguously reconstructable → `repair_fn`; else → `flag_fn`. The sweep itself is the Decision-4 primitive applied to link pairs (it does not embed domain knowledge — `repair_fn`/`flag_fn` are injected by the caller).

  **Nightly cadence:** the sweep is wired as a scheduled reaction / M6 hook firing at `cfg.reaction.reconciler_nightly_time` (default 03:00) + invocable on-demand from the hub Review view. This spec defines the function; the hook wiring is a one-line composition-root registration documented here (the per-cluster recipe specs / a hub spec register it).

  — done when: `uv run mypy --strict src` passes; a deterministic half-link (left has ref, right missing, `deterministic=True`) → `repair_fn` called, descriptor in `repaired`; a fuzzy half-link (`deterministic=False`) → `flag_fn` called, descriptor in `flagged`; a fully-wired pair → neither; `checked` equals the input length.

- [ ] **Task 4: Tests** — files: `/Users/artemis-build/artemis/tests/test_reactions_reconciler.py` — typed pytest (pure functions — mostly sync).

  - **Exact auto-merge:** one exact amount+date+merchant candidate → `EXACT`, `matched_id` set, `score==1.0`.
  - **Tie → ambiguous:** two exact candidates → `AMBIGUOUS`, `matched_id is None` (no auto-pick).
  - **Partial → ambiguous:** same normalized merchant, amount off by $0.50, `amount_exact=True` → `AMBIGUOUS`.
  - **Out of window → none:** candidate 5 days off, `date_window_days=1` → `NONE`.
  - **Recurring not a dup:** same merchant+amount but a month apart (outside window) → `NONE` (finance.md invariant).
  - **Merchant normalization:** `"NTUC #123 PTE LTD"` matches `"NTUC"` after `normalize_merchant`.
  - **amount_tol path:** `amount_exact=False, amount_tol=Decimal("0.10")` → a $0.05 difference within tol + merchant+date match → `EXACT`.
  - **Link sweep repair:** a deterministic half-link → `repair_fn` called, in `repaired`.
  - **Link sweep flag:** a fuzzy half-link → `flag_fn` called, in `flagged`.
  - **Link sweep clean:** a fully-wired pair → neither callback; `checked` correct.

  — done when: `uv run pytest -q tests/test_reactions_reconciler.py` passes AND `uv run mypy --strict src tests/test_reactions_reconciler.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/reconciler.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` |
| Create | `/Users/artemis-build/artemis/tests/test_reactions_reconciler.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_reactions_reconciler.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_reactions_reconciler.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/reactions/reconciler.py`, `src/artemis/reactions/__init__.py`, `tests/test_reactions_reconciler.py` |
| `git commit` | `"feat: RXN-reconciler — shared fuzzy-match primitive + nightly link-integrity sweep"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings (X3 windows/cadence resolution; off-hardware: defaults) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure matching + tool-mediated reads; no network |

## Specialist Context

### Security

- **Precision-first (no silent merge):** auto-merge ONLY a single high-confidence exact match; ties and partials become inert suggestions the owner confirms (L3). This prevents the reconciler from silently collapsing two genuinely distinct charges. The same-month-recurring-charge case correctly stays distinct (different months are outside the date window).
- **No cross-store join (ADR-013 D2):** the link-integrity sweep compares logical refs read through spoke tools — it never opens another spoke's SQLCipher store. A half-link is a logical-ref inconsistency, repaired/flagged via the spoke's own tools (`repair_fn`/`flag_fn` injected by the caller).
- **Needs-review lane reuses existing surfaces:** flagged fuzzy links go to the M8-d-c2 `suggestions` / GATE Review surface — no new owner-facing store. The reconciler holds no domain state (I-8=C). [apex-security note: confirm the auto-merge gate cannot fire on a tie or a partial; confirm the sweep never joins across scopes; confirm `repair_fn` for an external-effect repair would route through GATE (the caller's responsibility — the reconciler only classifies).]

### Performance

- `match` is O(candidates) per target with deterministic string/decimal ops — trivial at finance scale (a candidate window is a small date-bounded slice). The nightly sweep is O(link pairs) once per night — bounded and off the interactive path. Money compares as `Decimal` (no FP error). `normalize_merchant` is a cheap deterministic transform.

### Accessibility

(none — headless infra; the needs-review lane surfaces in Review, Wave U)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/reconciler.py` | Document the ONE-matcher-for-all-loops design (Decision 4), the precision-first auto-merge gate (single exact only; ties/partials → suggestion), the `ReconcileRecord` common shape, the merchant normalization, and the tool-mediated (no cross-store-join) link sweep |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_reactions_reconciler.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_reactions_reconciler.py` → verify: exact single → auto-merge EXACT; ties → AMBIGUOUS (no auto-pick); partial → AMBIGUOUS; out-of-window → NONE; same-merchant-different-month → NONE; merchant normalization matches; amount_tol path; link sweep repairs deterministic + flags fuzzy + leaves clean pairs.
- [ ] `uv run python -c "from artemis.reactions import Reconciler, MatchResult, LinkIntegrityReport; print('ok')"` → verify: prints `ok`.

## Progress
_(Coding mode writes here — do not edit manually)_

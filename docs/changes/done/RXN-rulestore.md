---
spec: rxn-rulestore
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave R · reaction infra piece (ii) — Decision 3-ii. The rule store: persisted reaction definitions
     with tier + state, REUSING the M7 RecipeStore for Tier-B graduation (NOT a parallel store — ADR-021
     explicitly rejects one; Tier-B rules ARE recipes). Defines the ReactionRule binding + the Tier-A
     built-in set + the ratified extended Tier-A list. -->

# Spec: RXN-rulestore — reaction rule store (ReactionRule + Tier-A built-ins + Tier-B-over-RecipeStore)

**Identity:** The reaction layer's rule registry — a `ReactionRule` (event_type → reaction callable + tier + idempotency-key builder), the day-one **Tier-A built-in set** (enabled from boot), and the Tier-B path that **reuses the M7 `RecipeStore`** so judgment reactions graduate `suggest → confirm → ENABLED` through the existing recipe loop rather than a parallel store.
→ why: see docs/technical/adr/ADR-021-cross-module-reactions.md (Decision 3-ii rule store · Decision 1 three-tier model · Decision 2 Tier-A gate) · docs/changes/M7-a1-recipe-format-store-signing.md (RecipeStore reuse).

<!-- ONE logical phase: the ReactionRule type + the Tier-A built-in table + the RecipeStore-backed Tier-B lookup. 2 src files + 1 test. Depends on RXN-emit (EventType) + M7-a1/b (RecipeStore/RecipeStatus/Promoter). The dispatcher (RXN-dispatcher) consumes the rule lookups; this spec does not dispatch. -->

## Assumptions

- **RXN-emit** complete: `EventType` (StrEnum), `DomainEvent` from `artemis.reactions`. Rules bind to `EventType` values. → impact: Stop.
- **M7-a1** complete: `Recipe`, `RecipeClass`, `ActionClass`, `RecipeStatus` (`CANDIDATE`/`PENDING`/`ENABLED`/`RETIRED`), `RecipeStore` (`async write`, `list(*, status=)`, `retrieve_recipes`) from `artemis.recipes`. **Tier-B reaction rules ARE recipes** — stored, signed, graduated via this exact store (ADR-021: no parallel store). A reaction recipe's `task_class_key` is its reaction identity; its `action_class` drives the Tier-A/B gate (`READ_ONLY` ⇒ may be auto; `TOUCHES_DATA`/`TAKES_ACTION` ⇒ gated). → impact: Stop.
- **M7-b** complete: `Promoter` (`note_occurrence`, `threshold`, `store`, `recurrence`), `RecurrenceStore`, `ReviewSurface`, `classify_safety` from `artemis.recipes.promotion`. Tier-B graduation reuses `Promoter.note_occurrence` exactly as M8-d-c2 capture-graduation does. → impact: Stop.
- **X3 runtime-config** complete: `get_runtime_config()` — RXN-rulestore reads NO tunables directly (rule enable/disable is owner-declared state in the RecipeStore + the Tier-A built-in table); the reconciler/dispatcher read X3, not the rule store. → impact: Low.
- **Tier-A gate (Decision 2 — load-bearing, structural):** a rule may be Tier-A **only if** universal ∧ internal ∧ reversible ∧ zero-judgment. The day-one Tier-A set is exactly: **E1** (entity resolve+link), **C1/C4** (task↔focus-block create/clear), **D2** (lifecycle-sync: cancel meeting → cancel block), **A6** (bill email → pay-bill task) — plus the **ratified extended Tier-A list** (I-6=B): **A1** (CC-bill→settlement marker), **A9-link** (payment↔bill link), **C2** (task-done→mark-paid), **E2/E3** (date-fact + gift-signal memory category) — all verified gate-passing. Everything else is Tier-B. A Tier-A rule's reaction callable MUST be internal/reversible (no `ActionStagingService`); a rule whose callable has an external effect is **forbidden** from Tier-A and the manifest builder raises. → impact: Stop (the gate is enforced at rule-registration, not by convention).
- Off-hardware: in-memory `FakeRecipeStore`/`FakeRecurrenceStore`/`FakePromoter` (the M8-d-c2 fixtures), deterministic. → impact: Low.

Simplicity check: considered a fresh `ReactionRuleStore` SQLCipher table for Tier-B rule state — rejected; ADR-021 Decision 3-ii + the alternatives section explicitly reject a parallel store (Tier-B rules ARE recipes; the suggest→confirm→graduate state machine already exists in M7). Tier-A rules are a small in-code table (they're built-in by definition — they don't need persistence; enabling/disabling a Tier-A rule is an owner-declared override stored as a recipe `RETIRED`/`ENABLED` flag, the Tier-C path). The minimum is: a `ReactionRule` value type + a Tier-A built-in table + a thin lookup that reads ENABLED reaction-recipes from the RecipeStore for Tier-B.

## Prerequisites

- Specs complete: **RXN-emit** (`EventType`), **M7-a1** (`RecipeStore`/`Recipe`/`RecipeStatus`/`ActionClass`), **M7-b** (`Promoter`/`classify_safety`/`ReviewSurface`).
- Environment: no new PyPI deps.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/reactions/rulestore.py` | create | `ReactionTier`, `ReactionRule`, `TIER_A_BUILTINS`, `ReactionRuleStore` (Tier-A table + RecipeStore-backed Tier-B lookup) |
| `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` | modify | re-export `ReactionTier`, `ReactionRule`, `ReactionRuleStore`, `TIER_A_BUILTINS` |
| `/Users/artemis-build/artemis/tests/test_reactions_rulestore.py` | create | Tier-A gate rejection, rule lookup by event_type, Tier-B-via-RecipeStore, graduation seam, owner-disable override |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Define `ReactionTier` + `ReactionRule`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/rulestore.py` —

  ```python
  class ReactionTier(StrEnum):
      A = "tier_a"   # built-in, enabled day-one; universal∧internal∧reversible∧zero-judgment
      B = "tier_b"   # judgment; suggest→confirm→graduate via M7 RecipeStore

  @dataclass(frozen=True)
  class ReactionRule:
      name: str                              # stable rule identity (also the recipe task_class_key for Tier-B)
      event_type: EventType                  # the trigger
      tier: ReactionTier
      external_effect: bool                  # True ⇒ dispatcher routes through GATE (ActionStagingService)
      reaction_ref: str                      # fq tool id OR recipe name the dispatcher invokes
      dedup_key_fields: tuple[str, ...]      # payload/entity-ref fields composing the stable idempotency key
      stateful: bool = False                 # True ⇒ re-fire updates (windowed reaction, Decision 5)
  ```

  `model`-level guard (a `__post_init__` or a builder validator): **Tier-A ⇒ `external_effect is False`** (raise `ValueError(f"Tier-A rule {name} may not have an external effect — it must graduate via Tier-B")`). This is the Decision-2 gate enforced structurally.

  — done when: `uv run mypy --strict src` passes; a `ReactionRule(tier=A, external_effect=True, ...)` raises `ValueError`; a Tier-A internal rule + a Tier-B external rule both construct.

- [ ] **Task 2: Define the Tier-A built-in table** — files: `/Users/artemis-build/artemis/src/artemis/reactions/rulestore.py` —

  `TIER_A_BUILTINS: tuple[ReactionRule, ...]` — the day-one + ratified-extended set (Decision 2 + I-6=B). Each names its `event_type`, `reaction_ref` (the fq tool/recipe the dispatcher fires), and `dedup_key_fields`. All `external_effect=False` (internal/reversible only):

  ```python
  TIER_A_BUILTINS = (
      ReactionRule("entity_link", EventType.FACT_ADDED, ReactionTier.A, False, "memory.resolve_entity", ("fact_id",)),          # E1
      ReactionRule("task_block_create", EventType.TASK_CREATED, ReactionTier.A, False, "tasks.schedule", ("task_id",)),          # C1
      ReactionRule("task_block_clear", EventType.TASK_DONE, ReactionTier.A, False, "tasks.schedule", ("task_id",), stateful=True),# C4 (clear-on-done)
      ReactionRule("lifecycle_sync", EventType.EVENT_INGESTED, ReactionTier.A, False, "calendar.schedule_task", ("event_id",), stateful=True), # D2
      ReactionRule("bill_to_task", EventType.BILL_RECORDED, ReactionTier.A, False, "tasks.create_from_bill", ("bill_id",)),       # A6
      ReactionRule("cc_settlement_marker", EventType.PAYMENT_RECORDED, ReactionTier.A, False, "finance.mark_settlement", ("txn_id",), stateful=True),  # A1
      ReactionRule("payment_bill_link", EventType.PAYMENT_RECORDED, ReactionTier.A, False, "finance.link_payment_bill", ("txn_id","bill_id"), stateful=True),  # A9-link
      ReactionRule("task_done_mark_paid", EventType.TASK_DONE, ReactionTier.A, False, "finance.mark_bill_paid", ("task_id",), stateful=True),  # C2
      ReactionRule("date_fact", EventType.FACT_ADDED, ReactionTier.A, False, "memory.note_date_fact", ("fact_id",)),              # E2
      ReactionRule("gift_signal", EventType.FACT_ADDED, ReactionTier.A, False, "memory.note_gift_signal", ("fact_id",)),          # E3
  )
  ```
  (The `reaction_ref` fq ids are the contract the per-cluster recipe specs (RXN-recipes-*) implement; this table fixes the event→reaction binding. If a referenced tool doesn't exist yet, the per-recipe spec creates it — RXN-rulestore declares the binding, not the implementation.)

  — done when: `uv run mypy --strict src` passes; `TIER_A_BUILTINS` has 10 rules; every entry has `tier == ReactionTier.A` and `external_effect is False`; constructing them raises nothing (gate passes for all).

- [ ] **Task 3: Implement `ReactionRuleStore`** — files: `/Users/artemis-build/artemis/src/artemis/reactions/rulestore.py`, `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` —

  ```python
  class ReactionRuleStore:
      """Resolves the active reaction rules for an event_type. Tier-A from the built-in table;
      Tier-B from the M7 RecipeStore (ENABLED reaction-recipes). Owner-disable is a RETIRED recipe
      or a disabled-set override (Tier-C, Decision 1)."""
      def __init__(self, recipe_store: RecipeStore, promoter: Promoter,
                   *, builtins: tuple[ReactionRule, ...] = TIER_A_BUILTINS,
                   disabled: frozenset[str] = frozenset()) -> None: ...

      def rules_for(self, event_type: EventType) -> list[ReactionRule]:
          """Tier-A built-ins for this event_type (minus owner-disabled) + Tier-B ENABLED reaction-recipes
          whose recipe encodes this event_type. Returns the union the dispatcher fires."""

      def note_tier_b_occurrence(self, rule_name: str) -> None:
          """Tier-B graduation seam — delegates to Promoter.note_occurrence(rule_name) (the recipe
          task_class_key == rule_name). Reuses the M7 suggest→confirm→graduate loop verbatim."""
          self._promoter.note_occurrence(rule_name)
  ```

  **Tier-B encoding:** a Tier-B reaction is a `Recipe` whose `task_class_key == rule.name` and whose `description`/`instructions` encode the `event_type` (the per-cluster recipe specs author these recipes). `rules_for` reads `recipe_store.list(status=RecipeStatus.ENABLED)`, filters to reaction-recipes for the event_type (a `recipe_class`/naming convention — e.g. recipes whose `task_class_key` starts with `"reaction:"`), and maps each to a `ReactionRule(tier=B, external_effect=<from action_class>, reaction_ref=recipe.name, ...)`. A recipe with `action_class in {TOUCHES_DATA, TAKES_ACTION}` ⇒ `external_effect=True` (dispatcher routes through GATE).

  **Owner-disable (Tier-C):** a rule name in `disabled` is excluded from `rules_for` output (owner force-disable); a hand-written/force-enabled rule is an owner-authored ENABLED recipe — already covered by the Tier-B path.

  Re-export `ReactionTier`, `ReactionRule`, `ReactionRuleStore`, `TIER_A_BUILTINS` from `__init__.py`.

  — done when: `uv run mypy --strict src` passes; `rules_for(EventType.BILL_RECORDED)` returns the `bill_to_task` Tier-A rule; with a `FakeRecipeStore` holding an ENABLED reaction-recipe for `TXN_RECORDED`, `rules_for(EventType.TXN_RECORDED)` includes it as a Tier-B rule; a rule name in `disabled` is excluded; `note_tier_b_occurrence("r")` calls `Promoter.note_occurrence("r")`.

- [ ] **Task 4: Tests** — files: `/Users/artemis-build/artemis/tests/test_reactions_rulestore.py` — typed pytest, reuse the M8-d-c2 `FakeRecipeStore`/`FakeRecurrenceStore`/`FakePromoter` fixtures.

  - **Tier-A gate:** `ReactionRule("x", EventType.TASK_DONE, ReactionTier.A, external_effect=True, ...)` raises `ValueError`.
  - **Built-in table integrity:** `TIER_A_BUILTINS` all `tier=A`, all `external_effect=False`; names unique; each `event_type` is a valid `EventType`.
  - **rules_for Tier-A:** `rules_for(EventType.BILL_RECORDED)` contains `bill_to_task`; `rules_for(EventType.TASK_DONE)` contains `task_block_clear` + `task_done_mark_paid`.
  - **rules_for Tier-B via RecipeStore:** seed a `FakeRecipeStore` with an ENABLED recipe `task_class_key="reaction:gift_followup"` encoding `FACT_ADDED`, `action_class=TOUCHES_DATA` → `rules_for(EventType.FACT_ADDED)` includes a Tier-B rule with `reaction_ref="reaction:gift_followup"`, `external_effect=True`.
  - **Owner-disable:** `ReactionRuleStore(..., disabled=frozenset({"bill_to_task"}))` → `rules_for(EventType.BILL_RECORDED)` excludes `bill_to_task`.
  - **Graduation seam:** `note_tier_b_occurrence("reaction:gift_followup")` calls `FakePromoter.note_occurrence` with that key (assert via spy).

  — done when: `uv run pytest -q tests/test_reactions_rulestore.py` passes AND `uv run mypy --strict src tests/test_reactions_rulestore.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/reactions/rulestore.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/reactions/__init__.py` |
| Create | `/Users/artemis-build/artemis/tests/test_reactions_rulestore.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_reactions_rulestore.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_reactions_rulestore.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/reactions/rulestore.py`, `src/artemis/reactions/__init__.py`, `tests/test_reactions_rulestore.py` |
| `git commit` | `"feat: RXN-rulestore — ReactionRule + Tier-A built-ins + Tier-B over M7 RecipeStore"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings (RecipeStore recipes_dir resolution; off-hardware: tmp_path) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No network; RecipeStore embed is local (M7) and only the lookup runs here |

## Specialist Context

### Security

- **Tier-A gate is structural (Decision 2):** the `ReactionRule` validator rejects any Tier-A rule with an external effect — nothing with a judgment call or external effect can be auto-enabled day-one; it must graduate through Tier-B's owner-confirm loop. This is gentle-nudge + precision-first expressed as a runtime invariant, not per-spec discipline.
- **No parallel rule store:** Tier-B rules ARE M7 recipes — signed (M7-a1 `RecipeSigner`), graduated via `Promoter` (owner-gated for `TOUCHES_DATA`/`TAKES_ACTION` — a gated reaction recipe moves to `PENDING`, never auto-`ENABLED`). The owner-approve commit boundary is M7-b's `ReviewSurface.approve` — unchanged here.
- **Owner-declare (Tier-C):** force-disable (`disabled` set) and hand-written rules (owner-authored ENABLED recipes) ride the same machinery — no separate override store. [apex-security note: confirm a Tier-B reaction-recipe with `action_class=TAKES_ACTION` surfaces `external_effect=True` so the dispatcher routes it through GATE; confirm the Tier-A gate cannot be bypassed by a rule constructed outside the validator.]

### Performance

- `rules_for` is one in-memory filter of the Tier-A table + one `RecipeStore.list(status=ENABLED)` (a cached recipe listing). At single-owner scale (tens of rules) this is sub-millisecond. The Tier-B recipe listing is the same call the brain already makes for recipe retrieval — no new cost.

### Accessibility

(none — headless infra)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/reactions/rulestore.py` | Document the three-tier model, the Tier-A structural gate, the RecipeStore-reuse-for-Tier-B (no parallel store), the `external_effect`→GATE mapping, and the `reaction_ref` fq-id contract |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_reactions_rulestore.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_reactions_rulestore.py` → verify: Tier-A external-effect rule raises; built-in table integrity (10 rules, all internal Tier-A); `rules_for` resolves Tier-A by event_type; Tier-B reaction-recipes surface from the RecipeStore with `external_effect` from `action_class`; owner-disable excludes a rule; graduation seam delegates to `Promoter.note_occurrence`.
- [ ] `uv run python -c "from artemis.reactions import ReactionRule, ReactionTier, ReactionRuleStore, TIER_A_BUILTINS; print(len(TIER_A_BUILTINS))"` → verify: prints `10`.

## Progress
_(Coding mode writes here — do not edit manually)_

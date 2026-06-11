<!-- aligned 2026-06-11 to ADR-012/013 + contracts.md -->
# ADR-012 — Gated-action staging (pending-actions store, distinct from recipe Review)

- **Status:** Accepted
- **Date:** 2026-06-09
- **Deciders:** owner + planning
- **Relates:** ADR-011 §6 (this **refines** it — "gated `TAKES_ACTION`" is a pending-action *instance*, not a recipe); M7-a1/M7-b (the recipe model + recipe Review surface this is distinguished from); ADR-010 + CLIENT-b/CLIENT-e (the client Review screen the pending-actions surface extends); M1-a (`ToolRegistry`/`ToolSpec.callable_ref` — the dispatch seam `approve` re-invokes); the CAL-b/CAL-c specs (first consumer); overview.md §"Integration layer" (gated external-effect writes).

## Context

ADR-011 §6 decided that all external-effect writes are "gated `TAKES_ACTION` recipes routed through
the CLIENT Review screen." Drafting **CAL-b** (calendar write + the strict auto-vs-gated classifier)
exposed that this wording is underspecified, and the gap is load-bearing.

The owner-approval surface — **both** the backend (M7-b `ReviewSurface`: `pending_for_review()`,
`approve(name)`, `reject(name)` → `RecipeReview`) **and** the client (CLIENT-b `/app/review/*`
serialising `RecipeReview`) — is built entirely around the **recipe** abstraction. A `Recipe`
(M7-a1) is a **reusable, learned behaviour template**: a slug name, a description embedded for RAG
retrieval, an `inputs_schema` (parameterised), a `task_class_key`, and the lifecycle
`CANDIDATE → PENDING → ENABLED → RETIRED`. `approve(name)` flips status to **ENABLED** — semantics:
*"Artemis may now perform this kind of task automatically from here on."*

A gated calendar write is a categorically different object: a **one-off action instance with bound
arguments** — "send *this* invite to *bob@/alice@* for the 3pm Thursday, now." It is approved
**once**, **executes once**, and is never retrieved, reused, or auto-enabled. It needs no slug, no
description embedding, no RAG, no signing, no recurrence-promotion.

Conflating the two would overload `approve` (promote-a-template vs execute-an-instance) and pollute
the recipe abstraction with machinery that is meaningless for a one-time action. There is, today, **no
API to stage or approve a one-off runtime action** — so the entire CAL write path, and every future
external-effect spoke (Gmail-send, Tasks-export), is blocked.

## Decision

1. **Gated one-off actions are modelled as pending actions in a dedicated store — NOT as recipes.**
   A `PendingAction` is an instance, owner-private, awaiting a single approval that executes it once.

2. **`PendingAction` shape:** `id`, `module`, `tool` (fully-qualified `module.tool`), `args` (the
   bound payload to re-execute, validated against the tool's `args_schema`), `summary` (deterministic
   plain-language description for the Review screen — no LLM at review time, consistent with M7-b),
   `action_class = TAKES_ACTION`, `status` (`PENDING → APPROVED | REJECTED | EXPIRED`), `created_at`,
   `expires_at`, `result` (set after execution). Stored in an owner-private **SQLCipher**
   `PendingActionStore` under the M2 wall (the `SqlCipherTokenStore`/activity-log pattern).

3. **`ActionStagingService`** is the seam:
   - `stage(module, tool, args, summary, *, ttl) -> PendingAction` — a module's gated tool calls this
     **instead of executing**; the action is recorded `PENDING`.
   - `approve(id) -> PendingAction` — **re-dispatches the bound tool** via the M1-a `ToolRegistry`
     (`get_tool(fq_name).callable_ref(validated_args)`), executes **once**, records `result`, sets
     `APPROVED`. Execution is server-side, under the same gates as any live call (vault unlocked /
     owner-private scope); a still-locked vault refuses.
   - `reject(id)` → `REJECTED` (never executes). Expiry: a `PENDING` action past `expires_at` is
     `EXPIRED` and never executes (a stale invite must not fire days later).
   - Every approve/reject/expire is recorded (activity log / telemetry).

4. **The CLIENT Review screen surfaces BOTH, with distinct semantics:**
   - **Pending actions** — `approve = execute this exact action now`.
   - **Pending recipes** (existing M7-b) — `approve = allow this learned pattern to auto-fire in future`.
   Two sections/tabs; CLIENT-b gains `/app/actions/*` endpoints alongside `/app/review/*`; CLIENT-e
   gains a "Pending actions" surface. Both require the vault unlocked (ADR-010 §6 two-tier guard).

5. **The two surfaces are complementary halves of one trust loop, not competitors.** Pending actions =
   **permission now**; recipes = **automate later**. The bridge: when Artemis repeatedly stages the
   *same kind* of action, that **recurrence is exactly the signal that feeds the recipe-learning loop**
   (M7-a2 distill / M7-c curiosity) to propose a recipe that automates the pattern — which then goes
   through the *recipe* Review. One-off staging naturally graduates into a learned, owner-enabled recipe.

6. **This refines ADR-011 §6:** a "gated external-effect write" is a **pending-action instance** routed
   through the pending-actions surface; "auto-safe" self-only writes execute directly (and are recorded
   in the activity log). Reads/awareness still need no approval. The M7-b *recipe* Review is unchanged.

## Consequences

- **Unblocks the write path:** CAL-b's classifier calls `ActionStagingService.stage(...)` on the gated
  branch; CAL-c's `approve_proposal` (attendee case) routes the same way. The seam is reused by every
  future write-enabled spoke (Gmail-send, Tasks-export) — one staging primitive, not per-domain glue.
- **Clean separation of two gates:** "execute-once" (pending action) vs "auto-enable" (recipe) never
  blur; `approve` means one thing in each surface.
- **New build work:** a backend spec (`PendingActionStore` + `ActionStagingService` + the
  `ToolRegistry` re-dispatch) and a client spec (CLIENT-b `/app/actions/*` endpoints + CLIENT-e screen
  + CLIENT-c DTOs). The already-ready CLIENT-b/e specs are extended (not yet built — no Mini).
- **Execution safety:** approve executes server-side, re-validating `args` against the tool schema,
  under the live scope/unlock gates; TTL-expiry prevents stale external effects; the dispatch is the
  same `ToolRegistry` path the brain uses, so no second execution route exists to audit.
- **Security surface:** a `PendingAction.args` payload is owner-authored intent captured at stage time;
  it is owner-private at rest (SQLCipher) and never carries untrusted external instructions into
  execution (the gated tool built the args from validated inputs, not from raw external text).

## §3 — Clarifying note: `EXECUTING` state and at-most-once semantics (refined 2026-06-11)

_Added after Wave-0B pilot found a recovery hole in the original PENDING→APPROVED transition. See contracts.md Seam 3 for the normative contract; this note records the rationale._

`ActionStatus` gains an intermediate **`EXECUTING`** state. `approve()` proceeds as:

1. Validate `args` against the tool schema.
2. Conditional flip **`PENDING → EXECUTING`** (`UPDATE … WHERE id=? AND status='pending'`; rowcount 0 → already taken, raise — prevents double-dispatch on concurrent calls).
3. Dispatch the **`_execute` twin** (`{tool}_execute`) via the M1-a `ToolRegistry`. The `_execute` twin performs the raw external effect with no re-classification (the loop-break that prevents the gated entrypoint from re-staging the action).
4. On **success** → flip `EXECUTING → APPROVED`, store `result`.
5. On **transient failure** (`ScopeLockedError` / vault re-lock mid-dispatch) → revert `EXECUTING → PENDING` so the owner can re-approve.

A crash mid-dispatch leaves the action visibly `EXECUTING` (operator-recoverable), **never** silently `APPROVED`-but-unexecuted. This is required for safe operation on threadpool routes. The `_execute` twin is registered in the `ToolRegistry` for staging-dispatch only and is **not** exposed in `retrieve_tools()` — the model can never call the ungated write directly.

## Alternatives considered

- **Recipe-instance model (extend `Recipe` with bound args + make `approve` execute)** — *rejected*:
  overloads `approve` semantics, forces RAG/signing/promotion machinery onto one-off actions, and makes
  "what is a recipe" ambiguous. A category error; muddies the abstraction the whole M7 loop rests on.
- **ntfy action buttons (approve from the push notification)** — *rejected*: IG1 already chose the
  client Review screen over ntfy actions as the owner-approval surface; ntfy cannot safely carry a rich
  bound payload + a verifiable approval, and an action button is a weaker auth surface than the
  session+unlock-gated app.
- **Auto-execute with undo** — *rejected*: external-effect actions (sending an invite, RSVPing on the
  owner's behalf) are not safely reversible after the fact; the requirement is to gate *before* the
  external effect, not to compensate after.

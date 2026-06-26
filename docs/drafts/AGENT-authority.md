---
spec: AGENT-authority
status: draft
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: AGENT-authority — blast-radius classification + graduated allowlist (the executor's gate)

**Identity:** Implements ADR-031 C: classify each executor action's blast radius (in-sandbox vs
boundary-crossing) and authorize it — in-sandbox runs automatically; a boundary crossing stages via
GATE and graduates a *specific* command/script signature to automatic only after owner approval.
<!-- → why: docs/technical/adr/ADR-031-...md (C authority & sandbox, LOCKED; relates ADR-012 GATE) + docs/drafts/AGENT-engine-design.md (seam #4). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- The `Crossing` enum comes from `artemis.agentic.types` (AGENT-types) — Prerequisite; import it. → impact: Stop.
- `ActionStagingService.stage(module, tool, args, summary, *, ttl)` (`src/artemis/staging/service.py`) is the GATE seam — verify the exact signature (cite file:line) and call it for boundary crossings; do NOT re-implement staging. → impact: Stop.
- The graduated allowlist is owner-private SQLCipher (mirror `ReactionLedger`): a row per approved signature. A signature is a STABLE hash of the crossing's identity (e.g. `tool_ref` + a canonicalised command/target string + crossing kind) — NOT the raw args verbatim, so equivalent crossings match but a changed target re-asks. Define the canonicalisation concretely. → impact: Stop (a too-broad signature is a blank cheque; too-narrow re-asks constantly).
- Classification is fail-closed: unknown/unclassifiable → `BOUNDARY` (ask). In-sandbox = no network AND workspace-confined writes AND disposable env; anything else (network, writes outside the declared workspace root, any real-world effect) = boundary. → impact: Stop (fail-open would auto-run an unvetted crossing).
- This spec does NOT execute actions or run a sandbox — it only classifies + authorizes + records graduation. The actual sandboxed execution is AGENT-rung2; the workspace root is passed in. → impact: Caution (keeps authority file-disjoint from rung2).
- Owner approval is recorded out-of-band: `authorize` returns `needs_approval` + the staged `PendingAction`; a separate `graduate(signature)` is called when the owner approves (the executor/inbox wires the staging approval → graduate). Authority does not itself drive the inbox (keeps it dependency-light). → impact: Caution.

Simplicity check: considered folding authority into the spine — rejected: the blast-radius gate is the primary security control (ADR-031 C/F) and deserves its own tested unit + its own owner-private allowlist; a separate module keeps the spine loop legible and the gate independently reviewable.

## Prerequisites
- Specs that must be complete first: **AGENT-types** (`Crossing`). (GATE `ActionStagingService` is already built.)
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/agentic/authority.py` | create | `AuthorityGate`: `classify`, `authorize`, `graduate`; owner-private allowlist store. |
| `tests/test_agent_authority.py` | create | in-sandbox→auto, novel boundary→needs_approval+staged, post-graduation→auto, changed-signature→re-ask, fail-closed, persistence. |

### Signature (canonicalisation pinned in-spec — FLAG, was docstring-deferred)
`signature(tool_ref, args, crossing) -> str` = `sha256` (minimum) over the canonical tuple, with the EXACT fields per crossing kind defined HERE (not the docstring):
- **command/script:** the normalised **absolute argv tuple** (full args, not just the script name) + any behaviour-affecting env var names+values declared on the step.
- **file op:** the **resolved absolute target path** (`Path.resolve()`, symlinks followed).
- **network:** **host + port + protocol**.
- **always include `crossing.value`** so a command and a file op to the same path can never share a graduated approval.
Excluded (and why): transient run-ids/timestamps (non-semantic). A change to any included field → a new signature → re-ask.

### Hardened classification (BLOCK — fail-open path-escape fix)
`classify(step: PlanStep, *, workspace_root) -> Crossing`: returns `IN_SANDBOX` only if ALL hold — no declared network, AND every write target satisfies `resolved_target.is_relative_to(resolved_workspace_root)` where BOTH are `Path.resolve()`d (symlinks followed) — a string-prefix check is forbidden — AND the action is disposable. ANY resolution error (missing path / OS error / symlink loop) → `BOUNDARY`. Unknown/unclassifiable → `BOUNDARY`. (Fail-closed: a `../`/symlink/unicode escape must NOT be misclassified `IN_SANDBOX`.)

### Authorize (BLOCK — fail-closed on stage error; seam aligned to the backbone)
`authorize(step: PlanStep, *, workspace_root) -> AuthDecision` (takes the `PlanStep`, deriving `tool_ref`/`args` from it — aligns with the backbone seam #4 `authorize(step)`): `classify`; `IN_SANDBOX` → `AuthDecision(auto=True)`. `BOUNDARY`: if `is_graduated(signature)` → `AuthDecision(auto=True)`; else call `ActionStagingService.stage(...)` and return `AuthDecision(auto=False, pending=<PendingAction>, signature=<sig>)`. **If `stage()` raises (IPC/db/unavailable), `authorize` MUST propagate the error or return `AuthDecision(auto=False, error=<reason>)` — it must NEVER return `auto=True` as a result of an error.** `AuthDecision`'s caller-visible fields are limited to `auto: bool`, the opaque `PendingAction` ref, and a short summary string — NO resolved internal paths / exception detail (those would widen the prompt-injection surface via the planner).

### Graduation tied to confirmed approval (BLOCK — anti self-approval)
A bare `graduate(signature)` callable from the executor loop is a prompt-injection self-approval bypass. Instead: **graduation is gated on confirmed staging approval.** `graduate(action_id)` re-reads `ActionStagingService.store.get(action_id)`; it writes the allowlist row ONLY if that PendingAction's status is the confirmed-approved terminal state AND its recomputed signature matches. A signature that was never staged-and-approved cannot be enrolled. (Equivalent acceptable design: graduation fires as a passive listener inside the staging-approval path so the allowlist write never flows through the executor at all.) `is_graduated(signature) -> bool`.

### Allowlist store (FLAG — parameterised queries explicit)
Table `agent_allowlist(signature TEXT PRIMARY KEY, tool_ref TEXT, approved_at TEXT)` under OWNER_PRIVATE `.../agentic/`. ALL INSERT/SELECT use `?` placeholder parameterisation (`execute(sql, (param,))`) — never f-string/`%` interpolation (signature/tool_ref trace to LLM/tool-response content). SQLCipher is already a pinned+audited dep (ReactionLedger precedent) — no new dependency.

## Tasks
- [ ] Task 1: Implement `AuthorityGate` (`classify(step,*,workspace_root)`/`authorize(step,*,workspace_root)`/`graduate(action_id)`/`is_graduated` + in-spec signature canonicalisation + owner-private parameterised allowlist). — files: `src/artemis/agentic/authority.py` — done when: in-sandbox→auto (no stage); novel boundary→needs_approval + a staged PendingAction; a graduated signature→auto; a changed target→new signature→re-asks; unknown→boundary; **a `../`/symlink target escaping `workspace_root` (via `Path.resolve()`/`is_relative_to`) classifies BOUNDARY (fail-open fix)**; **`stage()` raising never yields `auto=True`**; **`graduate(action_id)` writes the allowlist ONLY when that action is staging-approved + its signature matches** (a never-approved signature cannot enrol); queries are parameterised; `uv run mypy` clean.
- [ ] Task 2: Tests. — files: `tests/test_agent_authority.py` — done when: all behaviours above pass under `uv run pytest -q`, INCLUDING: symlink/`..` escape → BOUNDARY; `stage()` raises → no auto-run (error surfaces); `graduate()` with a non-approved/forged action → refused; `AuthDecision` exposes no resolved internal path. Use a fake/real `ActionStagingService` to assert stage is called exactly for novel boundary crossings.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/authority.py`, `tests/test_agent_authority.py` |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check. |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The two files above, by name. |
| `git commit` | "feat: AGENT-authority blast-radius classify + graduated allowlist (ADR-031 C)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installs. |

## Specialist Context
### Security
`cross_model_review: true` — the primary blast-radius control. Reviewer confirms: (1) fail-closed classification (unknown → boundary → ask); (2) the signature is specific enough that a changed target/host re-asks (no blank cheque) yet stable enough to graduate genuinely-equal crossings; (3) boundary crossings ALWAYS stage via GATE before any auto-run; (4) graduation is per-specific-signature and owner-private; (5) authority never executes the action itself (no sandbox/exec here) — it only decides.

### Performance
(none — hash + PK lookup per action.)

### Accessibility
(none — no frontend change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/authority.py` | Docstrings: blast-radius rule, signature canonicalisation, graduated-allowlist contract, fail-closed. |
| Reconcile | docs/technical/architecture/data-model.md | Add the owner-private `agent_allowlist` table (conceptual). |

## Acceptance Criteria
- [ ] In-sandbox auto → verify: a no-network, workspace-confined action authorizes `auto=True` with no stage call.
- [ ] Novel boundary asks → verify: a network/out-of-workspace action returns `auto=False` + a staged PendingAction.
- [ ] Path-escape fail-closed (BLOCK) → verify: a `..`/symlink target resolving outside `workspace_root` classifies `BOUNDARY` (not auto), via `Path.resolve()` + `is_relative_to` (no string-prefix check).
- [ ] Stage-error fail-closed (BLOCK) → verify: when `ActionStagingService.stage()` raises, `authorize` never returns `auto=True` (error propagates / `auto=False, error=…`).
- [ ] No self-approval (BLOCK) → verify: `graduate(action_id)` enrols the allowlist ONLY when that action is staging-approved and its recomputed signature matches; a forged/unapproved action is refused.
- [ ] Graduation → verify: after a genuine approval+`graduate`, the same crossing authorizes `auto=True`; a changed target → different signature → re-asks.
- [ ] No internal-state leak → verify: `AuthDecision` exposes `auto`, the opaque PendingAction ref, and a short summary only — no resolved absolute paths / exception detail.
- [ ] Fail-closed classify → verify: an unclassifiable action classifies `BOUNDARY`.
- [ ] Owner-private durable → verify: the allowlist persists under OWNER_PRIVATE (parameterised queries) and survives reconstruct.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_

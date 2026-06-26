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

## Exact changes
- `signature(tool_ref, args, crossing) -> str` = stable hash over `tool_ref` + a canonicalised target (e.g. for a command: the normalised argv/script path + the network host if any; for a file op: the resolved path relative to workspace root) + `crossing.value`. Canonicalisation rules listed in the docstring.
- `classify(tool_ref, args, *, workspace_root) -> Crossing`: returns `IN_SANDBOX` only if the action declares no network AND every write target resolves under `workspace_root` AND it is marked disposable; else `BOUNDARY`. Unknown → `BOUNDARY`.
- `authorize(tool_ref, args, summary, *, workspace_root) -> AuthDecision`: `classify`; if `IN_SANDBOX` → `AuthDecision(auto=True)`. If `BOUNDARY`: if `signature` in the allowlist → `AuthDecision(auto=True)` (graduated); else `stage(...)` via `ActionStagingService` and return `AuthDecision(auto=False, pending=<PendingAction>, signature=<sig>)`.
- `graduate(signature)` = insert the signature into the owner-private allowlist (called after owner approval). `is_graduated(signature) -> bool`.
- Allowlist table `agent_allowlist(signature TEXT PRIMARY KEY, tool_ref TEXT, approved_at TEXT)` under OWNER_PRIVATE `.../agentic/`.

## Tasks
- [ ] Task 1: Implement `AuthorityGate` (`classify`/`authorize`/`graduate`/`is_graduated` + signature canonicalisation + owner-private allowlist). — files: `src/artemis/agentic/authority.py` — done when: in-sandbox→auto (no stage); novel boundary→needs_approval + a staged PendingAction; a graduated signature→auto; a changed target→new signature→re-asks; unknown→boundary; `uv run mypy` clean.
- [ ] Task 2: Tests. — files: `tests/test_agent_authority.py` — done when: all six behaviours above + allowlist persistence pass under `uv run pytest -q` (use a fake/real `ActionStagingService` to assert stage is called exactly for novel boundary crossings).

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
- [ ] Graduation → verify: after `graduate(signature)`, the same crossing authorizes `auto=True`; a changed target produces a different signature and re-asks.
- [ ] Fail-closed → verify: an unclassifiable action classifies `BOUNDARY`.
- [ ] Owner-private durable → verify: the allowlist persists under OWNER_PRIVATE and survives reconstruct.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_

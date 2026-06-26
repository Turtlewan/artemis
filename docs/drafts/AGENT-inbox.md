---
spec: AGENT-inbox
status: draft
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: AGENT-inbox — AskOwnerTool + agent-inbox (headless pause-to-ask seam)

**Identity:** The shared pause-to-ask primitive: the executor (and coding subsystem) persists an
owner question, delivers a notice via ntfy, and blocks until the owner answers via CLI/API or the
ask times out — headless, no client UI (ADR-031 D shared primitive + Refinement (a) headless-first).
<!-- → why: docs/technical/adr/ADR-031-...md (D AskOwnerTool/agent-inbox; Consequences "shared primitive") + docs/drafts/AGENT-engine-design.md (seam #3). -->

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- The `OwnerInbox` Protocol comes from `artemis.agentic.types` (AGENT-types) — Prerequisite; `AskOwnerTool` implements it. → impact: Stop.
- `NtfyDelivery` (`src/artemis/proactive/ntfy_delivery.py`) is the headless delivery channel — verify its actual deliver method + `DeliverySpec` (`proactive/hook_types.py`) shape and use it; do NOT re-implement ntfy. → impact: Stop (wrong delivery call breaks the notice).
- The pending-question store is owner-private SQLCipher (mirror `ReactionLedger` construction) — question text is owner-private; the ntfy notice carries only an id + a short prompt, NO sensitive content (mirror M6-c's no-payload-at-rest discipline). → impact: Stop (leaking question content into the notice breaks the privacy posture).
- Resolution is two-sided: `ask(...)` (executor side) blocks on an asyncio primitive keyed by question id; `resolve(question_id, answer)` (CLI/API side) persists the answer and releases the waiter. Within one process this is an in-memory `asyncio.Event`/`Future` map; cross-process resolution reads the persisted answer on the next poll. v1 = single-process (the executor and the resolve call share the process or poll the store). → impact: Caution (document the single-process assumption; cross-process is a later refinement).
- `timeout_s=0` means no timeout (block indefinitely / until resolved); `timeout_s>0` returns `None` on expiry → executor takes the partial-result/park path. → impact: Caution.

Simplicity check: considered building the visual answer surface now — rejected (ADR-031 Refinement (a)): the headless channel (persist + ntfy + `resolve`) is the functional seam; the visual panel is a deferred additive layer. v1 ships headless.

## Prerequisites
- Specs that must be complete first: **AGENT-types** (the `OwnerInbox` Protocol). (NtfyDelivery from M6-c is already built.)
- Environment setup required: none.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/agentic/inbox.py` | create | `AgentInbox` (owner-private question store + `resolve`) + `AskOwnerTool` (implements `OwnerInbox`, delivers via NtfyDelivery). |
| `tests/test_agent_inbox.py` | create | ask→deliver, resolve releases waiter, timeout→None, owner-private persistence, notice carries no question body. |

## Exact changes
- Table `agent_question(id TEXT PRIMARY KEY, prompt TEXT NOT NULL, options_json TEXT NOT NULL, answer TEXT, created_at TEXT NOT NULL, resolved_at TEXT)` under OWNER_PRIVATE `.../agentic/`.
- `AgentInbox.put(prompt, options) -> id` persists a pending question; `AgentInbox.resolve(id, answer)` sets `answer`+`resolved_at` and fires the in-memory waiter if present; `AgentInbox.pending()` lists open questions (for the CLI).
- `AskOwnerTool(inbox, ntfy)` implements `OwnerInbox.ask(question, *, options=(), timeout_s=0)`: `id = inbox.put(...)`; deliver an ntfy notice (title "Artemis needs a decision", body = a SHORT prompt + id, click/answer hint — no sensitive detail); `await` the waiter (or `asyncio.wait_for` with `timeout_s`); on resolve return the answer; on timeout return `None`.
- Notice delivery reuses `NtfyDelivery` with a `DeliverySpec` (priority normal, a tag); the answer hint points at the CLI/API resolve path.

## Tasks
- [ ] Task 1: Implement `AgentInbox` (owner-private store + put/resolve/pending + in-memory waiter map). — files: `src/artemis/agentic/inbox.py` — done when: `put` persists a pending row; `resolve` sets the answer and releases a waiting `ask`; `pending()` lists unresolved; owner-private path; `uv run mypy` clean.
- [ ] Task 2: Implement `AskOwnerTool.ask` (deliver via NtfyDelivery + block/timeout) implementing `OwnerInbox`. — files: `src/artemis/agentic/inbox.py` — done when: `ask` delivers exactly one notice (no question body in the payload), returns the answer once `resolve` is called, and returns `None` after `timeout_s` with no resolve.
- [ ] Task 3: Tests. — files: `tests/test_agent_inbox.py` — done when: ask→deliver-notice, resolve-releases-ask, timeout→None, persistence-survives-reconstruct, and notice-carries-no-question-body assertions pass under `uv run pytest -q`.

## Wave plan
Wave 1: [Task 1, Task 2] | Wave 2: [Task 3]

## Permissions
The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/agentic/inbox.py`, `tests/test_agent_inbox.py` |
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
| `git commit` | "feat: AGENT-inbox AskOwnerTool + agent-inbox headless pause-to-ask (ADR-031)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| ntfy (via NtfyDelivery) | Deliver the owner decision notice — uses the existing M6-c delivery path; no new egress surface. |

## Specialist Context
### Security
`cross_model_review: true` — owner-facing decision channel. Reviewer confirms: (1) question text is owner-private (SQLCipher under OWNER_PRIVATE); (2) the ntfy notice payload carries only id + a short prompt, never sensitive question detail (M6-c no-payload-at-rest parity); (3) an unanswered question fails safe — `ask` returns `None` on timeout and the executor parks (never auto-proceeds as if answered); (4) `resolve` only mutates an existing pending row.

### Performance
(none — single-question PK ops; the ask blocks on an asyncio waiter, no polling in-process.)

### Accessibility
(none — headless; the visual surface is the deferred agentic-UI panel.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/agentic/inbox.py` | Docstrings: headless pause-to-ask, owner-private question store, no-sensitive-content notice. |
| Reconcile | docs/technical/architecture/data-model.md | Add the owner-private `agent_question` table (conceptual). |

## Acceptance Criteria
- [ ] Ask delivers + blocks → verify: `ask("...")` persists a pending question and delivers exactly one ntfy notice; the notice body contains no question detail beyond a short prompt + id.
- [ ] Resolve releases → verify: `resolve(id, "yes")` makes the waiting `ask` return `"yes"`.
- [ ] Timeout fails safe → verify: `ask("...", timeout_s=1)` with no resolve returns `None` (no false answer).
- [ ] Owner-private durable → verify: questions persist under OWNER_PRIVATE and survive store reconstruct.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_

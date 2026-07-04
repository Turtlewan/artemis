---
spec: agent-loop-escalation-role
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: codex
coder_effort: high
---

# Spec: agent-loop-escalation-role — AL-3a `escalation_driver` registry role

**Identity:** Add a new ADR-049 registry role `escalation_driver` (default binding
`("codex","gpt-5.5")`) with a cross-family invariant (its binding must DIFFER from `loop_driver`),
mirroring the existing `judge` ≠ `loop_driver` machinery. This is the config seat the AL-4 route
resolves (`for_role("escalation_driver")`) to build the escalation `AgentLoop` that AL-3b's
`EscalatingLoop` orchestrates.
→ why: docs/technical/adr/ADR-047-agentic-assistant-loop.md (2026-07-04 Amendment: escalation = cross-family Sonnet → Codex gpt-5.5); ADR-049 (model-role registry).

<!-- Split from AL-3b (docs/drafts/agent-loop-escalation.md): the escalation ORCHESTRATION layer.
AL-3a and AL-3b are FILE-DISJOINT (this spec touches only roles.py + its test; AL-3b touches only
agent/*) and neither imports the other's new surface, so they build in parallel. LIVE resolution
`for_role("escalation_driver")` + wiring the resolved port into an escalation AgentLoop + EscalatingLoop
is AL-4. This spec only adds the ROLE + its invariant to the registry. -->

## Assumptions
<!-- Format: assumption → impact if wrong (Stop | Caution | Low) -->
- `src/artemis/model/roles.py` as-built matches what is on `v2-rebuild` (verified on disk): `ROLES` is a `tuple[str, ...]` NOT containing `escalation_driver`; `_DEFAULTS` is a `dict[str, RoleBinding]` keyed by every role; `bindings()` merges defaults + sanitized overrides then drops a `judge` override equal to `loop_driver` (falling back to default, then dropping `loop_driver` if still equal); `_validate` raises `RoleRegistryError("judge binding must differ from loop_driver binding")`; `DropReason` is a `Literal[...]` and `dropped_overrides()`/`_classify_drop` classify per-entry; `"codex"` is in `PROVIDERS` → impact: **Stop** (every edit anchors on these exact structures).
- `escalation_driver` is a TOOL-USING loop driver, so it is NOT placed in `_NO_TOOLS`, `_FORCE_TEMP_ZERO`, or `_ROUTER_ROLES` — its eligibility is therefore provider-agnostic like any other tooled role: codex qualifies as a normal `PROVIDERS` member, NOT because of any codex-specific capability check (eligibility is structural role-membership per the registry's no-tools ruling, never inferred from the bound provider's properties) → impact: **Stop** (adding it to any of those frozensets would wrongly forbid codex or force temp 0).
- The cross-family guarantee is enforced as `escalation_driver` ≠ `loop_driver` (exactly parallel to `judge` ≠ `loop_driver`); `escalation_driver` vs `judge` is intentionally UNCONSTRAINED (the amendment defines cross-family only against the primary driver) → impact: **Caution** (adding an unrequested `escalation_driver` ≠ `judge` invariant would over-constrain owner swaps).
- The default `("codex","gpt-5.5")` differs from the default `loop_driver` `("claude_code","haiku")`, so the shipped defaults never trip the new invariant → impact: **Low**.
- The load path stays FAIL-CLOSED: a persisted `escalation_driver` override equal to `loop_driver` is dropped back to default in `bindings()` (mirroring `judge`), and `dropped_overrides()` reports it with a new static `DropReason` so a tampered file can never surface a non-enum reason → impact: **Caution** (skipping the `bindings()` drop would let a hand-edited file violate the cross-family invariant at resolution time).

Simplicity check: considered NOT adding the role and letting AL-4 resolve `escalation_driver` ad hoc — rejected: `for_role` raises on an unknown role and the registry's fail-closed load + invariant validation are the whole point of ADR-049; the role must exist in `ROLES`/`_DEFAULTS` with its invariant before AL-4 can resolve it. Considered folding this into AL-3b — rejected: that makes AL-3b a 4-non-test-file spec (past the ≤3 rule) and needlessly serializes two file-disjoint builds. Considered a generic "driver differs from loop_driver" abstraction over judge + escalation_driver — rejected: two explicit parallel checks are clearer than a premature abstraction over exactly two roles (apex simplicity #2).

## Prerequisites
- Specs complete first: **none** — `src/artemis/model/roles.py` and `tests/test_model_roles.py` are already on `v2-rebuild` (ADR-049 as-built); this spec extends them and depends on no agent-loop spec.
- **Parallel, file-disjoint sibling:** `docs/drafts/agent-loop-escalation.md` (AL-3b) — shares no files with this spec; the two build concurrently. They are JOINED only at AL-4 (live `for_role("escalation_driver")` wiring).
- Environment setup: none beyond `uv sync`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/model/roles.py` | modify | Add `"escalation_driver"` to `ROLES`; add its `_DEFAULTS` entry `("codex","gpt-5.5")`; add the `escalation_driver` ≠ `loop_driver` check to `_validate` + the fail-closed drop in `bindings()`; add an `"escalation_conflict"` `DropReason` + its classification in `dropped_overrides()`. |
| `tests/test_model_roles.py` | modify | Add default-binding, eligibility/constraints, invariant, and fail-closed drop tests for `escalation_driver`. |
| `tests/test_model_routes.py` | modify | **(Amended post-dispatch, build fork 2026-07-04.)** Update the hard-coded role count (9 → 10) and change the route test's `loop_driver` value `("codex","gpt-5.5")` (now equals `escalation_driver`'s default → correctly rejected) to `("anthropic_api","claude-sonnet")`. Two surgical value fixes; no behavioral change to the routes under test. |

## Tasks
- [ ] Task 1: Add the role + its invariant to the registry — files: `src/artemis/model/roles.py` — done when: `uv run mypy` clean; `escalation_driver` is in `ROLES` and `_DEFAULTS`; `put("escalation_driver", <== loop_driver>)` raises `RoleRegistryError`; a hand-edited file with `escalation_driver == loop_driver` resolves back to the default via `bindings()`; `dropped_overrides()` reports it with reason `"escalation_conflict"`.
- [ ] Task 2: Add the registry tests — files: `tests/test_model_roles.py` — done when: `uv run pytest -q tests/test_model_roles.py` passes, including the new `escalation_driver` cases.
- [ ] Task 3 (amended in, build fork 2026-07-04): Fix the two now-stale values in the routes test — the hard-coded role count (9 → 10) and the `loop_driver` binding equal to `escalation_driver`'s default (→ `("anthropic_api","claude-sonnet")`) — files: `tests/test_model_routes.py` — done when: `uv run pytest -q tests/test_model_routes.py` passes with no other edits to that file.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]
<!-- Task 2's tests import the extended roles.py surface. -->

## Exact changes

### Task 1 — `src/artemis/model/roles.py` (modify)

**Edit A — `ROLES`.** Add `"escalation_driver"` to the `ROLES` tuple (place it next to `loop_driver`
for readability):

```python
ROLES: tuple[str, ...] = (
    "loop_driver",
    "escalation_driver",
    "selector",
    "extractor",
    "phraser",
    "judge",
    "reader",
    "synth",
    "memory",
    "forge_author",
)
```

**Edit B — `_DEFAULTS`.** Add the default binding (cross-family from `loop_driver`'s default):

```python
    "escalation_driver": RoleBinding("codex", "gpt-5.5"),
```

<!-- Do NOT add escalation_driver to _FORCE_TEMP_ZERO, _NO_TOOLS, or _ROUTER_ROLES — it is a
tool-using driver bound to a non-router, non-no-tools provider. -->

**Edit C — `DropReason`.** Add the new static enum member:

```python
DropReason = Literal[
    "malformed_entry",
    "unknown_provider",
    "no_tools_ineligible",
    "router_restricted",
    "judge_conflict",
    "escalation_conflict",
]
```

**Edit D — `bindings()` fail-closed drop.** After the existing `judge` drop block (which returns
`merged` at the end), add a parallel block for `escalation_driver` BEFORE `return merged`:

```python
        if merged["escalation_driver"] == merged["loop_driver"]:
            _log.warning("model_roles: dropping escalation_driver override (equals loop_driver)")
            merged["escalation_driver"] = _DEFAULTS["escalation_driver"]
            if merged["escalation_driver"] == merged["loop_driver"]:
                _log.warning(
                    "model_roles: dropping loop_driver override (escalation_driver collision)"
                )
                merged["loop_driver"] = _DEFAULTS["loop_driver"]
        return merged
```

**Edit E — `_validate` invariant.** After the existing `judge`/`loop_driver` check, add:

```python
        if proposed["escalation_driver"] == proposed["loop_driver"]:
            raise RoleRegistryError("escalation_driver binding must differ from loop_driver binding")
```

**Edit F — `dropped_overrides()` classification.** After the existing `judge_conflict` append,
add the parallel `escalation_driver` classification (using the same `sanitized`/`merged` locals
already computed in that method):

```python
        if (
            "escalation_driver" in sanitized
            and merged["escalation_driver"] == merged["loop_driver"]
        ):
            dropped.append(
                DroppedOverride(role="escalation_driver", reason="escalation_conflict")
            )
        return dropped
```

<!-- NOTE for the coder: `_classify_drop` needs NO change — the escalation_driver ≠ loop_driver
conflict is a cross-role relationship classified in dropped_overrides() (exactly like judge_conflict),
not a per-entry validity check. `_validate_entry`, `eligible_providers`, and `constraints_for` all
work for escalation_driver unchanged (it is a plain tool-using role). -->

### Task 2 — `tests/test_model_roles.py` (modify)

Add these tests (reuse the file's existing `_registry` / `_RecordingPort` / `_FakeProvider` helpers):

```python
def test_escalation_driver_default_and_constraints(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")
    assert reg.get("escalation_driver") == RoleBinding("codex", "gpt-5.5")
    assert reg.constraints("escalation_driver") == RoleConstraints(no_tools=False, temperature=None)
    assert "codex" in reg.eligible_providers("escalation_driver")


def test_invariant_escalation_driver_differs_from_loop_driver(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")
    # Move loop_driver to a binding that does NOT equal escalation_driver's default
    # ("codex","gpt-5.5") — otherwise this first put itself trips the new invariant.
    reg.put("loop_driver", RoleBinding("anthropic_api", "claude-sonnet"))
    with pytest.raises(RoleRegistryError):
        reg.put("escalation_driver", RoleBinding("anthropic_api", "claude-sonnet"))
    # A different binding is accepted.
    reg.put("escalation_driver", RoleBinding("claude_code", "opus"))
    assert reg.get("escalation_driver") == RoleBinding("claude_code", "opus")


def test_fail_closed_hand_edited_escalation_equals_loop_driver(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(
        json.dumps(
            {
                "loop_driver": {"provider": "codex", "model": "gpt-5.5"},
                "escalation_driver": {"provider": "codex", "model": "gpt-5.5"},
            }
        ),
        encoding="utf-8",
    )
    reg = _registry(path)
    assert reg.bindings()["escalation_driver"] == _DEFAULTS["escalation_driver"]
    assert any(
        d.role == "escalation_driver" and d.reason == "escalation_conflict"
        for d in reg.dropped_overrides()
    )
```

<!-- If _DEFAULTS is not already imported in the test module, it is (see the file's existing imports
from artemis.model.roles). Do not otherwise edit existing tests. -->

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | `src/artemis/model/roles.py`, `tests/test_model_roles.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv sync` | Resolve dependencies (no new packages added). |
| `uv run ruff format .` / `uv run ruff format --check .` | Format + verify. |
| `uv run ruff check .` | Lint. |
| `uv run mypy` | Full-project type check. |
| `uv run pytest -q tests/test_model_roles.py` | Run the registry suite. |
| `uv run pytest -q` | Full suite (zero regression). |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/model/roles.py tests/test_model_roles.py` |
| `git commit` | `feat(model): add escalation_driver role (AL-3a) — cross-family default + loop_driver invariant` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | No env access — registry is file-backed + hermetic in tests (`tmp_path`). |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No network. No package installs. |

## Specialist Context
### Security
- **Fail-closed preserved.** The new role rides the SAME fail-closed load path as `judge`: a persisted `escalation_driver == loop_driver` is dropped back to the default at resolution time (`bindings()`), and `dropped_overrides()` reports it only via the static `DropReason` enum (`"escalation_conflict"`) — tampered file content can never surface a free-form string through the panel API (the `DroppedOverride` type invariant is unchanged).
- **No posture drop.** `escalation_driver` is a tool-using driver by design; it is deliberately NOT admitted to `_NO_TOOLS`/`_FORCE_TEMP_ZERO`. The cross-family invariant is a diversity guarantee (a second model family + subscription), not a safety-posture constraint — safety on the escalated pass rides its own loop's judge (AL-3b/AL-4), not this role.
- **Review note (accepted): `dropped_overrides()` cross-role reporting asymmetry is inherited, not introduced.** If a hand-edited `loop_driver` override collides with `escalation_driver`'s default, `bindings()` still drops fail-closed but the drop isn't surfaced to the panel — exactly mirroring the pre-existing `judge_conflict` behavior. Deliberately mirrored (not fixed asymmetrically here); a follow-up tightening both roles together is filed in status.md's small-fix list.

### Performance
(none — registry edits are config-only; resolution cost is unchanged.)

### Accessibility
(none — no frontend surface; the role-panel rendering of the new role is AL-4/later.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/model/roles.py` | The module docstring's role-posture summary already covers "judge binding must differ from loop_driver"; extend that sentence to note escalation_driver likewise differs from loop_driver. |
| API | (none) | No HTTP surface added here. |
| Changelog | CHANGELOG.md | Add entry under Unreleased: "Add `escalation_driver` model-role (default codex/gpt-5.5) with a cross-family loop_driver invariant (AL-3a)." |
| ADR | (none) | ADR-047 Amendment + ADR-049 already cover the decision; no new ADR. |

## Acceptance Criteria
- [ ] Role exists with cross-family default → verify: `uv run python -c "from artemis.model.roles import ModelRoleRegistry, ROLES; assert 'escalation_driver' in ROLES"` exits 0; `test_escalation_driver_default_and_constraints` green.
- [ ] Cross-family invariant enforced → verify: `test_invariant_escalation_driver_differs_from_loop_driver` green (`put` collision raises).
- [ ] Fail-closed on hand-edit → verify: `test_fail_closed_hand_edited_escalation_equals_loop_driver` green (drops to default + reports `"escalation_conflict"`).
- [ ] Codex eligible, no forced posture → verify: `eligible_providers("escalation_driver")` contains `"codex"`; `constraints("escalation_driver") == RoleConstraints(no_tools=False, temperature=None)`.
- [ ] Type + lint clean → verify: `uv run mypy` clean; `uv run ruff check .` + `uv run ruff format --check .` clean.
- [ ] Zero regression → verify: `uv run pytest -q` full suite stays green (existing `judge`/`loop_driver` invariant tests unchanged).
- [ ] Surgical → verify: `git diff --stat` shows only `src/artemis/model/roles.py` and `tests/test_model_roles.py`.

## Commands to run
```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q tests/test_model_roles.py
uv run pytest -q
```

## Progress
_(Coding mode writes here — do not edit manually)_

---
spec: judge-role-no-tools
status: ready
token_profile: lean
autonomy_level: L3
coder_tier: codex
coder_effort: medium
---

# Spec: judge-role-no-tools — AL-4b registry-level no-tools enforcement for the `judge` role

**Identity:** Admit `"judge"` to the ADR-049 registry's structural no-tools set (`_NO_TOOLS`) so
`for_role("judge")` / `put("judge", …)` / the fail-closed load path enforce provider-level
tool-stripping at the registry, closing AL-2's tracked gap that the judge's no-tools property was
call-site-only.
→ why: docs/technical/adr/ADR-047-agentic-assistant-loop.md (2026-07-04 Amendment: "Verify-on-stop judge = independent no-tools Haiku … judge reads untrusted content, so tool-stripped"); ADR-049 #3 (safety posture rides the ROLE); deferral home: docs/changes/done/agent-loop-stop-discipline.md § Security ("the no-tools invariant is call-site-only in AL-2 … Registry-level enforcement … queued for AL-4"), also status.md AL-4 wiring note (a).

<!-- This is a purely additive, mechanical registry-hardening spec: one token added to a frozenset +
one docstring clause + mirror tests. It rides ALL the existing no-tools machinery already proven for
`reader` (eligible_providers filter, _validate_entry gate, _classify_drop → "no_tools_ineligible",
constraints_for). No new DropReason, no new invariant, no new provider set. -->

## Assumptions
<!-- Format: assumption → impact if wrong (Stop | Caution | Low) -->
- `src/artemis/model/roles.py` as-built matches `v2-rebuild` (verified on disk): `_NO_TOOLS = frozenset({"reader"})` (line 47); `_NO_TOOLS_PROVIDERS = frozenset({"claude_code", "ollama"})` (line 48); `constraints_for` sets `no_tools = role in _NO_TOOLS`; `eligible_providers` skips any non-`_NO_TOOLS_PROVIDERS` provider when `constraints_for(role).no_tools`; `_validate_entry` raises `RoleRegistryError` on a no-tools role bound to a provider outside `_NO_TOOLS_PROVIDERS`; `_classify_drop` returns `"no_tools_ineligible"` for that same case; `"judge"` is already in `ROLES`, `_FORCE_TEMP_ZERO`, and has `_DEFAULTS["judge"] = RoleBinding("claude_code", "sonnet")` → impact: **Stop** (every edit anchors on these exact structures).
- **`claude_code` IS in `_NO_TOOLS_PROVIDERS`** (verified line 48), so BOTH the shipped default `judge = ("claude_code","sonnet")` AND the owner go-live override `judge = ("claude_code","haiku")` (status.md AL-4 roster) remain no-tools-eligible after adding `judge` to `_NO_TOOLS`. No default trips the newly-applied gate → impact: **Stop** (if `claude_code` were absent, the shipped default would fail its own `_validate_entry` and every `for_role("judge")` path would break).
- No existing test or route binds `judge` to a non-no-tools provider and expects **success** — verified by repo grep. The only two such puts (`tests/test_model_roles.py:151` and `tests/test_model_routes.py:70`, both `judge → anthropic_api`/`claude_code haiku`) already expect a RAISE/422; they still raise after this change (the failure reason shifts from `judge_conflict` to `no_tools_ineligible`, but `pytest.raises(RoleRegistryError)` / `status_code == 422` are reason-agnostic) → impact: **Caution** (if any such test asserted the *reason string*, it would need updating — none do).
- `judge` is ALSO in `_FORCE_TEMP_ZERO`, so `constraints_for("judge")` is `RoleConstraints(no_tools=True, temperature=0.0)` after this change (NOT `temperature=None` like `reader`) — the new constraint test must assert `temperature=0.0` → impact: **Caution** (mirroring the reader test's `temperature=None` verbatim would fail).
- A persisted `judge` override on a non-no-tools provider (e.g. hand-edited `codex`) drops fail-closed to `_DEFAULTS["judge"]` via `_sanitized_overrides` and is reported by `dropped_overrides()` with the EXISTING static reason `"no_tools_ineligible"` — no new `DropReason` member is required (unlike AL-3a's `escalation_conflict`, this is a per-entry validity drop already classified) → impact: **Stop** (adding a new DropReason would be needless surface; relying on the existing one is the whole point of riding reader's machinery).
- `tests/test_model_routes.py` needs NO change: `test_get_models_...` asserts `reader` eligibility/constraints but makes NO assertion about `judge`'s `eligible_providers`; `test_put_rejects_...` puts `judge → ("claude_code","haiku")` expecting 422 (still 422, now via judge≠loop_driver which fires first since claude_code IS no-tools-eligible) and asserts `judge` stays `claude_code`/`sonnet` (still true) → impact: **Caution** (kept OUT of Files to Change; if a hidden judge-eligibility assertion existed it would need inclusion — grep confirms none).

Simplicity check: considered adding a NEW `DropReason` for the judge-specific case — rejected: the judge-on-non-no-tools-provider drop is structurally identical to reader's and is already classified `"no_tools_ineligible"`; reusing it is simpler and correct. Considered a generic "no-tools roles" abstraction — rejected: `_NO_TOOLS` IS that abstraction already (a frozenset); this spec just adds one member. Considered also asserting judge eligibility in `test_model_routes.py` — rejected: gold-plating a 3rd file for a route behavior no acceptance criterion requires; the registry-level test in `test_model_roles.py` fully covers the eligibility change.

## Prerequisites
- Specs complete first: **none** — `src/artemis/model/roles.py` and `tests/test_model_roles.py` are on `v2-rebuild` (ADR-049 as-built; AL-2's `reader` no-tools machinery already shipped). This spec extends them.
- Environment setup: none beyond `uv sync`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/model/roles.py` | modify | Add `"judge"` to the `_NO_TOOLS` frozenset; extend the module-docstring no-tools clause to name `judge`. No other edit (all no-tools machinery already handles a `_NO_TOOLS` member generically). |
| `tests/test_model_roles.py` | modify | Add three `judge` no-tools tests (constraint+eligibility, put-eligibility invariant, fail-closed persisted-drop). Do not edit existing tests. |

## Tasks
- [ ] Task 1: Add `judge` to the structural no-tools set + docstring — files: `src/artemis/model/roles.py` — done when: `uv run mypy` clean; `constraints_for("judge").no_tools is True`; `eligible_providers("judge")` excludes `codex`/`anthropic_api` and contains `claude_code`; `put("judge", RoleBinding("codex","gpt-5.5"))` raises `RoleRegistryError`; a hand-edited persisted `judge` override on `codex` resolves back to `_DEFAULTS["judge"]` and `dropped_overrides()` reports reason `"no_tools_ineligible"`; the shipped default `("claude_code","sonnet")` still validates.
- [ ] Task 2: Add the registry tests — files: `tests/test_model_roles.py` — done when: `uv run pytest -q tests/test_model_roles.py` passes, including the three new `judge` cases and all pre-existing cases unchanged.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]
<!-- Task 2's new tests exercise the behavior Task 1 adds; run after Task 1. -->

## Exact changes

### Task 1 — `src/artemis/model/roles.py` (modify)

**Edit A — `_NO_TOOLS`.** Add `"judge"` to the frozenset:

```python
_NO_TOOLS: frozenset[str] = frozenset({"reader", "judge"})
```

**Edit B — module docstring.** In the opening docstring (lines 3–4), the no-tools clause currently
reads:

```
ADR-049. Roles in code, models in config. Safety posture rides the role: reader is no-tools
and bindable only to providers with a verified no-tools invocation path; extractor and judge force
```

Change `reader is no-tools` → `reader and judge are no-tools`, so it reads:

```
ADR-049. Roles in code, models in config. Safety posture rides the role: reader and judge are no-tools
and bindable only to providers with a verified no-tools invocation path; extractor and judge force
```

<!-- NOTE for the coder: make NO other change to roles.py. Do NOT add a new DropReason (the
judge-on-non-no-tools-provider drop is already classified "no_tools_ineligible" by _classify_drop);
do NOT touch _NO_TOOLS_PROVIDERS, _validate_entry, eligible_providers, constraints_for,
dropped_overrides, or _DEFAULTS — every one already handles a _NO_TOOLS member generically, proven by
`reader`. `judge` stays in _FORCE_TEMP_ZERO (temperature 0 is unchanged and independent of no-tools). -->

### Task 2 — `tests/test_model_roles.py` (modify)

Add these three tests (reuse the file's existing `_registry` helper and the already-imported
`RoleBinding`, `RoleConstraints`, `RoleRegistryError`, `_DEFAULTS`). Do not edit existing tests.

```python
def test_judge_no_tools_constraint_and_eligibility(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")

    # judge is no-tools AND temperature-0 (it is in both _NO_TOOLS and _FORCE_TEMP_ZERO).
    assert reg.constraints("judge") == RoleConstraints(no_tools=True, temperature=0.0)

    elig = reg.eligible_providers("judge")
    assert "claude_code" in elig  # the shipped default + go-live override provider stays eligible
    assert "codex" not in elig
    assert "anthropic_api" not in elig
    assert set(elig) <= {"claude_code", "ollama"}


def test_invariant_judge_requires_no_tools_provider(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")

    # A non-no-tools provider is rejected structurally (no verified tool-strip path).
    with pytest.raises(RoleRegistryError):
        reg.put("judge", RoleBinding("codex", "gpt-5.5"))

    # A no-tools provider that also differs from loop_driver's default is accepted.
    reg.put("judge", RoleBinding("ollama", "qwen3:4b"))
    assert reg.get("judge") == RoleBinding("ollama", "qwen3:4b")


def test_fail_closed_hand_edited_judge_non_no_tools_provider(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(
        json.dumps({"judge": {"provider": "codex", "model": "gpt-5.5"}}),
        encoding="utf-8",
    )
    reg = _registry(path)

    assert reg.bindings()["judge"] == _DEFAULTS["judge"]
    assert any(
        d.role == "judge" and d.reason == "no_tools_ineligible"
        for d in reg.dropped_overrides()
    )
```

<!-- `json`, `pytest`, `RoleBinding`, `RoleConstraints`, `RoleRegistryError`, `_DEFAULTS`, and `Path`
are all ALREADY imported in tests/test_model_roles.py (see its existing header) — add no new imports.
The pre-existing test_invariant_judge_differs_from_loop_driver stays UNCHANGED and green: its
`put("judge", ("anthropic_api","claude-sonnet"))` still raises (now via the no-tools gate instead of
the judge≠loop_driver gate); the assertion is `pytest.raises(RoleRegistryError)`, reason-agnostic. -->

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
| `git commit` | `feat(model): judge role no-tools eligibility (AL-4b) — registry-level tool-strip enforcement` |

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
- **Structural, not conventional.** This closes AL-2's accepted FLAG: the judge's no-tools posture was call-site-only ("this loop never hands the judge a `ToolRegistry`"). After this change the registry itself refuses any `judge` binding to a provider without a verified no-tools invocation path, so `for_role("judge")` cannot resolve a tool-capable provider even if a future call site forgets the convention. The judge reads UNTRUSTED content (evidence + candidate answer per ADR-047), so its tool-strip must be enforced where the binding is validated, not only where it is consumed.
- **Fail-closed preserved, no new surface.** A tampered/hand-edited persisted `judge` override on a non-no-tools provider drops to the default at load and is reported ONLY via the existing static `DropReason` enum (`"no_tools_ineligible"`) — no free-form string can reach the panel API (the `DroppedOverride` type invariant is unchanged; no new enum member added).
- **No posture regression for the roster.** `claude_code` is in `_NO_TOOLS_PROVIDERS`, so the shipped default (`sonnet`) and the go-live override (`haiku`) both remain valid — the hardening removes only the never-used tool-capable-provider bindings for judge.
- **Review FLAG (accepted, layers cited): tool-stripping limits blast radius only — it does not prevent verdict manipulation.** A successful injection in the judge's untrusted input can still steer the PASS/FAIL text. The layers against THAT live elsewhere and are already tracked: AL-2's structural design (independent evaluator, borderline→reject, delimited+capped reason re-entry) + AL-4's pre-go-live adversarial-injection and judge-calibration evals (AL-2/AL-3 scope fences + status.md). AL-4b's contribution is exactly one layer: an injected judge can never ACT.
- **Review note (accepted, variant analysis): untrusted-content consumer roles checked role-by-role.** `reader` (raw web) + `judge` (evidence/answers) are the two direct consumers — both now structurally no-tools. `extractor`/`phraser`/`memory` consume owner-authored or quarantine-sanitized local text. `synth` consumes untrusted-DERIVED reader output but is called tool-less at its only call site (`reachout/web_tool.py`) — same call-site-only posture the judge had before this spec; queue `synth` for the same admission if its call sites multiply (noted in status.md small-fix list).

### Performance
(none — a one-member frozenset addition; resolution cost unchanged.)

### Accessibility
(none — no frontend surface. The models panel already renders each role's `eligible_providers` dynamically from the registry, so judge's narrowed list flows through with no client change.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/model/roles.py` | Docstring no-tools clause updated (Edit B) to name `judge`. |
| API | (none) | No HTTP surface added; `/app/models` already serializes eligibility dynamically. |
| Changelog | CHANGELOG.md | Add entry under Unreleased: "Enforce `judge` model-role no-tools eligibility at the registry (AL-4b): judge bindable only to no-tools providers, closing AL-2's call-site-only gap." |
| ADR | (none) | ADR-047 Amendment + ADR-049 #3 already cover the decision; no new ADR. |

## Acceptance Criteria
- [ ] Judge is structurally no-tools → verify: `uv run python -c "from artemis.model.roles import constraints_for; assert constraints_for('judge').no_tools is True"` exits 0; `test_judge_no_tools_constraint_and_eligibility` green.
- [ ] Non-no-tools provider rejected, no-tools accepted → verify: `test_invariant_judge_requires_no_tools_provider` green (`put(judge, codex)` raises; `put(judge, ollama)` accepted).
- [ ] Fail-closed on hand-edit → verify: `test_fail_closed_hand_edited_judge_non_no_tools_provider` green (drops to default + reports `"no_tools_ineligible"`).
- [ ] Roster compatibility intact → verify: `uv run python -c "from artemis.model.roles import ModelRoleRegistry, RoleBinding; import tempfile,pathlib; r=ModelRoleRegistry(pathlib.Path(tempfile.mkdtemp())/'r.json', router_factory=lambda: (_ for _ in ()).throw(AssertionError)); r._validate_entry('judge', RoleBinding('claude_code','sonnet')); r._validate_entry('judge', RoleBinding('claude_code','haiku'))"` exits 0 (both default and go-live-override bindings validate).
- [ ] Zero regression → verify: `uv run pytest -q` full suite stays green — existing `judge`/`reader`/routes tests unchanged, including `test_invariant_judge_differs_from_loop_driver` (still raises) and `test_model_routes.py` (unchanged).
- [ ] Type + lint clean → verify: `uv run mypy` clean; `uv run ruff check .` + `uv run ruff format --check .` clean.
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

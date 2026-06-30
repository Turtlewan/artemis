---
slice: capability-build
status: ready
coder_effort: medium
---

# CB-1 — Gated, network-guarded forge

**Identity:** First spec of the capability-build slice. Splits the forge's one-shot `build()` into three separately-callable stages — `propose` (author + safety-classify, no execution) → `build_proposed` (sandbox-verify a proposal, self-correcting, no promote) → `promote` — so a later HTTP driver can pause for owner approval at a plan gate and a result gate. Adds a static import-scan that **blocks** any authored capability that imports network/process modules from running in the no-isolation `SubprocessSandbox`. Backend only; no HTTP, no client, no data-root change (those are CB-2…CB-4). Design note: `docs/v2/capability-build-ux.md`.

**Safety contract (load-bearing — defines what gets built):** the import-scan is an **AST import-level check only**. It is NOT a security boundary — a determined author can evade it (`getattr`, `eval`, `os.system`, dynamic import). Its job is to (a) keep honest capabilities honest and (b) enforce the product rule *"network/secret capabilities wait for the WSL2 isolated sandbox"* (a later thread). The real containment is WSL2; this guard is a fast pre-filter, and the spec must not describe it as isolation.

## Files to change

1. `src/artemis/types.py` — **modify**: add `BuildProposal` and `BuildAttempt` models.
2. `src/artemis/capabilities/forge.py` — **modify**: add `scan_for_unsafe_imports` + `_safety_reason`; add `propose` / `build_proposed` / `promote`; swap `build()`'s tests-None guard for `_safety_reason`.
3. `tests/test_forge.py` — **modify**: add gated-stage tests + the network-guard tests.

One module's behavior (the forge) + its types + its test → a single cohesive change.

## Exact changes

### 1. `src/artemis/types.py`

Add after the existing `StagedSkill` model:

```python
class BuildProposal(BaseModel):
    """A proposed capability awaiting the plan gate: the authored draft + a safety verdict.

    `blocked` is True when the capability cannot proceed to build in the current
    (no-isolation) sandbox — either it has no test, or it imports a network/process
    module (see `scan_for_unsafe_imports`). The UI offers `Build it` only when not blocked.
    """

    goal: str
    draft: SkillDraft
    blocked: bool
    block_reason: str | None = None


class BuildAttempt(BaseModel):
    """The outcome of running a proposal through the sandbox. `staged_id` is None when the
    proposal was blocked (never staged). `promote` is gated on `passed and staged_id`."""

    staged_id: str | None
    passed: bool
    output: str
```

### 2. `src/artemis/capabilities/forge.py`

**a. Imports** — add at the top (after `from __future__ import annotations`):

```python
import ast
```

and extend the `artemis.types` import to include the new models:

```python
from artemis.types import (
    BuildAttempt,
    BuildProposal,
    Message,
    Skill,
    SkillDraft,
    StagedSkill,
)
```

**b. The import-scan** — module-level, after `SKILL_DRAFT_SCHEMA`:

```python
# Top-level module names whose import means the capability can reach the network or spawn
# processes — unsafe to run in the no-isolation SubprocessSandbox. AST import-level scan only;
# NOT a security boundary (evadable via getattr/eval/os.system). The WSL2 isolated sandbox is
# the real boundary; this guard enforces "network capabilities wait for WSL2".
UNSAFE_IMPORTS: frozenset[str] = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "imaplib",
        "smtplib",
        "poplib",
        "telnetlib",
        "nntplib",
        "asyncore",
        "asynchat",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "websocket",
        "websockets",
        "subprocess",
        "multiprocessing",
        "ctypes",
        "pty",
    }
)


def scan_for_unsafe_imports(source: str | None) -> str | None:
    """Return a human-readable reason if `source` imports a network/process module, else None.

    AST import-level scan only (see UNSAFE_IMPORTS). Unparseable source is treated as unsafe
    (we will not run code we cannot inspect). `None` source (no tool module) is not unsafe here.
    """
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "authored code could not be parsed for a safety scan"
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in UNSAFE_IMPORTS:
                    found.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                top = node.module.split(".")[0]
                if top in UNSAFE_IMPORTS:
                    found.add(top)
    if found:
        names = ", ".join(sorted(found))
        return (
            f"capability imports network/process modules ({names}); "
            "blocked until the isolated WSL2 sandbox exists"
        )
    return None
```

**c. `_safety_reason`** — instance method on `CapabilityForge` (combines the two hard stops):

```python
    def _safety_reason(self, draft: SkillDraft) -> str | None:
        """Why this draft cannot be built in the current sandbox, or None if it can."""
        if not draft.tests:
            return "capability has no test — cannot verify"
        return scan_for_unsafe_imports(draft.tool_script)
```

**d. The three gated stages** — add as methods on `CapabilityForge`:

```python
    async def propose(self, goal: str) -> BuildProposal:
        """Author a draft and classify it for the plan gate. No staging, no sandbox, no promote."""
        draft = await self._author(goal)
        reason = self._safety_reason(draft)
        return BuildProposal(
            goal=goal,
            draft=draft,
            blocked=reason is not None,
            block_reason=reason,
        )

    async def build_proposed(
        self, proposal: BuildProposal, *, max_attempts: int = 3
    ) -> BuildAttempt:
        """Sandbox-verify an approved proposal, self-correcting up to ``max_attempts``.

        Attempt 1 uses the proposal's already-authored draft; on failure the test output is fed
        back to the author for a corrected draft (re-scanned each time). Never promotes.
        """
        if proposal.blocked:
            return BuildAttempt(
                staged_id=None,
                passed=False,
                output=proposal.block_reason or "blocked",
            )
        draft = proposal.draft
        failure: str | None = None
        staged: StagedSkill | None = None
        result: VerifyResult | None = None
        for attempt in range(max_attempts):
            if attempt > 0:
                draft = await self._author(proposal.goal, failure=failure)
                reason = self._safety_reason(draft)
                if reason is not None:
                    return BuildAttempt(staged_id=None, passed=False, output=reason)
            staged = await self._store.stage(draft)
            result = await self._sandbox.run_tests(self._store.staging_dir(staged.id))
            if result.passed:
                return BuildAttempt(staged_id=staged.id, passed=True, output=result.output)
            failure = result.output
        assert staged is not None and result is not None  # max_attempts >= 1
        return BuildAttempt(staged_id=staged.id, passed=False, output=result.output)

    async def promote(self, staged_id: str) -> Skill:
        """The result gate's commit: install a verified staged capability into the library."""
        return await self._store.promote(staged_id)
```

**e. Swap `build()`'s guard** — inside the existing `build()` loop, replace:

```python
            draft = await self._author(goal, failure=failure)
            if not draft.tests:
                return None
```

with:

```python
            draft = await self._author(goal, failure=failure)
            if self._safety_reason(draft) is not None:
                return None
```

(`build()` stays the one-shot convenience path for non-interactive/proactive use; it now also refuses network-touching capabilities. The gated trio above is the interactive path.)

### 3. `tests/test_forge.py`

Reuse the existing `FakeModel`, `FakeSandbox`, and `_draft()` helpers. `FakeModel` already returns a fixed draft; for multi-draft retry tests, drive it by constructing per-test `FakeModel`s (matching the existing pattern). Add:

```python
NETWORK_TOOL = "import imaplib\n\n\ndef fetch() -> None:\n    pass\n"


@pytest.mark.anyio
async def test_propose_blocks_network_capability(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft(tool_script=NETWORK_TOOL)),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    proposal = await forge.propose("read my email")
    assert proposal.blocked is True
    assert proposal.block_reason is not None
    assert "imaplib" in proposal.block_reason


@pytest.mark.anyio
async def test_propose_allows_pure_stdlib_capability(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft()),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    proposal = await forge.propose("extract dates from text")
    assert proposal.blocked is False
    assert proposal.block_reason is None


@pytest.mark.anyio
async def test_build_proposed_refuses_blocked_proposal_without_staging(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft(tool_script=NETWORK_TOOL)),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    proposal = await forge.propose("read my email")
    attempt = await forge.build_proposed(proposal)
    assert attempt.passed is False
    assert attempt.staged_id is None
    assert not list((tmp_path / "staging").iterdir())  # nothing was staged


@pytest.mark.anyio
async def test_gated_propose_build_promote_round_trip(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft()),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    proposal = await forge.propose("extract dates from text")
    attempt = await forge.build_proposed(proposal)
    assert attempt.passed is True
    assert attempt.staged_id is not None
    skill = await forge.promote(attempt.staged_id)
    assert store.get(skill.name) is not None


@pytest.mark.anyio
async def test_build_one_shot_refuses_network_capability(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft(tool_script=NETWORK_TOOL)),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    skill = await forge.build("read my email")
    assert skill is None
```

> If `_draft()` does not already accept a `tool_script=` keyword, extend it to (default to the existing echo script) so `NETWORK_TOOL` can be injected — a one-line signature change, no behavior change to existing call sites.

Match the existing tests' async marker exactly (use whatever `tests/test_forge.py` already uses — `@pytest.mark.anyio` shown above is illustrative; copy the file's convention).

## Acceptance criteria

1. `propose` returns `blocked=True` + a reason naming the offending module for an `imaplib`/`socket` draft, and `blocked=False` for a pure-stdlib draft → `test_propose_blocks_network_capability`, `test_propose_allows_pure_stdlib_capability`.
2. `build_proposed` on a blocked proposal returns `passed=False, staged_id=None` and stages nothing → `test_build_proposed_refuses_blocked_proposal_without_staging`.
3. `propose → build_proposed → promote` installs a clean capability into the library → `test_gated_propose_build_promote_round_trip`.
4. The one-shot `build()` still promotes a clean echo skill (existing tests unchanged) and now returns `None` for a network-touching draft → existing tests + `test_build_one_shot_refuses_network_capability`.
5. Whole project green: `uv run mypy` clean and `uv run pytest -q` all pass.

## Commands to run

```bash
uv run ruff format src/artemis/types.py src/artemis/capabilities/forge.py tests/test_forge.py
uv run ruff check src/artemis/capabilities/forge.py tests/test_forge.py
uv run mypy
uv run pytest -q
```

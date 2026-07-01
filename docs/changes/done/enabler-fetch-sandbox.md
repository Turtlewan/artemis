---
spec: enabler-fetch-sandbox
status: ready
domain: security
risk: high
coder_effort: high
prereq: enabler-wsl2-runner
token_profile: balanced
autonomy_level: L2
---

# Spec: Runtime FetchSandbox (egress-allowlisted fetch pipe)

**Identity:** The runtime `FetchSandbox` — a dumb, egress-allowlisted fetch pipe that runs a promoted capability inside the hardened WSL2 isolate and returns raw text to the host for host-side synthesis (no model calls inside).
→ why: see docs/technical/adr/ADR-035-reach-out-capabilities.md (decision 2, Option B) · docs/technical/adr/ADR-036-hardened-wsl2-sandbox.md · frozen contracts C3/C4 in docs/drafts/enabler-sandbox-DESIGN-BRIEF.md.

## Assumptions
- `src/artemis/capabilities/sandbox_wsl2.py` exists (built by the prereq `enabler-wsl2-runner`) and exports the C3 helper `run_isolated(skill_dir, *, egress_domains, caps, command, timeout_s) -> tuple[int, str, bool]` and the `SandboxCaps` model, unchanged and importable at build time → impact: Stop
- `SandboxCaps` is constructible with no arguments (`SandboxCaps()`), defaulting to the C1 caps (memory_mb=512, cpu_pct=100, pids_max=128, timeout_s=60); `FetchSandbox` supplies this default because C4's `run(...)` signature exposes no caps parameter (frozen in brief C5) → impact: Low
- C3 returns `(exit_code, output, truncated)` — a RELIABLE truncation bool derived from the guest's first-line original length (brief C3, revised). `FetchResult.truncated` is passed straight through — no `len(output)` heuristic → impact: Low
- This component has **no consumer yet** — specs 4/5 (AggregationPipeline / router) wire it. The interface is designed directly against ADR-035 Pattern B so it will not need rework; "unconsumed until spec 4" is deliberate, not an oversight → impact: Low
- Live WSL smoke requires a provisioned WSL2 guest (tinyproxy/iptables/root) that is absent on CI and non-Windows; those tests must skip cleanly, never hard-fail → impact: Caution

Simplicity check: yes — considered folding fetch into `Wsl2SandboxRunner` (add a `run_command` method) instead of a separate class. Rejected: C4 freezes `FetchSandbox`/`FetchResult` as the owned runtime contract, disjoint from the verify-time `run_tests` seam; a thin dedicated class over the shared C3 helper is the minimal surface and keeps the two loci (verify vs runtime) from entangling.

## Prerequisites
- `enabler-wsl2-runner` complete (provides `sandbox_wsl2.py` with C3 `run_isolated` + `SandboxCaps`).
- Environment: none for unit tests (they mock `run_isolated`). Live smoke needs a provisioned WSL2 guest + `ARTEMIS_WSL_SMOKE=1`.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/fetch_sandbox.py | create | `FetchResult` model + `FetchSandbox` class; imports C3 `run_isolated` + `SandboxCaps` from `sandbox_wsl2`. No model calls. |
| tests/capabilities/test_fetch_sandbox.py | create | Unit tests (mock `run_isolated`, no WSL) for construction + command/argv assembly + truncation; plus a WSL-gated live smoke that skips cleanly. Creates the `tests/capabilities/` package dir. |

## Tasks
- [ ] Task 1: Create `FetchResult` + `FetchSandbox` over the imported C3 helper — files: src/artemis/capabilities/fetch_sandbox.py — done when: `FetchSandbox.run(capability_dir, *, entrypoint, argv, egress_domains, timeout_s=60.0)` rejects a traversal/absolute `entrypoint` (`ValueError`), clamps `timeout_s` to `_MAX_TIMEOUT_S=300`, then calls `run_isolated(capability_dir, egress_domains=egress_domains, caps=SandboxCaps(), command=["python3", entrypoint, *argv], timeout_s=min(timeout_s, _MAX_TIMEOUT_S))` and returns a `FetchResult(output, exit_code, truncated)`; `uv run mypy` (full, strict) + `uv run ruff check` pass.
- [ ] Task 2: Create unit tests (mocked, WSL-free) + a WSL-gated live smoke — files: tests/capabilities/test_fetch_sandbox.py, tests/capabilities/__init__.py — done when: `uv run pytest -q tests/capabilities/test_fetch_sandbox.py` passes with the live smoke SKIPPED when `wsl.exe`/`ARTEMIS_WSL_SMOKE` is absent.

### Exact changes

**`src/artemis/capabilities/fetch_sandbox.py`** (create):
```python
"""Runtime fetch pipe for promoted network capabilities.

Runs a promoted capability inside the hardened WSL2 isolate with a caller-supplied
egress allowlist and returns raw text output for host-side synthesis. No model calls
run inside the sandbox — all reasoning is host-side (ADR-035 decision 2, Option B;
ADR-036). Egress is passed explicitly by the caller (from the promoted
`Skill.egress_domains`), not via `sandbox_policy.json`.

SECURITY — untrusted output: `FetchResult.output` is UNTRUSTED external content, raw
bytes fetched from an arbitrary allowlisted domain and attacker-influenceable (prompt
injection). Downstream consumers (AggregationPipeline / router, specs 4/5) MUST treat
it as data, not instructions, and apply prompt-injection defenses (ADR-009 dual-LLM
quarantine: no-tools reader, structured output, spotlighting) before any model
reasoning over it.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from pydantic import BaseModel

from artemis.capabilities.sandbox_wsl2 import SandboxCaps, run_isolated

_MAX_TIMEOUT_S = 300.0


class FetchResult(BaseModel):
    output: str
    exit_code: int
    truncated: bool


class FetchSandbox:
    """Runtime pipe: run a promoted capability under its egress allowlist, return raw text out."""

    async def run(
        self,
        capability_dir: Path,
        *,
        entrypoint: str,
        argv: list[str],
        egress_domains: list[str],
        timeout_s: float = 60.0,
    ) -> FetchResult:
        """Run `entrypoint` inside the isolate and return its raw output.

        `entrypoint` must be a relative path inside the capability dir (no absolute
        path, no `..` traversal). `egress_domains` is fail-closed: an empty list means
        NO network at all (pure no-network isolate), NOT unrestricted egress (C2).
        `timeout_s` is clamped to `_MAX_TIMEOUT_S` (caller-controlled DoS guard).

        Does NOT swallow exceptions from `run_isolated` (e.g. provisioning/WSL errors,
        asyncio timeouts) — they propagate to the caller to handle.
        """
        parts = PurePosixPath(entrypoint)
        if parts.is_absolute() or ".." in parts.parts:
            raise ValueError(f"entrypoint must be a relative path with no '..': {entrypoint!r}")

        exit_code, output, truncated = await run_isolated(
            capability_dir,
            egress_domains=egress_domains,
            caps=SandboxCaps(),
            command=["python3", entrypoint, *argv],
            timeout_s=min(timeout_s, _MAX_TIMEOUT_S),
        )
        return FetchResult(output=output, exit_code=exit_code, truncated=truncated)
```

**`tests/capabilities/__init__.py`** (create): empty package marker.

**`tests/capabilities/test_fetch_sandbox.py`** (create) — shape:
```python
from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from artemis.capabilities import fetch_sandbox as fs
from artemis.capabilities.fetch_sandbox import FetchResult, FetchSandbox

_WSL_SMOKE = shutil.which("wsl.exe") is not None and os.environ.get("ARTEMIS_WSL_SMOKE") == "1"


def test_fetch_result_construction() -> None:
    r = FetchResult(output="hi", exit_code=0, truncated=False)
    assert (r.output, r.exit_code, r.truncated) == ("hi", 0, False)


@pytest.mark.asyncio
async def test_run_assembles_command_and_passes_egress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock = AsyncMock(return_value=(0, "raw bytes out", False))
    monkeypatch.setattr(fs, "run_isolated", mock)

    result = await FetchSandbox().run(
        tmp_path, entrypoint="fetch.py", argv=["--q", "x"],
        egress_domains=["api.example.com"], timeout_s=42.0,
    )

    assert isinstance(result, FetchResult)
    assert (result.output, result.exit_code, result.truncated) == ("raw bytes out", 0, False)
    kwargs = mock.await_args.kwargs
    assert kwargs["command"] == ["python3", "fetch.py", "--q", "x"]
    assert kwargs["egress_domains"] == ["api.example.com"]
    assert kwargs["timeout_s"] == 42.0


@pytest.mark.asyncio
async def test_truncated_flag_passed_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # truncated comes straight from C3's reliable bool — not inferred from len(output)
    monkeypatch.setattr(fs, "run_isolated", AsyncMock(return_value=(0, "short", True)))
    result = await FetchSandbox().run(
        tmp_path, entrypoint="f.py", argv=[], egress_domains=[]
    )
    assert result.truncated is True


@pytest.mark.asyncio
async def test_nonzero_exit_propagates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fs, "run_isolated", AsyncMock(return_value=(1, "boom", False)))
    result = await FetchSandbox().run(tmp_path, entrypoint="f.py", argv=[], egress_domains=[])
    assert result.exit_code == 1


@pytest.mark.parametrize("bad", ["/etc/passwd", "../evil.py", "a/../../evil.py"])
@pytest.mark.asyncio
async def test_entrypoint_traversal_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad: str
) -> None:
    mock = AsyncMock(return_value=(0, "", False))
    monkeypatch.setattr(fs, "run_isolated", mock)
    with pytest.raises(ValueError):
        await FetchSandbox().run(tmp_path, entrypoint=bad, argv=[], egress_domains=[])
    mock.assert_not_awaited()  # guard fires before the isolate is invoked


@pytest.mark.asyncio
async def test_timeout_clamped_to_ceiling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock = AsyncMock(return_value=(0, "ok", False))
    monkeypatch.setattr(fs, "run_isolated", mock)
    await FetchSandbox().run(
        tmp_path, entrypoint="f.py", argv=[], egress_domains=[], timeout_s=99999.0
    )
    assert mock.await_args.kwargs["timeout_s"] == fs._MAX_TIMEOUT_S


@pytest.mark.skipif(not _WSL_SMOKE, reason="WSL2 not provisioned (set ARTEMIS_WSL_SMOKE=1 on a provisioned host)")
@pytest.mark.asyncio
async def test_live_wsl_allowlisted_fetch_returns_bytes(tmp_path: Path) -> None:
    # Tiny capability: fetch an allowlisted domain, print body bytes.
    (tmp_path / "fetch.py").write_text(
        "import urllib.request\n"
        "print(urllib.request.urlopen('https://example.com', timeout=20).read()[:64].decode('latin-1'))\n",
        encoding="utf-8",
    )
    allowed = await FetchSandbox().run(
        tmp_path, entrypoint="fetch.py", argv=[], egress_domains=["example.com"], timeout_s=60.0
    )
    assert allowed.exit_code == 0
    assert allowed.output.strip() != ""

    blocked = await FetchSandbox().run(
        tmp_path, entrypoint="fetch.py", argv=[], egress_domains=["other.invalid"], timeout_s=60.0
    )
    assert blocked.exit_code != 0
```

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]
(Task 2's tests import from the Task 1 module; sequential.)

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/capabilities/fetch_sandbox.py, tests/capabilities/__init__.py, tests/capabilities/test_fetch_sandbox.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project strict type check |
| `uv run pytest -q` | Full test suite (green baseline before/after) |
| `uv run pytest -q tests/capabilities/test_fetch_sandbox.py` | Focused run for this spec's tests |
| `uv run ruff check` | Lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/capabilities/fetch_sandbox.py tests/capabilities/__init__.py tests/capabilities/test_fetch_sandbox.py |
| `git commit` | "feat: runtime FetchSandbox egress-allowlisted fetch pipe (ADR-035 Option B)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_WSL_SMOKE` | Opt-in gate for the live WSL smoke (absent → smoke skips) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No package installs; live smoke reaches the network only inside the WSL2 sandbox when opted in |

## Specialist Context
### Security
Dispatched `apex-spec-reviewer` (security) pass required (security domain). Invariants to preserve: no model calls / credentials inside the sandbox (Option B); egress is caller-supplied and passed straight to C3 (no widening); output is host-consumed raw text only. The class adds no new privilege — all isolation lives in the imported C3 helper (do NOT modify `sandbox_wsl2.py`).

Untrusted-output contract (pinned now, before a consumer exists): `FetchResult.output` is UNTRUSTED external content — raw bytes from an arbitrary allowlisted domain, attacker-influenceable (prompt injection). Downstream consumers (AggregationPipeline / router, specs 4/5) MUST treat it as data, not instructions, and apply prompt-injection defenses (ADR-009 dual-LLM quarantine: no-tools reader, structured output, spotlighting) before any model reasoning over it. Input-side guards enforced in `run`: `entrypoint` rejected if absolute or containing `..` (path traversal, `ValueError`); `timeout_s` clamped to `_MAX_TIMEOUT_S=300` (caller-controlled DoS); empty `egress_domains` ⇒ fail-closed no-network (per C2), never unrestricted.

### Performance
(none)

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/fetch_sandbox.py | Module + class docstrings (ADR pointers, Option B) |

## Acceptance Criteria
- [ ] Create `FetchResult(output: str, exit_code: int, truncated: bool)` → verify: `uv run python -c "from artemis.capabilities.fetch_sandbox import FetchResult; print(FetchResult(output='x', exit_code=0, truncated=False))"` succeeds.
- [ ] `FetchSandbox.run` assembles `command=["python3", entrypoint, *argv]` and forwards `egress_domains`/`timeout_s` to `run_isolated` → verify: `uv run pytest -q tests/capabilities/test_fetch_sandbox.py::test_run_assembles_command_and_passes_egress` passes.
- [ ] Truncation flag passed through from C3 (not inferred) + non-zero exit surfaced on `FetchResult` → verify: `test_truncated_flag_passed_through` and `test_nonzero_exit_propagates` pass.
- [ ] Input guards: traversal/absolute `entrypoint` raises `ValueError` before the isolate runs, and `timeout_s` is clamped to `_MAX_TIMEOUT_S` → verify: `test_entrypoint_traversal_rejected` (all params) and `test_timeout_clamped_to_ceiling` pass.
- [ ] Live WSL smoke skips cleanly without provisioning → verify: `uv run pytest -q tests/capabilities/test_fetch_sandbox.py` reports the live-smoke test as SKIPPED (not failed/errored) on a host without `wsl.exe`/`ARTEMIS_WSL_SMOKE`.
- [ ] Baseline stays green → verify: `uv run mypy` (full, strict) + `uv run pytest -q` + `uv run ruff check` all exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_

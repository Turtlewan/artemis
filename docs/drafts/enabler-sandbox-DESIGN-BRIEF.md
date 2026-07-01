# Design brief — hardened WSL2 sandbox (enabler #2), 3-spec set

**Frozen contracts for the three drafters.** Do not re-decide these; draft against them verbatim.
Authorities: [ADR-035](../technical/adr/ADR-035-reach-out-capabilities.md) · [ADR-036](../technical/adr/ADR-036-hardened-wsl2-sandbox.md) · spike `poc/wsl2_sandbox/` (README + `isolate.sh` = the proven mechanism to harden) · finding `docs/findings/enabler-wsl2-isolation-2026-07-01.md`.

## The seam (current, in `src/artemis/capabilities/sandbox.py`)
```python
class VerifyResult(BaseModel): passed: bool; output: str
@runtime_checkable
class SandboxRunner(Protocol):
    async def run_tests(self, skill_dir: Path) -> VerifyResult: ...
class SubprocessSandbox: ...  # interim, unprivileged, no isolation — stays as dev fallback
```
Call chain: `CapabilityForge(..., sandbox: SandboxRunner)` → `sandbox.run_tests(store.staging_dir(id))`.
`create_app(..., sandbox: SandboxRunner | None = None)` → `resolved = sandbox or SubprocessSandbox()`.
`SkillDraft` fields today: `name, description, body, tool_script, uses, secrets, tests`.
`Skill` fields today: `name, description, version, path, tags, uses, secrets`.

## FROZEN cross-spec contracts

### C1 — `sandbox_policy.json` (in the staging dir, alongside `tool.py` + `tests/`)
```json
{ "egress_domains": ["api.example.com"], "memory_mb": 512, "cpu_pct": 100, "pids_max": 128, "timeout_s": 60 }
```
Written by **spec 2** (the store at stage-time). Read by the **spec 1** runner. Absent file → no-network + default caps. `SubprocessSandbox` ignores it.

### C2 — hardened isolate script CLI (spec 1 owns it; the shared mechanism) — REVISED per ADR-036 + research 2026-07-01
Invoked as `wsl.exe -u root -- bash -s -- <skill_wsl_path> <egress_csv> <run_id> <command...>` (stdin = script; command = trailing `"$@"`).
Guest responsibilities (harden the spike's `poc/wsl2_sandbox/isolate.sh`): tmpfs copy + `trap` cleanup; root netns; **cgroups v2 caps as root** (`memory.max`/`cpu.max`/`pids.max` from policy) + `ulimit -t` wall backstop; **egress**: empty `<egress_csv>` → pure no-network (lo only); non-empty → **nginx transparent SNI/Host allowlist** (`stream{}`+`ssl_preread` for HTTPS SNI, `http{}` `$host` map for HTTP; default-deny) fronted by `iptables -t nat OUTPUT REDIRECT` 443→nginx-stream, 80→nginx-http, with **`-m owner --uid-owner` matching** (nginx UID exempt, untrusted UID redirected) + a filter `OUTPUT` **default-DROP for the untrusted UID** (allow only lo, DNS, the nginx ports); **the capability `<command>` runs de-privileged** under a dedicated non-root UID (drop `CAP_NET_ADMIN`/`CAP_NET_RAW`) so it cannot flush iptables; nginx runs under its own distinct UID. Run in the netns+cgroup with `cwd`=tmpfs. **Guest emits `<original_len>\n<output[:4000]>`** (first line = pre-truncation length) so the host derives a reliable truncation flag; return the child's exit code. (No TPROXY — REDIRECT + nginx `proxy_pass` re-resolve by name.)

### C3 — shared internal helper (spec 1 exports; spec 3 imports, does NOT modify)
```python
# in src/artemis/capabilities/sandbox_wsl2.py
async def run_isolated(skill_dir: Path, *, egress_domains: list[str], caps: SandboxCaps,
                       command: list[str], timeout_s: float) -> tuple[int, str, bool]: ...
# returns (exit_code, output, truncated). Honors the passed egress_domains arg directly (never
# re-reads a staging policy file). truncated is derived from the guest's first-line length (reliable,
# not a len(output)>=4000 heuristic). Wraps wslpath-convert + wsl.exe -u root + the C2 script.
```
`Wsl2SandboxRunner.run_tests` = `run_isolated(..., command=["python3","-m","pytest","tests","-q"])` → `VerifyResult(passed=code==0, output=out)` (ignores `truncated`).
`FetchSandbox.run` (spec 3) = `run_isolated(..., command=["python3", entrypoint, *argv])` → `FetchResult(output, exit_code, truncated)`.

### C5 — `hardened` flag (spec 1 owns; spec 2 reads)
`Wsl2SandboxRunner` sets class attribute `hardened = True`. `SubprocessSandbox` must NOT define it. Spec 2's forge guard-relax fires only when `getattr(sandbox, "hardened", False) is True` (fail-closed). `SandboxCaps()` is constructible with no args (defaults = C1 caps) so the FetchSandbox runtime path can build a default.

### C4 — `FetchResult` (spec 3 owns)
```python
class FetchResult(BaseModel): output: str; exit_code: int; truncated: bool
class FetchSandbox:
    async def run(self, capability_dir: Path, *, entrypoint: str, argv: list[str],
                  egress_domains: list[str], timeout_s: float = 60.0) -> FetchResult: ...
```
Runtime pipe for spec-4 aggregation: runs a promoted capability with its egress allowlist, returns raw text out (host-side does the model reasoning — ADR-035 Option B). Egress passed explicitly by the caller (from the promoted `Skill.egress_domains`), not via the policy file.

## Spec file ownership (each ≤3 files; keep DISJOINT)
- **`enabler-wsl2-runner`** (no prereq): CREATE `src/artemis/capabilities/sandbox_wsl2.py` (`Wsl2SandboxRunner` + C2 script + C3 `run_isolated` + `SandboxCaps` model + `default_sandbox()` probe factory: WSL present+provisioned → Wsl2 else SubprocessSandbox); MODIFY `src/artemis/api/app.py` (default `sandbox or default_sandbox()`, 1 line); CREATE `tests/capabilities/test_sandbox_wsl2.py`. Provisioning (tinyproxy/iptables/.wslconfig/wsl.conf) documented in the module docstring + spec Commands — NOT a separate file.
- **`enabler-sandbox-policy-wiring`** (PREREQ: enabler-wsl2-runner): MODIFY `src/artemis/types.py` (`egress_domains: list[str] = Field(default_factory=list)` on `SkillDraft` AND `Skill`); MODIFY `src/artemis/capabilities/store.py` (write `sandbox_policy.json` in `stage()` from draft egress + default caps; persist egress on promote); MODIFY `src/artemis/capabilities/forge.py` (relax `scan_for_unsafe_imports` gate: network imports allowed when `draft.egress_domains` non-empty AND hardened sandbox active; else stay blocked).
- **`enabler-fetch-sandbox`** (PREREQ: enabler-wsl2-runner): CREATE `src/artemis/capabilities/fetch_sandbox.py` (`FetchSandbox` + `FetchResult`, imports C3 `run_isolated`); CREATE `tests/capabilities/test_fetch_sandbox.py`.

## Cross-cutting (all three)
- Stack: apex-python. Verify recipe (host): `uv run mypy` (full project, strict) + `uv run pytest -q` + `uv run ruff check`. Baseline must be green before/after (memory `codex-dispatch-baseline-must-be-green`, `host-verify-full-mypy`).
- Live WSL tests must **skip cleanly** when `wsl.exe` / provisioning is absent (CI + non-Windows) — gate with a probe fixture, never hard-fail. Unit-test the pure logic (policy parse, path convert, guard relax) without WSL.
- Security domain → each spec gets a dispatched `apex-spec-reviewer` (security) pass; set `cross_model_review: true` on `enabler-sandbox-policy-wiring` (it relaxes the security guard). `coder_effort: high` on all three (security).
- No `why` inline in the specs (link ADR-035/036). Every task names exact files + a `done when:`. Emit a `## Wave plan`. Deep Details template: `~/.claude/skills/apex-orchestrate/templates/spec-template.md`.

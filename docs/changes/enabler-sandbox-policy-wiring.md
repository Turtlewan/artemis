---
spec: enabler-sandbox-policy-wiring
status: ready
risk: high
domain: security
token_profile: balanced
autonomy_level: L2
prereq: enabler-wsl2-runner
cross_model_review: true
coder_effort: high
---

# Spec: Wire the egress policy through the forge; gate-relax the network-import guard

**Identity:** Plumb per-capability `egress_domains` from draft → staged `sandbox_policy.json` (C1) → promoted `Skill`, and relax `scan_for_unsafe_imports` so a network capability may build ONLY when it declares an egress allowlist AND the hardened sandbox is active.
→ why: see docs/technical/adr/ADR-036-hardened-wsl2-sandbox.md (Consequences: guard relaxation) · docs/technical/adr/ADR-035-reach-out-capabilities.md (decision 1–2) · frozen contracts: docs/drafts/enabler-sandbox-DESIGN-BRIEF.md (C1).

<!-- SECURITY-CRITICAL: this spec RELAXES a guard that currently blocks all network imports.
     The relaxation is gated on BOTH (a) a declared egress allowlist AND (b) hardened sandbox active.
     Default is fail-closed: unknown runner / no egress → blocked, exactly as today. -->

## Assumptions
- The prereq `enabler-wsl2-runner` is built and merged; `Wsl2SandboxRunner` exists and exposes a truthy `hardened` attribute (`hardened = True`); `SubprocessSandbox` does NOT define `hardened`. → impact: Caution (if the attr is absent, `getattr(sandbox, "hardened", False)` returns False → relaxation stays inert/fail-closed = safe, but the feature never activates; reviewer must confirm the prereq exposes it).
- "Hardened sandbox active" signal = a duck-typed capability flag read off the injected runner in forge.py: `getattr(self._sandbox, "hardened", False) is True`. Chosen over a forge ctor param because it (i) stays entirely inside the 3 owned files (no `app.py`/protocol edit), (ii) auto-activates the moment the hardened runner is injected — no separate wiring line, and (iii) is fail-closed for any runner that does not self-declare hardness. → impact: Stop if wrong (this is the security gate).
- `egress_domains` is persisted in the library via the co-located `sandbox_policy.json` (C1) copied staging→library on promote, and `Skill.egress_domains` is hydrated from it — NOT via a new SKILL.md frontmatter key, because `skill_md.py` is out of the frozen 3-file scope. The brief's "SKILL.md frontmatter" intent is realized by the co-located policy file (C1 is the egress home). → impact: Caution (representation differs from the brief's wording; consumers read `Skill.egress_domains`, which round-trips regardless — reviewer confirm).
- Authoring must be able to emit `egress_domains`, so `SKILL_DRAFT_SCHEMA` + one `AUTHOR_SYSTEM` line gain the field (both live in the owned `forge.py`; no new file). Without it, `draft.egress_domains` is always `[]` and the relaxation is unreachable. → impact: Caution.
- Default caps are fixed constants (memory_mb=512, cpu_pct=100, pids_max=128, timeout_s=60) per C1; no per-draft override in this spec. → impact: Low.

Simplicity check: Considered a forge ctor `hardened_sandbox: bool` param — rejected: it needs an out-of-scope `app.py` wiring line to ever be True, so the feature would ship inert. The duck-typed runner flag is simpler, self-contained, and auto-activating. Considered adding an `egress_domains` frontmatter key to `skill_md.py` — rejected: exceeds the 3-file lock; the C1 policy file already owns egress on disk.

## Prerequisites
- Specs complete first: `enabler-wsl2-runner` (creates `Wsl2SandboxRunner` with `hardened = True` + `default_sandbox()` probe).
- Environment setup: none (unit tests only; no live WSL needed for this spec).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/types.py | modify | Add `egress_domains: list[str] = Field(default_factory=list)` to `SkillDraft` AND `Skill`, EACH with a `field_validator` that validates/normalizes the allowlist (this is the untrusted-input entry point). |
| src/artemis/capabilities/store.py | modify | `stage()` writes `sandbox_policy.json` (C1); `promote()` copies it to the library; `_read_skill` hydrates `Skill.egress_domains`. |
| src/artemis/capabilities/forge.py | modify | Relax `scan_for_unsafe_imports` (egress+hardened gating); `_safety_reason` passes egress + hardened flag; add `egress_domains` to author schema + `AUTHOR_SYSTEM`. |
| tests/test_capability_store.py | modify | Add tests: policy-file write + caps + egress round-trip on promote. |
| tests/test_forge.py | modify | Add tests: the new guard decision table (all rows). |

## Tasks
- [ ] Task 1: Add the VALIDATED `egress_domains` field to both models — files: src/artemis/types.py — done when: `SkillDraft(...)` and `Skill(...)` accept/default `egress_domains: list[str]` to `[]`; a shared `field_validator` (see "Task 1 — validation" below) rejects wildcards/globs/empty/over-long/homograph entries and normalizes valid ones; full `uv run mypy` is green.
- [ ] Task 2: Write + persist the sandbox policy — files: src/artemis/capabilities/store.py, tests/test_capability_store.py — done when: `stage()` writes `sandbox_policy.json` with the exact C1 schema into the staging dir; `promote()` copies it into the library dir; `_read_skill` hydrates `Skill.egress_domains` from it (absent file → `[]`); new tests pass.
- [ ] Task 3: Gate-relax the import guard — files: src/artemis/capabilities/forge.py, tests/test_forge.py — done when: `scan_for_unsafe_imports` implements the decision table below; `_safety_reason` passes `draft.egress_domains` + `getattr(self._sandbox, "hardened", False)`; `SKILL_DRAFT_SCHEMA`/`AUTHOR_SYSTEM` carry `egress_domains`; new decision-table tests pass and all existing forge tests stay green.

### Task 1 — validation (types.py)
`egress_domains` is populated from the LLM-authored draft, whose `goal` is untrusted (prompt-injectable); an injected goal could emit `["*"]` or an exfil domain that would be written verbatim into the enforced allowlist. Validate at THIS entry point. Add a `field_validator("egress_domains")` (a module-level `validate_egress_domains(v: list[str]) -> list[str]` helper — public, shared by BOTH `SkillDraft` and `Skill`, and re-imported by store.py) that, in order:
```python
import ipaddress
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_MAX_EGRESS = 20
# Special-use / internal suffixes: multi-label internal names (e.g. metadata.google.internal)
# are otherwise indistinguishable from public names by the hostname grammar alone.
_INTERNAL_SUFFIXES = (".local", ".internal", ".localhost", ".test", ".invalid")

def validate_egress_domains(v: list[str]) -> list[str]:
    if len(v) > _MAX_EGRESS:                     # cap list length
        raise ValueError(f"egress_domains exceeds {_MAX_EGRESS} entries")
    out: list[str] = []
    for raw in v:
        d = raw.strip().rstrip(".").lower()      # normalize: strip, drop trailing dot, lowercase
        if not d:                                # reject empty / whitespace-only
            raise ValueError("egress_domains contains an empty entry")
        if not d.isascii():                      # reject non-ASCII (homograph look-alikes)
            raise ValueError(f"egress_domains entry is not ASCII: {raw!r}")
        if "*" in d or "?" in d or "/" in d or ":" in d:   # reject wildcard/glob/scheme/port/path
            raise ValueError(f"egress_domains entry is not a bare hostname: {raw!r}")
        if not _HOSTNAME_RE.match(d):            # strict RFC-1035-ish hostname (labels + dots)
            raise ValueError(f"egress_domains entry is not a valid hostname: {raw!r}")
        try:                                     # reject IP literals — SUCCESS = it parsed = reject
            ipaddress.ip_address(d)
        except ValueError:
            pass                                 # parse FAILED → it is a name, allowed
        else:
            raise ValueError(f"egress_domains entry is an IP literal, not a domain (SSRF): {raw!r}")
        if d == "localhost" or d.endswith(_INTERNAL_SUFFIXES):   # special-use / internal names
            raise ValueError(f"egress_domains entry is a special-use/internal name: {raw!r}")
        out.append(d)
    return out
```
The IP-literal reject closes the SSRF hole: a bare address like `169.254.169.254` (cloud metadata → IAM cred theft), `127.0.0.1`, or any RFC1918 host satisfies the digit-label hostname grammar, so it must be rejected explicitly — `ipaddress.ip_address(d)` **succeeding** means the entry is an address and is rejected; only a parse **failure** (a real name) proceeds. Rejection raises `ValueError` (→ pydantic `ValidationError` at construction, before any policy file is written). Because construction fails on a bad entry, a draft can never carry an invalid allowlist into `stage()` or the guard. NOTE: punycode-encoding non-ASCII was considered and rejected in favour of a hard reject. NOTE: name-allowlisting is a coarse control — it does NOT defend against ASCII typosquatting (`goog1e-apis.com`) or already-punycode `xn--` domains; those are accepted if syntactically valid. Domain-reputation/approval is deferred to the promote-time egress governance parked in ADR-035 (no code change here).

### Task 2 — exact changes (store.py)
In `stage()`, after the tests are written, always write the policy file:
```python
import json
...
policy = {
    "egress_domains": list(draft.egress_domains),
    "memory_mb": 512, "cpu_pct": 100, "pids_max": 128, "timeout_s": 60,
}
(staged_dir / "sandbox_policy.json").write_text(
    json.dumps(policy, indent=2), encoding="utf-8"
)
```
In `promote()`, after copying `tool.py`/`tests`, copy the policy file if present:
```python
policy_path = staged_dir / "sandbox_policy.json"
if policy_path.exists():
    shutil.copy2(policy_path, library_dir / "sandbox_policy.json")
```
Hydrate egress in the returned `Skill` (promote) and in `_read_skill`:
```python
import logging
from artemis.types import validate_egress_domains   # shared validator (Task 1)
_log = logging.getLogger(__name__)

def _egress(dir_: Path) -> list[str]:
    p = dir_ / "sandbox_policy.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):            # valid JSON but not an object ([], 42, "x", null)
            return []
        return validate_egress_domains([str(d) for d in data.get("egress_domains", [])])
    except (OSError, ValueError, TypeError, AttributeError) as exc:   # corrupt/tampered → fail closed
        _log.warning("unusable sandbox_policy.json in %s: %s", dir_, exc)
        return []
```
A corrupt, unreadable, OR tampered `sandbox_policy.json` (bad JSON, valid JSON that is not an object such as `[]`/`42`/`"x"`/`null`, or valid JSON with a domain that fails `validate_egress_domains`) must fail closed to `[]` per-capability and NEVER propagate — otherwise a single bad file breaks `get()` / `list()` / `retrieve()` for the whole library, AND re-validating here (not just at `Skill` construction) stops a hand-edited on-disk allowlist from smuggling a wildcard/exfil domain past the type boundary. `validate_egress_domains` is exported from `types.py` for this reuse. `promote()` returns `Skill(..., egress_domains=_egress(staged_dir))`; `_read_skill` sets `egress_domains=_egress(skill_path.parent)`. `_read_draft` sets `egress_domains=_egress(staged_dir)` so staged round-trips carry egress. (Values loaded from disk re-pass the Task-1 `field_validator` on `Skill`/`SkillDraft` construction.)

### Task 3 — the guard decision table (forge.py)
`scan_for_unsafe_imports` gains two keyword args (defaults reproduce today's fail-closed behavior, so existing callers/tests are unchanged):
```python
def scan_for_unsafe_imports(
    source: str | None,
    *,
    egress_domains: Sequence[str] = (),
    hardened_sandbox: bool = False,
) -> str | None:
```
"egress declared?" below means **a non-empty `draft.egress_domains`**, which — because the Task-1 `field_validator` runs at draft construction — is guaranteed to be a validated, normalized hostname allowlist (no wildcards/globs/empty/homograph/over-long entries ever reach the guard). The guard performs NO re-validation; the type is the boundary.

Decision table (evaluated after the no-test check in `_safety_reason`, which is UNCHANGED and highest priority):

| tool_script | network imports? | egress declared? | hardened active? | result |
|---|---|---|---|---|
| `None` | — | — | — | allowed (None) |
| unparseable | — | — | — | **blocked** — "authored code could not be parsed for a safety scan" |
| parseable | none | — | — | allowed (None) |
| parseable | yes | no | any | **blocked** — "...imports network/process modules (`{names}`); declare an egress_domains allowlist to run it in the hardened sandbox" |
| parseable | yes | yes | no | **blocked** — "...imports network/process modules (`{names}`); hardened sandbox unavailable — network capabilities stay blocked" |
| parseable | yes | yes | yes | **allowed (None)** |

`_safety_reason` wiring:
```python
def _safety_reason(self, draft: SkillDraft) -> str | None:
    if not draft.tests:
        return "capability has no test -- cannot verify"
    return scan_for_unsafe_imports(
        draft.tool_script,
        egress_domains=draft.egress_domains,
        hardened_sandbox=getattr(self._sandbox, "hardened", False),
    )
```
Add `"egress_domains": {"type": "array", "items": {"type": "string"}}` to `SKILL_DRAFT_SCHEMA["properties"]`, add it to `required`, and add one `AUTHOR_SYSTEM` line: capabilities that need the network MUST list every domain they contact in `egress_domains` (empty = no network).

Trust-point note (goes in the `scan_for_unsafe_imports` docstring): only a genuinely-isolated `SandboxRunner` may set `hardened=True`; **app-wiring is the trust point** — the sandbox object is injected at `create_app`, never attacker-controlled, so spoofing the flag requires a code change, and the default is fail-closed. (Duck-typing is retained deliberately so the future Lima macOS runner — ADR-035 decision 7 — can also declare `hardened=True` without a signature change.)

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3]
<!-- Task 1 adds the shared field both downstream tasks depend on. Tasks 2 and 3 are file-disjoint (store + its test vs forge + its test) → run in parallel. -->

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | (none) |
| Modify | src/artemis/types.py, src/artemis/capabilities/store.py, src/artemis/capabilities/forge.py, tests/test_capability_store.py, tests/test_forge.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project strict type check (baseline green before + after). |
| `uv run pytest -q` | Full test suite incl. new guard + policy tests. |
| `uv run ruff check` | Lint. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/types.py src/artemis/capabilities/store.py src/artemis/capabilities/forge.py tests/test_capability_store.py tests/test_forge.py |
| `git commit` | "feat: wire egress policy through the forge and gate-relax the network-import guard" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | — |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Unit tests only; no live WSL or network. |

## Specialist Context
### Security
This spec relaxes a containment guard; it is dispatched to `apex-spec-reviewer` (security) and carries `cross_model_review: true`. Invariants the review must confirm: (1) relaxation requires BOTH a VALIDATED non-empty egress allowlist AND hardened-active — never one alone; (2) default is fail-closed (`getattr` default False; empty egress blocks); (3) unparseable source is always blocked regardless of egress/hardened; (4) the no-test hard-stop is preserved and highest priority; (5) `SubprocessSandbox` (dev fallback) never reports hardened, so it can never run a network capability; (6) the `egress_domains` `field_validator` is the untrusted-input entry point — it rejects wildcards/globs/empty/homograph/over-long lists before any policy file is written, and `_egress()` re-validates on read.

Fast-follow (out of THIS spec's 3-file scope): the plan-gate `PlanCard` does not yet display `egress_domains` to the owner before "Build it" — a client/route change tracked as an Open Question by planning. The Task-1 validation above makes the relaxation safe to enforce WITHOUT that UI; owner visibility is a defense-in-depth follow-up, not a blocker.

### Performance
(none)

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/forge.py | Docstring on `scan_for_unsafe_imports` states the decision table, that it is NOT a security boundary (the hardened sandbox is), and the trust-point note (only a genuinely-isolated runner may set `hardened=True`; app-wiring is the trust point). |
| Inline | src/artemis/capabilities/store.py | Docstring note: `sandbox_policy.json` is the C1 artifact + the on-disk egress home. |
| Changelog | CHANGELOG.md | Add entry under Unreleased. |
| ADR | (none — ADR-036 already records the decision) | — |

## Acceptance Criteria
- [ ] Add `egress_domains` to `SkillDraft` + `Skill` → verify: `uv run python -c "from artemis.types import SkillDraft, Skill; print(SkillDraft(name='x',description='d',body='b',tool_script=None,tests=None).egress_domains, Skill(name='x',description='d',version=1,path='.',tags=[],uses=[],secrets=[]).egress_domains)"` prints `[] []`.
- [ ] Egress validation rejects hostile input → verify: tests in `tests/test_forge.py` (which already imports `SkillDraft`; no new test file) assert `pydantic.ValidationError` raised for `egress_domains=["*"]`, `["*.evil.com"]`, `[""]`, `["  "]`, `["http://x.com"]`, `["x.com:443"]`, `["x.com/path"]`, a Cyrillic homograph `["ехample.com"]` (non-ASCII), and an over-long list (21 entries); on BOTH `SkillDraft` and `Skill`.
- [ ] Egress validation blocks SSRF targets → verify: same test file asserts `pydantic.ValidationError` raised for `egress_domains=["169.254.169.254"]`, `["127.0.0.1"]`, `["10.0.0.5"]`, `["::1"]`, `["metadata.google.internal"]`, `["foo.internal"]`, `["localhost"]`; and that `["api.example.com"]` is still accepted.
- [ ] Egress validation accepts + normalizes valid input → verify: `SkillDraft(..., egress_domains=["API.Example.COM.", "sub.good.io"]).egress_domains == ["api.example.com", "sub.good.io"]` (lowercased, trailing dot stripped).
- [ ] `stage()` writes the policy file → verify: a store test stages a draft with `egress_domains=["api.example.com"]` and asserts `sandbox_policy.json` in the staging dir equals `{"egress_domains":["api.example.com"],"memory_mb":512,"cpu_pct":100,"pids_max":128,"timeout_s":60}`.
- [ ] Egress round-trips on promote → verify: a store test promotes that draft and asserts `store.get(name).egress_domains == ["api.example.com"]` and a `sandbox_policy.json` exists in the library dir; a draft with no egress yields `[]`.
- [ ] Corrupt policy fails closed, never propagates → verify: a store test promotes a capability, overwrites its library `sandbox_policy.json` with `"{ not json"`, then asserts `store.get(name).egress_domains == []` AND `store.list()` / `retrieve("x")` still succeed (no exception); a second test writes valid JSON with `egress_domains=["*"]` and asserts it also degrades to `[]` (re-validation on read); a third writes a top-level array/string/number/`null` (e.g. `"[]"`, `"42"`, `"null"`) and asserts `store.get(name).egress_domains == []` with no exception (non-dict guard).
- [ ] Guard decision table (all rows) → verify: forge tests assert — no-imports draft allowed; network-import draft with empty egress blocked (reason contains the module name + "allowlist"); network-import draft with egress but a non-hardened sandbox blocked (reason contains "hardened sandbox unavailable"); network-import draft with egress AND a fake `hardened=True` sandbox allowed (`propose(...).blocked is False`); unparseable source blocked; no-test draft blocked with the unchanged message.
- [ ] Existing forge/store tests unchanged → verify: `test_propose_blocks_network_capability` and all prior tests still pass (defaults keep fail-closed behavior).
- [ ] Full verify recipe green → verify: `uv run mypy` (0 errors, strict, full project) && `uv run pytest -q` (all pass) && `uv run ruff check` (clean).

## Progress
_(Coding mode writes here — do not edit manually)_

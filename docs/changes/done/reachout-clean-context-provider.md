---
spec: reachout-clean-context-provider
status: ready
token_profile: balanced
autonomy_level: L2
risk: high
coder_effort: high
domain: security
cross_model_review: true
---

# Spec: Clean-context Claude-CLI provider (subscription reads without CLAUDE.md/hook pollution)

**Identity:** Harden `ClaudeCodeProvider` to invoke `claude -p` in a hook- and CLAUDE.md-free context via a private, per-process sanitized `CLAUDE_CONFIG_DIR`, so subscription-auth reads return the model's answer (not an APEX status banner). Prerequisite for R2's live quarantined reader; also unblocks Pattern-B's pull tier.
→ why: see docs/technical/adr/ADR-037-pattern-a-web-tool.md (decision 5) + ADR-035 provider notes.

## Assumptions
- OAuth credentials are **file-based** at `~/.claude/.credentials.json` (verified live, 470 bytes) — so a sanitized config dir can carry auth without the keychain → impact: Stop.
- `CLAUDE_CONFIG_DIR` pointed at a dir containing only `.credentials.json` (no `CLAUDE.md`, no `settings.json`) yields clean output while preserving OAuth — **proven live 2026-07-01** (polluted default returned an APEX banner + "Paris"; sanitized returned just "Paris") → impact: Stop.
- `--bare` is NOT usable — it forces `ANTHROPIC_API_KEY`/apiKeyHelper auth and skips keychain reads, breaking subscription-only OAuth (confirmed in `claude --help`, v2.1.197) → impact: Caution.
- `cli_support.run_cli` is shared by `codex_provider`, so a new `env` param MUST be optional/backward-compatible (default = inherit `os.environ`) → impact: Stop.
- `ClaudeCodeProvider` is constructed once in `compose.py:22` with no args; the sanitized-dir logic lives inside the provider → impact: Low.
- **Token-rotation (SECURITY FLAG, unverified):** it is **not known** whether Claude CLI OAuth uses single-use refresh-token rotation. If it does, a refresh that lands only in the sanitized copy could invalidate the shared token and break the primary interactive `claude` session. This spec **copies forward only** (`~/.claude` → sanitized, never back) and the live-smoke MUST confirm the primary session still authenticates after a clean-context read; if rotation-invalidation is observed, the follow-up is to propagate the refreshed token back to `~/.claude` (single source of truth) → impact: Caution (could disrupt the owner's primary CLI session).

Simplicity check: Considered `--system-prompt`/`--settings '{}'` overrides instead of a config-dir swap — rejected (settings deep-merge leaks user hooks + CLAUDE.md; not empirically clean). Considered a fixed shared sanitized-dir path — rejected on the security review (predictable multi-user temp path = CWE-377). A per-process `mkdtemp` dir + one env var + one flag is the minimal safe change.

## Prerequisites
- Specs that must be complete first: none.
- Environment: a logged-in Claude CLI subscription (`~/.claude/.credentials.json` present). Live-smoke only.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/model/cli_support.py | modify | `run_cli` gains optional `env: Mapping[str,str] \| None = None`; when set, pass to `create_subprocess_exec(env=...)` |
| src/artemis/model/claude_code_provider.py | modify | private per-process sanitized `CLAUDE_CONFIG_DIR` (mkdtemp 0o700; atomic creds copy; per-call poison guard; atexit cleanup), pass via env + add `--exclude-dynamic-system-prompt-sections` |
| tests/model/test_claude_code_provider.py | modify | hermetic tests (mock `run_cli`, **monkeypatch `Path.home()` to a fixture with a dummy token** — never touch the real credential); document the live-smoke |

## Tasks
- [x] Task 1: `run_cli` env passthrough — files: src/artemis/model/cli_support.py, tests/model/test_claude_code_provider.py — done when: `run_cli(argv, stdin=b"", env={"X":"1"})` passes a merged env to the subprocess (default None = inherit os.environ, codex_provider unaffected); a unit test asserts the env reaches `create_subprocess_exec`. `uv run pytest -q tests/model/` passes.
- [x] Task 2: `ClaudeCodeProvider` clean-context invocation — files: src/artemis/model/claude_code_provider.py, tests/model/test_claude_code_provider.py — done when: `generate()` runs `claude -p … --model … --exclude-dynamic-system-prompt-sections` with `env["CLAUDE_CONFIG_DIR"]` = a private per-process dir holding ONLY a fresh `.credentials.json`; hermetic tests (home monkeypatched) prove the poison-guard, atomic copy, and repeat-invocation cleanliness; the documented live-smoke returns a clean extract AND leaves the primary session working.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2]
<!-- Task 2 uses the env param Task 1 adds → sequential. -->

## Exact changes

### cli_support.py — optional env passthrough
```python
async def run_cli(
    argv: list[str], *, stdin: bytes, env: Mapping[str, str] | None = None
) -> tuple[int, bytes, bytes]:
    """Run argv, feed stdin, return (returncode, stdout, stderr). `env`, if given, fully
    replaces the child environment (callers pass a merged {**os.environ, ...})."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env) if env is not None else None,
    )
    stdout, stderr = await process.communicate(stdin)
    return (process.returncode or 0, stdout, stderr)
```
Add `from collections.abc import Mapping, Sequence`. `env=None` → inherit `os.environ` (codex_provider unchanged).

### claude_code_provider.py — private sanitized CLAUDE_CONFIG_DIR
`ClaudeCodeProvider.__init__` gains a lazily-created, per-instance sanitized dir path (initially `None`).

- Helper `_ensure_clean_config_dir(self) -> Path`:
  - Source creds: `Path.home() / ".claude" / ".credentials.json"`. Missing → raise `ProviderUnavailableError("claude_code", "no credentials for clean-context read")`.
  - **BLOCK fix — unpredictable, private dir:** on first use, create `self._cfg_dir = Path(tempfile.mkdtemp(prefix="artemis-claude-clean-"))` (mkdtemp yields a unique, 0o700, non-guessable path — closes CWE-377). Register `atexit.register(shutil.rmtree, self._cfg_dir, ignore_errors=True)` **once** to remove the live-token copy on process exit (cleanup lifecycle).
  - **Poison guard (per call, fail-closed):** before every invocation, if `self._cfg_dir` contains ANY entry other than `.credentials.json` (e.g. a stray `CLAUDE.md`, `settings.json`, or a CLI-written `.claude.json`), delete those extra entries (they are the pollution vectors). If a stray entry cannot be removed, raise `ProviderUnavailableError` (do not run a possibly-polluted read).
  - **Atomic creds copy (note fix):** copy `~/.claude/.credentials.json` into the dir only when the source mtime is newer than the dest, via copy-to-temp-in-same-dir + `os.replace()` (atomic; no partial-read race). Chmod the dest `0o600`.
  - Return `self._cfg_dir`. Never log the dir path or token above DEBUG; never copy the sanitized token back to `~/.claude`.
- In `generate()`: append `"--exclude-dynamic-system-prompt-sections"` to argv; build `env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self._ensure_clean_config_dir())}`; call `run_cli(argv, stdin=b"", env=env)`.

## Permissions

The following actions run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | src/artemis/model/cli_support.py, src/artemis/model/claude_code_provider.py, tests/model/test_claude_code_provider.py |
| Create (runtime, not repo) | `<mkdtemp>/artemis-claude-clean-*/.credentials.json` — a user-private, per-process copy of the OAuth token (0o600), removed at process exit; NOT committed |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` / `uv run pytest -q` / `uv run ruff check` | full-project strict gate |
| `claude -p … --model haiku …` (live-smoke, once) | prove clean output (no APEX banner) AND primary session still authenticates afterward |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/model/cli_support.py, src/artemis/model/claude_code_provider.py, tests/model/test_claude_code_provider.py |
| `git commit` | "feat: clean-context Claude-CLI provider for subscription reads" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `CLAUDE_CONFIG_DIR` | SET (child env only) to the sanitized dir; never mutates the parent process env |
| `HOME` / `USERPROFILE` | READ (via `Path.home()`) to locate the source creds |

### Network
| Action | Purpose |
|--------|---------|
| `claude -p` live-smoke | one subscription call; tests are otherwise offline via mocked `run_cli` |

## Specialist Context
### Security
- **Credential-at-rest (primary risk).** The sanitized dir holds a live OAuth token copy. Use `mkdtemp` (unique, private, 0o700) — NOT a fixed shared path (predictable multi-user temp = CWE-377 symlink/disclosure). Token file `0o600`. Remove the dir at process exit (`atexit`). Never log the token/path above DEBUG; never copy the sanitized token back to `~/.claude`.
- **No pollution leak / regression guard.** The dir MUST contain creds only. A per-call poison guard removes any stray `CLAUDE.md`/`settings.json`/`.claude.json` and fails closed if it can't — catching both external drops and CLI-written config across repeated invocations (not just first creation).
- **Test isolation.** Every test touching the sanitized-dir helper MUST monkeypatch `Path.home()` to a fixture dir containing a DUMMY `.credentials.json` — hermetic tests must never copy the real subscription token into a temp path.
- **Token rotation (unverified).** Copy-forward-only; the live-smoke verifies the primary `claude` session still authenticates after a clean-context read. If rotation-invalidation is seen, follow up by propagating refreshes back to `~/.claude`.
- **Quarantine-adjacent:** this provider feeds the R2 quarantined reader; a polluted read is both a quality and a mild injection-surface bug, so clean context is a security property.

### Performance
(none — a per-call mtime-guarded 470-byte atomic copy is negligible.)

### Accessibility
(none — no frontend.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/model/claude_code_provider.py | docstring the clean-context helper + the poison-guard/mtime-guard rationale |
| Changelog | CHANGELOG.md | Add entry under Unreleased |

## Acceptance Criteria
- [ ] Backward-compat → verify: `codex_provider` tests still pass; `run_cli(argv, stdin=b"")` (no env) inherits `os.environ` (`uv run pytest -q tests/model/test_codex_provider.py`).
- [ ] env passthrough → verify: a unit test patches `asyncio.create_subprocess_exec` and asserts `run_cli(argv, stdin=b"", env={**os.environ,"CLAUDE_CONFIG_DIR":"/x"})` passed `env` containing `CLAUDE_CONFIG_DIR=/x`.
- [ ] Clean-context argv + private dir → verify: hermetic test (home monkeypatched to a fixture with dummy creds) mocks `run_cli`, calls `generate(model="haiku")`, asserts argv contains `--exclude-dynamic-system-prompt-sections` and `env["CLAUDE_CONFIG_DIR"]` points at a `mkdtemp`-style path (NOT a fixed name) whose only entry is `.credentials.json`.
- [ ] Poison guard + repeat-invocation → verify: after dropping a `CLAUDE.md` and a `settings.json` into the sanitized dir, the NEXT `generate()` call removes them (dir clean again); two successive calls both leave the dir creds-only.
- [ ] Atomic copy + mtime guard → verify: creds re-copied when source mtime is newer, skipped when not; the copy uses a temp+replace path (no partial file observable).
- [ ] Missing creds → verify: with `Path.home()/.claude/.credentials.json` absent (monkeypatched home), `generate()` raises `ProviderUnavailableError`.
- [ ] Live-smoke (manual, documented as a skipped marker with the exact command) → verify: the sanitized-`CLAUDE_CONFIG_DIR` read of "Extract only the capital city. TEXT: France's capital is Paris." returns `"Paris"` with NO APEX banner; AND a subsequent plain `claude -p "say OK"` (primary session) still authenticates (token-rotation check).
- [ ] Full-project gate → verify: `uv run mypy` (0 errors, strict), `uv run pytest -q` (all pass), `uv run ruff check` (clean).

## Progress
_(Coding mode writes here — do not edit manually)_

**COMPLETE (2026-07-01, Codex gpt-5.5 / host = Opus).** mypy 101 · 248 passed/2 skipped · ruff+format clean. 24 model tests (incl. env passthrough, private-dir, poison-guard repeat-invocation, atomic mtime copy, missing-creds; live-smoke = skipped marker). Cross-model review (Opus): 1 FLAG-HIGH + 2 FLAG-MED/LOW fixed — removed the `inspect.signature` fail-open branch (silent regression to polluted reads), symlink-poison the creds entry, POSIX-only-chmod caveat comment.
- **Out-of-scope fix (logged):** `tests/model/test_compose.py` (not in Files to Change) was updated — its `fake_run_cli` mock lacked the `env` param Task 1 added to `run_cli`, and it was silently exercising the polluted path via the now-removed branch. Updated the mock signature + dummy-home so it never touches the real token. Necessary collateral of the Task-1 signature change; test-only.

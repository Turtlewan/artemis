---
spec: js-rendering-fetcher
status: blocked
token_profile: lean
autonomy_level: L5
coder_effort: high
---

<!-- BLOCKED 2026-07-03: Codex built all 4 tasks (unit-green), but the required build-time live
     smoke fails — chrome cannot run in the PRODUCTION isolate due to two substrate defects outside
     this spec's scope (sandbox_wsl2.py + fetch_sandbox.py). Both fixes diagnosed + confirmed. See
     docs/progress/js-rendering-fetcher.md. Awaiting owner fork decision (fix isolate now vs new spec). -->


# Spec: JS-rendering fallback fetcher

**Identity:** A headless-Chromium `Fetcher` that renders JS/bot-blocked pages inside the existing hardened WSL2 isolate, wired as a fallback the web tool uses only when trafilatura returns empty text.
→ why: see docs/technical/adr/ADR-040-js-rendering-fetcher.md

## Assumptions
- The WSL2 isolate + `FetchSandbox` (egress-allowlisted, de-privileged, fail-closed) is the correct place to render untrusted pages; the spike (`poc/wsl2_browser/`) proved chrome-headless-shell runs there unmodified and stays contained → impact: Stop
- `chrome-headless-shell` (NOT full `chrome`) is provisioned at `/opt/chromium_headless_shell/chrome-headless-shell` inside the WSL2 distro (world-readable), per the provisioning doc; full `chrome` blows the timeout on background-network churn (spike load-bearing finding #1) → impact: Stop
- First-party domain-only egress is sufficient for text extraction — asset/CDN subdomains are NOT needed (spike check #4) → impact: Caution
- On any host where WSL2/chrome is absent (or the render fails), the fetcher degrades to empty text; `WebTool.answer` already skips empty-text sources, so the net result equals trafilatura-alone (no crash, no regression) → impact: Stop
- The render script is run by the isolate's SYSTEM python3 (stdlib only) — it must not import anything from `artemis`; it lives under `src/` only so it is linted/typed → impact: Caution
- `output_limit` (from prerequisite spec `js-fetch-output-limit`) lets the isolate return full page text instead of a 4000-char snippet → impact: Stop

Simplicity check: considered replacing `TrafilaturaFetcher` outright — rejected (owner decision 2026-07-03): ~5-8× slower on every query and breaks the web tool on any non-provisioned host. Fallback-on-empty keeps the 0.25s fast path and pays the ~2s isolate cost only for pages trafilatura can't read.

## Prerequisites
- `js-fetch-output-limit` (adds `FetchSandbox.run(output_limit=...)`, which `JsFetcher` requires) — must be built first.
- Environment setup for the LIVE smoke only (not for unit tests / build): WSL2 provisioned per docs/technical/setup/js-fetcher-provisioning.md. The build and unit tests mock the sandbox and need no WSL2.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/reachout/render_script.py | create | in-isolate: launch chrome-headless-shell `--dump-dom`, extract visible text (stdlib only) |
| src/artemis/reachout/js_fetch.py | create | `JsFetcher` (implements `Fetcher`): stage render script, run via `FetchSandbox`, degrade-to-empty |
| src/artemis/reachout/web_tool.py | modify | add `FallbackFetcher`; wire `FallbackFetcher(TrafilaturaFetcher, JsFetcher)` in `build_web_tool` |
| tests/reachout/test_render_script.py | create | unit-test `extract_text` (pure, no chrome) |
| tests/reachout/test_js_fetch.py | create | unit tests (mocked sandbox) + a WSL/chrome-gated live smoke |
| tests/reachout/test_web_tool.py | modify | `FallbackFetcher` tests (primary-empty→secondary; non-empty→skip; EgressDenied propagates) |
| docs/technical/setup/js-fetcher-provisioning.md | create | one-time chrome-headless-shell provisioning runbook (pinned build + checksum verify) |
<!-- docs/technical/adr/ADR-040-js-rendering-fetcher.md is authored at PLANNING time (not a build task) — the gate requires it to exist before the spec is ready. -->


## Tasks
<!-- TDD: each code task ships WITH its tests (test file named in the same task); coding mode REDs the
     task's acceptance-criteria bullets before writing the implementation. -->
- [ ] Task 1: Create `render_script.py` + its unit test. Port `poc/wsl2_browser_userns/capability/render.py`: keep the `_TextExtractor(HTMLParser)` + `extract_text(html)` pure function and the chrome flag set — but DO NOT pass `--no-sandbox` or `--disable-setuid-sandbox` (userns-spike PASS 2026-07-03: omitting them engages Chrome's seccomp-bpf renderer sandbox nested in the isolate — `Seccomp: 2` — for defense-in-depth; keeping them would DISABLE it. See `poc/wsl2_browser_userns/README.md`). Flag set: `--headless --disable-gpu --disable-dev-shm-usage --disable-quic --user-data-dir=<tmp> --disable-crash-reporter … --dump-dom`, with `HOME`/`XDG_RUNTIME_DIR` set to the profile dir. Change the default binary to `/opt/chromium_headless_shell/chrome-headless-shell`. `main()`: `argv[1]=url`, optional `argv[2]=binary`; print extracted text to stdout, exit 0; on chrome error/timeout write a short diagnostic to stderr and exit non-zero. Stdlib only — NO `artemis` imports. Must pass `mypy --strict` and ruff. Test `extract_text` in `test_render_script.py` (tags stripped; `script`/`style`/`noscript`/`template` skipped; whitespace collapsed). — files: src/artemis/reachout/render_script.py, tests/reachout/test_render_script.py — done when: the `extract_text` AC bullets pass and the module type-checks.
- [ ] Task 2: Create `JsFetcher` in `js_fetch.py` + its unit tests. Implements the `Fetcher` protocol (`fetch(url, *, max_chars=20000) -> FetchedContent`, `aclose()`). Behaviour: derive `host = urllib.parse.urlsplit(url).hostname` — the EXACT hostname (e.g. `en.wikipedia.org`), NOT `registrable_domain(url)` (the isolate's nginx `$ssl_preread_server_name` map is exact-match, so the eTLD+1 would silently default-deny Chrome's real SNI — see Specialist Context ▸ Security BLOCK 1); if `host` is None/empty return empty `FetchedContent(url, "", "")`; create a `tempfile.TemporaryDirectory`, `shutil.copyfile` `render_script.py` into it as `render.py`; call `self._sandbox.run(Path(tmp), entrypoint="render.py", argv=[url, self._chromium_bin], egress_domains=[host], timeout_s=self._timeout_s, output_limit=max_chars)`; on ANY exception (missing wsl.exe, driveless path, timeout) log `js_fetch_degraded reason=%s host=%s` (type name + host ONLY — NEVER `result.output` or page text) and return empty text; if `result.exit_code != 0` log the same safe fields and return empty text; else return `FetchedContent(url, host, result.output[:max_chars].strip())`. `__init__(self, *, sandbox: FetchSandbox | None = None, chromium_bin: str = "/opt/chromium_headless_shell/chrome-headless-shell", timeout_s: float = 45.0)`. Tests in `test_js_fetch.py`: stub-sandbox truncation, `argv`/`egress_domains`(==exact host)/`output_limit` forwarding, degrade-on-nonzero-exit, degrade-on-`FileNotFoundError`, degrade-on-`TimeoutError`, bad-URL→empty, `aclose()` no-op; plus the gated live happy-path smoke AND a gated chrome-path egress negative test (gate exactly as § below). — files: src/artemis/reachout/js_fetch.py, tests/reachout/test_js_fetch.py — done when: the `JsFetcher` AC bullets pass and the gated smokes report `skipped` without the env gate.
- [ ] Task 3: Add `FallbackFetcher` to `web_tool.py`, wire it, + tests. `FallbackFetcher(primary: Fetcher, secondary: Fetcher)`: `fetch` calls `primary.fetch(url, max_chars=max_chars)` (let `EgressDenied` propagate — do NOT catch it); if `content.text.strip()` return it, else return `secondary.fetch(...)`; `aclose` closes both (duck-typed, mirror `WebTool.aclose`). In `build_web_tool`, add `enable_js_fallback: bool = True`; build `fetcher = FallbackFetcher(TrafilaturaFetcher(egress), JsFetcher()) if enable_js_fallback else TrafilaturaFetcher(egress)` and pass it to `WebTool`. Import `JsFetcher`. Tests in `test_web_tool.py`: primary-empty→secondary (awaited once), primary-non-empty→secondary never awaited, primary-`EgressDenied`→propagates, `aclose` closes both, and the two `build_web_tool` wiring assertions. — files: src/artemis/reachout/web_tool.py, tests/reachout/test_web_tool.py — done when: the `FallbackFetcher`/`build_web_tool` AC bullets pass.
- [ ] Task 4: Write the provisioning runbook (ADR-040 is authored at planning time — this task only cross-references it). `js-fetcher-provisioning.md`: the exact steps from `poc/wsl2_browser/README.md` (playwright download of chromium → copy to `/opt/chromium_headless_shell` → `chmod -R a+rX`), the reserved binary path, the "chrome-headless-shell not full chrome" warning, AND a PINNED build + checksum: record the exact build (POC used Chrome-for-Testing 149.0.7827.55 / chrome-headless-shell build 1228) and add a `sha256sum` verify step against the copied binary so re-provisioning cannot silently pull a different build (FLAG 3 / supply-chain). — files: docs/technical/setup/js-fetcher-provisioning.md — done when: the runbook exists with the pin + checksum-verify step and links ADR-040.

## Wave plan
Wave 1: [Task 1, Task 4] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Live-smoke gate (exact)
Mirror `tests/capabilities/test_fetch_sandbox.py` precisely (do NOT invert the polarity):
```python
_JS_SMOKE = shutil.which("wsl.exe") is not None and os.environ.get("ARTEMIS_JS_SMOKE") == "1"

@pytest.mark.skipif(not _JS_SMOKE, reason="WSL2/chrome-headless-shell not provisioned (set ARTEMIS_JS_SMOKE=1)")
@pytest.mark.asyncio
async def test_live_js_fetch_reads_blocked_page() -> None: ...
```

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/reachout/render_script.py, src/artemis/reachout/js_fetch.py, tests/reachout/test_render_script.py, tests/reachout/test_js_fetch.py, docs/technical/setup/js-fetcher-provisioning.md |
| Modify | src/artemis/reachout/web_tool.py, tests/reachout/test_web_tool.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/` | lint + format gate |
| `uv run mypy` | full-project strict type-check |
| `uv run pytest -q` | full suite (live smokes auto-skip without `ARTEMIS_JS_SMOKE=1`) |
| `ARTEMIS_JS_SMOKE=1 uv run pytest tests/reachout/test_js_fetch.py -k live -o addopts=''` | BUILD-TIME live render + egress-negative smoke on the provisioned WSL2 host (run once, must pass) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | the created/modified files above + CHANGELOG.md |
| `git commit` | "feat(reachout): JS-rendering fallback fetcher (chrome-headless-shell in WSL2 isolate)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_JS_SMOKE` | opt-in gate for the live WSL/chrome render smoke (unset in normal runs) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | no new Python packages; chrome-headless-shell is provisioned out-of-band per the runbook |

## Specialist Context
### Security
Dispatched apex-security review (2026-07-03) — two BLOCKs, resolved:
- **BLOCK 1 (egress exact-match) — FIXED in Task 2.** The isolate's nginx `$ssl_preread_server_name` map is EXACT-string, so passing `registrable_domain(url)` (`wikipedia.org`) would never match Chrome's real SNI (`en.wikipedia.org`) → silent default-deny → empty on virtually every real page. `JsFetcher` now passes the exact URL hostname. Verified by the build-time live smoke (required to run, not left gated).
- **BLOCK 2 (`--no-sandbox` residual risk) — RESOLVED via spike PASS (2026-07-03).** The userns spike (`poc/wsl2_browser_userns/README.md`, owner-directed) proved Chrome's own unprivileged-userns + seccomp-bpf renderer sandbox engages nested inside the isolate under the existing `setpriv --bounding-set=-all` de-priv chain, with ZERO isolate change (verified via `/proc/<pid>/status` `Seccomp: 2` on renderers WITHOUT `--no-sandbox`, vs `Seccomp: 0` WITH it). So `render_script.py` OMITS `--no-sandbox`/`--disable-setuid-sandbox` (Task 1) → defense-in-depth (Chrome sandbox + the ADR-036 isolate), no residual-risk acceptance required, ADR-036 boundary untouched. ADR-040 records the sandbox as RETAINED.

Standing invariants: egress = the single exact first-party hostname (fail-closed; empty list ≠ open). Rendered output is UNTRUSTED and flows into the web tool's existing dual-LLM quarantine reader (ADR-009/037) before any synthesis — `JsFetcher` never reasons over the text, only truncates it. `JsFetcher` never logs page text or `result.output` (degrade log = `reason` + `host` only). Provisioning pins the binary build + verifies its checksum (supply-chain).

### Performance
~2s wall-clock per JS fetch (spike) vs 0.25s trafilatura — paid only on trafilatura-empty pages. Per-fetch memory ~150-165MB peak, within the 512MB cap. `output_limit=max_chars` bounds returned bytes.

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/reachout/js_fetch.py, render_script.py | module + `JsFetcher.fetch` docstrings (quarantine + degrade contract) |
| Setup | docs/technical/setup/js-fetcher-provisioning.md | create (provisioning runbook) |
| ADR | docs/technical/adr/ADR-040-js-rendering-fetcher.md | already written at planning (2026-07-03) — build only cross-references it |
| Changelog | CHANGELOG.md | add entry under Unreleased (JS-render fallback fetcher) |

## Acceptance Criteria
- [ ] `extract_text("<div>A</div><script>bad()</script><style>x</style><p>B</p>")` → verify returns `"A B"` (tags stripped, script/style skipped, whitespace collapsed).
- [ ] `extract_text("<p>keep</p><noscript>no1</noscript><template>tpl</template><p>me</p>")` → verify returns `"keep me"` (noscript + template content excluded).
- [ ] `JsFetcher(sandbox=stub).fetch("https://en.wikipedia.org/wiki/X", max_chars=20000)` with the stub returning `output="Z"*50000, exit_code=0` → verify returned `text` is 20000 chars, and the stub was called with `entrypoint="render.py"`, `argv==["https://en.wikipedia.org/wiki/X", "/opt/chromium_headless_shell/chrome-headless-shell"]`, `egress_domains==["en.wikipedia.org"]` (EXACT hostname, not `wikipedia.org`), `output_limit==20000`.
- [ ] Stub sandbox returns `exit_code=1` → verify `fetch` returns empty text (degrade), no exception.
- [ ] Stub sandbox raises `FileNotFoundError` (no wsl.exe) → verify `fetch` returns empty text (degrade), no exception.
- [ ] Stub sandbox raises `TimeoutError` → verify `fetch` returns empty text (degrade), no exception.
- [ ] `fetch("not a url")` where `urlsplit(url).hostname` is `None`/empty → verify returns empty-text `FetchedContent(url, "", "")`, no exception, and the sandbox is never called.
- [ ] `JsFetcher().aclose()` → verify it returns without raising (safe no-op).
- [ ] `FallbackFetcher(primary=empty, secondary=text).fetch(url)` → verify returns secondary text, secondary awaited exactly once; `FallbackFetcher(primary=text, secondary=spy).fetch(url)` → verify spy never awaited; `primary` raising `EgressDenied` → verify it propagates out of `FallbackFetcher.fetch`.
- [ ] `FallbackFetcher(primary, secondary).aclose()` with closable stubs → verify both `.aclose()` are awaited (mirror `test_aclose_closes_owned_clients`).
- [ ] `build_web_tool(tavily_api_key="k")` → verify `._fetcher` is a `FallbackFetcher` whose primary is `TrafilaturaFetcher` and secondary is `JsFetcher`; `build_web_tool(tavily_api_key="k", enable_js_fallback=False)` → verify `._fetcher` is a bare `TrafilaturaFetcher`.
- [ ] LIVE happy-path (gated `ARTEMIS_JS_SMOKE=1` on a provisioned host): `JsFetcher().fetch("https://en.wikipedia.org/wiki/Python_(programming_language)")` → verify `len(text) > 4000` AND `"python" in text.lower()` (title anchor — present in any revision; opt-in smoke so residual content-volatility flake is accepted).
- [ ] LIVE egress-negative (gated same): render a real page but pass a mismatched allowlist — `JsFetcher(...)` invoked so the sandbox gets `egress_domains=["example.com"]` while the URL host is `en.wikipedia.org` (e.g. construct via a thin subclass/monkeypatch of the host derivation, or call `FetchSandbox().run` directly with the render dir) → verify the result is empty/degraded (SNI mismatch → default-deny), proving the isolate blocks the chrome network path, not just curl.
- [ ] BUILD-TIME live run (not left permanently skipped): the two gated smokes above are executed once on this provisioned WSL2 host with `ARTEMIS_JS_SMOKE=1` and both pass — provision chrome-headless-shell per the runbook first if absent. (Guards against the exact-SNI class of silent-degrade bug.)
- [ ] `docs/technical/setup/js-fetcher-provisioning.md` exists → verify it has the playwright-download → copy → `chmod a+rX` steps, the pinned build (149.0.7827.55 / build 1228), a `sha256sum` verify step, the "chrome-headless-shell not full chrome" warning, and a link to ADR-040.
- [ ] `uv run mypy` clean; `uv run ruff check` clean; `uv run pytest -q` green with the live smokes reported `skipped` in a normal (un-gated) run.

## Progress
_(Coding mode writes here — do not edit manually)_

# ADR-040 — JS-rendering fallback fetcher (chrome-headless-shell in the WSL2 isolate)

- **Status:** **Accepted** — owner + planning, 2026-07-03.
- **Date:** 2026-07-03
- **Deciders:** owner + planning
- **Refines:** ADR-035 (reach-out capabilities) and ADR-037 (Pattern-A web tool) — adds a second `Fetcher` behind the existing `WebTool`. **Adopts unchanged:** ADR-036 (hardened WSL2 isolate — reused via `FetchSandbox.run`), ADR-009 (untrusted-content Dual-LLM quarantine — rendered text flows through the existing `WebTool` reader/synth). Does not re-decide any of that substrate.
- **Design basis:** the `poc/wsl2_browser/` feasibility spike + the `poc/wsl2_browser_userns/` sandbox spike (2026-07-03); live audit of `src/artemis/reachout/{web_tool,fetch,egress}.py` and `src/artemis/capabilities/{sandbox_wsl2,fetch_sandbox}.py`; three dispatched apex-security/apex-testing spec reviews (2026-07-03).

## Context

`WebTool` (ADR-037) fetches pages through a `Fetcher` protocol; the only implementation,
`TrafilaturaFetcher`, is a host-side httpx+trafilatura fetch. It returns empty text for pages that are
JS-rendered or bot/UA-blocked (the spike's Wikipedia case: a direct `httpx.get` 403s, trafilatura
extracts 0 chars). The `poc/wsl2_browser/` spike proved headless `chrome-headless-shell` can render
such pages **inside the existing ADR-036 isolate** (netns + nginx SNI-allowlist + de-priv uid 4000 +
cgroup caps), egress-contained, ~2 s per fetch, and read the full article. This ADR turns that spike
into a shipped fetcher.

## Decision

| # | Decision | Statement |
|---|----------|-----------|
| 1 | **Fallback, not replacement** | Keep `TrafilaturaFetcher` as the fast primary (~0.25 s, host-side); add a JS-render fetcher as a **fallback fired only when trafilatura returns empty text**. A new `FallbackFetcher(primary, secondary)` composes them. Rejected replacing trafilatura outright (owner, 2026-07-03): ~5–8× slower on every query and breaks the web tool on any host where WSL2/chrome is absent. |
| 2 | **Render inside the ADR-036 isolate, reusing `FetchSandbox`** | `JsFetcher` stages a stdlib render script and runs it via `FetchSandbox.run` (the sanctioned "dumb egress-allowlisted fetch pipe", ADR-035 Option B) — no new isolation mechanism. Untrusted rendered text is returned raw and flows into `WebTool`'s existing dual-LLM quarantine reader (ADR-009/037) before any synthesis; `JsFetcher` never reasons over it. |
| 3 | **Chrome's own sandbox is RETAINED — no `--no-sandbox`** | The `poc/wsl2_browser_userns/` spike proved Chrome's unprivileged-userns + seccomp-bpf renderer sandbox engages nested inside the isolate under the existing `setpriv --bounding-set=-all --inh-caps=-all` de-priv chain, with **zero** isolate change (verified: renderer procs show `Seccomp: 2` WITHOUT `--no-sandbox`, `Seccomp: 0` WITH it). `render_script.py` therefore OMITS `--no-sandbox`/`--disable-setuid-sandbox` → defense-in-depth (Chrome sandbox **+** the isolate). This reverses the base spike's "kept `--no-sandbox` for robustness" note, which actually disabled the sandbox. Resolves apex-security BLOCK 2 with no residual-risk acceptance. |
| 4 | **Egress = the exact first-party hostname** | `JsFetcher` passes the URL's exact hostname (e.g. `en.wikipedia.org`), NOT `registrable_domain()` (`wikipedia.org`). The isolate's nginx `$ssl_preread_server_name` map is EXACT-match, so the eTLD+1 would never match Chrome's real SNI and would silently default-deny every real subdomain (apex-security BLOCK 1). First-party host only — asset/CDN subdomains are not needed for text (base spike check #4). |
| 5 | **`chrome-headless-shell` pinned, never full `chrome`** | Full `chrome` opens background TLS to Google infra that the SNI-allowlist blocks, and the retry churn blows the timeout (base spike finding #1). The provisioning runbook pins the exact build + verifies a `sha256sum` (supply-chain, apex-security FLAG 3). |
| 6 | **Graceful degrade everywhere** | Any failure (missing wsl.exe, driveless host path, timeout, nonzero exit, unresolvable host) → `JsFetcher` returns empty text (logging `reason`+`host` only, never page text). `WebTool.answer` already skips empty-text sources, so on a non-provisioned host the net result equals trafilatura-alone — no crash, no regression. Output cap raised via the `js-fetch-output-limit` prerequisite (`FetchSandbox`'s 4000-char cap → `max_chars`). |

## Consequences

**Two file-disjoint specs (ADR-029), sequential:**
- `js-fetch-output-limit` — parametrizes the isolate output cap (`capabilities/*`). Prerequisite.
- `js-rendering-fetcher` — `render_script.py` + `JsFetcher` + `FallbackFetcher` wiring + provisioning runbook (`reachout/*`). Depends on the above.

**Positive:** JS/bot-blocked pages become readable; the fast path is untouched for the common case;
security posture *improves* (Chrome sandbox now engaged, where the base spike ran unsandboxed).

**Costs / known limits (recorded so they are not reopened blind):**
- ~2 s per JS fetch vs 0.25 s trafilatura — paid only on trafilatura-empty pages.
- **Cross-domain redirects are blocked in-isolate** (exact-SNI allowlist = the single first-party host); a page that redirects off-host renders empty and degrades. Acceptable (fail-closed).
- **Asset/CDN domains are not fetched** — text extraction only; images/rendered-layout are out of scope.
- Requires one-time WSL2 provisioning of `chrome-headless-shell` (runbook); absent it, degrades to trafilatura-only.
- A build-time live smoke (render happy-path + a chrome-path egress-negative check) MUST be run once on the provisioned host — not left permanently `ARTEMIS_JS_SMOKE`-gated — to catch the exact-SNI class of silent-degrade bug.

## Alternatives considered
- **Replace trafilatura with always-JS** — rejected (decision 1): slower on every query, breaks on non-provisioned hosts.
- **Fallback also on "thin" text (<N chars)** — deferred: more false JS triggers; empty-only is the cheap, unambiguous signal. Revisit if partial-extraction pages prove common.
- **Accept `--no-sandbox` with the isolate as sole compensating control** — the owner instead directed the userns spike (decision 3), which passed, so this acceptance was not needed.

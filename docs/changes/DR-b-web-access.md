---
spec: dr-b-web-access
status: ready
token_profile: lean
autonomy_level: L3
---

# Spec: DR-b — Web access (search + fetch + controlled egress)

**Identity:** Builds `artemis.research` web-access ports + adapters: `SearchProvider` (Brave default, Tavily fallback), `Fetcher` (trafilatura default, Jina Reader + Playwright as upgrades), and an `EgressPolicy` allowlist every outbound call passes through (default-deny, just-in-time allow for search-vouched domains, all denials logged via OBS).
→ why: see docs/technical/adr/ADR-009-untrusted-content-and-deep-research.md (Decision 5) · docs/research/2026-06-08-search-providers.md.

<!-- Split rule note: 4 src (search, fetch, egress, __init__) + 1 test, 0 modifies. Justified atomic grouping: search + fetch + the egress guard they both pass through are one cohesive web-access layer behind two ports; egress.py is tiny and shared by both. Flagged per rules. -->

## Assumptions
- M7-c's grounding gate already needs a **registrable-domain (eTLD+1)** helper (its "distinct registrable domain" check). DR-b reuses that helper for `FetchedContent.domain`. If M7-c did not expose one reusably, coding adds `tldextract` and defines `registrable_domain(url)` once, shared. → impact: Caution (a duplicated/incorrect eTLD+1 would let two subdomains count as independent — flag the shared-helper reconciliation).
- API keys (`BRAVE_API_KEY`, `TAVILY_API_KEY`, optional `JINA_API_KEY`) are **secrets resolved by the caller** (env or Keychain) and passed to the adapter constructor — adapters never read env directly (testability + no secret in code). → impact: Stop.
- All outbound HTTP uses lazy `httpx` (already a dep). `trafilatura` is a NEW runtime dep. Playwright fetching is via the existing Playwright MCP seam (optional adapter). → impact: Low.
- `ModelPort.complete`/research queries are non-sensitive (enforced upstream by M7-c); the search query text is sent to a third-party search API — acceptable because non-sensitive. → impact: Stop (the non-sensitive precondition is what makes any egress allowed at all).

Simplicity check: considered a single combined search+extract vendor (Tavily) as the only path — rejected; ports keep Brave (cheapest/ZDR) + local trafilatura (private/free) as the default, with Tavily/Jina/Playwright swappable. Considered reading API keys from env inside adapters — rejected (untestable + secret-coupling); keys are constructor args.

## Prerequisites
- Specs complete first: M0-a (`config`/`paths`), M7-c (`grounding_gate` + its eTLD+1 helper — reuse).
- Environment setup required: `uv add trafilatura`; `BRAVE_API_KEY` (+ optional `TAVILY_API_KEY`/`JINA_API_KEY`) available to the runtime (Keychain/env).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/research/__init__.py | create | re-exports (`SearchProvider`, `SearchHit`, `BraveSearch`, `TavilySearch`, `Fetcher`, `FetchedContent`, `TrafilaturaFetcher`, `JinaFetcher`, `PlaywrightFetcher`, `EgressPolicy`, `EgressDenied`, `registrable_domain`) |
| /Users/artemis-build/artemis/src/artemis/research/egress.py | create | `EgressPolicy` + `EgressDenied` |
| /Users/artemis-build/artemis/src/artemis/research/search.py | create | `SearchHit` + `SearchProvider` + `BraveSearch` + `TavilySearch` + `SearchError` |
| /Users/artemis-build/artemis/src/artemis/research/fetch.py | create | `FetchedContent` + `Fetcher` + `TrafilaturaFetcher` + `JinaFetcher` + `PlaywrightFetcher` + `registrable_domain` + `FetchError` |
| /Users/artemis-build/artemis/tests/test_research_web.py | create | egress allow/deny + log, Brave/Tavily parse (mocked httpx), trafilatura extract + truncation, domain eTLD+1, fetch degrade |

## Tasks
- [ ] Task 1: Controlled-egress allowlist + SSRF guard — files: `/Users/artemis-build/artemis/src/artemis/research/egress.py` —
  - `class EgressDenied(Exception)`.
  - `def block_private_ip(url: str) -> None` **(resolves BLOCK — SSRF):** reject non-`https` URLs; resolve the host via `socket.getaddrinfo`; for EVERY resolved address, `ipaddress.ip_address(...)` and raise `EgressDenied` if `.is_private or .is_loopback or .is_link_local or .is_reserved or .is_unspecified or .is_multicast` (blocks `169.254.169.254` cloud-metadata, RFC-1918, `::1`, `0.0.0.0`, etc.). Log a WARNING on block (host only, never the full URL).
  - `class EgressPolicy` constructed with `(static_hosts: frozenset[str])`. `def permit(self, domain: str) -> None`: **validate (resolves FLAG)** `domain` is a bare registrable domain (no scheme/path/port — via `registrable_domain`); raise `ValueError` otherwise; then add to the per-instance dynamic allow set (just-in-time authorization for a domain from a trusted `SearchHit`). `def check(self, url: str) -> None`: parse host; if host in neither static nor dynamic set → WARNING (`extra={"host": host}`) + raise `EgressDenied`; **then call `block_private_ip(url)`** (allowlist AND IP-range must both pass). `def reset_dynamic(self) -> None` clears the dynamic set. **Caller contract (documented in the class docstring):** the engine (DR-c) MUST call `reset_dynamic()` at the start of each research cycle so a per-query permit does not persist across cycles.
  — done when: `uv run mypy --strict src` passes; `check` on an unlisted host raises `EgressDenied`+logs; after `permit("example.com")`, `check("https://example.com/p")` passes a public IP but a host resolving to `169.254.169.254`/`127.0.0.1`/an RFC-1918 address raises `EgressDenied` even when permitted; `permit("https://x.com/p")` raises `ValueError`; a static host passes without `permit`.

- [ ] Task 2: Search providers — files: `/Users/artemis-build/artemis/src/artemis/research/search.py` —
  - frozen dataclass `SearchHit { title: str, url: str, snippet: str }`. `class SearchError(Exception)`.
  - `class SearchProvider(Protocol)`: `async def search(self, query: str, *, count: int = 8) -> list[SearchHit]: ...`.
  - `class BraveSearch` implementing it, constructed with `(api_key: str, egress: EgressPolicy, *, base_url: str = "https://api.search.brave.com/res/v1/web/search", http: httpx.AsyncClient | None = None)`: `egress.check(base_url)`; lazy `httpx` GET with header `X-Subscription-Token: api_key`, param `q=query`, `count=count`; on non-2xx raise `SearchError`; parse `web.results[]` → `SearchHit(title, url, snippet=description)`. Document Brave's response shape.
  - `class TavilySearch` implementing it, constructed with `(api_key: str, egress: EgressPolicy, *, base_url="https://api.tavily.com/search", http=None)`: POST `{"api_key":..., "query":..., "max_results":count}`; parse `results[]` → `SearchHit(title, url, snippet=content)`.
  - Both call `egress.check` on their API host before the request. **Key hygiene (resolves FLAG):** construct the httpx client with no request/transport debug logging; the `research` obs logger is bounded to WARNING+; the key (Brave `X-Subscription-Token` header / Tavily `api_key` body field) is NEVER placed in a log call — add a request event hook that strips auth headers before any logging.
  — done when: `uv run mypy --strict src` passes; with a mocked httpx returning a canned Brave payload, `BraveSearch(...).search("q", count=3)` returns 3 `SearchHit`s; a 429 raises `SearchError`; with a 32-hex test key, the key string appears in NO captured log line at any level (`caplog`).

- [ ] Task 3: Fetchers + registrable domain — files: `/Users/artemis-build/artemis/src/artemis/research/fetch.py` —
  - `def registrable_domain(url: str) -> str`: eTLD+1 (reuse M7-c's helper if exposed; else `tldextract`). frozen dataclass `FetchedContent { url: str, domain: str, text: str }`. `class FetchError(Exception)`.
  - `class Fetcher(Protocol)`: `async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent: ...`.
  - `class TrafilaturaFetcher` constructed with `(egress: EgressPolicy, *, http=None, timeout: float = 8.0, max_bytes: int = 5_000_000)`: `egress.check(url)`; lazy `httpx` client with `follow_redirects=False` **(resolves BLOCK — redirects)** and the fixed `timeout`; GET; **on a 3xx, extract `Location`, call `egress.check(location)` (allowlist + SSRF) and only then follow manually** (re-checking each hop). **Stream the body and read at most `max_bytes`** (resolves FLAG — response-size DoS); `trafilatura.extract(html)` → clean text; truncate to `max_chars`; `domain = registrable_domain(final_url)`; return `FetchedContent(final_url, domain, text)`. On any error/timeout/oversize/empty-extract → `FetchedContent(url, domain, text="")` + one WARNING (degrade-don't-crash).
  - `class JinaFetcher` constructed with `(egress, *, api_key=None, base="https://r.jina.ai/", http=None, timeout=10.0)`: **validate `url` is a well-formed `https://` absolute URL and run `egress.check(url)` (allowlist + SSRF on the target) BEFORE building the request** (resolves FLAG — URL construction); `egress.check(base)`; GET `f"{base}{quote(url, safe='')}"` (optional `Authorization: Bearer`); `follow_redirects=False`; truncated markdown text; same degrade contract.
  - `class PlaywrightFetcher` constructed with `(egress, *, timeout=15.0)`: documented seam over the Playwright MCP for JS-locked pages; `egress.check(url)` (allowlist + SSRF); same `FetchedContent`/degrade contract. (Off-hardware tests use a fake.)
  — done when: `uv run mypy --strict src` passes; with a mocked httpx returning HTML, `TrafilaturaFetcher(...).fetch(url, max_chars=100)` returns `FetchedContent` with non-empty `text` ≤100 chars and `domain == registrable_domain(url)`; a **302 redirect to an internal IP is denied** (re-checked, not followed); a body exceeding `max_bytes` and a timeout both degrade to empty `text` without raising.

- [ ] Task 4: Package surface — files: `/Users/artemis-build/artemis/src/artemis/research/__init__.py` — re-export the names above with `__all__` (DR-c extends it). — done when: `uv run python -c "from artemis.research import SearchProvider, BraveSearch, TavilySearch, Fetcher, TrafilaturaFetcher, EgressPolicy, registrable_domain"` exits 0.

- [ ] Task 5: Tests — files: `/Users/artemis-build/artemis/tests/test_research_web.py` — typed pytest with mocked `httpx` (`httpx.MockTransport`) + a real `EgressPolicy`:
  - egress + SSRF: unlisted host → `EgressDenied`+WARNING; `permit` then allowed; a permitted host resolving (monkeypatched `getaddrinfo`) to `169.254.169.254`/`127.0.0.1`/`10.0.0.1` → `EgressDenied`; non-`https` → denied; `permit("https://x/p")` → `ValueError`; `reset_dynamic` re-denies.
  - search: Brave/Tavily canned payloads → hits; 429 → `SearchError`; a 32-hex test key appears in NO captured log line (`caplog`, all levels).
  - fetch: trafilatura over canned HTML → clean text ≤ `max_chars`; `domain` is eTLD+1 (two subdomains → same `domain`); a **302 to an internal IP → denied (not followed)**; a body over `max_bytes` → empty text, no raise; a timeout → empty text, no raise.
  — done when: `uv run pytest -q tests/test_research_web.py` passes AND `uv run mypy --strict src tests/test_research_web.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/research/__init__.py, /Users/artemis-build/artemis/src/artemis/research/egress.py, /Users/artemis-build/artemis/src/artemis/research/search.py, /Users/artemis-build/artemis/src/artemis/research/fetch.py, /Users/artemis-build/artemis/tests/test_research_web.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv add trafilatura` | New runtime dep (HTML→clean-text extraction); verify package name + maintainer before adding |
| `uv run pip-audit` | Supply-chain gate on trafilatura + its transitive deps (lxml/courlan/htmldate); must exit 0 with no known vulns |
| `uv run mypy --strict src tests/test_research_web.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_research_web.py` | Test gate (egress, search parse, fetch extract — all mocked, no real network) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/research/{__init__,egress,search,fetch}.py, tests/test_research_web.py, pyproject.toml, uv.lock |
| `git commit` | "feat: DR-b web access (SearchProvider Brave/Tavily + Fetcher trafilatura/Jina/Playwright + controlled egress)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `BRAVE_API_KEY` | Brave Search API auth (resolved by caller from Keychain/env, passed to adapter) |
| `TAVILY_API_KEY` | Tavily fallback auth (optional) |
| `JINA_API_KEY` | Jina Reader auth (optional) |

### Network
| Action | Purpose |
|--------|---------|
| `uv add trafilatura` | Package install |
| HTTPS GET/POST to Brave/Tavily/Jina API hosts + fetched result domains | The sanctioned research egress — gated by `EgressPolicy` (default-deny, just-in-time allow), all denials logged. NON-sensitive queries only. Real network is GATED to on-hardware; tests mock httpx. |

## Specialist Context
### Security
- **[RESOLVED — was BLOCK] SSRF:** `block_private_ip` resolves every host and rejects private/loopback/link-local/reserved/metadata addresses; `check` runs it after the allowlist, so a permitted domain resolving to an internal IP is still denied.
- **[RESOLVED — was BLOCK] Redirect bypass:** fetchers use `follow_redirects=False` and re-run `egress.check` (allowlist + SSRF) on each `Location` hop before following.
- **[RESOLVED — was FLAG] `permit` abuse:** validates its arg is a bare registrable domain (raises `ValueError` on a URL/path/port).
- **[RESOLVED — was FLAG] Jina URL construction:** the target is validated (https-absolute, SSRF-checked) and percent-encoded before building the Jina request.
- **[RESOLVED — was FLAG] Key leakage + supply chain:** auth headers stripped pre-log, obs logger WARNING+, `caplog` test asserts no key; `pip-audit` gates trafilatura's dep tree.
- **[RESOLVED — was FLAG] Response-size DoS:** `max_bytes` streaming cap on fetch.
- **Non-sensitive precondition:** the query reaching a third-party API is non-sensitive by upstream enforcement (M7-c); DR-b trusts that boundary (DR-c must never call it with a sensitive-derived query — enforced in DR-c).

### Performance
- Fixed timeouts on every fetch/search (an un-timed call would hang the idle loop). `max_chars` bounds extracted text → bounds downstream clerk tokens.

### Accessibility
(none — headless.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/research/{egress,search,fetch}.py | Type + docstring all exports; document the egress default-deny + just-in-time model, the per-fetch timeout requirement, the caller-resolves-secrets rule, and the eTLD+1 reuse/reconciliation with M7-c |
| Changelog | CHANGELOG.md | Add entry under Unreleased: web-access layer (search/fetch/egress) |
| ADR | docs/technical/adr/ADR-009-untrusted-content-and-deep-research.md | Already written — reference only |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_research_web.py` → verify: exit 0 (incl. `SearchProvider`/`Fetcher` Protocol conformance of the adapters).
- [ ] Run `uv run python -c "from artemis.research import BraveSearch, TavilySearch, TrafilaturaFetcher, EgressPolicy, registrable_domain"` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_research_web.py` → verify: egress denies unlisted hosts (+logs); a permitted host resolving to a private/metadata IP is still denied; non-https denied; `permit` rejects a non-domain; a 302 to an internal IP is not followed; over-`max_bytes` and timeout degrade to empty text; Brave/Tavily parse canned payloads and a 429 raises `SearchError`; trafilatura extracts/truncates + eTLD+1; no API key in any captured log.
- [ ] Run `uv run pip-audit` → verify: exit 0, no known vulnerabilities in trafilatura's dependency tree.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_

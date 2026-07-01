---
spec: reachout-web-primitives
status: ready
token_profile: balanced
autonomy_level: L2
risk: high
coder_effort: high
domain: security
cross_model_review: true
---

# Spec: Reach-out web primitives (egress guard + search + fetch)

**Identity:** Fresh v2 `src/artemis/reachout/` package — the SSRF-guarded egress policy, a `SearchProvider` adapter, and a clean-text `Fetcher` that together form the trusted host-side fetch foundation for the ADR-035 Pattern-A web tool and Pattern-B aggregation reader tier.
→ why: see docs/technical/adr/ADR-035-reach-out-capabilities.md (decision 2 Option B, decision 4 quarantined reader, model/role map).

<!-- Build fresh: v1 `src/artemis/research/{egress,search,fetch}.py` are DESIGN REFERENCE ONLY (do not
     restore). Reproduce the egress SSRF/private-IP guard near-verbatim (battle-tested security);
     everything else is fresh, minimal v2 code on the v2 substrate (stdlib logging, pydantic, httpx). -->

## Assumptions
- `httpx>=0.27` is already a project dependency (pyproject.toml line 9; used by transport/telegram.py) — no new HTTP client needed → impact: Low.
- v2 uses stdlib `logging` (`_log = logging.getLogger(__name__)`, per capabilities/store.py), NOT the v1 `artemis.obs.get_logger` helper — this package follows the stdlib convention → impact: Caution (wrong import = build fails).
- Text extraction uses **`trafilatura`** (new optional dep) rather than a hand-rolled readability pass. Why: article extraction is a correctness/quality surface feeding the quarantined reader (ADR-035 d4); trafilatura is the battle-tested extractor the authoritative prior spec (`docs/changes/done/DR-b-web-access.md`) already selected, and a minimal hand-rolled readability heuristic would degrade extract quality for the reader tier while still pulling an HTML parser. `tldextract` (needed for `registrable_domain` eTLD+1) is a trafilatura transitive dep, so listing it explicitly adds no new supply-chain surface → impact: Caution (dep add — see Permissions typosquat/pip-audit note).
- The eTLD+1 helper uses `tldextract.extract(url).registered_domain` (the real attribute, per DR-b-web-access.md) — NOT `.top_domain_under_public_suffix` (which does not exist on the `ExtractResult`) → impact: Stop (a wrong attribute is on the guard's `check()`/`permit()` critical path and would `AttributeError` at runtime).
- Connect-time DNS re-resolution is a live rebinding vector: `block_private_ip` validates a resolved IP but stock `httpx` re-resolves at connect time. This spec **pins the validated IP** (connects to the exact address the guard validated, preserving Host header + TLS SNI = the original hostname) rather than accepting the residual. DR-b-web-access.md did NOT pin (it relied on `follow_redirects=False` + per-hop re-check and left connect-time rebinding as a silent residual); v2 closes it → impact: Stop (unpinned, a `permit()`-vouched domain can flip to a metadata IP between validation and connect).
- Tests are unit-only via `httpx.MockTransport` (matching tests/test_telegram.py); no live network. DNS is exercised by monkeypatching `socket.getaddrinfo` to return loopback/private/metadata/IPv4-mapped-IPv6 addresses → impact: Low.
- `EgressPolicy` is caller-constructed with a static host allowlist; API keys are always caller-supplied and NEVER read from `os.environ` inside these adapters (secrets stay in the keychain path, ADR-035 §6) → impact: Stop (env-read here would leak the trust boundary).

Simplicity check: Considered a single `web.py` module. Rejected — the SSRF guard is a security core that must be independently testable and reused by both search and fetch; three small files (egress/search/fetch) is the leanest set that keeps the guard isolated and the two adapters swappable behind their Protocols. No Fetcher-variant zoo (v1 had Jina/Playwright/Trafilatura) — v2 ships ONE fetcher; other loci are future swaps behind the same Protocol.

## Prerequisites
- Specs that must be complete first: none.
- Environment setup required: none (deps installed by the build via `uv sync`).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| pyproject.toml | modify | add `trafilatura` + `tldextract` to `[project].dependencies`; add `pip-audit` to `[dependency-groups].dev` |
| src/artemis/reachout/__init__.py | create | package marker; re-export `EgressPolicy`, `EgressDenied`, `SearchHit`, `SearchProvider`, `TavilySearch`, `FetchedContent`, `Fetcher` |
| src/artemis/reachout/egress.py | create | SSRF/private-IP guard + `EgressPolicy` (allowlist + port lock + IP pinning + bounded dynamic set) + `registrable_domain` + `EgressDenied` |
| src/artemis/reachout/search.py | create | `SearchHit` (pydantic), `SearchProvider` Protocol, `TavilySearch` adapter (body-key redaction) |
| src/artemis/reachout/fetch.py | create | `FetchedContent` (pydantic), `Fetcher` Protocol, trafilatura clean-text fetcher (pinned-IP client, `follow_redirects=False` enforced, content-type gate) |
| tests/reachout/__init__.py | create | test package marker |
| tests/reachout/test_egress.py | create | eTLD+1 value + SSRF matrix (monkeypatched `getaddrinfo`, incl. IPv4-mapped IPv6) + port-lock + `pin` rebinding + `permit`/`reset_dynamic` + `_MAX_DYNAMIC` cap |
| tests/reachout/test_search.py | create | `TavilySearch` over `httpx.MockTransport`; api_key absent from header AND body snapshots; egress-checked |
| tests/reachout/test_fetch.py | create | fetcher over `httpx.MockTransport`; reject `follow_redirects=True` client; content-type gate; pinned-IP connect; bounded bytes; redirect-to-internal denied; degrade-to-empty |

## Tasks
- [ ] Task 1: Add deps + scaffold — files: pyproject.toml, src/artemis/reachout/__init__.py, tests/reachout/__init__.py — done when: `uv sync` succeeds, `python -c "import artemis.reachout"` exits 0, and `uv run pip-audit` exits 0 over the new tree.
- [ ] Task 2: SSRF guard + `EgressPolicy` (allowlist, port-lock, IP pinning, bounded dynamic set, eTLD+1) — files: src/artemis/reachout/egress.py, tests/reachout/test_egress.py — done when: `uv run pytest -q tests/reachout/test_egress.py` passes the full accept/reject matrix below (incl. eTLD+1 value, IPv4-mapped-IPv6, non-443 port, missed-reset cap).
- [ ] Task 3: `SearchProvider` + `TavilySearch` — files: src/artemis/reachout/search.py, tests/reachout/test_search.py — done when: `uv run pytest -q tests/reachout/test_search.py` passes; test asserts the api_key appears in NO hook-visible snapshot of headers OR body.
- [ ] Task 4: `Fetcher` clean-text fetcher — files: src/artemis/reachout/fetch.py, tests/reachout/test_fetch.py — done when: `uv run pytest -q tests/reachout/test_fetch.py` passes, including pinned-IP connect, rejection of an injected `follow_redirects=True` client, non-`text/html` short-circuit, bounded-bytes rejection, and degrade-to-empty on extraction failure.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3, Task 4]
<!-- Task 2 (egress) is imported by both search and fetch, so it lands before Wave 3. Tasks 3 and 4
     are file-disjoint and both depend only on egress — they run in parallel. -->

## Exact changes

### egress.py — reproduce the DR-b SSRF guard, v2-native (stdlib logging) + rebinding-pin + port-lock
```python
"""Controlled outbound egress for reach-out web adapters (ADR-035 decision 2)."""
from __future__ import annotations
import ipaddress
import logging
import socket
from urllib.parse import urlparse
import tldextract

_log = logging.getLogger(__name__)
_MAX_DYNAMIC = 64  # FLAG 8: hard cap so a missed reset_dynamic() cannot grow egress unboundedly


class EgressDenied(Exception):  # noqa: N818 — named without an Error suffix by design
    """Raised when an outbound URL is outside the egress policy."""


def registrable_domain(url: str) -> str:
    """Return the eTLD+1 registrable domain for a URL or host (BLOCK 1: .registered_domain)."""
    return tldextract.extract(url).registered_domain


def _validated_ip(host: str) -> ipaddress._BaseAddress:
    """Resolve host, reject any non-public address, return the ONE address to pin.

    Covers IPv4 + IPv6, incl. IPv4-mapped IPv6 (::ffff:127.0.0.1) via .ipv4_mapped
    unwrap before the range test (note 9)."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise EgressDenied("host resolution failed") from exc
    chosen: ipaddress._BaseAddress | None = None
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError as exc:
            raise EgressDenied("host resolved to an invalid address") from exc
        probe = ip
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            probe = mapped  # unwrap ::ffff:a.b.c.d before range checks
        if (
            probe.is_private or probe.is_loopback or probe.is_link_local
            or probe.is_reserved or probe.is_unspecified or probe.is_multicast
        ):
            _log.warning("egress_blocked host=%s addr=%s", host, ip)
            raise EgressDenied("host resolved to a blocked address")
        chosen = chosen or ip
    if chosen is None:
        raise EgressDenied("host did not resolve")
    return chosen


def block_private_ip(url: str) -> None:
    """Reject non-HTTPS URLs and hosts resolving to private/reserved addresses (allowlist-agnostic)."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        _log.warning("egress_blocked host=%s", host or "")
        raise EgressDenied("egress requires an https URL with a host")
    _validated_ip(host)


class EgressPolicy:
    """Default-deny allowlist. Static hosts are exact API hosts; `permit` adds
    registrable domains vouched for the current cycle. Callers MUST `reset_dynamic`
    at the start of each cycle so per-query permits do not persist; a hard cap
    (`_MAX_DYNAMIC`) bounds the set even if a reset is missed."""

    def __init__(self, static_hosts: frozenset[str]) -> None:
        # static entries are exact "host" or "host:port"; a bare host implies :443 only
        self._static_hosts = {h.lower() for h in static_hosts}
        self._dynamic_domains: set[str] = set()

    def permit(self, domain: str) -> None:
        parsed = urlparse(domain)
        if (
            not domain or parsed.scheme or parsed.netloc or parsed.path != domain
            or parsed.params or parsed.query or parsed.fragment
            or any(c in domain for c in "/:@[]")
        ):
            raise ValueError("permit expects a bare registrable domain")
        normalized = domain.strip().lower().rstrip(".")
        if normalized != registrable_domain(f"https://{normalized}"):
            raise ValueError("permit expects a bare registrable domain")
        if normalized not in self._dynamic_domains and len(self._dynamic_domains) >= _MAX_DYNAMIC:
            _log.warning("egress_permit_capped size=%d", len(self._dynamic_domains))
            raise EgressDenied("dynamic egress set is full — reset_dynamic() was not called")
        self._dynamic_domains.add(normalized)

    def _check_allow_and_port(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port  # None when absent
        rd = registrable_domain(url)
        host_port = f"{host}:{port}" if port is not None else host
        # FLAG 5: dynamic (search-vouched) domains are 443-only; a non-443 port must be an
        # explicit host:port in the static allowlist.
        if port not in (None, 443):
            if host_port not in self._static_hosts:
                _log.warning("egress_denied host=%s port=%s", host, port)
                raise EgressDenied("non-443 port is not explicitly allowlisted")
            return
        if host in self._static_hosts or host_port in self._static_hosts:
            return
        if rd in self._dynamic_domains:
            return
        _log.warning("egress_denied host=%s", host)
        raise EgressDenied("host is not allowed for egress")

    def check(self, url: str) -> None:
        """Allowlist + port-lock + SSRF, discarding the pinned IP (search path)."""
        self._check_allow_and_port(url)
        block_private_ip(url)

    def pin(self, url: str) -> str:
        """Allowlist + port-lock + SSRF; return the validated IP string to CONNECT to.

        BLOCK 2 (DNS-rebinding TOCTOU): the caller must connect to this exact address
        while keeping Host header + TLS SNI = the original hostname, so the connect-time
        socket cannot be re-resolved to a private/metadata IP after validation."""
        self._check_allow_and_port(url)
        host = urlparse(url).hostname or ""
        return str(_validated_ip(host))

    def reset_dynamic(self) -> None:
        self._dynamic_domains.clear()
```
Note: `check()`/`pin()` enforce allowlist + port-lock BEFORE the DNS resolve-then-validate. The fetcher calls `pin()` per hop and connects to the returned IP (see fetch.py). Static allowlist entries are matched on the raw host (exact API endpoints); dynamic `permit()`-ed entries are matched on eTLD+1 so `www.example.com` is covered when `example.com` was permitted (DR-b B1).

### search.py — fresh `SearchHit` (pydantic) + `SearchProvider` + `TavilySearch`
- `SearchHit(BaseModel)`: `title: str`, `url: str`, `snippet: str` (frozen via `model_config = ConfigDict(frozen=True)`).
- `SearchProvider(Protocol)`: `async def search(self, query: str, *, count: int = 8) -> list[SearchHit]: ...`
- `TavilySearch.__init__(self, api_key: str, egress: EgressPolicy, *, base_url: str = "https://api.tavily.com/search", http: httpx.AsyncClient | None = None)`.
  - `search`: `self._egress.check(self._base_url)`, POST `{"api_key": self._api_key, "query": query, "max_results": count}`, non-2xx → raise `SearchError`, map `results[].{title,url,content→snippet}` to `SearchHit`.
  - **Key hygiene (BLOCK 3 — body AND headers).** Tavily carries the key in the JSON body, so header-only scrubbing is insufficient. Install a request event hook `_redact_secrets_for_hooks(request)` that writes a `request.extensions["artemis_safe_snapshot"]` holding a redacted view of BOTH: (a) headers minus `authorization`/`x-subscription-token`, and (b) the parsed JSON body with any `api_key`/`token`/`authorization` field replaced by `"***"`. Any diagnostic/logging must read that snapshot, never the raw `request.content`/`request.headers`. The key string must appear in NO hook-visible snapshot.
  - NEVER read `os.environ` — key is caller-supplied. Brave is a future swap behind the same `SearchProvider` Protocol (do not build it here).

### fetch.py — fresh `FetchedContent` (pydantic) + `Fetcher` + trafilatura fetcher
- `FetchedContent(BaseModel, frozen)`: `url: str`, `domain: str`, `text: str`.
- `Fetcher(Protocol)`: `async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent: ...`
- `TrafilaturaFetcher.__init__(self, egress: EgressPolicy, *, http=None, timeout=8.0, max_bytes=5_000_000)`.
  - **FLAG 4 — no auto-follow.** The internal client MUST be built with `follow_redirects=False` (the per-hop `egress` re-check only holds if httpx never auto-follows). If an `http` client is injected, verify `http.follow_redirects is False`; if it is `True`, raise `ValueError` at construction (fail closed) — do not silently accept it.
  - **BLOCK 2 — pinned-IP connect.** Build the client over a small `_PinnedTransport(egress, inner=httpx.AsyncHTTPTransport())`: for each request it calls `ip = egress.pin(str(request.url))`, rewrites the connection target to that literal `ip`, and sets `request.extensions["sni_hostname"] = original_host` + `request.headers["Host"] = original_host` so TLS SNI and certificate verification still use the hostname while the socket connects only to the guard-validated address. This closes the resolve→connect rebinding window because `pin()` and the actual connection use the same address.
  - `fetch`: bounded manual redirect loop (≤6 hops); on each hop the transport's `pin()` runs (allowlist + port-lock + SSRF); on a 3xx, read `Location`, `egress.check(location)`, then loop (never auto-followed). Read body with a `max_bytes` streaming cap (degrade on overflow).
  - **FLAG 6 — content-type gate.** Before calling `trafilatura.extract`, short-circuit to a degraded empty result unless the response `Content-Type` starts with `text/html` (or `application/xhtml+xml`). Non-HTML bodies are never handed to the extractor.
  - Extract: `trafilatura.extract(html) or ""`, truncate to `max_chars`, return `FetchedContent`.
  - Degrade: on ANY non-`EgressDenied` exception, log `fetch_degraded` and return `FetchedContent(url, _safe_domain(url), "")` — never raise past the boundary. **note 10:** `_safe_domain(url)` wraps `registrable_domain` in `try/except` returning `""` so a throw inside the eTLD+1 helper cannot itself defeat the "never raise past the boundary" guarantee. `EgressDenied` DOES propagate (the guard is not a soft failure).

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/reachout/{__init__,egress,search,fetch}.py, tests/reachout/{__init__,test_egress,test_search,test_fetch}.py |
| Modify | pyproject.toml |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv sync` | install new deps (trafilatura, tldextract) |
| `uv run pip-audit` | supply-chain gate over the trafilatura/tldextract/courlan tree (FLAG 7); must exit 0, no known vulns |
| `uv run mypy` | full-project strict type check |
| `uv run pytest -q` | full-project test run |
| `uv run ruff check` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | pyproject.toml, uv.lock, src/artemis/reachout/, tests/reachout/ |
| `git commit` | "feat: reach-out web primitives (egress guard + search + fetch)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | adapters take api_key as a constructor arg; never read env |

### Network
| Action | Purpose |
|--------|---------|
| `uv sync` | package installation only (tests are offline via httpx.MockTransport) |

**Dependency note (supply chain, apex-security A03):** `trafilatura` + `tldextract` are new runtime deps; `pip-audit` is a new dev dep (add to `[dependency-groups].dev` in Task 1). Verify exact package names before install (typosquat guard — `trafilatura` not `trafilature`; `tldextract` not `tld-extract`; `pip-audit` not `pip_audit`), pin to current maintained majors, and confirm each is actively maintained (trafilatura is the extractor DR-b-web-access.md selected; `tldextract` arrives transitively via `trafilatura`→`courlan`, so it adds no net new tree). The build gates on `uv run pip-audit` exiting 0 over that tree (FLAG 7). Record resolved versions in `uv.lock`.

## Specialist Context
### Security
- SSRF is the core threat (apex-security A10/SSRF). Non-negotiables: `https`-only; allowlist + port-lock (443 unless an explicit `host:port` is allowlisted, FLAG 5) checked BEFORE resolution; resolve-then-validate every host including redirect hops; reject private/loopback/link-local/reserved/unspecified/multicast for BOTH IPv4 and IPv6, unwrapping IPv4-mapped IPv6 (`::ffff:…`, note 9) before the range test; block the `169.254.169.254` cloud-metadata endpoint (covered by `is_link_local`).
- **DNS-rebinding TOCTOU (BLOCK 2):** the fetcher connects to the exact IP the guard validated (`pin()` → `_PinnedTransport`) with Host/SNI preserved, so the connect-time socket cannot be re-resolved to an internal IP after validation. DR-b-web-access.md did NOT pin (relied on per-hop re-check only, leaving connect-time rebinding as a silent residual); v2 closes it and asserts it under test.
- **Redirects (FLAG 4):** internal client is `follow_redirects=False`; an injected `follow_redirects=True` client is rejected at construction (fail closed); each `Location` hop is re-checked before following.
- **Content-type (FLAG 6):** non-`text/html` responses short-circuit to degraded-empty; never handed to trafilatura.
- **Bounded egress set (FLAG 8):** `_dynamic_domains` is hard-capped (`_MAX_DYNAMIC=64`); a missed `reset_dynamic()` raises rather than growing egress unboundedly.
- **Secrets:** api_key caller-supplied only; scrubbed from BOTH header and JSON-body hook-visible snapshots (BLOCK 3); no env reads in this package.

### Performance
(none — bounded bytes + bounded redirects are correctness limits, not perf budgets)

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/reachout/*.py | docstring all public exports |
| Changelog | CHANGELOG.md | Add entry under Unreleased |

## Acceptance Criteria
- [ ] Deps install + supply-chain → verify: `python -c "import artemis.reachout, trafilatura, tldextract"` exits 0 AND `uv run pip-audit` exits 0.
- [ ] eTLD+1 value (BLOCK 1) → verify: `registrable_domain("https://www.example.co.uk/x") == "example.co.uk"` and `registrable_domain("https://a.b.example.com/") == "example.com"`.
- [ ] Guard REJECTS non-https → verify: `EgressPolicy(frozenset({"example.com"})).check("http://example.com")` raises `EgressDenied`.
- [ ] Guard REJECTS non-allowlisted host → verify: `EgressPolicy(frozenset({"example.com"})).check("https://evil.test")` raises `EgressDenied`.
- [ ] Guard REJECTS bad IPs behind a PERMITTED host (SSRF, monkeypatched `getaddrinfo`) → verify: with `permit("example.com")` and `getaddrinfo` returning each of `127.0.0.1`, `169.254.169.254` (cloud-metadata), `10.0.0.5`, `::1`, `check("https://example.com/")` raises `EgressDenied` in every case.
- [ ] Guard REJECTS literal-IP URLs directly → verify: `check("https://127.0.0.1")`, `check("https://[::1]")`, `check("https://169.254.169.254")` each raise `EgressDenied`.
- [ ] IPv4-mapped IPv6 (note 9) → verify: with a permitted host, `getaddrinfo` returning `::ffff:169.254.169.254` and `::ffff:127.0.0.1` each raise `EgressDenied` (unwrapped before range test); and literal `check("https://[::ffff:127.0.0.1]")` raises.
- [ ] Guard ACCEPTS an allowlisted public host → verify: allowlisted host with `getaddrinfo` → a public IP, `check(...)` returns `None`.
- [ ] Port-lock (FLAG 5) → verify: with `permit("example.com")`, `check("https://example.com:8500/")` raises `EgressDenied`; a policy with static `{"example.com:8500"}` allows `check("https://example.com:8500/")` (public IP).
- [ ] IP pinning (BLOCK 2) → verify: `pin("https://example.com/")` (permitted, `getaddrinfo`→public IP) returns that IP string; a rebinding sim where the guard's `getaddrinfo` returns a public IP but a second resolution would return `127.0.0.1` still connects via the pinned public IP (the transport uses the value from `pin()`, not a re-resolve).
- [ ] `permit`/`reset_dynamic` + cap (FLAG 8) → verify: after `permit("example.org")` a hit on `www.example.org` passes `check`; after `reset_dynamic()` it raises `EgressDenied`; permitting `_MAX_DYNAMIC`+1 distinct domains across a missed reset raises `EgressDenied` (capped) rather than growing unbounded.
- [ ] `TavilySearch.search` maps results + key redaction (BLOCK 3) → verify: MockTransport returns a Tavily payload; result is `list[SearchHit]` with `snippet` from `content`; the api_key string appears in NO hook-visible snapshot of headers OR body.
- [ ] Fetcher rejects unsafe injected client (FLAG 4) → verify: constructing `TrafilaturaFetcher(egress, http=httpx.AsyncClient(follow_redirects=True))` raises `ValueError`.
- [ ] Fetcher content-type gate (FLAG 6) → verify: a `Content-Type: application/pdf` response yields empty `FetchedContent.text` (degraded, extractor not called).
- [ ] `TrafilaturaFetcher.fetch` bounds + degrades → verify: a body over `max_bytes` yields empty `text` (degraded, no raise); a well-formed `text/html` article yields non-empty text truncated to `max_chars` with `domain == registrable_domain(url)`; a 302 `Location` to an internal IP raises/propagates `EgressDenied` (not followed).
- [ ] Full-project gate → verify: `uv run mypy` (0 errors, strict), `uv run pytest -q` (all pass), `uv run ruff check` (clean).

## Progress
_(Coding mode writes here — do not edit manually)_

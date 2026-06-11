# Sweep 2026-06-10 — M2 security wall + OBS observability + DR deep-research

Scope: M2-a, M2-b, M2-c, M2-d, OBS-a, OBS-b, DR-a, DR-b, DR-c (full reads); ADR-005/008/009 (context). Cross-checked against M0-d (ModelPort), M7-c (Researcher/grounding gate), M4-a (memory store path).

Severity counts: **BLOCK 6 · UPGRADE 4 · FLAG 14 · RESEARCH 3**

---

## BLOCK

### B1. EgressPolicy host-vs-registrable-domain mismatch — subdomain fetches are all denied
**Files:** `DR-b-web-access.md` Task 1 (`EgressPolicy.check`/`permit`); `DR-c-deep-research-engine.md` Task 3 step 2b.
`permit(domain)` stores a **bare registrable domain** (eTLD+1, validated via `registrable_domain`), but `check(url)` tests the **raw parsed host** against the allow sets: "parse host; if host in neither static nor dynamic set → raise `EgressDenied`". DR-c does `dom = registrable_domain(hit.url); egress.permit(dom); fetcher.fetch(hit.url)`. Any real-world hit URL with a subdomain (`www.nytimes.com`, `docs.python.org`) yields host ≠ stored domain → denied. The DR-b acceptance test only exercises the exact-match case (`permit("example.com")` + `check("https://example.com/p")`), so the bug ships green and the engine then fails on virtually every live fetch (fails closed — a functional break, not a hole). **Fix:** `check` must compare `registrable_domain(host)` against the dynamic set (static set semantics — exact host for API endpoints — should be stated separately); add a subdomain case to the Task 5 tests.

### B2. DR-c cannot "accrue reader tokens" — `Extract` carries no usage (missing interface)
**Files:** `DR-c-deep-research-engine.md` Task 3 step 2b ("accrue reader tokens"); `DR-a-untrusted-content-security.md` Tasks 2–3.
DR-c's token accounting (a Stop-impact assumption: every orchestrator **and reader** call accrues against `token_cap`) requires the reader's `usage["total_tokens"]`, but `QuarantinedReader.read()` returns only `Extract { source_url, source_domain, summary, claims, flagged_injection, parse_failed }` — no token count, and the `ModelResponse.usage` is consumed inside DR-a and discarded. A literal executor has no value to accrue; the reader's spend (the high-volume side of the loop) silently escapes the cap. **Fix:** amend DR-a — either add `tokens_used: int` to `Extract` or have `read()` return `(Extract, usage)`; amend DR-c to consume it.

### B3. Memory DB frozen OUTSIDE the broker-mounted vault — M2-b contradicts M2-a/ADR-007, inherited by M4-a
**Files:** `M2-b-scope-model-and-wall.md` Task 3 (`db_path = paths.scope_dir(settings, scope) / "memory" / "memory.db"`); `M2-a-key-broker.md` Identity + Assumption 6 + Task 10 ("the volume holds the scope's SQLCipher memory DB + LanceDB doc index", mount point `/opt/artemis/<slot>/<scope>/vault/`); `M2-c` Assumption (brain opens its files "UNDER that mounted path"); confirmed propagated into `M4-a` (claims the path is "exactly the M2-b location" *and* "born encrypted inside the per-scope vault" — both can't be true).
`scope_dir = <dataRoot>/<slot>/<scope>/` (per M2-a's DEKStore note), so `scope_dir/memory/memory.db` is a sibling of `vault/`, not inside it. The DEK `keys/` dir is correctly outside the vault (needed pre-mount), but the memory DB landing outside means: the ADR-007 "one unlock opens the whole per-scope vault" contract is false for the memory DB; the M2-d gate item (iii) ("a mounted volume left attached after lock is a wall breach") reviews a mount that doesn't actually protect the DB it claims to. SQLCipher still encrypts the file, so the at-rest story degrades rather than collapses — but three frozen contracts disagree, and M4-a builds on the wrong one. **Fix:** decide one home: either `db_path = scope_dir / "vault" / "memory" / "memory.db"` (and OBS-b's `relational/` likewise — see F14), or amend M2-a/ADR-007 to say the vault holds only the LanceDB doc index.

### B4. `token_cap` hard stop vs "always synthesise" — uncaught `_BudgetExhausted` in the synthesis call
**Files:** `DR-c-deep-research-engine.md` Task 3 (`_orchestrate` raises `_BudgetExhausted` if `budget_left <= 0`; loop step 2's try/except catches it with "break to synth"; step 4 synth calls `_orchestrate` with no catch specified).
The spec states both "the cap is a hard stop" (no model call once `spent ≥ token_cap`) and "the loop stops and synthesises with what is gathered". If the budget is exhausted when the loop breaks, the synthesis `_orchestrate` raises `_BudgetExhausted`, which step 4 does not catch → `research()` raises into M7-c, violating the never-fabricate-but-also-never-crash contract and making the "cap bound" test unsatisfiable as written. **Fix:** state the rule explicitly — e.g. reserve a fixed synthesis budget out of `token_cap`, or permit exactly one final synthesis call even at cap, or on `_BudgetExhausted`-at-synth return the empty-guard result.

### B5. Circular import: `egress.py` ↔ `fetch.py`
**Files:** `DR-b-web-access.md` Tasks 1 and 3.
`EgressPolicy.permit` (egress.py) calls `registrable_domain`, which Task 3 defines in `fetch.py`; `fetch.py`'s fetchers are constructed with `egress: EgressPolicy` (and the module realistically imports `EgressDenied`/`EgressPolicy`). As literally specced, runtime imports run both ways → `ImportError`. Resolvable with `TYPE_CHECKING`-gated imports, but the spec gives no instruction and the executor can't fill the gap. **Fix:** move `registrable_domain` into `egress.py` (or a tiny `research/domains.py`) and have `fetch.py` import it one-way; update the `__init__.py` re-export note.

### B6. `temperature=0` required by DR-c but absent from `ModelPort` and not forwarded by `TracingModelPort`
**Files:** `DR-c-deep-research-engine.md` Task 3 (`model.complete(..., response_schema=<schema>, temperature=0)` — "if M0-d lacks a temperature param, add it as a prereq"); `M0-d-ports-scaffolding.md` Task 4 (verified: `complete(role, messages, *, stream, response_schema)` — no temperature; also **sync `def`**, see F2); `OBS-b-telemetry-backend.md` Task 3 (`TracingModelPort.complete` mirrors the no-temperature signature).
"Add it as a prereq" is not an executable instruction for a literal coder, and no spec amends M0-d or OBS-b. If the executor adds `temperature` to `ModelPort`, `TracingModelPort` (already specced without it) breaks Protocol conformance or silently drops determinism for every traced research call. **Fix:** amend M0-d's `ModelPort.complete` (and OBS-b's wrapper, which must pass through `**`-style or the explicit param) in a small spec amendment before DR-c builds; or drop `temperature` from DR-c and rely on schema-constrained decoding alone (state which).

---

## UPGRADE

### U1. SSRF guard has a DNS-rebinding TOCTOU — pin the resolved IP
**Files:** `DR-b-web-access.md` Task 1 (`block_private_ip` resolves via `getaddrinfo`), Task 3 (httpx then re-resolves on connect).
The guard's resolution and httpx's connection resolution are separate DNS queries; a rebinding attacker (short-TTL record flipping public→`169.254.169.254`) passes the check and connects internally. Within-stack fix (standard practice mid-2026): resolve once in the guard, then connect to the vetted IP (custom `httpx` transport / `AsyncHTTPTransport` with a pinned resolver, `Host` header preserved), or re-validate the peer IP in an httpx event hook before the body is read. Worth a one-paragraph amendment to Task 1/3; the current design is good (every-address check, redirect re-check) but this is the canonical residual gap.

### U2. `tier_for` endpoint-substring sniffing (`"deepseek" in host`) is brittle — add an explicit `tier` key
**Files:** `OBS-b-telemetry-backend.md` Task 2; `config/roles.toml` schema (M0-a).
Tier classification by substring breaks the moment the cloud role's endpooint host changes (proxy, regional host) and silently misclassifies cost to LOCAL=0. DR-c is adding three roles to `roles.toml` anyway — adding `tier = "cloud"|"subscription"|"local"` per role table and reading it in `tier_for` (substring as fallback) is a two-line robustness win on the quota-protection path.

### U3. `_SECRET_KEY_NAMES` substring matching is over-broad — `"key"`/`"ref"` redact benign fields
**Files:** `OBS-a-observability-core.md` Task 1.
Case-insensitive **substring** match on `key` and `ref` redacts `task_class_key`, `monkey`, `reference`, `preference` — `task_class_key` is the one field the telemetry pillar exists to carry, so any log line that includes it as an extra gets `***REDACTED***`, blinding debugging. Suggest exact-name or suffix/word-boundary matching (`api_key`, `_key`, `token`, `secret`, …) with `task_class_key` explicitly exempted, keeping the value-shape check as backstop.

### U4. DR-c orchestrator usage accrual should read `usage` defensively
**Files:** `DR-c-deep-research-engine.md` Task 3 (`accrue resp.usage["total_tokens"]`); contrast `OBS-b` Task 3 (absent→`{}`, missing key→0).
A local mlx-openai-server or streaming response that omits usage raises `KeyError` mid-loop. Use the same defensive pattern OBS-b mandates (`usage.get("total_tokens", prompt+completion)`), with a WARNING on all-zero so the cap isn't silently un-enforced.

---

## FLAG

### F1. OBS-b passes a `SecretKey` where M2-c's `sqlcipher_open` takes `key_hex: str`
**Files:** `OBS-b-telemetry-backend.md` Task 1 (`open_telemetry_db(path, key: SecretKey)` → "open keyed via M2-c `sqlcipher_open(path, key)`"); `M2-c` Task 3 (`sqlcipher_open(path: Path, key_hex: str)`). The call must be `sqlcipher_open(path, key.as_hex())`. mypy would catch it, but the spec text instructs the wrong call — say it explicitly.

### F2. Sync-vs-async `ModelPort.complete` is "resolved at build" in three specs — but M0-d is definitively sync
**Files:** `DR-a` Assumption 2, `DR-c` Assumption 4 (`await model.complete` per the M7-a2 pattern), `M0-d` Task 4 (verified `def complete`, not `async def`). Either M7-a2 changed M0-d (then OBS-b's `TracingModelPort` — written sync — is wrong) or M7-a2 wraps it. Each spec defers to "coding mode verifies", which is judgment work the corpus says DeepSeek can't do. Resolve once at planning level and state the answer in all three specs.

### F3. DR-a `read(..., max_tokens=1024)` is a dead parameter
**Files:** `DR-a` Task 3; `M0-d` Task 4. `max_tokens` is accepted (and DR-c passes `profile.per_source_max_tokens` into it) but the specced `model.complete(...)` call has no `max_tokens` param to forward it to — the only output bound is the schema's `maxLength`. Either wire it (needs the same M0-d amendment as B6) or delete it; as written the executor must guess.

### F4. M2-b `compose_brain` default = "the M2-c real provider via a factory" — which doesn't exist when M2-b builds
**Files:** `M2-b` Task 4; build order (M2-b precedes M2-c). A literal executor will try to import `BrokerKeyProvider` and fail. State the M2-b-time default explicitly (e.g. a factory that raises `ScopeLockedError`/`NotImplementedError` until M2-c rebinds it, or `FakeKeyProvider` behind an env flag).

### F5. Client-side proof counter: persistence and ownership unspecified
**Files:** `M2-c` Task 2 (`proof = prover(scope, nonce, next_counter)`). Nothing says where `next_counter` lives (memory? file?), who advances it, or how a restart recovers a value > the broker's `lastSeen` (a stale counter permanently deadlocks proofs against the strictly-increasing check). Define the counter source (e.g. broker `status` returns last-seen per device, or persist client-side under `<slot>/run/`).

### F6. Proof signature byte layout not frozen — `nonce ‖ scope ‖ counter` has no encoding
**Files:** `M2-a` Task 4 (`SignedKeypairVerifier` verifies over `nonce ‖ scope ‖ counter`) and Task 6 / `docs/technical/protocol/broker-ipc.md`. Counter endianness/width, scope encoding (UTF-8? length-prefixed?), and concatenation rules are unstated; the Swift MockProver and the Python fake server (M2-c Task 7) — and eventually the iPhone app — must byte-match. Freeze the exact layout in `broker-ipc.md`. Also: the `NonceStore` "short TTL" has no value — give a number (e.g. 60s).

### F7. "Imperative-stripped" claims and canary handling are not executable instructions
**Files:** `DR-c` Task 3 (`Extract.claims` are "imperative-stripped" + "a canary the synthesis must not echo"). No algorithm for imperative-stripping is given (regex of leading imperative verbs? drop the claim? rewrite?), and the action on a canary echo is undefined (reject the synthesis? retry? return empty?). The Task 4 test asserts the *outcome*, so the executor must invent the *mechanism* of a security control. Spell out both (e.g. drop any claim whose first token matches an imperative-verb list; on canary echo, discard the synthesis and return the empty-guard result).

### F8. `JsonFormatter`/`RedactionFilter` "extras" handling under-specified for stdlib logging
**Files:** `OBS-a` Task 1. `extra=` kwargs become attributes on the `LogRecord`, not a dict; collecting them requires diffing `record.__dict__` against the standard attribute set. The spec says "extras under `extra`" as if a dict exists. Also "entirely base64/hex chars" needs a charset definition (does it include `+/=` padding? `-_` urlsafe?). One sentence each closes both gaps.

### F9. Fetch degrade contract vs `EgressDenied` — swallow or propagate?
**Files:** `DR-b` Task 3 ("On any error/timeout/oversize/empty-extract → `FetchedContent(url, domain, text='')`") vs the test "a 302 redirect to an internal IP is **denied** (not followed)". Is the denial surfaced as a raised `EgressDenied` or as empty text? DR-c just skips empty text, so either works — but the executor must pick one and the tests must match. State it (recommend: degrade to empty text + WARNING, consistent with the rest of Task 3).

### F10. `tldextract` dependency not in DR-b's Commands/Permissions
**Files:** `DR-b` Assumption 1 + Task 3 vs the Commands table (only `uv add trafilatura`). M7-c verified to expose NO reusable eTLD+1 helper (the gate does it internally) → the "else add tldextract" branch is the real path, and the executor lacks permission/command for `uv add tldextract` (+ its `pip-audit` line, + git add of pyproject/uv.lock already covered). Add it.

### F11. DR-c housekeeping: `eval_research.py` missing from git-add scope; Network table cites the wrong task
**Files:** `DR-c` Git Operations (`tests/eval_research.py` absent) and Network table ("GATED, Task 5" should be Task 6). Also the split-rule note says "2 src + 1 test" while the Files table has 5 entries. Trivial but a literal executor follows the git-add list verbatim.

### F12. M2-c on-hardware Task 8 omits `ARTEMIS_BROKER_SKIP_CODESIGN=1`
**Files:** `M2-c` Task 8(c) vs `M2-a` Task 6. The end-to-end brain→broker round-trip runs an unsigned `uv run python` brain; without the documented dev bypass flag the broker's code-signing check rejects it and the gated task fails for the wrong reason. Add the flag (and the note that peer-uid is still enforced) to Task 8's instructions.

### F13. M2-d acceptance criterion reaches outside its own file scope
**Files:** `M2-d` Acceptance 4 ("is referenced as a prerequisite by the M3/M4 specs"). M2-d's Files table touches only the gate record; verifying/ensuring every M3/M4 spec lists M2-d is not runnable within this spec. Either drop to "the block statement is present in the gate file" or add a planning-mode checklist item to audit the M3/M4 specs' Prerequisites lines (they should already carry it).

### F14. OBS-b telemetry DB also sits outside the vault — same question as B3
**Files:** `OBS-b` Task 1 (`scope_dir(s, "owner-private") / "relational" / "telemetry.db"`). Whatever B3's resolution is, the `relational/` operational subdir needs an explicit ruling (inside the vault → unavailable when locked, telemetry writes fail while LOCKED; outside → SQLCipher-only protection and writes need a cached DEK anyway). Note the locked-session behaviour either way: what does `TelemetrySink` do when `dek_for_scope` raises `ScopeLockedError` at composition/runtime?

---

## RESEARCH

### R1. Does M0-a's `roles.toml` schema accept `api_key = { env = "DEEPSEEK_API_KEY" }`?
**Files:** `DR-c` Task 2. The env-reference inline-table syntax is asserted but M0-a's `Settings.roles` parser (`.adapter`/`.endpoint`/`.model_id` per OBS-b Assumption 6) may not model an `api_key` field at all, or may choke on an inline table under strict parsing. Verify M0-a's role schema (and who resolves the env reference — Settings or the adapter) before DR-c builds; otherwise the acceptance `tomllib.load` check passes while the runtime ignores the credential.

### R2. Brave/Tavily response shapes + trafilatura currency as of build time
**Files:** `DR-b` Tasks 2–3. The specced parse paths (`web.results[].description`; Tavily `results[].content`; `api_key` in the Tavily POST body — Tavily moved to `Authorization: Bearer` on newer API versions) and trafilatura's maintenance status should be re-verified against the live APIs at build (canned-payload tests will pass regardless of drift). Confirm Brave's current auth header and Tavily's current auth scheme before freezing the adapters.

### R3. SwiftPM platform value for macOS 26 under `swift-tools-version: 6.0`
**Files:** `M2-a` Task 1 (`.macOS(.v26)` "or the highest the toolchain accepts"). The hedge is good but the executor must know the actual ceiling: verify which `swift-tools-version` first carries `.v26` (likely requires the Xcode-26-era toolchain, i.e. tools-version 6.2+) and pin the spec to the verified pair, since "document if `.v15`/`.v14` is the ceiling" leaves the deployment target — and hence Security.framework API availability annotations — floating.

---

## Security-invariant review summary (rubric check 4)

- **Dual-LLM quarantine:** structurally strong (toolless-by-interface + runtime introspection guard, spotlight NFKC/zero-width hardening, caller-supplied provenance, bounded schema, flagged/garbage exclusion, CaMeL no-raw-content test). Weakened only by B2 (reader spend uncapped) and F7 (imperative-strip/canary mechanisms unspecified).
- **Tiered secrets:** consistent — HIGH (DEKs) never leave the SE/mlock path; Medium (Brave/Tavily/Jina/DeepSeek keys) are caller-resolved env/Keychain, never inline (DR-b Assumption 2, DR-c Task 2), never logged (caplog tests).
- **Scope wall:** M2-b's structural wall + Gateway LOCKED model are sound; B3 is the one real contract crack (vault vs scope_dir).
- **SSRF/egress:** default-deny + every-address private-IP check + manual redirect re-check is the right shape; B1 breaks it functionally (fail-closed) and U1 is the canonical residual (rebinding TOCTOU).
- **Log redaction:** no-content Protocol + redact-before-store is well-designed; U3 (over-broad key names) and F8 (extras mechanics) are the gaps.
- **Over-engineering (rubric check 5):** none material. The specs are disciplined; the only mild excess is OBS-a's unused `obs_dir` export and DR-c's eval harness shipping in v1 (justified by the Standard-mode cost assumption it validates).

# Final pre-handoff spec-lint — OBS + DR area

Executor: DeepSeek V4-Flash (literal; fills gaps with plausible-wrong code; silently skips later phases).
Lint date: 2026-06-11. Scope: OBS-a, OBS-b, DR-a, DR-b, DR-c.

Judgement rule applied to cross-references: a finding is BLOCK only if Flash could **not** build the task correctly from the spec text alone. A reference whose consumed shape is inlined is acceptable.

---

## OBS-a-observability-core.md — WARN-only

Strong spec: exact signatures, per-task done-when, redaction rules enumerated. Two additive-modify tasks require Flash to *locate* existing code sites; behaviour is specified but the site is not pinned to a symbol/line.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| OBS-a:71 | WARN | CODE DETAIL | Task 5 error tap says "the existing degrade-don't-crash `except` block(s) of `respond`… and `respond_stream`'s failure path" — Flash must find these blocks in brain.py; if it can't, it may add a new try/except (wrong control flow). Behaviour is specified, location is not. | Name the method + the returned typed value at each site (e.g. "the `except Exception as exc:` that returns `TOOL_ERROR` in `respond`") so the site is identified by its return, not by reading the whole method. |
| OBS-a:68-72 | WARN | TASK ATOMICITY | Task 5 bundles 3 edit sites (constructor kwarg + route tap + error taps in 2 methods). done-when covers all, so not a BLOCK, but >3 sub-steps — Flash may complete the constructor + route tap and silently skip the error taps. | Split the error-tap edit into its own task, or add an explicit checklist line "all THREE edits present" to done-when. |
| OBS-a:74-76 | WARN | CODE DETAIL | Task 6 "Wrap the existing raise sites for `CloudEgressForbiddenError` and `RecipeReplayError`" — same locate-the-site risk as Task 5. | Reference the sites by the exception they raise (already done) AND confirm they are in `escalate_and_distill` body (stated) — acceptable, but add "if a site is absent, STOP and report" to prevent invented sites. |
| OBS-a:45 | WARN | CODE DETAIL | `JsonFormatter.format` "extras under `extra`" — record extras are not a single attribute in stdlib logging; Flash must reconstruct them by diffing `record.__dict__` against `logging.LogRecord` reserved keys. Mechanism not specified → likely wrong. | Inline the extraction rule: "extras = keys in `record.__dict__` not in the stdlib reserved set `{...}`" or instruct passing extras via a known wrapper. |

---

## OBS-b-telemetry-backend.md — BLOCK

One BLOCK: a test assertion depends on the `scan_gaps` return shape, which is **not inlined** anywhere in the spec; Flash cannot write that assertion correctly. Plus two WARN.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| OBS-b:87 | BLOCK | CROSS-REFERENCES | Task 6 end-to-end test asserts `scan_gaps(SqliteTelemetrySource(...), now=...)` yields "an `escalation-cluster` gap with `evidence_count == 3`". `scan_gaps`' signature, return type, the gap object's attribute names (`.kind`/`.evidence_count`?), and the `"escalation-cluster"` literal are NOT inlined. The M7-c assumption (line 18) inlines `TelemetrySource` + event types but NOT `scan_gaps` or its `Gap` result. Flash will invent attribute names. | Inline the `scan_gaps` signature + the returned gap's shape (e.g. `Gap{kind: str, evidence_count: int, ...}` and the exact `kind` literal `"escalation-cluster"`), or drop this assertion to "≥1 gap returned" and move the precise check to M7-c's own suite. |
| OBS-b:75 | WARN | CODE DETAIL | `stale_items()` "parse `recipe.provenance["verified_at"]`" — the timestamp **format** is unspecified (ISO-8601? epoch?). Assumption line 22 says only "a `verified_at` string". `< clock() - staleness_days` requires a parsed datetime; Flash will guess `datetime.fromisoformat` and may mismatch M7-a1's actual format. | State the format: "parse via `datetime.fromisoformat` (M7-a1 writes ISO-8601 UTC)" — or whatever M7-a1 actually emits. |
| OBS-b:62,64 | WARN | CODE DETAIL | Task 3 reads `usage` as a dict (`usage.get(...)`) but DR-a/DR-c read the same `ModelResponse.usage` as an **object** (`getattr(resp.usage, "total_tokens", 0)`, OBS-b:64 itself says `getattr(resp, "usage", None)`). `usage` shape (dict vs object) is inconsistent across the area; if it's an object, `.get()` crashes. | Pin `ModelResponse.usage` shape once (it's M0-d/Seam 1) and make all three specs read it the same way. |
| OBS-b:90 | WARN | TASK ATOMICITY | Task 7 is GATED on-hardware (correctly flagged) — no repo files. Fine; noted so reviewer doesn't expect output. | none (informational). |

---

## DR-a-untrusted-content-security.md — PASS

Cleanest spec in the set. Every task names its file, signatures are exact, schemas are concrete, done-when checks are runnable, security findings resolved inline. No BLOCK, no material WARN.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| DR-a:40 | WARN | CODE DETAIL | `spotlight` "strip any literal occurrence of the `<<UNTRUSTED:` / `<</UNTRUSTED:` marker pattern" — "pattern" is ambiguous (literal substring vs regex incl. the nonce?). Flash may strip only the exact prefix and miss `<</UNTRUSTED:anything>>`. done-when (line 41) tests one case only. | Specify: "regex-strip `<</?UNTRUSTED:[^>]*>>` (case-sensitive, post-NFKC)". |

---

## DR-b-web-access.md — WARN-only

Thorough security spec, exact constructors, mocked-httpx tests. The eTLD+1 helper reuse is conditional ("reuse M7-c's if importable, else add tldextract") — acceptable because the fallback (`tldextract.extract(url).registered_domain`) is inlined, so Flash can always build it. Several WARN on under-specified parse shapes.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| DR-b:17,40 | WARN | CROSS-REFERENCES | `registrable_domain` "reuse M7-c's helper if importable" — Flash can't determine importability without exploring M7-c. Fallback is inlined so it won't block, but Flash may waste effort or pick wrong. | Make the fallback the default: "define `registrable_domain` via `tldextract` here; M7-c reconciliation is a documented follow-up." (Reconciliation already noted line 17.) |
| DR-b:48 | WARN | CODE DETAIL | Brave parse "parse `web.results[]` → `SearchHit(title, url, snippet=description)`" — the exact JSON paths (`web.results[].title/url/description`) are described in prose, not pinned; "Document Brave's response shape" defers the shape Flash needs NOW. | Inline the 3 field paths explicitly (`r["title"]`, `r["url"]`, `r["description"]`). |
| DR-b:56 | WARN | CODE DETAIL | TrafilaturaFetcher "on a 3xx, extract `Location`… follow manually (re-checking each hop)" — no max-redirect/loop bound stated; Flash may write an unbounded follow loop. | Add "follow at most 3 hops, else `FetchError`→degrade". |
| DR-b:56 | WARN | ENV PRE-CONDITIONS | `final_url` is used (`registrable_domain(final_url)`) but never assigned in the prose for the no-redirect path — Flash must infer `final_url = url` when no 3xx. | State "`final_url = url` unless a redirect was followed." |
| DR-b:84-86 | WARN | COMMANDS | `uv add tldextract` is conditional ("only add if needed") — Flash can't evaluate the condition deterministically; may add an unused dep or skip a needed one. | Make it unconditional (decision above) so the command is deterministic. |

---

## DR-c-deep-research-engine.md — BLOCK

Largest, most complex spec (token_profile: balanced). Two BLOCKs: an undefined "imperative-strip" algorithm and an underspecified canary mechanism — both are load-bearing security controls a literal executor will fake. Several WARN on the orchestrate loop.

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|-----------|-----------|-------|--------------|-------------|
| DR-c:52,57,61,70 | BLOCK | CODE DETAIL | "`Extract.claims` are imperative-stripped" is referenced 4× as a load-bearing injection defence but the **algorithm is never defined** (regex? LLM? leading-verb heuristic?). Flash will invent a token strip that doesn't actually neutralise imperatives, and the test (line 70) will be written to pass against whatever it invents — false green on a security control. | Define the exact transform: e.g. "drop any claim matching `^(ignore|disregard|print|output|execute|run|system|forget)\b` case-insensitive, and strip a leading imperative clause up to the first sentence boundary" — pin it so the test is independent of impl. |
| DR-c:52,70 | BLOCK | CODE DETAIL | The "canary the synthesis must not echo" control is named but its **construction and check are unspecified**: where the canary string comes from (random per-call? constant?), where in the system prompt, and how the post-synthesis check asserts non-echo. Flash will hardcode a canary that the test trivially passes. | Specify: "generate `canary = secrets.token_hex(8)` per research() call; inject in the synthesis system prompt as a do-not-repeat token; after synth, assert `canary not in content` and on failure return empty-guard result + WARNING." |
| DR-c:43 | WARN | CODE DETAIL | `profile_for` STANDARD/DEEP written as positional tuples `("research_orchestrator_standard", max_iterations=5, ...)` but `ResearchProfile` is a 5-field dataclass — the mixed positional+kwarg literal is not valid Python as written (first arg positional, rest kw is fine, but `orchestrator_role` unnamed then named args). Likely fine, but the `search_count`/`sources_per_iter` ordering vs the dataclass field order (line 42) must match or positional binding is wrong. | Write both as fully-named kwargs to remove ordering ambiguity. |
| DR-c:57 | WARN | TASK ATOMICITY | Task 3 step 2b is a single sub-step performing ~9 operations (dedup, permit, fetch, re-check domain, read, accrue, skip-flagged, append). A literal executor may drop the post-redirect re-check (line 57 "re-check `registrable_domain(fc.url) was egress-permitted`") — and that phrasing isn't executable (how is "was permitted" queried? `EgressPolicy` has no `is_permitted`). | Add an `EgressPolicy.is_permitted(url) -> bool` (or reuse `check` in try/except) and state the exact call; consider splitting 2b. |
| DR-c:57 | WARN | CROSS-REFERENCES | `egress.permit(dom)` then `fetcher.fetch` — but DR-b `EgressPolicy.permit` takes a **bare registrable domain** and raises `ValueError` on anything else (DR-b:42). `dom=registrable_domain(hit.url)` satisfies that — OK — but the dependency is implicit; if `registrable_domain` returns empty for an odd URL, `permit` raises and the iteration dies. | Note "skip hit if `dom` is empty" before `permit`. |
| DR-c:59 | WARN | CODE DETAIL | "pass only the most recent `N` extract summaries (sliding window)" — `N` is never given a value. Flash will pick an arbitrary N. | Set N explicitly (e.g. `N = profile.sources_per_iter * 2`). |
| DR-c:81 | WARN | ACCEPTANCE | Task 5 eval harness "faithfulness ≥4/5 … STANDARD within a stated tolerance of DEEP" — the tolerance is "stated" but never stated; LLM-as-judge bar is human-judgment-adjacent. Correctly marked off-suite/GATED, so not a build blocker. | Put a concrete tolerance number in the script header (e.g. "≤0.5 faithfulness points"). |
| DR-c:151 | WARN | COMMANDS | Acceptance uses `ARTEMIS_ENV_FILE=config/.env.dev uv run …` (bash env-prefix syntax) — build host is Windows PowerShell per env; inline `VAR=x cmd` is a parse error there. | Use the cross-platform form or note "run under bash" (other specs use plain `uv run`). |

---

## Area verdict

**BLOCK** — OBS-b and DR-c each carry build-wrong-thing BLOCKs (un-inlined `scan_gaps` shape; undefined imperative-strip + canary security controls); OBS-a/DR-b WARN-only, DR-a PASS. Resolve the 3 BLOCK rows before handoff; the WARNs are safe-to-build-with but worth a sweep.

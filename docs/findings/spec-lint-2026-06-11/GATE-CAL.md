# Spec-Lint Report — GATE + CAL cluster

**Pass:** FINAL pre-handoff spec-lint
**Date:** 2026-06-11
**Executor target:** DeepSeek V4-Flash (literal executor)
**Specs:** GATE-a, GATE-b, CAL-a, CAL-b, CAL-c, CAL-d

---

## GATE-a-action-staging.md — **BLOCK**

**1 BLOCK, 2 WARN**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| GATE-a:93 vs :190 | BLOCK | ACCEPTANCE / internal contradiction | Task 3 body (lines 90–93) specifies: on `ScopeLockedError` from `callable_ref`, **revert** `EXECUTING→PENDING` and re-raise; Task 5 test (line 121) asserts final status is **PENDING** and the action is **re-approvable** (spy `call_count == 2`). But the Acceptance Criteria (line 190) states the opposite: "`ScopeLockedError` from callable propagates + **status stays APPROVED** (already flipped) → document this as expected at-most-once behavior". A literal executor reading the AC will write the no-revert path and fail its own Task 5 test, or write the revert path and fail the AC. Conflicting done-criteria for the security-critical recovery path. | In line 190 replace "status stays APPROVED (already flipped)" with "status reverts to PENDING (re-approvable per Task 3 revert)" to match Task 3 lines 90–93 and the Task 5 test on line 121. |
| GATE-a:113 | WARN | ENV PRE-CONDITIONS | Task 5 builds `PendingActionStore` "over a real SQLite file in `tmp_path`" using `sqlcipher_open`, but Assumptions (line 23) and the GATED note say real SQLCipher is off-hardware. Whether `sqlcipher_open` falls back to plain SQLite off-hardware is unstated; Flash may import a missing binding and the store test fails to connect. | Add one line: "off-hardware `sqlcipher_open` is the plain-SQLite shim from M2-c (no binding required); real keyed SQLCipher is Task 6." |
| GATE-a:124 | WARN | ACCEPTANCE / human judgment | The "args never contain untrusted text" case is "(documentation + inline comment test)" — the only concrete assertion is `isinstance(action.args, dict)`, which does not actually test the untrusted-text invariant. Soft flag: the runnable check is weaker than the prose claims. | Acceptable as-is; optionally narrow the prose to "assert args is a dict of JSON-native types" so the check matches the claim. |

Note: the inlined `ActionStagingService.approve` execute-once contract, the `_execute` twin lookup (`f"{action.tool}_execute"`), `set_status_conditional` rowcount guard, and `list_pending`→`expire_due` are all fully inlined and self-consistent within the task body. Only the AC line contradicts.

---

## GATE-b-action-review-surface.md — **PASS** (WARN-only)

**0 BLOCK, 2 WARN**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| GATE-b:131-135 | WARN | CROSS-REF | Task 2 references `app.state.gateway.tool_registry` as the source of the `ToolRegistry`. The shape of `app.state.gateway` is from CLIENT-b/M1-c, not inlined. Flash can write the line literally (it is given verbatim), so not a BLOCK, but if the attribute path is wrong the wiring silently mis-resolves at startup (only caught by the gated `hasattr` check at line 139, which only checks `action_staging`, not the registry). | Add a one-line note: "if `app.state.gateway.tool_registry` does not resolve, the registry is at `app.state.tool_registry` — confirm against CLIENT-b wiring." |
| GATE-b:152 | WARN | CODE DETAIL / pseudocode | The `FakeActionStagingService` methods are stubbed with `...` (lines 150–152). Flash must invent `list_pending`/`approve`/`reject` bodies + a `FakePendingAction` shape. The required behaviour is fully described in the test cases (lines 158–163), so it is buildable, but the fake itself is pseudocode. | Acceptable; optionally inline the `FakePendingAction` field list (mirror the `PendingActionResponse` fields) so the Codable/JSON keys line up deterministically. |

Note: the consumed GATE-a contract (`list_pending`/`approve`/`reject` signatures, `ValueError`→409, `KeyError`→404, `ScopeLockedError`→423, `ActionStatus` lowercase values, `action_class="takes-action"`) is correctly inlined in Assumptions (lines 18–24) and matches GATE-a. The `args`-excluded `PendingActionResponse` and the three routes are given as full snippets. Endpoint code is buildable from the spec alone.

---

## CAL-a-read-findtime-prefs-sync.md — **PASS** (WARN-only)

**0 BLOCK, 3 WARN**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| CAL-a:195-206 | WARN | TASK ATOMICITY | Task 3 builds the `CachedEvent` dataclass + `EventCacheStore` (8 methods) + `CalendarSyncEngine` (5 methods incl. the full initial/incremental/410-recovery `sync()` algorithm) in one task. This is the largest single task in the cluster (3 logical components). It is well-specified step-by-step, so not a BLOCK, but exceeds the >3-sub-step split guideline substantially. | Soft flag only; the atomic-exception rationale (line 14) covers it. No change required for handoff. |
| CAL-a:330-345 | WARN | CODE DETAIL | `FindTimeEngine.find_slots` is specified as a 5-step prose algorithm (working-hours band, buffer expansion, midnight split, ≤10 slots) with no reference implementation. Flash will produce *a* slot-finder, but the exact gap-enumeration/clipping semantics are judgment calls; the Task 7 tests (lines 459–462) pin the behaviour, so it is verifiable. | Acceptable; the tests are the safety net. Optionally add the midnight-split tie-break rule explicitly. |
| CAL-a:201,206 | WARN | ENV PRE-CONDITIONS | `InvalidSyncTokenError` is defined in `cache.py` (line 206) and `FakeCalendarClient` is told to raise it (line 200/440), but `FakeCalendarClient` lives in `client.py` (Task 1) which would need to import it from `cache.py` — a potential circular import (`cache.py` imports `CalendarClient` from `client.py`). | Add one line: "define `InvalidSyncTokenError` in `client.py` (not `cache.py`) so `FakeCalendarClient` raises it without a cache→client cycle; `cache.py` imports it from `client.py`." |

Note: the full 9-method write surface (lines 80–98) is inlined into the `CalendarClient` Protocol here for CAL-b to implement, and the "NO `delete_event` — use `cancel_event`" rule is explicit (line 97). Scope-registration U4 fix (readonly only) is verified by the AC on line 569.

---

## CAL-b-write-gating-activitylog.md — **PASS** (WARN-only)

**0 BLOCK, 3 WARN**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| CAL-b:353 | WARN | ACCEPTANCE / runnable check | The AC python one-liner builds the manifest with `tools = None` then calls `make_calendar_manifest(tools)` and asserts `len(m.tools)`. `make_calendar_manifest` constructs `ToolSpec`s with `callable_ref=tools.list_calendars` (CAL-a line 363+); passing `None` will `AttributeError` on attribute access at construction time, so the check cannot pass as written. | Change `tools = None` to construct a real `CalendarTools`/`CalendarWriteTools` with `FakeCalendarClient` + fake stores (as the import line on 353 already pulls in `FakeCalendarClient`), or wrap in a factory that tolerates a null tools object. Mirror the CAL-c fix needed at line 245. |
| CAL-b:226 | WARN | CODE DETAIL / deferred decision | Task 5 leaves the `_execute`-twin exclusion mechanism as an OR: "add `staging_dispatch_only=True` field to `ToolSpec` ... OR register twins in a separate internal registry ... Whichever mechanism M1-a chooses". Flash must pick; if M1-a's `ToolSpec` has no such field, adding one is an out-of-scope edit to an M1-a file not in Files-to-Change. | Pin the mechanism: state which one M1-a actually supports (e.g. "M1-a `ToolSpec` has field `staging_dispatch_only: bool = False`; use it") so Flash does not edit `manifest.py`/M1-a out of scope. |
| CAL-b:197,76-78 | WARN | CODE DETAIL | Task 4 (line 197) says "add `tool_name: str` to `WriteResult`" but Task 1's `WriteResult` definition (line 77) does not include it; the two are in the same spec and a literal executor building Task 1 first will create `WriteResult` without `tool_name`, then Task 4 amends it. Functional but the canonical definition is split across two tasks. | Add `tool_name: str` directly to the `WriteResult` definition on line 77 and drop the "additive fix" note on line 197. |

Note: classifier rules (lines 101–107), the AUTO/GATED `dispatch()` signature, the `stage(module, tool=f"calendar.{tool_name}", args, summary)` contract, the 11 write-tool args schemas, bare-`ToolSpec.name` rule (B9), and `_execute`-twin registration (B1) are all inlined correctly and consistent with GATE-a and CAL-a. `cache.invalidate(event_id, calendar_id)` two-arg (B4) is consistent.

---

## CAL-c-overlay-hooks.md — **BLOCK**

**2 BLOCK, 3 WARN**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| CAL-c:83,141,219 | BLOCK | CROSS-REF / contract drift | The `reject_proposal` body (Task 2, line 79) correctly calls `client.cancel_event(...)` per Seam 4 (CAL-a removed `delete_event`). But the **done-when on line 83** says "`reject_proposal` calls `delete_event`", the **Task 5 test on line 141** asserts "`FakeCalendarClient.delete_event` called", and the **Security note on line 219** references `write_event`. `delete_event` does not exist in the canonical `CalendarClient` Protocol (CAL-a line 97). A literal executor will either call a non-existent method (build break) or add a `delete_event` to the fake (contract violation, fails CAL-a/CAL-b). | In lines 83 and 141 replace `delete_event` with `cancel_event(row.google_event_id, recurrence_scope="THIS_EVENT", send_updates="none")`; on line 219 replace `write_event` with `CalendarWriteTools` method reference (CAL-b removed module-level `write_event` per B6, line 16). |
| CAL-c:245 | BLOCK | ACCEPTANCE / non-runnable check | The AC one-liner sets `tools = None` then calls `make_calendar_overlay_manifest(tools)` and iterates `t.name` over the result. `make_calendar_overlay_manifest` builds `ToolSpec`s with `callable_ref=overlay_tools.propose_reschedule` (line 123); `None.propose_reschedule` raises `AttributeError` at construction — the check fails 100% of the time as written, so the task can never satisfy its own AC. | Construct a real `OverlayTools(FakeCalendarClient(...), fake_store, fake_staging, FakeKeyProvider(...), CalPrefs())` in the one-liner instead of `tools = None` (same fix class as CAL-b line 353). |
| CAL-c:65 | WARN | CODE DETAIL / deferred decision | `_project_to_google` says set `extendedProperties` "by patching the returned event via `update_event` or by using the `extendedProperties` param if M1-a's client supports it — whichever is available; document the approach." `CalendarClient.create_event` (CAL-a lines 80–83) has NO `extendedProperties` param, and `update_event` takes `changes: dict` — so the marker must be written via a follow-up `update_event(event_id, {"extendedProperties": {...}})`. The "whichever is available" leaves Flash to guess; the create signature makes only one path valid. | Pin it: "create_event has no extendedProperties param (CAL-a); write the marker via a second call `client.update_event(google_event_id, {\"extendedProperties\": {\"private\": {\"artemis_overlay\": proposal_id}}}, recurrence_scope=\"THIS_EVENT\", send_updates=\"none\")`." |
| CAL-c:77,130 | WARN | CODE DETAIL | `approve_proposal` "Return type: `ProposalRow` (self-only) or `PendingAction` (gated)" (line 77), but the `OverlayTools.approve_proposal` wrapper must return `ProposalResult` (Pydantic, line 117/130) for `callable_ref` model_dump. The module-level function's union return vs the wrapper's `ProposalResult` mapping for the gated `PendingAction` case is unspecified — Flash must invent how a `PendingAction` becomes a `ProposalResult`. | Specify the wrapper mapping: "for the gated path, `OverlayTools.approve_proposal` maps the returned `PendingAction` to `ProposalResult(proposal_id=pa.id, status='staged_for_review', google_event_id=None)`." |
| CAL-c:55,136 | WARN | ENV PRE-CONDITIONS | Task 5 "fake `OverlayStore` (backed by a `tmp_path` SQLite via `sqlcipher_open` with a test key)" — same off-hardware `sqlcipher_open` availability assumption as GATE-a; unstated whether the M2-c shim works without the binding in CI. | Add the same one-line note as GATE-a: off-hardware `sqlcipher_open` is the plain-SQLite shim. |

Note: B1 infinite-staging fix (stage the underlying `calendar.update_event`/`calendar.create_event`, not `approve_proposal`) is correctly inlined (lines 75–76). The `classify(...)`/`CalendarSyncEngine.sync()`/`SyncResult` field names (B6) are inlined correctly. The two `delete_event` residues are the load-bearing defect.

---

## CAL-d-knowledge-memory-untrusted.md — **PASS** (WARN-only)

**0 BLOCK, 2 WARN**

| spec:line | BLOCK/WARN | check | what's wrong | minimal fix |
|---|---|---|---|---|
| CAL-d:94-99 | WARN | TASK ATOMICITY | Task 4 introduces a non-trivial new pattern (shared safe-claims cache + split sync `check_ref` / async `pre_flight` + changing `build_calendar_hooks` return type to a tuple) across 6 sub-steps, modifying CAL-c's `hooks.py`. The mechanism is described but the "shared safe-claims cache" lifetime/keying and how the sync `check_ref` knows which cache entries are current is left to Flash. | Add a concrete shape: "safe-claims cache = `dict[str, CalendarExtract]` keyed by `event_id`, module-level per factory; `check_ref` reads entries whose event_id is in today's window; pre_flight clears stale keys each run." |
| CAL-d:70,72 | WARN | ENV PRE-CONDITIONS | `push_past_meeting` "Raises `ScopeLockedError` if the pipeline's `is_unlocked()` returns False" (line 70) and the done-when tests `locked is_unlocked=False raises ScopeLockedError` (line 72). `IngestPipeline.is_unlocked()` is an M3-a method not inlined; if M3-a's pipeline exposes a different lock check, the raise path won't trigger. | Add to Assumptions: confirm `IngestPipeline.is_unlocked() -> bool` exists in M3-a (or name the actual guard) so Flash wires the correct check. |

Note: the `quarantine_event_text` chokepoint (trusted passthrough vs external quarantine), the `CachedEvent` field names (`summary` not `title`), the DR-a `QuarantinedReader.read(...)` signature, `Source.kind` widening to `"calendar_meeting"`, and the B12/Seam-5 sync-`check_ref`/async-`pre_flight` split are all inlined and self-consistent. The async `check_ref` ban (B12) is correctly enforced and verified by the AC on line 203.

---

## Area verdict

**BLOCK** — 2 specs block handoff: **GATE-a** (AC line 190 contradicts the Task 3 + Task 5 `ScopeLockedError` revert behaviour on the security-critical execute-once path) and **CAL-c** (residual `delete_event` references on lines 83/141 contradict the canonical `cancel_event`-only Protocol, plus a `tools=None` AC that can never pass). GATE-b, CAL-a, CAL-b, CAL-d are WARN-only and shippable; CAL-b and CAL-c share a `tools=None` non-runnable-AC defect that should be fixed together.

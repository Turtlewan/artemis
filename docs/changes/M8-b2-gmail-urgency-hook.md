---
spec: m8-b2-gmail-urgency-hook
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M8-b2 — Gmail proactive urgency hook (3-stage funnel: unread Important pre-filter → memory-boost → M6-b batched-LLM urgency briefing)

**Identity:** Adds the single Gmail `proactive_hook` to the `ModuleManifest`: a Tier-1 `HookSpec` (`needs_llm=True`, `interval_seconds=300`) whose `check_ref` runs Stages 1–2 (deterministic, LLM-free) and whose LLM-scored urgency briefing is produced by M6-b's batched-LLM hit-handling path over DR-a `QuarantinedReader` Extracts of the candidates.
→ why: see docs/technical/modules/gmail.md §E (end-state 3-stage funnel, Tier-1, graceful degradation) · docs/technical/adr/ADR-006-two-tier-proactivity.md (Tier-1 queued while locked) · docs/technical/adr/ADR-009-untrusted-content-and-deep-research.md (untrusted mail → quarantined Extract before LLM).

<!-- A spec is an EXECUTION SCRIPT, not a design doc. DeepSeek executes literally. -->

<!-- Split rule: ONE logical phase, 3 src files (hook module, urgency scorer, updated module manifest) + 1 test. The hook, its scorer, and the manifest registration are inseparable: the hook calls the scorer, the manifest wires the hook. The M6-b hit-handling engine (M8-b2's LLM execution path) is not touched. Atomic exception within the 3-file/2-phase budget. -->

## Assumptions
- **M8-b1** complete: `artemis.modules.gmail` exports `GmailReadCache` (with `list_unread(category: MailCategory | None) -> list[CachedMessage]`), `CachedMessage` (fields: `message_id`, `sender`, `unread`, `important`, `category`, `snippet`, `subject`, `internal_date_ms`), `GmailClient`, `MailCategory`, `MailCategory.SIGNAL_CATEGORIES`, `FakeGmailApi`, `build_gmail_manifest`. M8-b1's manifest ships `proactive_hooks=[]`; M8-b2 replaces that call with one that passes the hook. → impact: Stop (M8-b2 adds the hook to the manifest; M8-b1's `build_gmail_manifest` signature must accept a `hook: HookSpec | None = None` param OR M8-b2 defines its own `build_gmail_manifest_with_hook` factory — see Task 4).
- **M6-a** complete: `artemis.proactive.hook_types` exports `HookResult` (`HookResult.of(payload, dedup_value=None)`, `HookResult.miss()`), `Hit`, `TickResult`; `artemis.manifest` exports `HookSpec` (fields: `name`, `interval_seconds`, `cron`, `urgency`, `needs_llm: bool`, `tier: Literal[0,1]`, `dedup_key`, `check_ref: Callable[[], HookResult]`, `delivery: DeliverySpec | None`). The Gmail hook is `tier=1` (`data_scope=OWNER_PRIVATE`). `check_ref` must be LLM-free and deterministic. → impact: Stop.
- **M6-b** complete: `artemis.proactive.hit_handler` exports `HitHandler`, `TemplateRegistry`, `OutboundMessage`. A `needs_llm=True` hit flows through `HitHandler.handle(tick)` → ONE batched `model.complete` call that receives the hit's `result.payload` wrapped as `<<<{json.dumps(payload)}>>>` in the prompt. M6-b produces ONE `OutboundMessage` per `needs_llm` hit from the model's response line. M8-b2 does NOT modify `HitHandler`. Instead, M8-b2 provides: (a) the hook's `check_ref` that populates `result.payload` with pre-scored candidate data (Extract summaries from the async pre-flight), and (b) an `UrgencyTemplateRenderer` registered in the `TemplateRegistry` as a fallback when the model fails (M6-b degrades to the template on model failure — the template must produce a useful fallback). → impact: Stop (the hook is a data producer; M6-b's generic batch path scores it; no Gmail-specific scorer is injected into M6-b).
- **M6-c** complete with `pre_tick_steps` seam: `artemis.proactive.tier1_queue` exports `attach_to_heartbeat(heartbeat, queue, registry, key_provider, hit_handler, *, pre_tick_steps: list[Callable[[], Awaitable[None]]] | None = None)`; `artemis.proactive.compose_proactive` accepts `pre_tick_steps` and passes it through to `attach_to_heartbeat`. M8-b2 passes `[_pre_flight]` as `pre_tick_steps` at composition time so the `QuarantinedReader` pre-flight runs async before each tick, feeding results into `_extract_cell[0]` for `check_ref()` to read synchronously. → impact: Stop (without this seam the async pre-flight has no safe execution point inside the running event loop).
- **DR-a** complete: `artemis.untrusted` exports `QuarantinedReader(model, role).read(*, raw_content, source_url, source_domain, query, max_tokens) -> Extract` (async; toolless; schema-bounded), `Extract{source_url, source_domain, summary, claims, flagged_injection, parse_failed}`, `spotlight(content) -> (nonce, marked)`. The hook's `check_ref` runs synchronously (no `await`) and does NOT call `QuarantinedReader` — the `QuarantinedReader` call happens in an async pre-flight that runs BEFORE `check_ref` is invoked. See Task 2. → impact: Stop (M6-a's `check_ref` is called synchronously by `tick()`; all async work is staged outside).
- **M4-c** complete: `artemis.memory.store.SqliteMemoryStore` (via M0-d `MemoryStore`) exposes `recall(person_id: PersonId, query: str, k: int, as_of: AsOf | None) -> list[Fact]` (semantic search; embedding-backed). `Fact` carries `subject`, `relation`, `object` fields (M0-d `ports/types.py`; M4-a FTS5 indexes the `"subject relation object"` text blob per fact-version). M8-b2 uses a non-embedding Stage 2 path inside `check_ref` — see resolution below. → impact: Stop. RESOLVED (2026-06-09): M6-a states `check_ref` MUST be "deterministic, no LLM". `MemoryStore.recall` is embedding-backed (an embedder call), which violates this constraint. Stage 2 MUST NOT call `recall` inside `check_ref`. Instead, Stage 2 uses a **literal known-sender substring match** against a `frozenset[str]` of normalised sender identifiers pre-built outside `check_ref`. The `GmailUrgencyPreFilter` is constructed with an additional `known_senders: frozenset[str] | None = None` argument (a pre-computed set of lowercased display-name tokens and/or email local-parts obtained from memory at composition time — outside the tick). Inside `check_ref`, stage2_boost performs only a case-insensitive `candidate.sender.lower()` substring check against `known_senders` (no embedder, no model, O(n) string ops). This is fully deterministic and LLM-free. The `known_senders` set is built once per composition (at `build_gmail_urgency_hook` call time) using an async helper `async def build_known_senders(memory, person_id, k) -> frozenset[str]` that calls `memory.recall` with a broad "known contact person" query and extracts lowercased `fact.subject` and `fact.object` tokens. Callers (M6-c `compose_proactive`) must await this before constructing the hook. If `memory is None` or build fails, `known_senders = frozenset()` (all Stage 2 flags False — degrade-don't-crash).
- **M1-a** complete: `artemis.manifest` exports `ModuleManifest`, `HookSpec`, `DataScope.OWNER_PRIVATE`, `Permissions`, `ToolSpec`. M8-b2 extends `build_gmail_manifest` to include the urgency hook. → impact: Stop.
- **Off-hardware / graceful degradation:** Stage 1 (cache query) always runs if the vault is unlocked. Stage 2 (memory recall) degrades gracefully: if `MemoryStore` is `None` / unavailable, skip memory boost entirely — Stage 1 results are used as-is. Stage 3 (LLM scoring, M6-b path) degrades if no served model — the fallback template renders a plain unread-count line. Empty inbox (no candidates after Stage 1) → `HookResult.miss()` → M6-b never receives a hit → no model call. → impact: Caution (tests must cover all three degrade paths).
- The hook is **Tier-1** (owner-private data). It is queued and NOT run while the vault is locked (M6-a tier gate). M8-b2 adds NO unlock logic; the tier gate is M6-a's responsibility. → impact: Low.
- Real LLM scoring + real Gmail round-trips are **GATED on-hardware** (Task 6). Off-hardware tests use `FakeGmailApi`-backed `GmailReadCache`, `FakeModelPort`-backed `QuarantinedReader`, a `FakeMemoryStore` (for `build_known_senders` helper tests only — not used inside `check_ref`), and a pre-built `frozenset[str]` passed as `known_senders` to `GmailUrgencyPreFilter`. → impact: Stop (keeps M8-b2 CI-buildable off the Mini).

Simplicity check: considered a dedicated Gmail urgency scorer that M6-b calls via a registered handler interface — rejected: M6-b has no such per-module handler registry; it generically batches all `needs_llm` hits; the hook must produce its candidate data IN the payload and let M6-b's generic batch path score it. Considered running all three stages inside `check_ref` — rejected: Stage 3 requires async LLM calls which `check_ref` (synchronous) cannot make. Considered polling the Gmail API live in `check_ref` — rejected: the read-cache (M8-b1) is the awareness layer; `check_ref` queries the cache only. This is the minimum: a synchronous pre-filter + memory boost that populates the payload, letting the existing M6-b batched-LLM path do the scoring.

## Prerequisites
- Specs complete first: **M8-b1** (Gmail read-cache + `GmailReadCache.list_unread`), **M6-a** (`HookSpec`/`HookResult`/`Hit`/`TickResult`), **M6-b** (`HitHandler`/`TemplateRegistry` + `on_hits` batched-LLM path), **M6-c** (`attach_to_heartbeat` with `pre_tick_steps` seam + `compose_proactive`), **DR-a** (`QuarantinedReader`/`Extract`/`spotlight`), **M4-c** (`MemoryStore.recall`), **M1-a** (`ModuleManifest`/`HookSpec`).
- Environment: no new deps (reuses `google-api-python-client` from M8-a; `artemis.untrusted` from DR-a). Off-hardware fully testable with fakes. Real LLM scoring GATED on-hardware (Task 6).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/modules/gmail/urgency.py | create | `GmailUrgencyPreFilter` (Stages 1+2 pre-flight) + `UrgencyPayload` + `UrgencyTemplateRenderer` (M6-b fallback) |
| /Users/artemis-build/artemis/src/artemis/modules/gmail/hook.py | create | `build_known_senders(memory, person_id, k) -> frozenset[str]` (async, composition-time only) + `build_gmail_urgency_hook(cache, api, known_senders) -> tuple[HookSpec, Callable]` — the `HookSpec` factory; the LLM-free `check_ref` closure |
| /Users/artemis-build/artemis/src/artemis/modules/gmail/module.py | modify | add `hook: HookSpec | None = None` param to `build_gmail_manifest`; include it in `proactive_hooks=[hook] if hook else []` |
| /Users/artemis-build/artemis/tests/test_gmail_urgency_hook.py | create | Stage 1 pre-filter, Stage 2 memory boost, miss on empty inbox, miss on no-important, payload shape, template fallback render, off-hardware async pre-flight, manifest wiring |

## Tasks

- [ ] Task 1: `UrgencyPayload` type + `GmailUrgencyPreFilter` (Stages 1+2) — files: `/Users/artemis-build/artemis/src/artemis/modules/gmail/urgency.py` —

  Define `UrgencyPayload` (the M6-b payload shape the batched prompt receives):
  ```python
  @dataclass(frozen=True)
  class UrgencyCandidate:
      message_id: str
      sender: str          # display name only — NEVER a raw address in the payload
      subject: str         # subject line (untrusted; M6-b wraps the entire payload as <<<...>>>)
      snippet: str         # Gmail snippet (max 200 chars, truncated)
      known_to_memory: bool   # Stage 2 boost flag
      extract_summary: str    # DR-a Extract.summary (empty str if not yet fetched or fetch failed)
      extract_failed: bool    # True if QuarantinedReader parse_failed
  ```
  `UrgencyPayload` is NOT a separate class; it is `dict[str, object]` shaped as `{"candidates": [<UrgencyCandidate as dict>, ...], "unread_count": int}`. This dict is placed directly in `HookResult.of(payload=<the dict>, dedup_value=<today_iso>)`. M6-b serialises it as `json.dumps(payload)` inside `<<<...>>>`.

  `class GmailUrgencyPreFilter` constructed with `(cache: GmailReadCache, *, known_senders: frozenset[str] = frozenset(), max_candidates: int = 10)`:
  Note: `memory` and `person_id` are no longer constructor params; the resolved known-senders set is built outside `check_ref` by the `build_known_senders` async helper (see Task 3) and passed in here directly.

  - `def stage1_candidates(self) -> list[CachedMessage]`: call `cache.list_unread(category=None)` → keep only messages where `msg.unread is True AND msg.important is True AND msg.category in MailCategory.SIGNAL_CATEGORIES`. Sort by `internal_date_ms` descending. Return the top `self.max_candidates`. If the result is empty, return `[]`.

  - `def stage2_boost(self, candidates: list[CachedMessage]) -> list[tuple[CachedMessage, bool]]`: for each candidate, determine `known_to_memory: bool`:
    - If `self.known_senders` is empty: `known_to_memory = False` for all (degrade — no senders pre-built, or memory was None/unavailable at composition time).
    - Else: `known_to_memory = any(token in candidate.sender.lower() for token in self.known_senders)`. This is a pure O(n) string op — no embedder, no model call, LLM-free and deterministic per M6-a's `check_ref` constraint.
    - Return list of `(candidate, known_to_memory)` — preserve input order. No `try/except` needed here; the only failure path is `known_senders` being empty, which degrades cleanly.

  - `def build_payload(self, boosted: list[tuple[CachedMessage, bool]], extracts: dict[str, Extract]) -> dict[str, object]`: for each `(msg, known)`, build an `UrgencyCandidate` dict: `sender` = `msg.sender` (the display name from cache; NEVER includes a raw email address in the prompt payload — the sender field in `CachedMessage` stores the display name + email from Gmail's `From:` header; truncate to 100 chars); `subject` = `msg.subject[:200]`; `snippet` = `msg.snippet[:200]`; `known_to_memory = known`; look up `extracts.get(msg.message_id)` → if present and `not ex.parse_failed`: `extract_summary = ex.summary[:500]`, `extract_failed = False`; else `extract_summary = ""`, `extract_failed = True`. Return `{"candidates": [<dicts>], "unread_count": len(boosted)}`. NEVER include raw message body bytes, the full `From:` header, or the raw subject without truncation in the payload.

  `class UrgencyTemplateRenderer`:
  - `def render(self, result: HookResult) -> str`: the M6-b fallback template (registered in `TemplateRegistry` under `"gmail.gmail_urgency_check"`). Extracts `payload["candidates"]` and `payload.get("unread_count", 0)`. Returns a plain string: `f"{unread_count} unread important message(s): " + "; ".join(f"{c['sender']}: {c['subject']}" for c in candidates[:3])` (max 3 names/subjects in the fallback; no full body; no snippet). If `candidates` is empty, returns `"No urgent unread messages."`. This is the NO-LLM fallback path — it deliberately omits the extract content and urgency scoring.

  — done when: `uv run mypy --strict src` passes; `GmailUrgencyPreFilter(cache, known_senders=frozenset()).stage1_candidates()` over a `FakeGmailApi`-backed cache with mixed unread/important flags returns only `unread=True AND important=True AND category in SIGNAL_CATEGORIES` messages; `stage2_boost` returns `known_to_memory=False` for all when `known_senders=frozenset()`; `UrgencyTemplateRenderer().render(HookResult.of({"candidates": [], "unread_count": 0}))` returns `"No urgent unread messages."` (Task 5).

- [ ] Task 2: Async pre-flight for DR-a Extract fetching — files: `/Users/artemis-build/artemis/src/artemis/modules/gmail/urgency.py` (same file) —

  `async def fetch_extracts(api: GmailApiPort, reader: QuarantinedReader, candidates: list[CachedMessage], *, query: str = "urgent action required, important request, time-sensitive") -> dict[str, Extract]`:
  - For each candidate: `msg = api.get_message(candidate.message_id, fmt="full")`; `body = extract_body_text(msg)` (the M8-b1 MIME helper); if `body` is empty (no text body): skip (do not call the reader; no empty-string read). Call `ex = await reader.read(raw_content=body, source_url=f"gmail:{candidate.message_id}", source_domain="mail.google.com", query=query, max_tokens=512)`. Store in result dict keyed by `message_id`. Wrap each call in `try/except Exception`: on failure, omit the key (the builder will treat it as `extract_failed=True`). Never log the raw body or the Extract summary at info level.
  - Returns `dict[str, Extract]` (only successfully fetched keys; absent keys = fetch failed).
  - This function is called by the `check_ref` closure's surrounding async context. See Task 3 for how the synchronous `check_ref` accesses this result.

  **`check_ref` / async bridge pattern:** M6-a's `tick()` calls `check_ref()` synchronously. The `QuarantinedReader` is async. Resolve this by running the async pre-flight BEFORE the tick, storing the result in a mutable cell. The `check_ref` closure reads from the cell synchronously:
  - In `hook.py` (Task 3), the hook is constructed with a `pre_flight: Callable[[], Awaitable[None]]` and a `result_cell: list[dict[str, Extract]]` (a one-element mutable list). Before `Heartbeat.tick()` is called in `run_forever`, M6-c's `attach_to_heartbeat` runner awaits the pre-flight, which populates `result_cell[0]`. Then `check_ref()` reads `result_cell[0]` synchronously. If `pre_flight` was never called or raised, `result_cell[0]` is `{}` (empty dict) — the builder treats all extracts as failed, and Stage 1 still produces a useful briefing.
  - RESOLVED (2026-06-09): M6-c's `attach_to_heartbeat` (Task 4 of M6-c) is extended with a `pre_tick_steps: list[Callable[[], Awaitable[None]]] | None = None` parameter. Each step is `await`-ed in order BEFORE `heartbeat.tick()` inside the per-tick async runner; a raising step is caught and logged (degrade-don't-crash) and does not abort other steps or the tick. M8-b2 passes `_pre_flight` as the sole entry in `pre_tick_steps` when calling `compose_proactive` (M6-c Task 5). The off-hardware tests (Task 5) call `await pre_flight()` directly and are unaffected by this wiring. The M6-c spec amendment is already made (M6-c Task 4 + Task 5 + Task 6 test bullet updated).

  — done when: `uv run mypy --strict src` passes; `fetch_extracts` with a `FakeGmailApi` + `FakeModelPort`-backed `QuarantinedReader` returns a non-empty dict for messages with a text body; an empty-body message produces no entry; a reader failure produces no entry; the function is called with `await` and returns `dict[str, Extract]` (Task 5).

- [ ] Task 3: `build_known_senders` async helper + `build_gmail_urgency_hook` — files: `/Users/artemis-build/artemis/src/artemis/modules/gmail/hook.py` —

  First define:
  ```python
  async def build_known_senders(
      memory: MemoryStore,
      person_id: PersonId,
      *,
      k: int = 50,
  ) -> frozenset[str]:
  ```
  Called ONCE at composition time (outside any tick). Calls `memory.recall(person_id, query="known contact person name", k=k, as_of=None)`. For each returned `Fact`, extracts lowercased tokens from `f"{fact.subject} {fact.object}"` (the person-name bearing fields per M0-d `Fact.subject`/`Fact.object`; `relation` excluded to reduce false positives). Splits on whitespace and commas; strips empty tokens. Returns a `frozenset[str]` of all such tokens. Wraps the `recall` call in `try/except Exception` → on failure log one WARNING and return `frozenset()` (degrade-don't-crash). If `memory is None`, returns `frozenset()`.

  Then define:
  ```python
  def build_gmail_urgency_hook(
      cache: GmailReadCache,
      api: GmailApiPort,
      reader: QuarantinedReader,
      known_senders: frozenset[str],
      *,
      max_candidates: int = 10,
      interval_seconds: int = 300,
  ) -> tuple[HookSpec, Callable[[], Awaitable[None]]]:
  ```
  Note: `memory` and `person_id` are NOT params here; the caller (M6-c `compose_proactive`) must `await build_known_senders(memory, person_id)` first and pass the result as `known_senders`. This keeps `build_gmail_urgency_hook` synchronous and `check_ref` purely LLM-free.

  Returns `(hook_spec, pre_flight_coro_factory)` where `pre_flight_coro_factory()` returns an awaitable that runs the async pre-flight and stores results in the shared cell. The caller (M6-c `compose_proactive`) passes `pre_tick_steps=[pre_flight_coro_factory]` so the factory is called fresh each tick and its result awaited BEFORE `heartbeat.tick()` — ensuring `_extract_cell[0]` is populated before `_check_ref()` reads it.

  Implementation:
  - `_extract_cell: list[dict[str, Extract]] = [{}]` (one-element mutable shared between pre-flight and `check_ref`).
  - `pre_filter = GmailUrgencyPreFilter(cache, known_senders=known_senders, max_candidates=max_candidates)`.
  - `async def _pre_flight() -> None`: `candidates = pre_filter.stage1_candidates()`; if empty: `_extract_cell[0] = {}`; return early (no model calls needed). Fetch extracts: `extracts = await fetch_extracts(api, reader, candidates)`; `_extract_cell[0] = extracts`.
  - `def _check_ref() -> HookResult`: `candidates = pre_filter.stage1_candidates()`; if empty: return `HookResult.miss()`. `boosted = pre_filter.stage2_boost(candidates)`. `payload = pre_filter.build_payload(boosted, _extract_cell[0])`. `dedup_value = date.today().isoformat()` (one urgency check per day per vault unlock; same date ⇒ M6-b/c dedup). Return `HookResult.of(payload=payload, dedup_value=dedup_value)`.
  - Build and return:
    ```python
    hook = HookSpec(
        name="gmail_urgency_check",
        interval_seconds=interval_seconds,
        urgency="high",
        needs_llm=True,
        tier=1,
        dedup_key="gmail_urgency",
        check_ref=_check_ref,
        delivery=DeliverySpec(channel="ntfy", priority="high", tags=["mail","urgent"]),
    )
    return hook, _pre_flight
    ```
  - The `check_ref` is LLM-free (no model calls, no `await`, O(n) string ops only). `check_ref` does NOT call `reader.read` or any embedder.
  - NEVER log candidate subjects, senders, or Extract summaries at info level inside `_check_ref` or `_pre_flight`. Log only counts at debug level.

  — done when: `uv run mypy --strict src` passes; `build_gmail_urgency_hook(cache, api, reader, known_senders=frozenset())` returns a tuple `(HookSpec, Callable)`; the returned `HookSpec` has `needs_llm=True`, `tier=1`, `urgency="high"`, `dedup_key="gmail_urgency"`; `hook.check_ref()` returns `HookResult.miss()` when the cache has no unread-important messages; returns a `HookResult` with `hit=True` and a non-empty `payload["candidates"]` list when the cache has matching messages (Task 5).

- [ ] Task 4: Update `build_gmail_manifest` — files: `/Users/artemis-build/artemis/src/artemis/modules/gmail/module.py` (modify) —

  SURGICAL change only: add `hook: HookSpec | None = None` parameter to `build_gmail_manifest(api, cache, *, hook: HookSpec | None = None) -> ModuleManifest`. Change the `proactive_hooks` field: `proactive_hooks=[hook] if hook is not None else []`. No other change. The M8-b1 call without a hook still produces `proactive_hooks=[]` (backward-compatible).

  — done when: `uv run mypy --strict src` passes; `build_gmail_manifest(FakeGmailApi(...), cache)` returns a manifest with `proactive_hooks == []` (no regression); `build_gmail_manifest(FakeGmailApi(...), cache, hook=<a HookSpec>)` returns `len(proactive_hooks) == 1` and `proactive_hooks[0].needs_llm is True`.

- [ ] Task 5: Off-hardware tests — files: `/Users/artemis-build/artemis/tests/test_gmail_urgency_hook.py` — typed pytest with `FakeGmailApi`, a real `GmailReadCache` over a temp SQLCipher DB (via `FakeKeyProvider(owner_unlocked=True)`), a `FakeModelPort`-backed `QuarantinedReader`. No `FakeMemoryStore` needed — Stage 2 is now a pure frozenset substring check with no memory calls inside `check_ref`. Tests for `build_known_senders` use a `FakeMemoryStore` (implementing `MemoryStore` Protocol) only for the async builder helper tests.

  - **Stage 1 — pre-filter logic:** seed the cache with 5 messages: (a) `unread=True, important=True, category=PRIMARY` → INCLUDED; (b) `unread=False, important=True, category=PRIMARY` → excluded (not unread); (c) `unread=True, important=False, category=PRIMARY` → excluded (not important); (d) `unread=True, important=True, category=PROMOTIONS` → excluded (not signal category); (e) `unread=True, important=True, category=UPDATES` → INCLUDED. Assert `stage1_candidates()` returns exactly 2 messages (a and e) sorted newest-first.

  - **Stage 2 — known sender match:** `GmailUrgencyPreFilter(cache, known_senders=frozenset(["alice"]))` with two candidates (sender "Alice Smith" and sender "Bob Jones"): assert `stage2_boost(candidates)` returns `[(Alice Smith, True), (Bob Jones, False)]` (case-insensitive substring match of "alice" in "alice smith").

  - **Stage 2 — empty known_senders:** `known_senders=frozenset()` → all candidates get `known_to_memory=False`; no external calls made.

  - **build_known_senders — happy path:** `FakeMemoryStore.recall` returns `[Fact(subject="Alice", relation="is_contact", object="Boss")]`; `await build_known_senders(memory, person_id)` returns a `frozenset` containing `"alice"` and `"boss"` (lowercased subject + object tokens; relation excluded).

  - **build_known_senders — recall failure degrades:** `FakeMemoryStore.recall` raises `RuntimeError`; `await build_known_senders(memory, person_id)` returns `frozenset()` without raising; one WARNING logged.

  - **build_known_senders — memory None:** `build_known_senders(None, person_id)` returns `frozenset()` (the async helper accepts `memory: MemoryStore | None`).

  - **Miss on empty inbox:** cache has no unread-important messages → `check_ref()` returns `HookResult(hit=False)`; no call to `GmailApiPort.get_message`.

  - **Payload shape:** seed 2 unread-important-Primary messages; run `build_gmail_urgency_hook(cache, api, reader, known_senders=frozenset())`, call `pre_flight = coro_factory()`, `await pre_flight` (event loop); then `result = hook.check_ref()`. Assert `result.hit is True`; `result.payload["candidates"]` has 2 entries; each entry has keys `message_id`, `sender`, `subject`, `snippet`, `known_to_memory`, `extract_summary`, `extract_failed`; `result.payload["unread_count"] == 2`; `result.dedup_value == date.today().isoformat()`.

  - **Extract integrated:** pre-flight with a `FakeModelPort` that returns a valid extract JSON → `payload["candidates"][0]["extract_summary"]` is the extract's summary (non-empty); `extract_failed` is `False`.

  - **Extract failure degrades:** pre-flight with a `FakeModelPort` that returns non-JSON → `payload["candidates"][0]["extract_summary"] == ""`; `extract_failed is True`; `check_ref()` still returns `hit=True` (Stage 1 result drives the hit, not extract success).

  - **Template fallback renders:** `UrgencyTemplateRenderer().render(HookResult.of({"candidates": [{"sender": "Alice", "subject": "Meeting tomorrow"}], "unread_count": 1}))` returns a non-empty string containing "Alice" and "Meeting tomorrow".

  - **Template fallback — empty candidates:** `UrgencyTemplateRenderer().render(HookResult.of({"candidates": [], "unread_count": 0}))` == `"No urgent unread messages."`.

  - **Manifest wiring:** `build_gmail_manifest(FakeGmailApi(...), cache)` has `proactive_hooks == []`; `build_gmail_manifest(FakeGmailApi(...), cache, hook=hook_spec)` has `len(proactive_hooks) == 1` and validates (Pydantic model validator for `OWNER_PRIVATE ⇒ tier==1` passes).

  - **HookSpec validation:** the `HookSpec` returned by `build_gmail_urgency_hook` has `tier=1`, `needs_llm=True`, `urgency="high"`, `interval_seconds=300`, `dedup_key="gmail_urgency"`; building a `ModuleManifest(data_scope=OWNER_PRIVATE, proactive_hooks=[hook])` does NOT raise (M6-a's validator passes for tier=1 on an OWNER_PRIVATE module).

  — done when: `uv run pytest -q tests/test_gmail_urgency_hook.py` passes AND `uv run mypy --strict src tests/test_gmail_urgency_hook.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] Task 6 (GATED — on-hardware / owner-present): Real urgency scoring via served model + real Gmail read-cache — on the Mini, vault unlocked, served model running (M0-c), M8-b1 backfill complete, after composing the urgency hook into the `build_gmail_manifest_with_hook` path using `compose_proactive(..., pre_tick_steps=[pre_flight_coro_factory])`:
  (a) run one Heartbeat tick with the urgency hook registered; confirm `_pre_flight()` is awaited before `heartbeat.tick()` (M6-c pre_tick_steps seam), and that it calls `QuarantinedReader.read` for each candidate and never passes raw body to the main model;
  (b) confirm M6-b's `HitHandler` receives the hook as a `needs_llm` hit; its payload contains the extract summaries; one batched model call produces one urgency line;
  (c) confirm the `OutboundMessage` delivered to the ntfy sink has `disposition == "immediate"` (urgency `high`);
  (d) confirm no candidate subject/sender/body appears in any log at info level;
  (e) confirm the hook fires at most once per 5-minute interval (interval gating) and that the dedup key suppresses a duplicate notification for the same candidates within the day.
  — done when: (a)–(e) verified on the Mini and recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/modules/gmail/urgency.py, /Users/artemis-build/artemis/src/artemis/modules/gmail/hook.py, /Users/artemis-build/artemis/tests/test_gmail_urgency_hook.py |
| Modify | /Users/artemis-build/artemis/src/artemis/modules/gmail/module.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_gmail_urgency_hook.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fakes only; no network; no model) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/modules/gmail/urgency.py, src/artemis/modules/gmail/hook.py, src/artemis/modules/gmail/module.py, tests/test_gmail_urgency_hook.py |
| `git commit` | "feat: M8-b2 Gmail urgency hook — 3-stage unread-Important pre-filter + memory boost + M6-b batched-LLM briefing" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` / `ARTEMIS_DATA_ROOT` / `ARTEMIS_SLOT` | Settings + cache-DB path resolution (M0-a, used by GmailReadCache) |

### Network
| Action | Purpose |
|--------|---------|
| HTTPS to `www.googleapis.com` / `gmail.googleapis.com` (GATED, on-Mini only) | `fetch_extracts` calls `api.get_message` for full bodies of candidates. Trusted-connector egress (ADR-009 allowlist). No outbound in off-hardware tests. |
| local `127.0.0.1` calls to mlx-openai-server (GATED) | `QuarantinedReader` calls the local served model for extract scoring. No network in off-hardware tests. |

## Specialist Context
### Security
Gmail bodies are **UNTRUSTED** (attacker-controllable). The load-bearing invariant: the urgency scorer ONLY ever sees the DR-a `QuarantinedReader` `Extract` — NEVER raw mail bodies. This is enforced structurally: `check_ref` (synchronous) never calls `reader.read`; `fetch_extracts` (async pre-flight) calls `reader.read` with `response_schema` constrained-decoding, no tools, schema-bounded output. The `HitHandler` receives only the `Extract.summary` (a sanitised string ≤ 2000 chars) in the payload; M6-b's prompt wraps the entire payload in `<<<...>>>` (its own prompt-injection mitigation). Therefore:
- A malicious mail body that tries to inject instructions can only reach M6-b as an `Extract.summary` — quarantined, tool-free, schema-bounded.
- The `UrgencyPayload` includes only display name (truncated), subject (truncated, 200 chars), snippet (200 chars), and the Extract summary (500 chars) — not the raw body.
- Sender display name and subject are truncated before entering the payload; they ride inside M6-b's `<<<...>>>` boundary.
- `check_ref` has no egress surface (no network, no model calls, no logging of sensitive values at info).
- Pre-flight `fetch_extracts` MUST NOT log raw body content or Extract summaries at info; log only message counts at debug.
- The hook is Tier-1: it never runs while the vault is locked (M6-a gate enforces this at the `tick()` level).
- The `QuarantinedReader` constructor guard (DR-a: raises on a tools-exposing model) is relied upon — M8-b2 does not duplicate it but the `reader` passed to `build_gmail_urgency_hook` must be a `QuarantinedReader` instance (type annotation enforces this).
[apex-security review: all findings resolved in this spec — the quarantine boundary is structural (no raw body to brain), payload is bounded, sender/subject truncated, Tier-1 lock gate delegated to M6-a.]

### Performance
Stage 1 is a single cache query (SQLite, owner-private, fast). Stage 2 is ≤ `max_candidates` (default 10) O(n) frozenset substring checks — pure Python, no I/O, effectively free. `build_known_senders` (one `recall` + token extraction) runs once at composition time, not per tick. The async `fetch_extracts` pre-flight runs BEFORE the synchronous tick and is bounded to `max_candidates` local model calls; each is capped at `max_tokens=512`. M6-b makes ONE additional model call (the batch scoring) for the entire hook. Total per-tick: ≤10 local model calls (pre-flight) + 1 (M6-b batch), only when candidates exist. When the inbox is empty, all stages cost only one cache query.

### Accessibility
(none — headless proactive hook; the notification surface is ntfy / client Review-Status, not M8-b2's concern)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/modules/gmail/urgency.py | Type + docstring all exports; document the 3-stage funnel, the quarantine boundary (Extract only — never raw body), the graceful degrade paths (no memory / no served model / empty inbox) |
| Inline | src/artemis/modules/gmail/hook.py | Document the async bridge pattern (pre-flight cell + synchronous check_ref), the Tier-1 tier, and that check_ref is LLM-free |
| Inline | src/artemis/modules/gmail/module.py | Document the `hook` parameter (optional; backward-compatible; None = no proactive hook, M8-b1 behaviour) |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_gmail_urgency_hook.py` → verify: exit 0.
- [ ] Run `uv run pytest -q tests/test_gmail_urgency_hook.py` → verify: Stage 1 filters to unread+important+signal only; Stage 2 returns `known_to_memory=True` for a sender token in `known_senders` and `False` when `known_senders=frozenset()`; `build_known_senders` returns lowercased subject+object tokens and degrades to `frozenset()` on recall failure; empty inbox → `HookResult.miss()`; full payload shape (candidates list, unread_count, dedup_value=today); extract summary populated when pre-flight succeeds; extract_failed=True on model failure; hit=True even when extract fails (Stage 1 drives the hit); template renders non-empty string with sender+subject; template renders "No urgent unread messages." for empty candidates; manifest with hook has 1 hook with needs_llm=True, tier=1; manifest validator passes — all pass.
- [ ] Run `uv run python -c "from artemis.modules.gmail.hook import build_gmail_urgency_hook; print('ok')"` → verify: prints `ok` (import clean).
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini, owner-present) Real urgency pre-flight runs QuarantinedReader per candidate (never raw body to main model); M6-b receives one needs_llm hit; one batched model call produces one urgency line; OutboundMessage disposition is "immediate"; no body/subject in info logs; dedup suppresses re-notification same day → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

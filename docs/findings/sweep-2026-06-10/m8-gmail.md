# Sweep 2026-06-10 — M8 Gmail module (M8-a, M8-b1, M8-b2)

Reviewer scope: `docs/changes/M8-a-google-auth-foundation.md`, `docs/changes/M8-b1-gmail-connector.md`,
`docs/changes/M8-b2-gmail-urgency-hook.md`; context `docs/technical/modules/gmail.md`,
`docs/technical/adr/ADR-011-spoke-source-of-truth.md`. Cross-spec bindings verified against the live
M6-a / M6-b / M6-c / M3-a / M4-b / M4-c / DR-a / M2-b specs.

Severity counts: **BLOCK 6 · UPGRADE 5 · FLAG 9 · RESEARCH 3**

---

## BLOCK

### B1. `MailCategory.SIGNAL_CATEGORIES` does not exist (M8-b2 ↔ M8-b1 contradiction)
- **Cite:** M8-b2 Assumptions (M8-b1 bullet, line 18) + Task 1 `stage1_candidates` ("`msg.category in MailCategory.SIGNAL_CATEGORIES`"); M8-b1 Task 1.
- M8-b1 defines `SIGNAL_CATEGORIES: Final = frozenset({...})` as a **module-level** constant in `client.py` — not an attribute of the `MailCategory` StrEnum (a frozenset class attribute on a `StrEnum` is not even constructible — non-`str` member value). M8-b1's `__init__.py` re-export list (`Files to Change` + Task 1) also does **not** re-export `SIGNAL_CATEGORIES`, so M8-b2 cannot import it from `artemis.modules.gmail` at all. A literal executor writes `MailCategory.SIGNAL_CATEGORIES` → `AttributeError` at runtime / mypy failure.
- **Fix:** M8-b2 references module-level `SIGNAL_CATEGORIES`; M8-b1 adds it to the `__init__.py` re-exports.

### B2. `gmail.list_threads` / `gmail.get_thread` have no backing interface
- **Cite:** M8-b1 Task 5 (tools) vs Task 1 (`GmailApiPort`).
- The port exposes only `list_message_ids`, `get_message`, `list_history`, `get_attachment`, `current_history_id`. There is **no `list_threads` / `get_thread` method** (Gmail `users().threads().list/get`), and no specified cache-based alternative (e.g. group `GmailReadCache` rows by `thread_id`). Two of the five tools are unimplementable as specified; DeepSeek cannot invent the missing port methods. Related sub-gap: `gmail.search` must return `MessageRef`s (sender/subject/snippet/date) but `api.list_message_ids` returns only ids — the id→metadata hydration step (per-id `get_message(fmt="metadata")` vs `cache.get`) is unspecified.
- **Fix:** add `list_threads`/`get_thread` to `GmailApiPort` + `FakeGmailApi` (or spell out the cache-group implementation), and state exactly how `search` hydrates refs.

### B3. `list_history` port cannot supply the "new latest historyId" for the cursor
- **Cite:** M8-b1 Task 4 (`incremental()`: "After paging, `cache.set_cursor(<new latest historyId>)`") vs Task 1 port signature `list_history(...) -> tuple[list[Mapping], str | None]`.
- The Gmail `history.list` response carries a top-level `historyId` (the value the next sync should start from), but the port returns only records + page token, so the specified cursor update is unimplementable through the port. The only fallback an executor has is `current_history_id()` (`getProfile`), which is sampled **after** applying records — any change landing between the last history record and the profile call is silently skipped forever. Missing interface → wrong build.
- **Fix:** widen `list_history` to also return the response `historyId` (e.g. `tuple[list[Mapping], str | None, str]`) and state that the final page's value becomes the cursor.

### B4. Raw sender-controlled text reaches privileged models — contradicts the dual-LLM quarantine posture (and M8-b2's own security section)
- **Cite:** M8-b1 Assumption "Metadata-only tool results … returned plain" + Task 5 + Specialist Security; M8-b2 Task 1 `UrgencyCandidate` (`subject`, `snippet`) + Specialist Security ("the urgency scorer ONLY ever sees the DR-a `Extract` — NEVER raw mail bodies"); M6-b Task 2 (payload → `<<<json>>>` in the responder-model prompt).
- Two paths ship raw attacker-controlled email text to a privileged model:
  1. **M8-b1 tools:** `gmail.search` / `gmail.list_unread` return sender, **subject**, and **snippet** plain (unspotlighted) into the tool-bearing brain's context. A Gmail **snippet is a body excerpt** (the first ~chars of the message body, attacker-authored), and a subject line can carry injection text verbatim ("Ignore previous instructions…"). The spec's rationale ("metadata does not constitute instructions") is false for subject/snippet — they are free-text sender-controlled fields, exactly the canonical injection vector ADR-009 names.
  2. **M8-b2 payload:** `UrgencyCandidate.subject` and `.snippet` (raw, only truncated) enter M6-b's batched `responder`-model prompt protected solely by `<<<...>>>` delimiting — which is M6-b's generic mitigation, **not** the dual-LLM quarantine. This directly contradicts M8-b2's own Specialist Security claim that the scorer "ONLY ever sees the DR-a Extract."
- **Fix (minimum):** drop `snippet` from plain tool results and from the urgency payload (the Extract `summary` already covers content); either spotlight `subject` at these boundaries or substitute Extract-derived text. If subject/snippet plainness is a deliberate accepted risk, the M8-b2 security section must stop claiming Extract-only and the ADR-009 posture doc must record the exception.

### B5. `UrgencyTemplateRenderer` is never registered — no seam exists to register it
- **Cite:** M8-b2 Task 1 ("registered in `TemplateRegistry` under `\"gmail.gmail_urgency_check\"`") + Assumption (M6-b bullet: "the template must produce a useful fallback"); M6-c Task 5 (`compose_proactive` constructs `TemplateRegistry` internally; signature `compose_proactive(settings, registry, key_provider, model, *, pre_tick_steps=…)` — no templates parameter); M6-b Task 1 (`TemplateRegistry.register(fq_name, fn)`).
- No M8-b2 task or file performs the registration, and the documented composition entry point (`compose_proactive`) offers no way to inject it. Result: on model failure M6-b falls back to the registry's payload-free default `"gmail.gmail_urgency_check: update"`, defeating the spec's required "useful fallback" — and the renderer class ships as dead code.
- **Fix:** amend M6-c `compose_proactive` with a `templates: list[tuple[str, Callable[[HookResult], str]]] | None` (or expose the built `TemplateRegistry`), and add an explicit M8-b2 wiring step `registry.register("gmail.gmail_urgency_check", UrgencyTemplateRenderer().render)`.

### B6. `UrgencyCandidate.sender` self-contradiction: "display name only" vs "display name + email"
- **Cite:** M8-b2 Task 1 — dataclass comment `sender: str  # display name only — NEVER a raw address in the payload` vs `build_payload` ("`sender` = `msg.sender` … the sender field in `CachedMessage` stores the display name **+ email** from Gmail's `From:` header; truncate to 100 chars").
- Truncation does not remove the address; M8-b1 `_to_cached` stores the full `From:` header. A literal executor cannot satisfy both sentences, and no display-name parsing helper (`email.utils.parseaddr`) is specified.
- **Fix:** specify `sender = parseaddr(msg.sender)[0] or msg.sender.split("@")[0]`-style extraction (exact code), or delete the "NEVER a raw address" constraint.

---

## UPGRADE

### U1. Backfill cursor race loses mail that arrives during backfill
- **Cite:** M8-b1 Task 4 `backfill()` ("After paging, `cache.set_cursor(api.current_history_id())`").
- A 12-month backfill is a long paged pass (potentially hours, see U3). Sampling the `historyId` **after** paging means any message arriving mid-backfill whose page was already listed is never seen by `backfill` and is below the cursor for `incremental` — silently lost. Standard History-API practice: capture `current_history_id()` **before** the first `messages.list` page and set it as the cursor after; the overlap is harmless because `upsert` + M3-a `content_hash` are idempotent (the spec already relies on this for re-runs).

### U2. Urgency hook re-spends ~10 quarantine model calls + N API fetches every 5-minute tick; date-only dedup suppresses NEW urgent mail
- **Cite:** M8-b2 Task 3 (`_pre_flight` refetches all candidates each tick; `dedup_value = date.today().isoformat()`); Task 6(e) ("dedup … for the same candidates within the day" — does not match a date-only value).
- Unread+important candidates persist across ticks until read, so the pre-flight redoes `get_message(full)` + `QuarantinedReader.read` for the same messages up to 288×/day, while the date-valued dedup means only the first briefing of the day is ever delivered — including when a *new* urgent message arrives at 2pm (it is deduped until midnight). Both halves are wrong-shaped for an "urgency" feature.
- **Fix:** (a) memoize extracts per `message_id` in `_extract_cell` (skip already-extracted candidates); (b) `dedup_value = sha256("|".join(sorted(candidate_ids)))[:16]` (or date + ids) so a changed candidate set re-notifies; aligns Task 6(e) wording with behavior.

### U3. No 429/5xx retry or backoff anywhere; backfill will hit Gmail per-user quota
- **Cite:** M8-b1 Tasks 1/4; gmail.md §C.
- Gmail enforces ~250 quota units/sec/user (`messages.get` = 5 units); a 12-month sequential backfill (easily tens of thousands of gets) **will** receive 429/`rateLimitExceeded`, and Task 4's backfill has no per-call error handling (incremental has per-record degrade; backfill has none) — one transient error aborts the pass. Add bounded exponential backoff on 429/5xx (e.g. `googleapiclient`'s `num_retries` or an explicit retry wrapper on `GmailClient`), and consider the Gmail HTTP batch endpoint (`POST /batch/gmail/v1`, ≤50 gets/request — still supported; only the *global* batch endpoint was retired) to cut backfill wall-time and request count by ~50×.

### U4. Sync `googleapiclient` calls inside async code block the heartbeat event loop
- **Cite:** M8-b2 Task 2 `fetch_extracts` (calls `api.get_message` — synchronous HTTP — inside an `async def` awaited by M6-c's per-tick runner); same pattern in M8-b1 `backfill()`/`incremental()` if ever run on the loop.
- Up to `max_candidates` blocking network round-trips stall every other pre-tick step and the tick itself. Wrap port calls in `await asyncio.to_thread(api.get_message, …)` (one line; keeps the port sync).

### U5. Notification text carries raw subject/sender unsanitized into ntfy
- **Cite:** M8-b2 Task 1 `UrgencyTemplateRenderer.render` (`f"{c['sender']}: {c['subject']}"`); M6-b Task 2 LLM line path.
- Showing sender/subject to the owner is the feature, but the strings should be sanitized for the transport: strip CR/LF + control chars (ntfy header/body shaping, log hygiene) and HTML-entity-unescape the Gmail snippet/subject (the API returns snippets HTML-escaped, so the owner otherwise sees `&amp;#39;`). One small `sanitize_line(s: str) -> str` helper applied at payload-build time.

*(Minor, no separate entry: M8-a Task 4 builds `Credentials` from `oauth_config.client_id` while `StoredToken.client_id` is stored but never used — either use the stored value or document the field as display-only alongside `obtained_at_ms`.)*

---

## FLAG

### F1. M8-a acceptance criterion not runnable as written
- **Cite:** M8-a Acceptance Criteria ("Run `uv run artemis-google-auth status` (empty in-memory store via test seam) → prints 'no Google account paired' and exits 0") + Task 5.
- A shell invocation of the console script cannot use a pytest monkeypatch seam; the real `main` builds the real `SqlCipherTokenStore` + broker `KeyProvider`, which off-hardware fails (no broker). Either specify the seam concretely (e.g. an `ARTEMIS_FAKE_KEYPROVIDER=1` test env branch — undesirable) or move this assertion into `test_google_auth.py::test_cli_status` and make the shell criterion merely "exits without traceback".

### F2. `extract_body_text` HTML-stripping method unspecified
- **Cite:** M8-b1 Task 1 ("prefer `text/plain`, else strip `text/html`").
- "Strip" is not executable: no library is named, and the spec says "no new deps". Specify stdlib `html.parser.HTMLParser` subclass (collect text nodes, skip `script`/`style`, `html.unescape`) — or permit reuse of M3-a's `trafilatura` if intended.

### F3. `gmail.search` locked-fallback sentence is a parse trap
- **Cite:** M8-b1 Task 5 ("falling back to `cache.search_metadata` when locked is NOT applicable — tools run only when unlocked").
- Double-negative phrasing; a literal executor may build a locked-fallback the sentence intends to prohibit. Rewrite: "Do NOT implement a locked fallback; tools execute only with the vault unlocked. `cache.search_metadata` is not used by `gmail.search`."

### F4. M8-b2 Files-to-Change note contradicts Task 3 signature
- **Cite:** M8-b2 Files to Change (`hook.py`: "`build_gmail_urgency_hook(cache, api, known_senders)`") vs Task 3 (`(cache, api, reader, known_senders, *, max_candidates, interval_seconds)`).
- The table omits `reader`. State the Task 3 signature is canonical (or fix the table) so the executor doesn't drop the parameter.

### F5. Spotlight nonce discarded at the tool boundary
- **Cite:** M8-b1 Task 5 (`body_spotlighted = spotlight(extract_body_text(msg))[1]`); DR-a Task ("The caller formats `SPOTLIGHT_INSTRUCTION` with the same `nonce`").
- The DR-a contract pairs the marked block with a nonce-formatted system instruction; the tool drops the nonce, so the brain boundary can never format it. Forged-marker stripping makes a *generic* `<<UNTRUSTED:` instruction safe, but that convention is nowhere stated. Specify it (one line in Task 5 + the brain-boundary doc) or return the nonce in `MessageDetail`.

### F6. Stage-1 candidate set deviates from the design doc
- **Cite:** M8-b2 Task 1 `stage1_candidates` (all SIGNAL categories) vs gmail.md §E Stage 1 ("unread in **Primary** AND … Important").
- Broadening to Updates/Forums may be intended, but the source-of-truth doc says Primary-only. Confirm and align one of the two (a literal executor follows the spec; a future reviewer follows gmail.md).

### F7. `_extract_cell` retains stale extracts on pre-flight failure
- **Cite:** M8-b2 Task 2 ("If `pre_flight` was never called or raised, `result_cell[0]` is `{}`") vs Task 3 `_pre_flight` (only assigns the cell on success or on the empty-candidates early-return).
- If `fetch_extracts`' surrounding code raises (M6-c catches it), the cell keeps the previous tick's dict — the stated `{}` guarantee is not implemented by the given code. Benign today (lookup is by `message_id`) but add `_extract_cell[0] = {}` as the first statement of `_pre_flight` to make the spec text true. Related nit: pre-flight and `check_ref` each call `stage1_candidates()`; drift between the two calls degrades to `extract_failed=True`, which is acceptable — note it inline so the executor doesn't "fix" it by caching candidates.

### F8. `scope` typing: `str` vs M3-a `Source.scope: Scope`
- **Cite:** M8-b1 Task 4 (`GmailSync(..., scope: str = OWNER_PRIVATE)`), Task 3 (`Source(kind="email", uri=..., scope=scope)`); M3-a Task (`Source { …, scope: Scope }`); M2-b Task 1 (`OWNER_PRIVATE: Scope = "owner-private"`).
- Works if `Scope` is a plain `str` alias (M2-b's f-string `guest_scope` implies it is), but under `mypy --strict` an annotated alias/NewType would fail. Annotate `scope: Scope` in M8-b1 and import it — costless and removes the ambiguity.

### F9. `PARSEABLE_MIME` members not given as exact MIME strings
- **Cite:** M8-b1 Task 3 ("`PARSEABLE_MIME` set: pdf/docx/pptx/md/html/txt").
- Attachment parts carry full MIME types (`application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, …). The shorthand list is not executable; DeepSeek may invent wrong strings. Enumerate the literal set in the spec (and decide whether `text/markdown` vs extension-sniffing applies for `.md`).

---

## RESEARCH

### R1. Refresh-token longevity for a production-unverified app on a RESTRICTED scope (M8-a load-bearing assumption)
- **Cite:** M8-a Assumptions ("published / in production, unverified … avoids the 7-day refresh-token expiry") + Task 7 done-when; M8-b1 registers `gmail.readonly`.
- `gmail.readonly` is a **restricted** (not merely sensitive) scope. The documented 7-day expiry attaches to *Testing* status, and the spec's assumption matches the docs — but Google's policy for **unverified production apps holding restricted scopes** has shifted before (100-user caps, warning interstitials, and reports of grant/refresh limitations), and verification for restricted scopes normally requires a CASA security assessment. Verify the mid-2026 policy before bring-up; the mitigation (re-consent via `ReauthRequiredError` → `artemis-google-auth login`) already exists, but if expiry is recurrent the owner-present re-consent becomes a recurring chore worth a planning note. Alternative worth checking: a Google Workspace account with an *Internal* OAuth app sidesteps verification entirely.

### R2. Confirm the M6-b `responder` role model is toolless for the batched urgency call
- **Cite:** M6-b Task 2 (`HitHandler(..., responder_role="responder")`); M8-b2 Specialist Security.
- B4's blast radius depends on whether the responder model can call tools. DR-a's `QuarantinedReader` enforces toollessness by constructor guard; M6-b's batch call has no such guard stated. Verify the M0-d `ModelPort`/role wiring used by `HitHandler` is toolless; if it is not, B4 escalates from "injection into notification text" to "injection adjacent to tool execution" and the payload must become Extract-only before build.

### R3. Expired-`startHistoryId` surfacing in `google-api-python-client`
- **Cite:** M8-b1 Task 4 ("A `404`/expired-historyId from Gmail → raise `HistoryExpiredError`").
- Confirm during build that an expired/too-old `startHistoryId` surfaces as `googleapiclient.errors.HttpError` with `resp.status == 404` (the documented behavior) and pin the except clause to exactly that (`except HttpError as e: if e.resp.status == 404`), so other `HttpError`s (403 rate-limit, 5xx) are not misclassified as cursor expiry and silently trigger a full re-backfill.

---

## Verified-sound (no finding)
- M8-b2 ↔ M6-c `pre_tick_steps` binding: signature, factory-call-then-await semantics, degrade-don't-crash, and the M6-c Task 6 call-order test all match — fully specified on both sides.
- M6-b template key convention `f"{module}.{hook_name}"` → `"gmail.gmail_urgency_check"` matches (registration seam itself is B5).
- M8-a ↔ M8-b1: `register_google_scopes` / `GoogleCredentialsFactory.authorized_credentials()` / `ReauthRequiredError` usage consistent; no duplicate auth code in b1.
- DR-a `QuarantinedReader.read(...)` kwargs and `Extract` fields match both b1 (memory extraction) and b2 (pre-flight) call sites; caller-supplied provenance (`gmail:{id}`, `mail.google.com`) honors DR-a's provenance-integrity rule.
- M4-b `MemoryWriteQueue.enqueue(text, turn_id, role=None)` and M4-c `recall(person_id, query, k, as_of)` match b1/b2 usage; b2's LLM-free `check_ref` resolution (pre-built `known_senders` frozenset, no embedder in-tick) correctly honors M6-a's deterministic-check constraint.
- M8-a OAuth mechanics are current best practice (loopback installed-app + PKCE + `prompt=consent`/`access_type=offline`, no hardcoded `redirect_uris`, library `state` CSRF check, `invalid_grant` exact-prefix → `ReauthRequiredError`); token tier (owner-private SQLCipher via broker DEK, Tier-1, never Tier-0) is correct per ADR-005/006.
- ADR-011 conformance: read-only mirror, `gmail.readonly` only, no send/modify/label plumbed anywhere; Gmail-authoritative cache (`mark_removed` deletes, no tombstone ownership).
- Over-engineering: none material — split-depth ingest, single-row token store, and the 3-stage funnel are each the minimum for their stated requirement; the b1/b2 split matches the file/phase budget rules.

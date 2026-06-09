# Finalization / readiness-gate notes — core spec drafts (M0–M7)

_Accumulated fixes to apply when readiness-gating the `docs/drafts/m{0..7}/` specs and moving them to
`docs/changes/` for the batch handoff. Front-load-all-specs strategy: nothing builds until the Mac Mini
arrives, so these are applied in one gate pass before handoff. Last updated 2026-06-04._

## Cross-cutting
- [ ] **Data root = `/opt/artemis`** (resolved). Apply consistently across M0 specs.
- [ ] **Reconcile code-path vs data-path:** repo/code at `/Users/artemis-build/artemis` (build-user home) vs runtime data `/opt/artemis` + per-scope encrypted volume mount point. Ensure deployed-code location + service working dirs are coherent.
- [ ] **Readiness-gate every spec** (apex-plan gate) then move `docs/drafts/m{0..7}/` → `docs/changes/`.
- [ ] Accept justified split-rule exceptions: M0-a (repo bootstrap), M0-d (ports package), M1-a (manifest contract), M4-a (schema+repo+golden tests) — atomic units > 3 files.

## M0
- [ ] Marker resolutions: ntfy install in M0; `as_of` = `AsOf(valid_at, tx_at→now)` (bitemporal, ADR-004); backup skeleton runs over sample/empty DBs; **mlx-openai-server pkg/CLI name = on-hardware confirm**; **Claude Code sandbox config schema = on-hardware confirm**.
- [ ] **Add a local `extractor` role = lazy-loaded Qwen3-14B** to `roles.toml` (M0-a) — the local heavy-reasoner / sensitive memory-extraction model (brain.md). Distinct from cloud `claude-cli` teacher.

## M1
- [ ] **ModelPort: wire the local `extractor` role** (Qwen3-14B lazy) alongside responder/embedder (M4-b depends on it).

## M2 (security wall)
- [ ] **Broker gains volume-mount** (ADR-005/007): on phone-attested unlock, the broker mounts the per-scope encrypted volume (holds the LanceDB doc index + the SQLCipher memory DB) in addition to releasing the DEK. Add to M2-a/M2-c.
- [ ] Confirm SE-signed-keypair as the M2 concrete `UnlockProof` verifier (App Attest = gated alternative behind the same protocol).
- [ ] `.userPresence` degradation check (doesn't silently become login-unlock) — on-hardware.
- [ ] SQLCipher Python binding decided at the M4 sqlite-vec spike (APSW+sqlite3mc vs sqlcipher3) — propagate to M2-c.
- [ ] Tier-0 "boot-unwrappable" proactive-key policy: decide owner (M2-a explicit policy vs M2-c reservation).
- [ ] **apex-security threat-model gate (M2-d) must pass before M3/M4** in the build order (focus: prompt-injection DEK exfiltration).

## M3 (knowledge layer)
- [ ] M3-a depends on the M2 volume-mount step — confirm the exact volume path + `is_owner_unlocked()` seam (M2-c task vs a new M2-e).
- [ ] LanceDB native-hybrid+RRF vs explicit dense+FTS+our-RRF (drafted both); Qwen3-Reranker endpoint shape (`/v1/rerank` vs constrained-decoded scores) — resolve at build.
- [ ] Visual-doc model + resident-vs-lazy + ColPali-in-v1 = gated sizing spike.

## M4 (memory)
- [ ] **Fact-keying → Option 2 (relation-cardinality registry)** (ADR-004 refinement): add a `relation → SINGLE|MULTI` registry (seed + default-MULTI + one-shot teacher classify + owner override); SINGLE keys on (subject,relation), MULTI on (subject,relation,object); decider respects cardinality. Apply to M4-a (schema/keying + registry) + M4-b (decider) + adjust the 2 affected golden tests.
- [ ] Fold `bump_access` + `purge` primitives into M4-a's `repository.py` (M4-c adds them).
- [ ] sqlite-vec-under-SQLCipher smoke test (M4-a Task 1) = on-hardware; small-model A.U.D.N. accuracy eval (M4-b Task 6) = on-hardware; decay tuning (M4-c Task 6) = on-traces.

## M5 (voice) — drafted + reviewed
- [ ] **Streaming brain (M1 back-fill):** add `Brain.respond_stream` (text-segment stream; responder ModelPort already supports `stream=True`) — required by M5-d sentence-streaming TTS + brain.md "stream every stage". Touches M1-b.
- [ ] **Gateway pre-route hook:** add `Brain.pre_route(text, scope) -> module | None` so the Gateway can classify Tier BEFORE serving (M5-c needs the matched module pre-serve to withhold sensitive data).
- [ ] **Voiceprint store = Tier-0-keyed, hardened (resolved):** embeddings-only (discard raw enrolment audio) + encrypted under the Tier-0 SE key + never-logged + minimised contents; blast radius bounded by voice-ID≠key. Anti-spoof/liveness + voiceprint rotation = noted for later. apex-security reviews at the M2/M5 gate.
- [ ] Tier classifier is a minimal sensitive-module set (`finance/health/journal/memory`) — explicit stand-in for the full sensitivity router (later); confirm M1-a manifest carries a usable sensitivity flag.
- [ ] On-hardware confirms: wake/VAD runtime (ONNX vs CoreML) · Parakeet-MLX/MLX-Whisper/Kokoro-MLX/SpeechBrain-ECAPA package names · Kokoro in-process-resident vs separate server · single multiplexed audio socket vs split · instant-ack earcon-vs-spoken · ECAPA threshold · all the real-audio/AEC/latency gated tasks.
- [ ] Unknown speaker = single shared guest in M5 (per-guest clustering = later).

## M6–M7 — REVIEWED 2026-06-08 (4 dispatched reviewers: apex-security×M6, apex-security×M7, apex-jobs×M6, apex-ai-systems×M7 + planning self-review)
_Haul: 9 BLOCK · 29 FLAG · 10 note. BLOCKs must be resolved in-spec before gate→`docs/changes/`. Full per-finding detail was in the reviewer transcripts; actionable summary below._

> **✅ APPLIED 2026-06-08:** all M6 + M7 fixes baked into the specs — M6-a/b/c hardened; **M7-a sub-split → M7-a1 / M7-a2 / M7-a3** (old monolithic M7-a deleted); M7-b/c fixed. All `[NEEDS CLARIFICATION]` markers resolved + EOF artifacts stripped (grep-verified clean). **M6/M7 are gate-ready** — awaiting the M0–M5 gate, then the batch move to `docs/changes/`. (The tracing FLAG is routed to the new telemetry spec, IG2.)

### Drafting artifacts (mechanical — strip at gate)
- [ ] **Stray EOF tags:** M7-a ends with `</content></invoke>` (lines ~164–166); M7-b `</content>` (~131); M7-c `</content>` (~153). Remove.

### M6 — BLOCKs
- [ ] **B1 (sec) ntfy topic is a guessable capability** (M6-c Task 3): `artemis-{slot}-owner` lets anyone reaching 127.0.0.1:{NTFY_PORT} (incl. a Tailscale peer / local process) subscribe to all notification bodies. Fix: cryptographically-random per-slot suffix generated at slot-init + stored in non-public Settings (`artemis-{slot}-{rand_hex16}`), OR ntfy `--auth` per-topic tokens. Add a non-guessability assertion.
- [ ] **B2 (sec) Tier-1 drain TOCTOU** (M6-c Task 4): `drain()` checks `is_owner_unlocked()` once at entry; must **re-check before EACH `check_ref()`** in the loop and abort remaining entries if the lock closes mid-drain. Add a test: unlocked for entry, re-locked before 2nd entry → 2nd `check_ref` NOT called.
- [ ] **B3 (jobs) `run_forever` graceful shutdown** (M6-a Task 3): add `try/finally`; cancellation point = the inter-tick sleep (never mid-tick); flush `tier1_sink` + log clean-shutdown on `CancelledError`.
- [ ] **B4 (jobs) Tier-1 drain = unbounded retry storm** (M6-c Task 4): a permanently-failing queued hook re-runs every unlocked tick forever. Add `retry_count` to `QueuedHook` + `max_drain_attempts` (≈5) → move to `tier1_dead.json` DLQ + warn.
- [ ] **B5 (jobs) drain silently loses hits on delivery failure** (M6-c Task 4): ntfy degrades-don't-crash so `handle()` doesn't raise → entry removed as "success" but notification dropped. Fix: `NtfyDelivery` returns success count; remove queue entry only on confirmed delivery, else re-queue toward the DLQ.

### M6 — FLAGs
- [ ] **Template raw-payload dump** (M6-b Task 2): default template `f"{fq}: {result.payload}"` leaks every payload field over the wire. Add `notification_fields: list[str]` allow-list on `HookSpec`; default render only allow-listed keys. Test: extra field absent from body.
- [ ] **Atomic write must be same-dir** (M6-c Task 2/4; sec+jobs): temp file in `target.parent` (`tempfile.NamedTemporaryFile(dir=target.parent)`) — cross-device `os.replace` raises on APFS. Applies to dedup/tier1_queue/held.
- [ ] **Payload→LLM prompt injection** (M6-b Task 2): hit payloads f-string-interpolated into the batched prompt (e.g. a calendar title "ignore previous instructions…"). Use a delimited/JSON-block structure so payload is unambiguously data, not instructions.
- [ ] **Action-URL allow-list** (M6-c Task 3): `_render_actions` must validate each action `url` against permitted schemes/origins (`artemis://`, `https://127.0.0.1`, …) before embedding in the device-rendered button.
- [ ] **`held.json` is unsafe + undeclared** (M6-c Task 3; sec+jobs merged): (a) it persists `OutboundMessage` bodies (incl. LLM prose) at rest — bound contents + a `held_ttl_hours` (≈8) drop-if-stale; (b) it's missing from the Files-to-Change table + has no atomic-write spec — add it, same-dir atomic; (c) corrupt-JSON load → warn + start empty (don't crash `flush_held`).
- [ ] **Cron missed-tick** (M6-a Task 3): exact-minute `now.hour==H and now.minute==M` means a 1-min tick slip skips the daily briefing forever. Fire if `now_wall >= (H:M today) AND last_fired_date < today`. Test a slipped tick.
- [ ] **Corrupt-file recovery** (M6-c Task 2/4): `dedup.json` + `tier1_queue.json` load must handle `JSONDecodeError`/`FileNotFoundError` → warn, (queue: rename to `.corrupt.<ts>`), start empty. Tests: pre-write invalid JSON → `pending()`/`seen()` no raise.
- [ ] **Coalesce preserves earliest `queued_at`** (M6-c Task 4): a duplicate enqueue must NOT refresh the timestamp (else a locked session resets the staleness clock forever).
- [ ] **Interval `next_due` advances on exception** (M6-a Task 3): a throwing `check_ref` is "due+attempted" → advance `next_due` regardless of success, else retry storm. State explicitly.
- [ ] **LLM partial line-count mismatch** (M6-b Task 2): test the 1-line-for-3-hits case (not just total model failure); unmatched hits fall back to template; consider an observability flag/log (silent LLM→template swap otherwise).

### M6 — notes
- [ ] `tier1_sink` queue-token `Hit` (result=`miss()`) must never be read as a real hit — `drain()` uses only the fresh `check_ref` return (clarify in M6-a).
- [ ] Digest `dedup_value` = `date.isoformat()` not `count` (count gives no dedup boundary) (M6-b Task 2).
- [ ] Wrap `on_hits(...)` call in try/except at the tick boundary (M6-a Task 3) — a HitHandler raise shouldn't kill `run_forever`.
- [ ] Tier-1 no-payload-at-rest test: assert raw JSON bytes contain no `payload`/`result`/`urgency` keys (not just object-level) (M6-c Task 6). Drain test: re-read queue from a fresh instance to catch atomic-write bugs.

### M7 — BLOCKs
- [ ] **B6 (sec+ai) script-`exec` has no gate** (M7-a Task 5): `apply_recipe` AND `replay_verify` run recipe-supplied Python via stripped-builtins `exec` (trivially escapable) — and replay-verify runs it in the **write path before owner review**. Fix: gate ALL SCRIPT-class exec behind a `SandboxPort` (Protocol; `sandbox: SandboxPort | None = None`); refuse to execute (typed `SandboxNotAvailableError`, fail-closed) when absent. Until the hardened VM-per-exec (Apple `container`) ships, SCRIPT-class recipes verify by **schema-conformance only** and cannot be applied on real data.
- [ ] **B7 (sec) cloud-egress boundary untested** (M7-a Task 4): `is_cloud_safe=False → local reasoner` is trusted entirely to the adapter mapping; no in-code assertion + tests use one FakeTeacher for both. Fix: raise `CloudEgressForbiddenError` inside `escalate_and_distill` if the resolved `role="teacher"` adapter is the cloud adapter while `is_cloud_safe is False`; add a `SpyModelPort` test proving the cloud adapter is never called when `is_cloud_safe=False`.
- [ ] **B8 (ai) replay-verify comparator is unsound** (M7-a Task 5): exact-string match on LLM-generated instructions-class output false-negatives ~always → the verification gate is broken by default. Fix: default comparator = **schema-conformance** against `outputs_schema` (structural), optional temp-0 LLM-judge rubric; never exact-match for a generation path.
- [ ] **B9 (ai) uncapped teacher calls** (M7-a Task 4): both the solve + distill `model.complete(role="teacher")` calls set no `max_tokens` (runaway cost/latency on the cloud CLI). Add caps (solve ≈1024, distill ≈2048); consider folding solve+distill into ONE structured call.

### M7 — FLAGs
- [ ] **HMAC canonical-bytes determinism** (M7-a Task 3): pin `json.dumps(model_dump(exclude={'signature'}), sort_keys=True, separators=(',',':'))`; add a `verify(sign(from_skill_md(to_skill_md(r))))==True` round-trip test (not just direct-mutation).
- [ ] **Recipes → always on the M2 encrypted volume** (M7-a Task 7): resolve the NEEDS-CLARIFICATION to "all recipes on the encrypted volume" (touches-data recipe instructions can encode sensitive structure). Make `recipes_dir(s)` return an encrypted-volume path unconditionally.
- [ ] **`promote()` must verify signature** (M7-b Task 2): owner-command promote enables without `RecipeSigner` verify → a recipe written directly to the store (bypassing `escalate_and_distill`) can reach ENABLED unsigned. Require `store.get(name)` (signature-checked) succeeds before ENABLE; test bad-sig → `RecipeSignatureError`.
- [ ] **Grounding-gate domain = eTLD+1** (M7-c Task 2): "distinct domain" on the raw `Source.domain` string lets two subdomains of one publisher pass. Use registrable domain (eTLD+1). Also define reachability semantics: which HTTP codes = reachable, a HEAD/GET **timeout** (required for non-raising), and "≥2 reachable" (not "all reachable") so one transient failure doesn't discard a good result.
- [ ] **Gap-phrasing call must be local-only** (M7-c Task 4 step 3): gap data derives from owner telemetry; the optional query-phrasing `model.complete` must bind a LOCAL role (never cloud) — or use the deterministic template unconditionally. Also: **record step-3 tokens** in the ledger (else the hard cap is understated).
- [ ] **Chunk `commit_staged` is unguarded** (M7-c Task 4): the RAG-chunk write path is deferred/undefined and bypasses the signing+gate machinery recipes go through. Until the M3 ingest hook is specced, the chunk branch raises `NotImplementedError`; when specced, ingest with `source="curiosity"` provenance + owner-private scope via the M3 validation pipeline (not a raw `VectorStore.add`).
- [ ] **`task_class_key` definition** (M7-a Task 4): resolve to **router top-candidate-id if present, else SHA-256(normalise(text))**. A pure text hash breaks the N≥2 recurrence gate (paraphrases never collapse). Test: two paraphrases routing to the same candidate → same key.
- [ ] **`set_status` stale index** (M7-a Task 2): `write`'s `index.add` must be upsert-by-id (remove-then-add) or RAG-for-recipes returns a RETIRED recipe's stale ENABLED entry. Test: ENABLE→RETIRE→`retrieve_recipes(status=ENABLED)` excludes it.
- [ ] **Distill-prompt framing leaks the instance** (M7-a Task 4): step-2 distill must use an instance-free framing (template over `task_class_key`+`action_class`, or an entity-strip of `request_text`) — the spec relies on "task class not instance" but passes `request_text`. Define the template/strip rule.
- [ ] **`ClaudeCliModelPort` structured-output failure path** (M7-a Task 8): `claude -p` has no native constrained decoding → "post-validate" parses freeform text. Define: parse→Pydantic-validate→retry-once-with-repair-prompt→`TeacherMalformedResponseError` (so `escalate_and_distill` writes no candidate). Also spawn the subprocess with a **sanitised `env=`** (no credential vars inherited).
- [ ] **Recurrence counting semantics** (M7-b Task 1): the draft counts every router classification into a class with a CANDIDATE → a common class hits N≥2 instantly (no real threshold). Decide: count **only re-escalations** (N≥2), OR count router-hits with a higher threshold (≈N≥5). Document the calibration. → owner fork (see gate-decisions).
- [ ] **Tracing across the distillation pipeline** (M7-a/b/c): no call-level tracing (tokens/cost/latency) on the teacher/responder calls — the most expensive, least-understood path. At minimum capture+log `ModelResponse.usage` on every teacher call; reference the M0 tracing port (or flag it unspecced → ties to the telemetry-spec gap below).

### M7 — notes
- [ ] `RECIPE_SCHEMA` from `model_json_schema()` carries `$defs`/`$ref` — confirm the constrained-decode/post-validate path accepts it; inline/flatten if needed (M7-a Task 1).
- [ ] `promote()` on a RETIRED recipe: define the RETIRED→ENABLED edge (raise `RecipeAlreadyRetiredError` or re-enable with warning) (M7-b Task 2).
- [ ] `dedupe_retire` near-dupe tiebreaker when `verified_at` equal → add deterministic tiebreaker (version, then name) (M7-a Task 6).
- [ ] `RecurrenceStore.note` read-increment-write race if Heartbeat ever runs hooks concurrently → file lock or document single-process assumption (M7-b Task 1).
- [ ] `TokenLedger` weekly window is wall-clock; document graceful degradation under clock reset (single-box accepted risk) (M7-c Task 3).

### Cross-milestone integration gaps (planning self-review — need decisions, see gate-decisions below)
- [x] **IG1 — owner-approval round-trip → RESOLVED 2026-06-08: option B (defer to the client app).** Approve/reject for gated recipes + curiosity commits happens in a **Review screen in the future iPhone/iPad client app**, over its M2-authenticated connection. NO inbound action-handler is built in M6/M7; the brain app stays loopback-only (no Tailscale exposure, no M2 auth pulled forward for approvals). `ReviewSurface` (M7-b) + `RecipeReview` + `explain()` are the stable backend the app renders — built now, unchanged. **Consequences:** (a) clearly-safe (`READ_ONLY`/`NO_DATA`) recipes still auto-enable with no channel; only the **gated** class (`TOUCHES_DATA`/`TAKES_ACTION`) + curiosity commits **park in `PENDING` until the client-app Review screen ships** — accepted bootstrapping posture; (b) **NEW dependency:** the (unspecced) client-app spec MUST include a Review screen backed by `ReviewSurface.pending_for_review/approve/reject` + curiosity `staged_for_digest/commit_staged/discard_staged`. Add when the app is specced. (c) Graduate this to an ADR (or extend ADR-006) at the gate/apex-init pass.
- [x] **IG2 → RESOLVED 2026-06-08: add two tracked pending specs, drafted AFTER the M0–M7 gate** (M7-c builds + tests against fakes without them): **(a) observability/telemetry spec** (the concrete `TelemetrySource` + the tracing home from the M7 FLAG: escalation/confidence/token-cost/latency metrics; cross-cutting with M2 escalation metrics + the M7-c `TokenLedger`) and **(b) the Deep-Research engine spec** (`Researcher` impl — spotlighting + CaMeL on untrusted web; gates the M7-c live cycle, Task 7). Both core-adjacent. Record in status.md Pending/Open-Questions that M7-c's runtime *value* is inert until both land.
- [x] **IG3 — briefing vs digest → RESOLVED 2026-06-08 (follows IG1=B).** The M6 ntfy briefing/digest is **informational only** for review items (it may surface "N recipes pending your review" / "a curiosity result is staged"), but it carries **no approve/reject action** — the action surface is the client-app Review screen (IG1=B). **Spec edit at gate:** correct M7-b/M7-c wording from "owner-gated commit **via the M6 Heartbeat digest**" → "**surfaced informationally** via the digest; **approved via the client-app `ReviewSurface`**." The M6 digest needs no inbound/action capability.

### Gate-decisions for the owner (ratify at the gate)
- [x] **Split-rule exceptions → DECIDED 2026-06-08:** accept M6-a (2-phase/4-file), M6-c (4-file), M7-c (4-file) as atomic. **SUB-SPLIT M7-a** → **M7-a1** (model+store+index+signing: Tasks 1,2,3 + the `__init__` surface) / **M7-a2** (escalation→distill→candidate + replay-verify + the Brain escalate-seam substitution + claude-cli adapter: Tasks 4,5,8) / **M7-a3** (dedupe/retire: Task 6). Re-slot M7-b/M7-c prerequisites onto the right sub-spec.
- [ ] **NEEDS-CLARIFICATION ratifications** (all resolved to a drafted default by review; the gate blocks while any `[NEEDS CLARIFICATION]` marker remains): tier field + `OWNER_PRIVATE⇒tier1` guard (keep); minimal daily-`"M H * * *"` cron evaluator (keep, + missed-tick fix above); separate `TemplateRegistry` (keep); JSON metadata stores for dedup/queue/held (keep, + atomic/corrupt fixes); `task_class_key` = router-candidate-else-hash (adopt); recipe-apply = one local call (keep); HMAC key from M2 `KeyProvider` (keep); recurrence counting → **DECIDED: count only re-escalations of the same `task_class_key`, N≥2, config-tunable** (NOT all router hits — that nullifies the threshold); drain-on-tick-when-unlocked, no M2 unlock event (keep — ≤1-tick drain latency acceptable; optional M2 unlock-event later).

---
spec: R-dev-email-harness
status: ready
cross_model_review: true
token_profile: balanced
autonomy_level: L2
---

# Spec: R-dev-email-harness — live-Gmail rules-building harness (observe-only, local, dev box)

**Identity:** The first running Artemis process for the gmail→reactions slice: a dev CLI that polls a real Gmail inbox, runs each message through the real laundered→structured→emit→dispatch pipeline on LOCAL models, fires reactions in **`observe`** (no effects), and logs the `WOULD …` stream + the per-email laundered structured extract — the surface for building/tuning the email reaction rules. Owner-private, local-only, no cloud, no real writes.
<!-- → why: dev rules-building loop for the ADR-032 reactions email path (Lane B, live Gmail polling). -->

## Prerequisites (BUILD-ORDER — the harness cannot run until these are true)
- Specs built first: **R1, R2, R5d, R4m, R6c, R3** (the reactions engine + email structured-extract layer + comms rules). Currently held — must be built before this.
- **`dev-model-stack` (Ollama + Qwen3)** running on the dev box: the harness makes TWO local model calls per email (quarantine read + structured classify). The reader model MUST be toolless.
- **M8-a Task 7** (live loopback OAuth + dev token store) enabled, and the owner has completed `artemis-google-auth` login for the test account (see § Google OAuth instructions in the session notes / README).
- **Google Cloud OAuth client** created by the owner (Desktop app, Gmail API enabled, `gmail.readonly` scope, test account added as a test user); client id/secret provided via the M0-f secrets inject path.
- Environment: a **throwaway/test Gmail account** (dev stores the token + laundered extracts in the plain-sqlite SQLCipher shim — no real encryption at rest until Mac).

## Assumptions
<!-- Coding mode verifies each item against the codebase before executing. -->
- `compose_reactions(...)` (R1) returns `(bus, dispatcher, worker_coro)` and accepts a `mode` resolved from `get_runtime_config().reaction.reactions_mode`. The harness FORCES `observe` regardless of config (a dev-safety belt) by constructing the dispatcher in observe (or asserting the resolved mode is observe and refusing to run in live). → impact: Stop (the harness must never run effects on real email).
- The reactions email emit lives in `GmailMemoryExtractor.extract` (R2), NOT `GmailIngestor.ingest_message`. The harness drives `GmailMemoryExtractor.extract(message_id=, body=)` directly per fetched message — it does NOT use `GmailIngestor`/the M3 `IngestPipeline`, so the harness does NOT need docling/M3-a. → impact: Stop (pulling in GmailIngestor drags the heavy docling dep for no benefit on this path).
- `GmailMemoryExtractor.__init__` takes `reader`, `queue`, `classifier`, `extract_store`, `emit`. The harness injects a real `QuarantinedReader` (local toolless model), real `EmailClassifier` (local model, R5d), real `EmailExtractStore` (dev shim, R5d), `emit=bus.emit`, and a **no-op `MemoryQueuePort` stub** for `queue` (the harness does not write memory facts). → impact: Caution (the memory-enqueue half is intentionally stubbed; rules-building only needs classify+emit).
- In `observe`, the dispatcher fires NO handler effect (R1) — it emits a `WOULD …: <rule>` per matched rule. So the harness injects **no-op stubs** for every effect seam `compose_reactions` requires (`capture_service`, `calendar_from_extract_fn`, `trip_assembler`, `get_linked_task_ref_fn`, `complete_task_fn`, `staging`, `memory`); they are never invoked in observe. `fetch_extract` is the real `EmailExtractStore.fetch` (harmless; the harness also reads the store directly to log the structured extract). → impact: Caution (if a future "dry-execute against fakes" mode is wanted, those stubs become real fakes — out of scope here).
- The harness drains deterministically with `dispatcher.drain_once()` per poll cycle (poll batch → emit all → `drain_once` → log), NOT the continuous `run_forever` worker — simpler + deterministic for a dev tool. → impact: Low.
- The local `ModelPort` for `QuarantinedReader` must be toolless (its ctor rejects a `complete` whose signature has `tools`/`tool_choice` — `untrusted/quarantine.py`). The harness builds the local model from the dev-model endpoint (the same adapter `compose_brain` uses for the local responder); verify/ensure it is toolless or wrap it. → impact: Stop (a tool-capable model makes `QuarantinedReader` raise).
- Gmail read uses the M8-a `GoogleCredentialsFactory` + a Gmail API client; the harness lists recent inbox messages (e.g. `q="newer_than:7d"` or since the last poll marker) and fetches each body with `extract_body_text` (`gmail/client.py`). Scope is `gmail.readonly`. → impact: Caution (no write/modify scope — reactions never touch Gmail).

Simplicity check: the harness is a thin composition + poll loop + two log sinks. It builds NO new domain logic — every reaction/classifier/store/rule already exists in the prereq specs. The effect seams are no-op stubs because observe never calls them; this keeps the harness small and guarantees it cannot act.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/dev/__init__.py` | create | Dev-tools package marker. |
| `src/artemis/dev/email_rules.py` | create | `build_dev_rules_runtime(...)`, `poll_once(...)`, `run(...)`, `main()` (CLI); WOULD + structured-extract log sinks. |
| `pyproject.toml` | modify | `[project.scripts]` → `artemis-dev-email-rules = "artemis.dev.email_rules:main"`. |
| `tests/test_dev_email_rules.py` | create | fake-Gmail + fake-local-model poll → asserts observe-only, WOULD log + structured-extract record, no network, no effects. |

## Tasks
- [ ] Task 1: `build_dev_rules_runtime(*, settings, key_provider) -> DevRulesRuntime`. Constructs: a local toolless `ModelPort` from the dev model endpoint; `QuarantinedReader(model, role=...)`; `EmailClassifier(model)`; `EmailExtractStore(settings, key_provider)`; `ReactionLedger(settings, key_provider)`; the rule store/promoter/registry (TIER_A_BUILTINS); a WOULD `notice_sink` + a structured-extract log sink (both write owner-private JSONL under the dev slot); then `bus, dispatcher, _ = compose_reactions(mode="observe", notice_sink=<WOULD sink>, fetch_extract=extract_store.fetch, <no-op effect stubs>, ...)`; a `GmailMemoryExtractor(reader=reader, queue=<no-op MemoryQueuePort stub>, classifier=classifier, extract_store=extract_store, emit=bus.emit)`; the Gmail API client from `GoogleCredentialsFactory`. ASSERT the resolved mode is `observe` and refuse to run otherwise. — files: `src/artemis/dev/email_rules.py` — done when: the runtime builds with all-real matching-path seams + no-op effect stubs, mode is observe, and a tool-capable reader model is rejected at build.
- [ ] Task 2: `poll_once(runtime) -> int`. Lists recent inbox messages (Gmail `users().messages().list(q=...)`); for each new message: fetch the body (`extract_body_text`), `await runtime.memory_extractor.extract(message_id=, body=)` (classifies → stores → emits `EMAIL_INGESTED`); after the batch, `await runtime.dispatcher.drain_once()`; then for each processed `source_ref` log the structured extract (`extract_store.fetch`) to the structured-extract sink. Persist a last-poll marker (owner-private) so re-runs don't reprocess. Returns the count processed. — files: `src/artemis/dev/email_rules.py` — done when: a poll over N messages produces N structured-extract records + the `WOULD …` lines for every matched rule, and a second poll reprocesses nothing.
- [ ] Task 3: `run(*, once: bool, interval_s: int = 60)` loop (`poll_once` then sleep unless `once`) + `main()` argparse CLI (`--once`, `--interval`); wire the console script. — files: `src/artemis/dev/email_rules.py`, `pyproject.toml` — done when: `uv run artemis-dev-email-rules --once` runs one poll and exits; the loop form polls on the interval.
- [ ] Task 4: Tests. A `FakeGmailApiPort` returning canned messages + a fake local `ModelPort` returning canned quarantine + structured-classify JSON (one commitment email, one flight email, one gift email, one nothing-email); drive `poll_once`; assert: (a) observe-only — no effect stub is ever called; (b) one structured-extract record per email with the expected flags; (c) `WOULD …: <rule>` emitted for the matched rules (A4 for commitment, A5/A7 for flight, gift for gift) and none for the nothing-email; (d) no network (fake api), no real model (fake port); (e) the second `poll_once` processes nothing (marker). — files: `tests/test_dev_email_rules.py` — done when: `uv run pytest -q tests/test_dev_email_rules.py` passes.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3] | Wave 3: [Task 4]

## Permissions

The following actions will run autonomously during build. Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `src/artemis/dev/__init__.py`, `src/artemis/dev/email_rules.py`, `tests/test_dev_email_rules.py` |
| Modify | `pyproject.toml` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy` | Full-project type check (host re-verify). |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate. |
| `uv run pytest -q` | Full test suite. |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | The four files above, by name. |
| `git commit` | "feat: R-dev-email-harness live-Gmail rules-building harness (observe-only, local)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_GOOGLE_CLIENT_ID` / `ARTEMIS_GOOGLE_CLIENT_SECRET` (or the M8-a secret names) | Live Gmail OAuth (read-only). Injected via M0-f; never hardcoded. |
| Dev model endpoint (Ollama, per `dev-model-stack`) | Local quarantine + classify calls. |

### Network
| Action | Purpose |
|--------|---------|
| Gmail API (read-only) | Poll the test inbox. Local Ollama endpoint for model calls. No other egress. |

## Specialist Context
### Security
`cross_model_review: true` — this harness READS real untrusted email and runs a live process. Hard invariants the reviewer must confirm: (1) **observe is forced** — the harness asserts the resolved mode is `observe` and refuses to run in `live`; every effect seam is a no-op stub that is never invoked; (2) **all model calls are LOCAL** (quarantine reader + classifier on the dev Ollama endpoint) — no cloud egress on real email (ADR-022 "email stays local"); (3) scope is **`gmail.readonly`** — no write/modify, reactions never touch Gmail; (4) the WOULD log + structured-extract log are **owner-private local files** under the dev slot (laundered content only — the raw body is never logged); (5) the OAuth token + extract store sit in the dev plain-sqlite shim — documented as test-account-only until SQLCipher is real (Mac). Recommend a security spec-review pass before build given the live-email surface.

### Performance
(none — a dev poll tool; two local model calls per email, deterministic `drain_once` per cycle.)

### Accessibility
(none — CLI/log tool, no frontend.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/dev/email_rules.py` | Module docstring: observe-only, local-only, test-account-only, the rules-building loop. |
| Product | README / docs | A short "Building email rules on the dev box" runbook: OAuth setup → `artemis-google-auth` → `artemis-dev-email-rules --once` → read the WOULD + structured-extract logs → tune R5d classifier / R6c rules → repeat. |
| ADR | (none) | Implements ADR-032's email path in a dev observe harness; no new decision. |

## Acceptance Criteria
- [ ] Observe forced → verify: the harness asserts `observe` and refuses to run in `live`; in the test, no effect stub is ever called.
- [ ] Local-only → verify: the only model calls go to the injected local `ModelPort`; the reader model is toolless (a tool-capable one is rejected at build).
- [ ] Poll produces the rules-building signal → verify: a poll over canned (commitment / flight / gift / nothing) emails yields one structured-extract record each (correct flags) and `WOULD …: <rule>` for A4 / A5-A7 / gift respectively, none for the nothing-email.
- [ ] Idempotent poll → verify: a second `poll_once` processes nothing (last-poll marker).
- [ ] Read-only + private → verify: scope is `gmail.readonly`; the WOULD + structured-extract logs are owner-private and contain no raw body.
- [ ] Whole project clean → verify: `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q` all pass.

## Progress
_(Coding mode writes here — do not edit manually)_

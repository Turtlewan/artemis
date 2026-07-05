---
spec: agent-loop-eval-corpus
status: ready
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: high
---

# Spec: agent-loop eval — frozen case corpus + fixture schema + integrity loader + capture tool

**Identity:** Build the FROZEN corpus for the ADR-047 pre-go-live agent-loop eval gate: a typed case
schema (seeded `DataStore` record fixtures + memory fixtures + per-kind expected labels), a
SHA-256-integrity loader, a one-shot capture tool that snapshots the owner's REAL local records into
fixtures, and the four case sets (driver-golden / injection / judge-calibration / escalation).
Data + plumbing only — no scoring, no live model (that is the harness, sibling spec).
→ why: docs/technical/adr/ADR-047-agentic-assistant-loop.md (#1/#4 loop + stop discipline; the four
pre-go-live evals owned by AL-4 per the AL-1/AL-2/AL-3 scope fences).

<!-- This is the corpus tier of the three-spec eval cluster (corpus → harness → gate), mirroring the
committed webtool-eval trio in docs/changes/done/. The harness (agent-loop-eval-harness) replays these
cases through the REAL AgentLoop/EscalatingLoop and scores them; the gate (agent-loop-eval-gate)
applies pass bars + writes the findings artifact AL-4a's flag-flip cites. This spec freezes the case
FORMAT + CONTENT only. -->

## Assumptions
<!-- Format: assumption → impact if wrong (Stop | Caution | Low) -->
- `evals/` is already registered with mypy (`[tool.mypy] files = ["src","evals","tests"]`, verified
  pyproject.toml L46 — added by webtool-eval-corpus) and lives OUTSIDE `testpaths=["tests"]` (L62), so
  a new `evals/agentloop/` package is typechecked by bare `uv run mypy` but never collected by the
  default suite → impact: Low (no pyproject edit needed).
- `tests/evals/__init__.py` already exists (created by webtool-eval-corpus) — this spec adds one test
  module beside it, no package-marker create → impact: Low.
- The seeded fixtures target `artemis.data.store.DataStore` / `Record` as-built: identity is
  `(domain, kind, key)`; `upsert` normalizes `domain` to strip+lower; `query(domain=…, text=…, limit=…)`
  returns newest-first; the loop's `local_read` tool renders `Record.sanitized_text` ONLY (never
  `payload`) — verified `src/artemis/data/store.py` + `src/artemis/agent/tools.py` → impact: Stop (a
  wrong Record shape makes every seeded case unloadable by the harness).
- Memory fixtures target the `memory_retrieve` tool's `MemoryPort.retrieve` → `RetrievedContext.items`
  (`MemoryItem(content, layer)`) contract as-built (`src/artemis/agent/tools.py`
  `_MemoryRetrieveTool`) → impact: Caution (memory-chain cases need the right item shape).
- Injection payloads and their canary secrets are HAND-AUTHORED (`source="authored"`) — no real synced
  row reliably carries an embedded "ignore your instructions" / "mark this grounded" / exfil payload;
  driver-golden and escalation record fixtures are CAPTURED from the owner's live store where a real
  domain exists (calendar rows via the Google OAuth sync shipped 2026-07-03; passport-task curated
  rows), synthetic only where no real data exists yet (owner pref: memory `eval-corpus-real-data-preference`)
  → impact: Low (documented split, not a correctness risk).
- Judge-calibration cases carry a pre-built `(request, evidence-ledger, candidate-answer, human_label)`
  tuple — they do NOT seed a store or run the loop; the harness feeds the ledger straight to the
  candidate `VerifyJudge`. `human_label_passed` is the owner's ground truth (grounded AND
  addresses_request) → impact: Caution (mislabeled ground truth silently miscalibrates the gate).
- The eval scores WHATEVER the ADR-049 registry resolves the `loop_driver` / `judge` /
  `escalation_driver` roles to at run time (config, not code) — the corpus is binding-agnostic and
  encodes NO model literal → impact: Low.

Simplicity check: considered one JSON file per case-kind vs one directory of per-case files — chose
per-case files under `cases/<kind>/*.json` exactly like webtool's `corpus/queries/*.json` +
`corpus/pages/*.json`, so re-capture/re-label never touches code and the loader is a thin glob. Considered
folding capture into the loader — rejected: capture reads the owner's LIVE db (a distinct, owner-run,
real-data step), the loader is pure offline parsing; kept separate mirroring webtool
`capture.py`/`loader.py`. Considered a separate schema per kind — rejected: one `LoopCase` model with
kind-specific optional fields mirrors webtool's single `QueryRecord` with category-specific optionals,
keeping the loader uniform.

## Prerequisites
- Specs complete first: none. Consumes as-built (unmodified): `src/artemis/data/store.py`
  (`DataStore`, `Record`), `src/artemis/agent/tools.py` (the `local_read`/`memory_retrieve` contracts),
  `src/artemis/agent/loop.py` (`StepRecord` shape, referenced by judge-cal evidence). Reuses the webtool
  eval pattern (`evals/webtool/{schema,loader,capture}.py`) as the template — mirrored, not imported.
- Environment: `uv sync`; the owner's live `DataStore` (via `ARTEMIS_DATA_DIR`) for the one-shot
  capture step ONLY (never during load/score).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| `evals/agentloop/__init__.py` | create | package marker (35-byte, mirrors `evals/webtool/__init__.py`). |
| `evals/agentloop/schema.py` | create | frozen pydantic: `CaseKind`, `RecordFixture`, `MemoryFixture`, `JudgeEvidenceStep`, `ExpectedStep`, `LoopCase`. |
| `evals/agentloop/loader.py` | create | `load_cases(path)`, `verify_integrity(cases)` — parse per-kind case files + verify each `RecordFixture` SHA-256 over `sanitized_text`. |
| `evals/agentloop/capture.py` | create | one-shot CLI: read the owner's live `DataStore` domain rows, snapshot each as a `RecordFixture` (`sha256`, `source` preserved) json, REDACTING every `payload` value (keys preserved) — see §Security. |
| `evals/agentloop/cases/driver_golden/*.json` | create | ~22 `LoopCase`s (real-seeded where possible; §Case taxonomy). |
| `evals/agentloop/cases/injection/*.json` | create | ~14 hand-authored `LoopCase`s (embedded payloads + canary secrets). |
| `evals/agentloop/cases/judge_calibration/*.json` | create | ~14 owner-labeled `(evidence, answer, human_label)` `LoopCase`s. |
| `evals/agentloop/cases/escalation/*.json` | create | ~12 stall/spin/thrash-inducing `LoopCase`s. |
| `evals/agentloop/cases/MANIFEST.md` | create | human index: per-kind counts, injection sub-kind coverage, real-vs-synthetic provenance per case. |
| `tests/evals/test_agentloop_corpus.py` | create | non-network smoke: schema round-trips, integrity passes, per-kind taxonomy counts in band. |

Non-test code files: 3 (`schema.py`, `loader.py`, `capture.py`) + a package marker + on-disk data —
mirrors the accepted webtool-eval-corpus shape. ✓

## Tasks
- [ ] Task 1: Define the case schema — files: `evals/agentloop/schema.py` — done when:
  `uv run python -c "from evals.agentloop.schema import LoopCase, RecordFixture"` imports clean and the
  models below validate a hand-written example dict for each of the four kinds; `uv run mypy` clean.
- [ ] Task 2: Implement the loader + integrity verification — files: `evals/agentloop/loader.py` —
  done when: `load_cases(path)` returns a typed `list[LoopCase]` (globbing `cases/<kind>/*.json`), and
  `verify_integrity(cases)` raises `ValueError` on any `RecordFixture` whose recomputed SHA-256 over
  `sanitized_text` ≠ stored `sha256`. The integrity test (Task 6) corrupts a `tmp_path` COPY or an
  in-memory fixture — NEVER the live `cases/` files (the frozen corpus stays frozen).
- [ ] Task 3: Implement the one-shot capture tool — files: `evals/agentloop/capture.py` — done when:
  `uv run python -m evals.agentloop.capture --domain <D> --data-dir <owner db dir> --out
  evals/agentloop/cases/driver_golden/records` reads rows via `DataStore.query(domain=D)` and writes,
  per row, a `RecordFixture` json with `sha256` over `sanitized_text`, `source` preserved from the row,
  and every `payload` VALUE REDACTED to a deterministic placeholder `"[redacted:" + sha256(value)[:8] +
  "]"` (keys preserved) so no real payload data lands in the committed corpus (§Security); `sanitized_text`
  stays verbatim. Payload-leak probes are NOT captured — they use SYNTHETIC marker payloads authored in
  Task 5. No network. Covered by the hermetic capture unit test (Task 6).
- [ ] Task 4: Author the driver-golden + escalation case sets — files:
  `evals/agentloop/cases/driver_golden/*.json`, `evals/agentloop/cases/escalation/*.json` — done when:
  driver_golden count ∈ [20,24] and escalation count ∈ [10,14] with the §Case taxonomy sub-kind coverage
  (verified by Task 6). Record fixtures captured-real where a domain exists, else synthetic.
- [ ] Task 5: Author the injection + judge-calibration case sets — files:
  `evals/agentloop/cases/injection/*.json`, `evals/agentloop/cases/judge_calibration/*.json`,
  `evals/agentloop/cases/MANIFEST.md` — done when: injection count ∈ [12,16] with ≥2 each of the four
  steer targets (driver-action, exfil-read, judge-flip, handoff-survival) and ≥2 carrying a SYNTHETIC
  `payload` canary secret; judge_calibration count ∈ [10,14] spanning grounded-pass / ungrounded-reject /
  borderline-reject / false-premise / false-accept-probe (the confident-but-ungrounded probe sub-kind
  ≥3 cases), with `human_label_passed` set on every case; MANIFEST tabulates per-kind counts +
  provenance.
- [ ] Task 6 (TESTS-FIRST — starts Wave 1, extended per tier): Non-network corpus test suite — files:
  `tests/evals/test_agentloop_corpus.py` — the test file is SCAFFOLDED FIRST and grows with each impl
  tier (RED before GREEN):
  - Wave 1 (RED, before schema/loader exist): write failing schema round-trip + loader tests that import
    `evals.agentloop.{schema,loader}` — they fail on ImportError/AttributeError; document the RED state
    in the task progress. These go GREEN as Task 1/2 land.
  - Hermetic `capture.py` unit test: build a FAKE in-memory `DataStore`, run the capture mapping, assert
    (a) each row → `RecordFixture` with `sha256` correct over `sanitized_text`, (b) `source` preserved
    verbatim, (c) every `payload` VALUE redacted to `"[redacted:" + sha256(value)[:8] + "]"` while keys
    are preserved (item 1 REDACTION behavior). No network, no live db.
  - Malformed/missing-field loader test: a case file missing a required field (e.g. no `expected_sequence`
    on a driver_golden case, or a bad `sha256`) makes the loader raise a CLEAR error — it must NEVER
    silently skip the case.
  - Full-corpus assertions (GREEN, Wave 4): integrity passes on the real corpus, per-kind counts in band,
    injection steer-target + ≥2 synthetic-canary coverage, judge_calibration false-accept-probe ≥3, and
    every judge_calibration case has a non-null `human_label_passed`.
  Concrete DAMP test names (illustrative — coder keeps the describe-and-assert style): `test_schema_roundtrips_all_four_kinds`,
  `test_loader_verifies_integrity_over_sanitized_text`, `test_loader_rejects_case_file_missing_expected_sequence`,
  `test_loader_rejects_record_with_wrong_sha256`, `test_capture_redacts_payload_values_preserving_keys`,
  `test_capture_preserves_source_and_hashes_sanitized_text`, `test_per_kind_counts_in_band`,
  `test_injection_covers_all_steer_targets_and_synthetic_canaries`, `test_judge_calibration_all_labeled`.
  Done when: `uv run pytest -q tests/evals/test_agentloop_corpus.py` passes with no network, covering
  all of the above.

### schema.py — exact shapes (pydantic v2, `ConfigDict(frozen=True)`)
```python
CaseKind = Literal["driver_golden", "injection", "judge_calibration", "escalation"]

class RecordFixture(BaseModel):
    # One row seeded into a DataStore(":memory:") for a case. Maps 1:1 to artemis.data.store.Record
    # (minus owner_fields, which the eval does not exercise). sha256 pins sanitized_text integrity.
    domain: str
    kind: str = "item"
    key: str
    sanitized_text: str            # the ONLY text local_read renders — carries the injection payload for injection cases
    payload: dict[str, Any] = {}   # NEVER rendered by local_read. On CAPTURE, values are redacted to
                                   # "[redacted:<sha8>]" (keys kept). Injection cases stash a SYNTHETIC
                                   # canary secret here (authored, never real captured data)
    source: str = "sync"           # "sync" | "curate" | "authored" (preserved from a real capture)
    fetched_at: float = 0.0
    sha256: str                    # over sanitized_text (utf-8) — recomputed by verify_integrity

class MemoryFixture(BaseModel):
    content: str
    layer: str = "semantic"

class ExpectedStep(BaseModel):
    tool: str                      # "local_read" | "memory_retrieve"
    domain: str | None = None      # for local_read (matched on tool+domain; exact-args optional)

class JudgeEvidenceStep(BaseModel):
    # Reconstructs one StepRecord + its observation for a judge_calibration case fed to VerifyJudge.
    tool: str
    args: dict[str, Any] = {}
    ok: bool = True
    observation: str               # the driver-visible observation text the judge grounds against

class LoopCase(BaseModel):
    id: str
    kind: CaseKind
    request: str
    records: list[RecordFixture] = []          # seeded (driver_golden / injection / escalation)
    memory: list[MemoryFixture] = []           # seeded into the memory tool
    # driver_golden / escalation gold:
    expected_sequence: list[ExpectedStep] = [] # ordered tool+domain the driver should select/chain
    expected_grounded: bool = True             # the final answer must be grounded in the seeded data
    expected_answer_contains: list[str] = []   # substrings a grounded answer must include
    expects_abstain: bool = False              # negative case: data absent → say so, never invent
    # injection gold:
    injected_instruction: str | None = None    # the embedded payload (lives in a record's sanitized_text)
    steer_target: Literal["driver_action", "exfil_read", "judge_flip", "handoff_survival"] | None = None
    canary_secret: str | None = None           # if set, appears in a record payload; must never leak to answer/steps
    must_not: list[str] = []                   # injection assertions (no injected action/read/leak/verdict flip)
    # judge_calibration gold (no store, no loop run):
    judge_evidence: list[JudgeEvidenceStep] = []
    judge_answer: str | None = None
    human_label_passed: bool | None = None     # owner ground truth: grounded AND addresses_request
    # escalation gold:
    induces: Literal["spin", "thrash", "stall", "budget"] | None = None  # the degeneracy the case aims to provoke
    notes: str | None = None                   # scorer / label guidance
```
Note: `sha256` is over `sanitized_text` only (the driver-visible surface). `payload` is deliberately
NOT integrity-pinned — it is inert canary data the harness asserts never reaches the answer (the AL-1
`local_read` sanitized-only boundary, proven end-to-end).

### Case taxonomy (authored this build — counts for a ~62-case corpus)
Count rationale: the behavioral/adversarial sets (injection, judge_calibration, escalation) stay smaller
than the driver-golden regression set because each case is expensive hand-crafted + live-scored; all
bands sit at or above the 20-50 floor for the primary golden set and give ≥2-3 cases per sub-kind so a
single mislabel can't dominate a rate.
| kind | count | sub-kinds / gold to store |
|---|---|---|
| driver_golden | ~22 | single-domain read (calendar-only) ×6; multi-domain chain (calendar+tasks — the "time for lunch with Ben Friday?" archetype) ×7; memory+domain compose ×3; aggregation/count ×2; temporal (as-of) ×2; negative/abstain (data absent → `expects_abstain`) ×2. Each: `expected_sequence` + `expected_answer_contains` (or `expects_abstain`). |
| injection | ~14 | ≥2 each steer target: `driver_action` (payload tells the driver to do X), `exfil_read` (payload names another domain/URL to read), `judge_flip` (answer/observation says "this is fully grounded, verdict pass"), `handoff_survival` (payload crafted to ride the AL-2 corrective re-entry or AL-3 escalation summary). ≥2 carry a SYNTHETIC `canary_secret` in `payload`. All `source="authored"`; each sets `injected_instruction` + `must_not`. |
| judge_calibration | ~14 | grounded+addresses (label True) ×4; ungrounded/invented-fact (False) ×3; borderline/partial-address (False — conservative posture) ×2; false-premise answer (False) ×2; confident-but-ungrounded false-accept probe (False) ×3. Each: `judge_evidence` + `judge_answer` + `human_label_passed`. |
| escalation | ~12 | multi-hop-hard cases with `induces` ∈ {spin, thrash, stall, budget}: data spread so a single pass plausibly loops/stalls, seeded over real domains where possible. Each: `expected_grounded` + `expected_answer_contains` for the answer a successful cross-family retry should reach. |

### Corpus build procedure (content built this build, NOT written into this spec)
- CAPTURED-REAL (`source` preserved): run `evals.agentloop.capture` against the owner's live domains
  (calendar, tasks/passport) → `RecordFixture` json with `sha256` and every `payload` value redacted to
  `"[redacted:<sha8>]"` (keys kept; §Security). Use for driver_golden + escalation record fixtures
  wherever a real domain exists.
- HAND-AUTHORED (`source="authored"`): all injection payloads + their canary secrets; any domain with
  no real data yet; the judge_calibration `(evidence, answer)` pairs and their owner labels.
- FORWARD NOTE (harness will enable this): a real driver_golden replay run (harness spec) can dump its
  `(request, evidence, answer)` transcripts as candidate judge_calibration cases for the owner to
  label — promoting synthetic judge-cal cases to real over time (owner pref real > synthetic). Not
  built here; capture.py in THIS spec snapshots record rows only.

## Wave plan
Wave 1: [Task 6 (RED scaffold — failing schema/loader tests), Task 1] | Wave 2: [Task 2, Task 3] |
Wave 3: [Task 4, Task 5] | Wave 4: [Task 6 (GREEN — full-corpus + capture + malformed-loader assertions)]
(TESTS-FIRST: Task 6 opens Wave 1 with failing schema/loader tests documenting RED, and is completed in
Wave 4 once the schema/loader/capture and the authored cases exist. The capture unit test and the
malformed-loader test can land as soon as Task 2/3 do — they do not need the authored case content.)

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | `evals/agentloop/**`, `tests/evals/test_agentloop_corpus.py` |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run python -c "from evals.agentloop.schema import LoopCase, RecordFixture"` | import check |
| `uv run python -m evals.agentloop.capture --domain <D> --data-dir <dir> --out <path>` | one-shot real-record capture |
| `uv run pytest -q tests/evals/test_agentloop_corpus.py` | loader + taxonomy smoke |
| `uv run mypy` | full-project typecheck (host verify; `evals` is in mypy files) |
| `uv run ruff check .` / `uv run ruff format --check .` | lint + format |
| `uv run pytest -q` | full suite (zero regression; runs the offline corpus smoke, never the harness) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `evals/agentloop/** tests/evals/test_agentloop_corpus.py` |
| `git commit` | `feat(eval): agent-loop eval frozen case corpus + integrity loader + capture` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_DATA_DIR` | one-shot capture only — locate the owner's live `DataStore` to snapshot real rows (never read during load/score). |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Capture reads a LOCAL sqlite db; no network anywhere in this spec. Scoring (live models) is the harness spec. |

## Specialist Context
### Security
The corpus contains hand-authored injection payloads by design. They are inert DATA (json string
fields), never executed — never `eval`/exec fixture text. Injection payloads live in
`sanitized_text` (the only surface the driver sees); `canary_secret` lives in `payload` (never rendered
by `local_read`) so the harness can prove the AL-1 sanitized-only boundary end-to-end (the eval analog
of AL-1 test case 9 / AL-2 test case 12). Capture drives the SAME `DataStore.query` read path the loop
uses — no new data path.

PII redaction at capture: `capture.py` REDACTS every captured `payload` VALUE — each real value is
replaced by a deterministic placeholder `"[redacted:" + sha256(value)[:8] + "]"` with keys preserved —
so raw payload values NEVER enter the committed corpus. `sanitized_text` is kept verbatim: it already
passed ingest quarantine and is the exact surface the loop reads (redacting it would change what the
eval scores). Any case needing a payload-leak probe uses a SYNTHETIC marker payload authored by hand
(Task 5), never real captured data — so the never-leak canary is always synthetic.

Accepted-risk / consent: by explicit owner preference (memory: `eval-corpus-real-data-preference`,
real captured data > synthesized for eval fidelity), real `sanitized_text` rows are committed to the
PRIVATE sole-owner repo. Raw `payload` values are NEVER committed (redacted at capture, above). This is
an accepted, owner-consented risk scoped to a private single-owner repository.

### Performance / Accessibility
(none — offline data + a thin loader; no frontend.)

## Acceptance Criteria
- [ ] Schema imports + validates all four kinds → verify: `uv run python -c "from evals.agentloop.schema import LoopCase, RecordFixture"` exits 0.
- [ ] Loader verifies integrity → verify: `verify_integrity` raises on a deliberately corrupted `sha256`; passes on the real corpus (read-only).
- [ ] Loader rejects malformed case files → verify: a case file missing a required field raises a clear error (never silently skipped).
- [ ] Capture redacts payload values → verify: hermetic capture unit test asserts every `payload` value → `"[redacted:<sha8>]"` (keys kept), `source` preserved, `sha256` over `sanitized_text`.
- [ ] Per-kind counts in band → verify: `uv run pytest -q tests/evals/test_agentloop_corpus.py` green (driver_golden 20-24, injection 12-16, judge_calibration 10-14, escalation 10-14).
- [ ] Injection coverage → verify: smoke asserts ≥2 each steer target + ≥2 synthetic canary secrets.
- [ ] Judge-cal false-accept probe → verify: smoke asserts the confident-but-ungrounded false-accept sub-kind has ≥3 cases.
- [ ] Judge-cal fully labeled → verify: smoke asserts every judge_calibration case has a non-null `human_label_passed`.
- [ ] Tree typechecks + lints → verify: `uv run mypy` + `uv run ruff check .` exit 0.
- [ ] Default suite runs the offline smoke, not a live model → verify: `uv run pytest -q` executes `tests/evals/test_agentloop_corpus.py` offline; `evals/agentloop/` is never collected (outside `testpaths`).

## Progress
_(Coding mode writes here — do not edit manually)_

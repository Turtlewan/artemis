---
spec: m5-c-speaker-id
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M5-c — Speaker-ID (ECAPA-TDNN) behind the `SpeakerID` port (voiceprint enrol + match→person; unknown→guest) + Gateway VOICE-path scope-attach encoding voice-ID≠key (Tier-1-while-locked → ask phone unlock; Tier-0 proceeds)

**Identity:** Implements the Python `SpeakerID` port adapter (SpeechBrain ECAPA-TDNN voiceprint enrolment + cosine match → `PersonId`; below threshold → `None` → guest), a voiceprint store, and the VOICE-path identity resolution in the Gateway that maps a matched owner to owner-scope routing while honouring voice-ID = identity-not-auth: a Tier-1 (sensitive) request on a voice-identified-but-locked owner returns a "needs phone unlock" response, while Tier-0 (non-sensitive) owner + guest requests proceed.
→ why: see docs/technical/architecture/brain.md § "Voice (cascaded, streaming every stage)" (SpeechBrain ECAPA-TDNN; enrol voiceprints → person scope; unknown → guest least-privilege; voice-ID = identity, not auth) · docs/technical/adr/ADR-005-owner-key-broker.md (voice-ID routes to owner scope but SENSITIVE owner data still needs the phone-attested broker unlock) · docs/technical/adr/ADR-006-two-tier-proactivity.md (Tier-0 vs Tier-1) · docs/drafts/m2/M2-b-scope-model-and-wall.md (the guest-recognition seam M2 deferred to M5; the `Identity`/`scopes_for`/Gateway scope-attach this fills).

<!-- Split rule: this spec touches >3 files because the voice identity wall is enforced across three agreeing seams: the SpeakerID adapter + voiceprint store (new), the sensitivity/Tier classification of a request (new, small), and the Gateway VOICE-path scope-attach (modify M2-b's Gateway). They share the `Identity`/`Scope`/`PersonId` vocabulary and the `KeyProvider.is_owner_unlocked()` check; splitting would let the Gateway route a voice-matched owner to sensitive data the Tier gate hasn't checked, or build a SpeakerID adapter with no consumer. Justified atomic exception, flagged per rules. The SpeakerID model + Gateway logic are off-hardware-testable with a fake adapter + fakes; real ECAPA embedding/enrolment is GATED. -->

## Assumptions
- M0-d (`SpeakerID` port: `def identify(self, audio: bytes) -> PersonId | None: ...`), M2-b (`Identity`/`Role`/`scopes_for`/`primary_scope`/`OWNER_PERSON_ID`, the `Gateway` with `_resolve_identity`/`_resolve_guest` + the owner-authenticated stub + the `KeyProvider` with `is_owner_unlocked()`, the `LOCKED` typed response), M2-c (`BrokerKeyProvider`) are complete. → impact: Stop (M5-c implements the M0-d port and FILLS M2-b's deferred guest-recognition seam + extends the Gateway; signatures must match exactly).
- **SpeakerID = SpeechBrain ECAPA-TDNN**: enrolment computes a fixed-dim speaker embedding (voiceprint) from a few seconds of enrolment audio; `identify` computes an embedding for the utterance and cosine-matches against enrolled voiceprints; above a threshold → that person's `PersonId`; below → `None` (unknown → guest). → impact: Caution. DRAFTED DEFAULT: SpeechBrain ECAPA-TDNN (PyTorch) behind a `_load_ecapa` seam + FakeSpeakerID; MPS with CPU fallback; default match threshold cosine ≥ 0.25 (ECAPA EER placeholder), tuned on-hardware. Exact package/MPS acceptability/tuned threshold confirmed GATED Task 6.
- **Voiceprint store**: enrolled voiceprints are owner-sensitive (they identify people) → stored in the OWNER scope's data dir, NOT a shared location. In M5 the store is a simple per-person embedding file under `scope_dir("owner-private")/voiceprints/<person_id>.npy` (or a small SQLite table). → impact: Caution. DECISION: voiceprints in a SEPARATE small store readable WITHOUT the owner DEK (identity routing must work while locked, to classify owner-Tier-0 + unknown→guest), encrypted under the Tier-0 proactive key (M2-c) — identity is a Tier-0-class need, not a Tier-1 secret. EMBEDDINGS ONLY (raw enrolment audio discarded after embedding), never-logged, minimised (person id + embedding). Anti-spoof/liveness + rotation noted-for-later (not v1).
- **Voice-ID = identity, not auth** (the locked nuance, ADR-005): a voice match to the owner ROUTES the request to owner scope, but does NOT unlock the owner DEK. The DEK unlock is still the phone-attested broker proof (M2-a/c). So: a voice-identified owner whose session is LOCKED can do **Tier-0 (non-sensitive)** owner things, but a **Tier-1 (sensitive)** request returns a "I need a phone unlock for that" response (NOT the M2 blanket `LOCKED` — the difference is M5-c lets non-sensitive owner interaction proceed on voice alone). → impact: Stop (this is the precise ADR-005/006 encoding the brief demands; the Tier classification gates which response).
- **Tier classification** of a request: M5-c needs a way to decide Tier-0 vs Tier-1 for a request to apply the nuance. A FULL sensitivity router is a later milestone; M5-c ships a MINIMAL deterministic classifier: a request is Tier-1 (sensitive) if its routed tool/module is flagged sensitive (finance/health/journal/memory — the same risky-module set as M0-b's `risky_paths.txt` + the M1-a manifest `data_scope`/sensitivity), else Tier-0. → impact: Caution. DECISION: the Tier-1 signal = the M1-a `ModuleManifest.data_scope` flag (RESOLVED 2026-06-08: M1-a carries `data_scope: DataScope` = owner-private | guest-visible | shared — a strict superset of a sensitive boolean; NO separate `sensitive: bool` was added). A matched module whose `data_scope == OWNER_PRIVATE` ⇒ Tier-1, else Tier-0. M5-c reads `data_scope` as the source of truth — NOT a name-keyed stopgap. Reuses M1-a manifest metadata; no model. The full provenance/sensitivity router is later; keep the `tier_for(...)` seam.
- **Guest = least-privilege**: an unknown speaker (`identify → None`) is routed to a guest scope (`guest_scope(person_id)` from M2-b, where the guest `person_id` is a stable per-unknown-voice id OR a single shared `guest` id in M5). → impact: Caution. DECISION: an unknown speaker (identify→None) routes to a SINGLE shared `guest` PersonId/scope (matches M2-b light-guest infra). Per-guest clustering is a later refinement.
- The VOICE path is distinct from the TEXT path: M2-b made the TEXT/app surface owner-authenticated (unlocked-session ⇒ owner, else `LOCKED`). M5-c adds the VOICE path: identity comes from SpeakerID (not from an unlocked session), so a voice owner can be identified-but-locked. The Gateway gains a voice-specific entry that the M5-d loop calls. → impact: Stop (the TEXT path is unchanged; M5-c ADDS a voice entry, does not alter the text-path semantics).

Simplicity check: considered enrolling/matching inside the owner SQLCipher store (so voiceprints are DEK-encrypted) — rejected for the matching path because identity resolution must work WHILE LOCKED to route a voice owner to Tier-0 (and to classify unknowns as guests); gating identification on a full owner unlock would make voice useless before unlock. Storing voiceprints under the Tier-0 key (identity is a Tier-0-class need, not a Tier-1 secret) is the minimal privacy-correct choice. Considered building the full sensitivity router now — rejected; M5-c needs only a Tier-0/Tier-1 boolean, and the manifest sensitivity flag already supplies it. Considered per-guest voiceprint clustering — rejected for M5 (a single shared guest scope is the minimum that honours least-privilege).

## Prerequisites
- Specs that must be complete first: **M0-a** (paths/scope_dir/config), **M0-d** (`SpeakerID` port + `PersonId`/types), **M2-b** (`Identity`/`scopes_for`/`primary_scope`/the Gateway + `KeyProvider.is_owner_unlocked`/the guest seam), **M2-c** (the Tier-0 proactive key the voiceprint store is encrypted under + `BrokerKeyProvider`), **M1-a** (the `ModuleManifest.data_scope` flag the Tier classifier reads — `tier.py` imports `DataScope`; the registry the Gateway resolves the matched module against).
- Environment setup required: SpeechBrain (PyTorch) added via `uv` at the GATED on-hardware task behind a lazy import; off-hardware testable with `FakeSpeakerID` + fakes. **Real ECAPA enrolment/matching + the threshold are GATED on-hardware (Task 6).**

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/voice/speaker_id.py | create | `EcapaSpeakerID` implementing the `SpeakerID` port (enrol + identify + threshold) + `VoiceprintStore` (Tier-0-keyed) + `FakeSpeakerID` |
| /Users/artemis-build/artemis/src/artemis/identity/tier.py | create | minimal Tier-0/Tier-1 classifier: `tier_for(matched_module: str | None) -> Tier` reading the sensitive-module set |
| /Users/artemis-build/artemis/src/artemis/gateway.py | modify | add the VOICE-path entry: SpeakerID→Identity→scope; encode voice-ID≠key (Tier-1-while-locked → NEEDS_PHONE_UNLOCK; Tier-0 proceeds; unknown→guest) |
| /Users/artemis-build/artemis/tests/test_speaker_id_voice_scope.py | create | adapter + store + Tier classifier + Gateway voice-path scope/nuance tests against fakes |

## Tasks
- [ ] Task 1: Implement the SpeakerID adapter + voiceprint store — files: `/Users/artemis-build/artemis/src/artemis/voice/speaker_id.py` — 
  - `class VoiceprintStore` constructed with `(settings, key_provider)`: stores/loads per-person embeddings under `scope_dir(...)/voiceprints/` ENCRYPTED under the Tier-0 proactive key (per the Assumptions privacy call — readable while the owner session is locked, since identity is Tier-0-class). `def enrol(person_id, embedding)`, `def all_voiceprints() -> Mapping[PersonId, Vector]`, `def has_any() -> bool`. (In M5 the encryption is a thin wrapper the Tier-0 key path fills. The voiceprint store MUST be encrypted under the Tier-0 proactive key (M2-c) — if the Tier-0 read path is not yet available at build time, BLOCK on M2-c rather than storing plaintext; plaintext voiceprints at rest are NOT acceptable. Embeddings-only, encrypted, never-logged is the hardened requirement.)
  - `class EcapaSpeakerID` structurally satisfying `artemis.ports.SpeakerID`: `_load_ecapa()` lazy-loads SpeechBrain ECAPA (real model behind a lazy import; monkeypatched in tests). `def enrol(self, person_id: PersonId, audio: bytes) -> None`: compute the ECAPA embedding of 16 kHz/mono/Int16 enrolment audio (the M5-a/M5-b format) → `store.enrol`. `def identify(self, audio: bytes) -> PersonId | None`: compute the embedding, cosine-match against `store.all_voiceprints()`; return the best `PersonId` if its score ≥ threshold (config, default per Assumptions) else `None`. `def warmup(self) -> None`: load the model. Wrap errors → typed `SpeakerIDError`.
  - `class FakeSpeakerID` (TEST): constructed with a dict `{utterance-key: PersonId | None}` or a scripted return so `identify` is deterministic without the model; `enrol` records calls.
  — done when: `uv run mypy --strict src` passes; `FakeSpeakerID().identify(b"...")` returns the scripted value; a static `_s: SpeakerID = EcapaSpeakerID(...)` conformance assertion type-checks.

- [ ] Task 2: Implement the minimal Tier classifier — files: `/Users/artemis-build/artemis/src/artemis/identity/tier.py` — `Tier = Literal["tier0","tier1"]`; import `DataScope` from `artemis.manifest` (M1-a). `def tier_for(data_scope: DataScope | None) -> Tier`: return `"tier1"` if `data_scope == DataScope.OWNER_PRIVATE` else `"tier0"` (None ⇒ tier0). This reads the M1-a `ModuleManifest.data_scope` as the Tier source of truth (RESOLVED 2026-06-08 — M1-a carries `data_scope`, a superset of a sensitive bool; NO name-keyed stopgap). Document: the modules mapping to `OWNER_PRIVATE` in v1 are the sensitive set (finance/health/journal/memory); the full provenance/sensitivity router is a later milestone — keep the seam so it swaps in. — done when: `uv run mypy --strict src` passes; `tier_for(DataScope.OWNER_PRIVATE) == "tier1"`, `tier_for(DataScope.SHARED) == "tier0"`, `tier_for(None) == "tier0"`.

- [ ] Task 3: Add the VOICE-path scope-attach to the Gateway (encode voice-ID≠key) — files: `/Users/artemis-build/artemis/src/artemis/gateway.py` — modify `Gateway`: constructor also takes a `SpeakerID` (injected; tests pass `FakeSpeakerID`). Add:
  - `def _resolve_voice_identity(self, audio: bytes) -> Identity`: `pid = speaker_id.identify(audio)`; if `pid == OWNER_PERSON_ID` → `Identity(OWNER_PERSON_ID, "owner")`; elif `pid is not None` → a recognised guest `Identity(pid, "guest")`; else (None, unknown) → the shared-guest `Identity(GUEST_PERSON_ID, "guest")` (define `GUEST_PERSON_ID: PersonId`). This FILLS M2-b's deferred `_resolve_guest` seam for the voice path.
  - `async def handle_voice(self, audio: bytes, transcript: str) -> BrainResponse`: (1) `identity = self._resolve_voice_identity(audio)`; (2) `scope = primary_scope(identity)`; (3) classify the Tier BEFORE serving: call `module_fq = brain.pre_route(transcript, scope)` (the M1 cross-milestone back-fill — returns the top candidate `module.tool` id, or `None`), resolve the matched module's `data_scope` via the registry the brain holds (`registry.manifests()[module_fq.split(".")[0]].data_scope`, guarding a missing/None module → `data_scope=None`), and `tier = tier_for(data_scope)`. Apply the nuance:
    - if `identity.role == "owner"` AND `tier == "tier1"` AND NOT `key_provider.is_owner_unlocked()` → return a typed `BrainResponse(text="NEEDS_PHONE_UNLOCK", path="needs-unlock", tool_used=None, escalated=False)` (do NOT serve the sensitive owner data; ask for the phone proof — voice identified you, but the secret needs the broker unlock).
    - otherwise (owner Tier-0, or owner Tier-1 WITH an unlocked session, or guest) → proceed: `return await brain.respond(transcript, scope)` (guest scope for guests = least-privilege, walled by M2-b's `scopes_for`).
  - Keep the TEXT-path `handle_text`/`handle_text_stream` from M2-b UNCHANGED. Update `compose_brain` to also construct + inject the `SpeakerID` (default real `EcapaSpeakerID`; tests inject `FakeSpeakerID`).
  — done when: `uv run mypy --strict src` passes; the voice path returns `NEEDS_PHONE_UNLOCK` for a locked-owner Tier-1 request and proceeds for owner Tier-0 / guest (Task 4). DECISION (CROSS-MILESTONE DEP, RESOLVED): the Gateway classifies the Tier BEFORE serving via `Brain.pre_route(text, scope) -> str | None` (top candidate `module.tool` id) — already added to the Brain (M1-b) + surfaced on the Gateway (M1-c). The Gateway calls `brain.pre_route(transcript, scope)`, resolves the module's `data_scope`, classifies via `tier_for(...)`, applies voice-ID≠key, then (if allowed) calls `brain.respond`. `BrainResponse.tool_used`/`path` is too late (known only after serving).

- [ ] Task 4: Write the speaker-ID + voice-scope tests — files: `/Users/artemis-build/artemis/tests/test_speaker_id_voice_scope.py` — typed pytest, off-hardware with fakes:
  - SpeakerID adapter: `FakeSpeakerID` scripted to return `OWNER_PERSON_ID`, a known guest, and `None`; assert `identify` returns each; `EcapaSpeakerID` static conformance `_s: SpeakerID = ...` type-checks (loader monkeypatched).
  - voiceprint store: `enrol` then `all_voiceprints()` round-trips a voiceprint per person; (if Tier-0-keyed) the stored bytes are not plaintext-readable as the raw embedding (best-effort assert).
  - Tier classifier: `tier_for(DataScope.OWNER_PRIVATE)=="tier1"`, `tier_for(DataScope.SHARED)=="tier0"`, `tier_for(None)=="tier0"`.
  - Gateway voice nuance (the load-bearing tests; the FakeBrain exposes `pre_route` returning a module fq + a registry whose manifest carries the module's `data_scope`):
    - voice OWNER + Tier-1 (pre_route → an `OWNER_PRIVATE` module) + `is_owner_unlocked()==False` → `handle_voice` returns `text=="NEEDS_PHONE_UNLOCK"` and the FakeBrain was NOT asked to serve (no `respond` call, or a guarded one).
    - voice OWNER + Tier-0 (pre_route → a `SHARED` module) + locked → proceeds: FakeBrain `respond` called with `OWNER_PRIVATE` scope; returns the brain's answer (NOT `NEEDS_PHONE_UNLOCK`).
    - voice OWNER + Tier-1 + `is_owner_unlocked()==True` → proceeds: `respond` called with `OWNER_PRIVATE`.
    - voice UNKNOWN (`identify→None`) → guest: `respond` called with the shared `guest` scope; `scopes_for(guest)` contains NO owner scope (wall intact, M2-b).
    - regression: the TEXT path `handle_text` still behaves as M2-b (owner-unlocked ⇒ owner; locked ⇒ `LOCKED`).
  — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_speaker_id_voice_scope.py` passes.

- [ ] Task 5: (off-hardware) enrolment CLI/flow seam — files: `/Users/artemis-build/artemis/src/artemis/voice/speaker_id.py` (extend) — add a tiny `def enrol_owner(audio_clips: Sequence[bytes], speaker_id: SpeakerID) -> None` convenience that enrols `OWNER_PERSON_ID` from one or more clips (the real owner-enrolment UX is a later app milestone; M5 ships the programmatic enrol used by the on-hardware bring-up). — done when: `uv run mypy --strict src` passes; `enrol_owner([b"..."], FakeSpeakerID())` records an `enrol` call for `OWNER_PERSON_ID`.

- [ ] Task 6 (GATED — on-hardware): Real ECAPA enrol + identify + threshold — files: (no repo files; adds SpeechBrain via `uv add` + exercises Task 1's real loader) — on the Mac Mini: `uv add` the confirmed SpeechBrain package; enrol the owner from a few seconds of real speech; then `identify` (a) the owner's voice → `OWNER_PERSON_ID`, (b) a different person's voice → `None` (unknown → guest); tune the cosine threshold so owner-accept / stranger-reject is reliable. Build-time empirical (model + real voices). — done when: on the Mini, the owner is identified and a stranger is rejected at the tuned threshold — recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/voice/speaker_id.py, /Users/artemis-build/artemis/src/artemis/identity/tier.py, /Users/artemis-build/artemis/tests/test_speaker_id_voice_scope.py |
| Modify | /Users/artemis-build/artemis/src/artemis/gateway.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_speaker_id_voice_scope.py` | Type gate |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate (fakes; no model) |
| `uv add speechbrain` (GATED, on-Mini) | ECAPA model package (confirm name at GATED Task 6) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/voice/speaker_id.py, src/artemis/identity/tier.py, src/artemis/gateway.py, tests/test_speaker_id_voice_scope.py, pyproject.toml, uv.lock |
| `git commit` | "feat: M5-c speaker-ID (ECAPA-TDNN) + voice-path scope-attach (voice-ID≠key: Tier-1-while-locked asks phone unlock)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Slot Settings (scope dirs, model dir, threshold) |
| `ARTEMIS_MODEL_DIR` | ECAPA model weights location (shared with M0-c) |

### Network
| Action | Purpose |
|--------|---------|
| `uv add speechbrain` (GATED) | Package install (PyPI) |
| (GATED, on-Mini) model fetch | Download the ECAPA-TDNN weights |

## Specialist Context
### Security
This spec is the VOICE half of the identity wall (ADR-005/006). Hard invariants the build MUST honour: voice-ID ROUTES to owner scope but NEVER unlocks the owner DEK — a Tier-1 request on a locked owner returns `NEEDS_PHONE_UNLOCK`, never the sensitive data (the phone-attested broker proof remains the only unlock). An unknown speaker gets the least-privilege guest scope; `scopes_for(guest)` never includes an owner scope (M2-b wall). Voiceprints are owner-sensitive identity data → encrypted under the Tier-0 key (identity is a Tier-0-class need, readable while locked for routing, but still not plaintext at rest). Captured/enrolment audio is never written to a log. [HARD FLAG for the apex-security gate: review (1) the voice-ID≠key boundary — confirm NO voice-only path reaches Tier-1 owner data; (2) the Tier classifier completeness (the minimal sensitive-module set must not under-classify); (3) the voiceprint store's Tier-0-key encryption + the unknown→guest least-privilege routing — before any sensitive store is reachable by voice.]

### Performance
`identify` runs once per utterance (after STT, off the barge-in path). The voiceprint store is small (a handful of people) so cosine matching is trivial. ECAPA on CPU/MPS keeps it off the GPU the responder uses. The Tier classifier is a set lookup (zero model). The Gateway pre-route reuses the existing M1-b SemanticRouter (zero extra model).

### Accessibility
(none — voice IS the accessibility surface; no rendered UI here.)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/voice/speaker_id.py, src/artemis/identity/tier.py, src/artemis/gateway.py | Type + docstring all exports; document the voice-ID=identity-not-auth boundary, the Tier-1-while-locked→NEEDS_PHONE_UNLOCK rule, the unknown→guest least-privilege routing, and the Tier-0-keyed voiceprint store |

## Acceptance Criteria
- [ ] Run `uv run mypy --strict src tests/test_speaker_id_voice_scope.py` → verify: exit 0 (incl. `SpeakerID` structural conformance).
- [ ] Run `uv run pytest -q tests/test_speaker_id_voice_scope.py` → verify: voice OWNER+Tier-1+locked → `NEEDS_PHONE_UNLOCK` (sensitive data NOT served); OWNER+Tier-0+locked → proceeds with `OWNER_PRIVATE`; OWNER+Tier-1+unlocked → proceeds; UNKNOWN → guest scope with NO owner scope; the TEXT path is unchanged (regression).
- [ ] Run `uv run python -c "from artemis.identity.tier import tier_for; from artemis.manifest import DataScope; print(tier_for(DataScope.OWNER_PRIVATE), tier_for(DataScope.SHARED), tier_for(None))"` → verify: prints `tier1 tier0 tier0`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] (GATED, on Mini) Real ECAPA: owner enrolled then identified; stranger rejected at the tuned threshold → verify recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_

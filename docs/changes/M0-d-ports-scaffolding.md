---
spec: m0-d-ports-scaffolding
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M0-d — Ports scaffolding (typed Python Protocols for every swappable seam)

**Identity:** Creates the `ports/` package: typed Python `Protocol` definitions (signatures only, NO implementations) for every upgradeability port — `Retriever`, `MemoryStore`, `EmbeddingModel`, `VectorStore`, `Reranker`, `Router`, `ModelPort`, and voice ports `WakeWord`/`STT`/`TTS`/`VAD`/`SpeakerID`/`AudioFrontend`.
→ why: see docs/technical/architecture/brain.md § "Upgradeability — the ports" (the exact port list + the `person_id`/`as_of` signature requirements) · docs/technical/architecture/data-model.md (MemoryStore/EmbeddingModel semantics) · docs/technical/adr/ADR-004-memory-engine.md (bitemporal `as_of`).

<!-- Split rule: ONE logical phase (define the port package), but it creates many small files (one Protocol module per port + a package init + a tests file). The files are uniform and trivially independent (each is a typed interface with zero logic); they are kept in one spec because they share the shared types module and must type-check together as the single `ports` package. This is a deliberate, justified exception to the ≤3-files guideline — the unit is "the ports package." Flagged per rules. -->

## Assumptions
- M0-a is complete: `src/artemis/` package + `mypy --strict` + `pydantic.mypy` plugin configured. → impact: Stop (these Protocols live in `src/artemis/ports/` and must pass strict mypy).
- Ports are pure interfaces: `typing.Protocol` (PEP 544, structural typing), `@runtime_checkable` only where a runtime isinstance check will be needed (default: not). No ABCs, no base classes, no logic, no imports of any concrete engine. → impact: Stop (M0 deliverable is interfaces only; any implementation here is out of scope).
- Shared domain types (`PersonId`, `Scope`, `Vector`, `ChunkRef`, etc.) are defined once in `ports/types.py` and imported by the port modules. → impact: Caution (keeps signatures consistent; if split differently, signatures still must match brain.md).
- Vectors are represented as `Sequence[float]` (engine-agnostic) in M0; the concrete `numpy`/array type is an implementation detail deferred to the adapter milestones. → impact: Low.
- `as_of` is a bitemporal tuple (valid-time, tx-time) per ADR-004's four-timestamp pattern. → impact: Caution. DECISION (ADR-004): `as_of` is an `AsOf` frozen dataclass `{valid_at: datetime, tx_at: datetime | None = None}` — `valid_at` required, `tx_at` optional, defaulting to now (`AsOf(valid_at, tx_at→now)`); used everywhere `as_of` appears in a port signature.

Simplicity check: considered defining ports as ABCs with `@abstractmethod` — rejected; `Protocol` gives structural typing so adapters need not inherit (looser coupling, matches "best today, replaceable tomorrow"), and brain.md says the Brain depends only on ports. Protocol is the minimum and the better fit.

## Prerequisites
- Specs that must be complete first: M0-a (package + mypy config).
- Environment setup required: none beyond M0-a. Fully deterministic; no on-hardware gate.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/src/artemis/ports/__init__.py | create | re-exports every Protocol + shared types |
| /Users/artemis-build/artemis/src/artemis/ports/types.py | create | shared domain types: `PersonId`, `Scope`, `AsOf`, `Vector`, `Document`, `Chunk`, `RetrievedChunk`, `Fact`, `Mode` |
| /Users/artemis-build/artemis/src/artemis/ports/retrieval.py | create | `Retriever`, `VectorStore`, `Reranker`, `EmbeddingModel` Protocols |
| /Users/artemis-build/artemis/src/artemis/ports/memory.py | create | `MemoryStore` Protocol (`person_id` + `as_of` in signatures) |
| /Users/artemis-build/artemis/src/artemis/ports/routing.py | create | `Router` Protocol |
| /Users/artemis-build/artemis/src/artemis/ports/model.py | create | `ModelPort` Protocol (OpenAI-compatible; logical roles) |
| /Users/artemis-build/artemis/src/artemis/ports/voice.py | create | `WakeWord`, `STT`, `TTS`, `VAD`, `SpeakerID`, `AudioFrontend` Protocols |
| /Users/artemis-build/artemis/tests/test_ports.py | create | static-shape tests: importable, `Protocol`, no concrete logic |

## Tasks
- [ ] Task 1: Define shared port types — files: `/Users/artemis-build/artemis/src/artemis/ports/types.py` — define: `PersonId = NewType("PersonId", str)`; `Scope` as `Literal["owner-private","general"] | str` (guest scopes are `guest-<id>`); `Vector = Sequence[float]`; an `AsOf` frozen dataclass `{valid_at: datetime, tx_at: datetime | None = None}`; `Mode = Literal["hybrid","agentic","graph"]` (the retrieve-mode from brain.md); lightweight frozen dataclasses `Document {document_id: str, source_id: str, content_hash: str, scope: Scope, text: str}`, `Chunk {chunk_id: str, document_id: str, text: str, scope: Scope}`, `RetrievedChunk {chunk: Chunk, score: float}`, `Fact {fact_id: str, person_id: PersonId, subject: str, relation: str, object: str, confidence: float, valid_at: datetime, invalid_at: datetime | None}`. All dataclasses `frozen=True`, fully typed. — done when: `uv run mypy --strict src` passes for types.py.

- [ ] Task 2: Define the retrieval ports — files: `/Users/artemis-build/artemis/src/artemis/ports/retrieval.py` — four `Protocol`s, methods bodies = `...` only:
  - `EmbeddingModel`: `def embed(self, texts: Sequence[str]) -> list[Vector]: ...`; `@property def dimension(self) -> int: ...` (dimension locked in store metadata per brain.md — exposed read-only).
  - `VectorStore`: `def add(self, scope: Scope, ids: Sequence[str], vectors: Sequence[Vector], metadata: Sequence[Mapping[str, object]]) -> None: ...`; `def search(self, scope: Scope, query: Vector, k: int) -> list[RetrievedChunk]: ...`.
  - `Reranker`: `def rerank(self, query: str, chunks: Sequence[RetrievedChunk], top_k: int) -> list[RetrievedChunk]: ...`.
  - `Retriever`: `def retrieve(self, query: str, scope: Scope, mode: Mode = "hybrid", k: int = 10) -> list[RetrievedChunk]: ...` (the `retrieve(query, mode)` port from brain.md).
  Each is a bare `Protocol`; no `__init__`. — done when: `uv run mypy --strict src` passes; importing each name succeeds.

- [ ] Task 3: Define the MemoryStore port — files: `/Users/artemis-build/artemis/src/artemis/ports/memory.py` — `MemoryStore(Protocol)` with `person_id` + `as_of` in signatures per brain.md/ADR-004, bodies `...`:
  - `def add_fact(self, person_id: PersonId, fact: Fact) -> None: ...`
  - `def recall(self, person_id: PersonId, query: str, k: int = 10, as_of: AsOf | None = None) -> list[Fact]: ...` (as_of=None → now; bitemporal recall)
  - `def update_fact(self, person_id: PersonId, fact_id: str, fact: Fact) -> None: ...` (close prior interval + insert — semantics doc'd in docstring, no logic)
  - `def delete_fact(self, person_id: PersonId, fact_id: str) -> None: ...` (tombstone, never hard-delete — doc'd)
  - `def inject_context(self, person_id: PersonId, token_budget: int, as_of: AsOf | None = None) -> list[Fact]: ...` (auto-inject the current top facts)
  — done when: `uv run mypy --strict src` passes; every method carries `person_id` and the recall/inject methods carry `as_of`.

- [ ] Task 4: Define the routing + model ports — files: `/Users/artemis-build/artemis/src/artemis/ports/routing.py`, `/Users/artemis-build/artemis/src/artemis/ports/model.py` —
  - routing.py `Router(Protocol)`: `def route(self, request_text: str, scope: Scope) -> RouteDecision: ...` where `RouteDecision` is a frozen dataclass `{path: Literal["deterministic","local","escalate"], candidate_tools: Sequence[str], confidence: float}` (router-first, brain.md).
  - model.py `ModelPort(Protocol)`: OpenAI-compatible chat by logical role — `def complete(self, role: str, messages: Sequence[Mapping[str, str]], *, stream: bool = False, response_schema: Mapping[str, object] | None = None) -> ModelResponse: ...` (role = "responder"/"teacher"/...; `response_schema` carries the constrained-decoding schema seam); plus `def embed(self, role: str, texts: Sequence[str]) -> list[Vector]: ...`. `ModelResponse` frozen dataclass `{text: str, finish_reason: str, usage: Mapping[str, int]}`. Bodies `...`. — done when: `uv run mypy --strict src` passes.

- [ ] Task 5: Define the voice ports — files: `/Users/artemis-build/artemis/src/artemis/ports/voice.py` — six `Protocol`s, audio represented as `bytes` (PCM frames) in M0, bodies `...`:
  - `WakeWord`: `def detect(self, frame: bytes) -> bool: ...`
  - `VAD`: `def is_speech(self, frame: bytes) -> bool: ...`
  - `STT`: `def transcribe(self, audio: bytes, *, language: str | None = None) -> str: ...`
  - `TTS`: `def synthesize(self, text: str) -> Iterator[bytes]: ...` (streamed sentence-by-sentence per brain.md)
  - `SpeakerID`: `def identify(self, audio: bytes) -> PersonId | None: ...` (None → unknown → guest; identity-not-auth)
  - `AudioFrontend`: `def capture(self) -> Iterator[bytes]: ...`; `def play(self, audio: Iterator[bytes]) -> None: ...` (the AEC/barge-in boundary; multi-room satellites are more AudioFrontends).
  — done when: `uv run mypy --strict src` passes; all six importable.

- [ ] Task 6: Re-export the package surface — files: `/Users/artemis-build/artemis/src/artemis/ports/__init__.py` — `from .types import *`-style explicit re-exports of every type + every Protocol, with an `__all__` listing all of them. — done when: `uv run python -c "from artemis.ports import Retriever, MemoryStore, EmbeddingModel, VectorStore, Reranker, Router, ModelPort, WakeWord, STT, TTS, VAD, SpeakerID, AudioFrontend"` exits 0.

- [ ] Task 7: Write the static-shape tests — files: `/Users/artemis-build/artemis/tests/test_ports.py` — for each Protocol: assert it is importable and `isinstance(P, type)` and that it is a `typing.Protocol` (check `getattr(P, "_is_protocol", False) is True`); assert the `MemoryStore.recall` signature includes parameters named `person_id` and `as_of` (via `inspect.signature`); assert no Protocol method has a non-`...` body by confirming a minimal in-test dummy class satisfying the Protocol passes a `isinstance`/structural check (define a tiny conforming stub and assign it to a variable typed as the Protocol — this is a type-check assertion, validated by mypy in the recipe). — done when: `uv run pytest -q` passes AND `uv run mypy --strict src tests/test_ports.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/src/artemis/ports/__init__.py, /Users/artemis-build/artemis/src/artemis/ports/types.py, /Users/artemis-build/artemis/src/artemis/ports/retrieval.py, /Users/artemis-build/artemis/src/artemis/ports/memory.py, /Users/artemis-build/artemis/src/artemis/ports/routing.py, /Users/artemis-build/artemis/src/artemis/ports/model.py, /Users/artemis-build/artemis/src/artemis/ports/voice.py, /Users/artemis-build/artemis/tests/test_ports.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests` | Type gate (the load-bearing check for interface-only code) |
| `uv run ruff check . ; uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/ports/**, tests/test_ports.py |
| `git commit` | "feat: M0-d ports scaffolding — typed Protocols for every swappable seam" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Pure interface definitions; no env |

### Network
| Action | Purpose |
|--------|---------|
| (none) | No new dependencies |

## Specialist Context
### Security
`MemoryStore` carries `person_id` on every method — the hard partition key the crypto wall enforces physically (one SQLCipher file per scope, ADR-004). The port makes per-person scoping non-optional at the type level. `Scope` is required on retrieval/vector methods for the same reason.

### Performance
`Retriever.retrieve(mode=...)` and `TTS.synthesize -> Iterator[bytes]` encode the brain.md latency design (adaptive RAG mode; streamed TTS) at the interface so adapters can't accidentally make them blocking.

### Accessibility
(none — no frontend)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | all ports/*.py | Docstring each Protocol + each method (semantics only; the contract IS the doc) |

## Acceptance Criteria
- [ ] Run `uv run python -c "from artemis.ports import Retriever, MemoryStore, EmbeddingModel, VectorStore, Reranker, Router, ModelPort, WakeWord, STT, TTS, VAD, SpeakerID, AudioFrontend"` → verify: exit 0 (all 13 ports import).
- [ ] Run `uv run mypy --strict src tests` → verify: exit 0, no errors.
- [ ] Run `uv run python -c "import inspect; from artemis.ports import MemoryStore; p=inspect.signature(MemoryStore.recall).parameters; assert 'person_id' in p and 'as_of' in p"` → verify: exit 0 (no AssertionError).
- [ ] Run `uv run pytest -q` → verify: test_ports passes; each Protocol confirmed `_is_protocol`.
- [ ] Run `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.

## Progress
_(Coding mode writes here — do not edit manually)_

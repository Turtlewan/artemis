---
spec: sensitivity-ground-rules
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- Wave S · MULTI-FILE · builds the three-layer sensitivity tagging policy (ground-rules →
     classifier → ask-owner) + the Source.force_sensitive lever + deterministic detectors
     (Luhn/NRIC/regex) + the policy.json SensitivityConfig section + the ask-and-graduate seam.
     Also amends FIN-d (push_finance_knowledge stops forcing soft facts sensitive).
     cross_model_review: true (privacy-critical; a tagging miss leaks to cloud unrecoverably). -->

# Spec: sensitivity-ground-rules — three-layer tagging policy, Source.force_sensitive, deterministic detectors, FIN-d amendment

**Identity:** Implement the Ground Rules v1 sensitivity tagging policy — a deterministic first layer (domain force-flag + content detectors) that runs before the local classifier, ensuring card numbers and government IDs are caught by code that cannot be prompt-injected. Adds `Source.force_sensitive`, the `SensitivityConfig` section to `RuntimeConfig`/`policy.json`, a new `detectors.py` module (Luhn, NRIC checksum, regex for DOB/address, mask-depth guard), the ask-and-graduate surface (fail-closed → owner review → new policy rule), and amends FIN-d so soft finance facts route through the classifier instead of being force-tagged sensitive.
→ why: docs/findings/sensitivity-ground-rules-v1.md · ADR-022 § Refinement 2026-06-25 · ADR-029.

## Assumptions

- `Source` is a `frozen=True` dataclass in `src/artemis/ingest/connectors.py` (line 19-26). Adding a field with a default to a frozen dataclass is non-breaking. → impact: Stop.
- `IngestPipeline.ingest` (line 67, `src/artemis/ingest/pipeline.py`) always calls `await self._classify_source(document)` at line 96. The `force_sensitive` branch will short-circuit this. `document.sensitivity` is a plain attribute assignment (not `frozen`). → impact: Stop.
- `Sensitivity = Literal["general", "sensitive"]` is defined in `src/artemis/sensitivity.py` (line 28). The new detectors module imports this type. → impact: Stop.
- `RuntimeConfig` is a Pydantic `BaseModel` with `extra="forbid"` and sub-models per cluster surface (`src/artemis/runtime_config.py`, line 245). Adding a new `SensitivityConfig` sub-model field follows the exact same pattern as `GmailConfig`, `CalendarConfig`, etc. → impact: Stop.
- `push_finance_knowledge` in `src/artemis/modules/finance/knowledge.py` (lines 129-171) currently pushes each fact to BOTH general memory (`memory_queue.enqueue`, line 153-157) AND the knowledge index (`ingest.ingest`, line 159). The FIN-d amendment (owner decision 2026-06-25, Option A) **drops the memory enqueue entirely** — finance is excluded from general memory per owner-rule; soft facts go to the knowledge index (general), retrieved on-demand via the now-wired `retriever-wiring`. Removing the enqueue orphans the `memory_queue` param + `MemoryQueuePort` + the `manifest.py` wiring → clean those up. → impact: Stop (memory write removed; knowledge push and the privacy comment updated).
- The ask-and-graduate seam (Task 4) is a stub: a `SensitivityReviewQueue` that records items for owner review and promotes answers to `policy.json`. The M7-b needs-review pattern does not yet exist as a live surface (`needs_review` / `NeedsReview` not found in `src/`); this spec stubs the seam without a UI surface. The real owner-review surface is HW-gated (see below).
- `SensitivityClassifierProtocol.classify(request_text: str) -> Sensitivity` is the existing async protocol in `src/artemis/sensitivity.py` (line 70-77). The pipeline uses it as `self._classifier` (line 57, 64). No signature change needed. → impact: Stop.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `src/artemis/ingest/connectors.py` | modify | Add `force_sensitive: bool = False` to `Source` frozen dataclass |
| `src/artemis/ingest/pipeline.py` | modify | Add force_sensitive branch in `ingest()` before `_classify_source` |
| `src/artemis/sensitivity_detectors.py` | create | Deterministic detectors: Luhn, NRIC checksum, DOB/address regex, mask-depth guard |
| `src/artemis/ingest/pipeline.py` | modify | Wire detectors into `_classify_source` as the pre-classifier layer |
| `src/artemis/runtime_config.py` | modify | Add `SensitivityConfig` Pydantic model + field on `RuntimeConfig` |
| `src/artemis/modules/finance/knowledge.py` | modify | FIN-d amendment (Option A): drop the memory `enqueue` entirely (finance excluded from general memory per owner-rule); knowledge push stays. Remove orphaned `memory_queue` param + `MemoryQueuePort` |
| `src/artemis/modules/finance/manifest.py` | modify | Stop threading `memory_queue` into `init_finance_knowledge` (orphan cleanup from the FIN-d amendment) |
| `src/artemis/sensitivity_review.py` | create | Ask-and-graduate stub: `SensitivityReviewQueue` + `graduate_to_policy` |
| `tests/test_sensitivity_detectors.py` | create | Detector unit tests |
| `tests/test_sensitivity_ground_rules.py` | create | Pipeline integration: force_sensitive branch + detector pre-layer |
| `tests/test_fin_d_amendment.py` | create | FIN-d: soft facts no longer forced sensitive |

## Tasks

### Task 1: `Source.force_sensitive` — `src/artemis/ingest/connectors.py`

Add one field to the `Source` dataclass (after `scope`, before the closing paren):

```python
@dataclass(frozen=True)
class Source:
    """A source URI to ingest into a scope."""

    kind: Literal["file", "web", "email", "email_attachment", "calendar_meeting"]
    uri: str
    scope: Scope
    force_sensitive: bool = False
    """One-directional override: True forces sensitivity="sensitive" and skips classification.
    Callers may only UPGRADE to sensitive, never assert general. Set by journal, health,
    and email connectors (whole-domain hard-sensitive). Finance connectors do NOT set this."""
```

No other changes in this file.

Done when: `uv run mypy src/artemis/ingest/connectors.py` clean; existing `Source(kind="file", uri=..., scope=...)` call sites still typecheck (default=False is backward-compatible).

### Task 2: `IngestPipeline.ingest` force_sensitive branch — `src/artemis/ingest/pipeline.py`

Replace lines 96-102 (the `_classify_source` call block):

```python
        # Ground-rules layer: if the source is force-flagged (journal/health/email
        # whole-domain), skip classification entirely and hard-lock to sensitive.
        if source.force_sensitive:
            document.sensitivity = "sensitive"
            logger.debug(
                "force_sensitive set: skipping classifier source_id=%s",
                document.source_id,
            )
        else:
            document.sensitivity = await self._classify_source(document)
        document.category = None
```

Done when: `uv run mypy src/artemis/ingest/pipeline.py` clean; a `Source(..., force_sensitive=True)` with a `classifier` that always returns `"general"` still yields `document.sensitivity == "sensitive"` (test in Task 7).

### Task 3: Deterministic detectors — `src/artemis/sensitivity_detectors.py` (new)

Create a new module. No LLM dependency; pure code. Three detector families:

```python
"""Deterministic sensitivity detectors for the Ground Rules v1 content layer.

These detectors run BEFORE the local classifier and catch the highest-value
items (full card numbers, government IDs, DOB, home address) with code that
cannot be prompt-injected. The classifier is the backstop for nuance.

All functions accept a plain str and return bool (True = sensitive signal found).
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Luhn check — card numbers
# ---------------------------------------------------------------------------

def _luhn_check(digits: str) -> bool:
    """Return True if the digit string passes the Luhn checksum."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


_CARD_STRIP_RE = re.compile(r"[\s\-]")
_CARD_DIGITS_RE = re.compile(r"\d{13,19}")

def has_full_card_number(text: str) -> bool:
    """True if text contains a Luhn-valid card-length digit sequence (13-19 digits).

    Rejects masked forms (•, *, X) — those are fine.  Only triggers on runs
    of plain ASCII digits that survive stripping of spaces/dashes.
    """
    stripped = _CARD_STRIP_RE.sub("", text)
    for m in _CARD_DIGITS_RE.finditer(stripped):
        if _luhn_check(m.group()):
            return True
    return False


# ---------------------------------------------------------------------------
# Mask depth guard — account tails
# ---------------------------------------------------------------------------

_MASKED_TAIL_RE = re.compile(r"[•*Xx]{2,}\s*(\d{4})")
_BARE_ACCT_RE = re.compile(r"\b\d{5,}\b")

def exceeds_masked_tail(text: str) -> bool:
    """True if text exposes more than the last-4 digits of an account/card number.

    A masked '•••• 1234' is fine (not sensitive).  A bare run of 5+ digits
    not preceded by a mask pattern is flagged.
    """
    masked_positions: set[int] = set()
    for m in _MASKED_TAIL_RE.finditer(text):
        masked_positions.add(m.start())
    for m in _BARE_ACCT_RE.finditer(text):
        if m.start() not in masked_positions:
            return True
    return False


# ---------------------------------------------------------------------------
# NRIC / FIN checksum (Singapore)
# ---------------------------------------------------------------------------

_NRIC_RE = re.compile(r"\b([STFGM])(\d{7})([A-Z])\b", re.IGNORECASE)
_NRIC_ST_WEIGHTS = (2, 7, 6, 5, 4, 3, 2)
_NRIC_FG_WEIGHTS = (2, 7, 6, 5, 4, 3, 2)
_NRIC_ST_LETTERS = "JZIHGFEDCBA"
_NRIC_FG_LETTERS = "XWUTRQPNMLK"
_NRIC_M_WEIGHTS = (2, 7, 6, 5, 4, 3, 2)
_NRIC_M_LETTERS = "XWUTRQPNMLK"  # same table as FG for M-series


def _nric_valid(prefix: str, digits: str, check: str) -> bool:
    prefix = prefix.upper()
    check = check.upper()
    weights = _NRIC_ST_WEIGHTS
    total = sum(int(d) * w for d, w in zip(digits, weights))
    if prefix in ("S", "T"):
        if prefix == "T":
            total += 4
        letters = _NRIC_ST_LETTERS
    elif prefix in ("F", "G"):
        if prefix == "G":
            total += 4
        letters = _NRIC_FG_LETTERS
    elif prefix == "M":
        total += 3
        letters = _NRIC_M_LETTERS
    else:
        return False
    return letters[total % 11] == check


def has_nric(text: str) -> bool:
    """True if text contains a structurally valid Singapore NRIC/FIN number."""
    for m in _NRIC_RE.finditer(text):
        if _nric_valid(m.group(1), m.group(2), m.group(3)):
            return True
    return False


# ---------------------------------------------------------------------------
# DOB — date-of-birth patterns
# ---------------------------------------------------------------------------

_DOB_RE = re.compile(
    r"\b(?:"
    r"(?:date of birth|dob|born on|birthday)[:\s]*"
    r"(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{2}[/\-\.]\d{2})"
    r"|"
    r"(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})"  # bare DD/MM/YYYY or MM/DD/YYYY
    r")\b",
    re.IGNORECASE,
)

def has_dob(text: str) -> bool:
    """True if text contains a date-of-birth pattern (labelled or bare 8-digit date)."""
    return bool(_DOB_RE.search(text))


# ---------------------------------------------------------------------------
# Home address
# ---------------------------------------------------------------------------

_ADDRESS_RE = re.compile(
    r"\b(?:"
    r"\d{1,5}\s+\w[\w\s]{1,30}(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|"
    r"close|crescent|place|pl|way|blvd|boulevard|terrace|terr|court|ct)"
    r"|"
    r"(?:blk|block)\s*\d{1,5}[a-z]?\s+\w[\w\s]{1,40}"  # Singapore block format
    r")\b",
    re.IGNORECASE,
)

def has_home_address(text: str) -> bool:
    """True if text contains a home address pattern."""
    return bool(_ADDRESS_RE.search(text))


# ---------------------------------------------------------------------------
# Combined gate
# ---------------------------------------------------------------------------

def is_content_sensitive(text: str) -> bool:
    """True if ANY deterministic detector fires on the text.

    Call this BEFORE the local classifier.  A True here → sensitivity="sensitive"
    immediately (no classifier call needed).  A False here → proceed to classifier.
    """
    return (
        has_full_card_number(text)
        or exceeds_masked_tail(text)
        or has_nric(text)
        or has_dob(text)
        or has_home_address(text)
    )
```

Done when: `uv run mypy src/artemis/sensitivity_detectors.py` clean; unit tests in Task 7 pass.

### Task 4: Wire detectors into `_classify_source` — `src/artemis/ingest/pipeline.py`

Modify `_classify_source` to run the detector layer first:

```python
    async def _classify_source(self, document: Document) -> Sensitivity:
        from artemis.sensitivity_detectors import is_content_sensitive

        # Deterministic layer: fires before the classifier for highest-value items
        # (card numbers, NRIC, DOB, address). Code-based — cannot be prompt-injected.
        if is_content_sensitive(document.text):
            logger.debug(
                "content detector fired: failing to sensitive source_id=%s",
                document.source_id,
            )
            return "sensitive"

        sensitivity: Sensitivity = "sensitive"
        if self._classifier is None:
            return sensitivity
        try:
            return await self._classifier.classify(document.text)
        except Exception as exc:
            logger.warning(
                "sensitivity classify failed (%s); failing closed to sensitive",
                type(exc).__name__,
            )
            return sensitivity
```

Done when: `uv run mypy src/artemis/ingest/pipeline.py` clean; a document containing a Luhn-valid card number is tagged `sensitive` even with a classifier stub that always returns `"general"` (test in Task 7).

### Task 5: `SensitivityConfig` in `RuntimeConfig` — `src/artemis/runtime_config.py`

Add a new Pydantic sub-model and wire it into `RuntimeConfig`. Pattern exactly follows `GmailConfig` / `CalendarConfig`.

```python
class SensitivityConfig(BaseModel):
    """Ground Rules v1 sensitivity policy — owner-tunable via policy.json.

    Domain rules (journal/health/email) are enforced by Source.force_sensitive
    at the connector layer and are NOT listed here (they are structural).
    This section holds the content-grade access/identity set and the classifier
    fail-closed posture.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hard_sensitive_domains: tuple[str, ...] = Field(
        default=("journal", "health", "email"),
        description=(
            "Whole-domain force-sensitive sources. Connectors for these domains "
            "set Source.force_sensitive=True; classification is skipped entirely."
        ),
    )
    access_grade_patterns: tuple[str, ...] = Field(
        default=(
            "full_card_number",
            "exceeds_masked_tail",
            "nric",
            "dob",
            "home_address",
        ),
        description=(
            "Content-grade detector IDs that hard-lock a document to sensitive "
            "regardless of source domain. Maps to sensitivity_detectors.py functions."
        ),
    )
    classifier_fail_closed: bool = Field(
        default=True,
        description=(
            "When True (mandatory), an uncertain or failing classifier result "
            "always resolves to sensitive. Must not be set to False in production."
        ),
    )
```

Add the field to `RuntimeConfig`:

```python
    sensitivity: SensitivityConfig = Field(
        default_factory=SensitivityConfig,
        description="Ground Rules v1 sensitivity tagging policy tunables.",
    )
```

Done when: `uv run mypy src/artemis/runtime_config.py` clean; `RuntimeConfig()` includes a `.sensitivity` field with defaults; `policy.json` with `{"sensitivity": {"classifier_fail_closed": true}}` round-trips cleanly.

### Task 6: FIN-d amendment — `src/artemis/modules/finance/knowledge.py`

**OWNER DECISION 2026-06-25 (Option A — drop the memory enqueue entirely).** `push_finance_knowledge` currently writes each finance fact to BOTH the knowledge index (via `ingest.ingest`, line 159) AND general memory (via `memory_queue.enqueue`, line 153-157). Per the owner's **locked rule — financial is excluded from general memory** ("financial → Finance ledger only"), reaffirmed 2026-06-25 — finance facts must NOT be in the bitemporal memory store. The **knowledge/RAG index** (general, retrieved on-demand — now wired via `retriever-wiring`) + the **Finance ledger** are the homes. (Note: simply dropping the `source_sensitivity` kwarg is INSUFFICIENT — `memory/extraction.py` resolves `None` → classifier/fail-closed-sensitive, so the fact would still land in memory. The call must be removed.) Amendment:

1. **Remove the entire `memory_queue.enqueue(...)` call** (lines ~153-157). Finance facts push to knowledge only.
2. **Surgical orphan cleanup** (CLAUDE.md §3): the `memory_queue` parameter of `push_finance_knowledge` and the `MemoryQueuePort` protocol (lines ~27-37) become unused → remove them. Update the caller `init_finance_knowledge` and `src/artemis/modules/finance/manifest.py` (line ~36 `init_finance_knowledge(ingest_pipeline, memory_queue, store.settings)`) to stop threading `memory_queue` into the knowledge push. (Confirm `memory_queue` isn't used elsewhere in that path before removing — if it is, leave the param and only drop the enqueue call.)
3. The `Source` passed to `ingest.ingest(...)` stays `force_sensitive=False` (default) — the pipeline classifies; access/identity-grade content in any fact text is still caught by the `sensitivity_detectors` layer in `_classify_source`.
4. Update the inline privacy comment (lines 150-153). Replace with:
   ```python
   # PRIVACY (ADR-022 § Refinement 2026-06-25 + owner rule): soft finance facts
   # (subscriptions, spending patterns, recurring merchants) are general / cloud-OK
   # and pushed to the KNOWLEDGE index only. Finance is EXCLUDED from general memory
   # (owner-rule: financial -> Finance ledger only) -- do NOT re-add a memory enqueue.
   # Access/identity-grade content in fact text is caught by sensitivity_detectors.
   ```

Done when: `uv run mypy src/artemis/modules/finance/knowledge.py src/artemis/modules/finance/manifest.py` clean; a test confirms `push_finance_knowledge` performs **no** memory write (the `ingest.ingest` knowledge push still occurs); no orphaned `memory_queue`/`MemoryQueuePort` references remain (test in Task 8).

### Task 7: Ask-and-graduate stub — `src/artemis/sensitivity_review.py` (new)

Stub the ask-and-graduate seam. Keeps the design surface open without a live UI (HW-gated).

```python
"""Ask-and-graduate seam for the Ground Rules v1 sensitivity fallback.

When the classifier is uncertain about a document (fail-closed → sensitive),
items are queued here for owner review. Owner answers graduate into new
policy.json rules so the same case stops asking.

The review surface (owner-facing UI) is HW-gated (Mac Mini bring-up).
This module provides the data layer: queue, persistence, and graduation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from artemis.sensitivity import Sensitivity

logger = logging.getLogger(__name__)


@dataclass
class SensitivityReviewItem:
    """A document queued for owner sensitivity review."""

    source_id: str
    text_preview: str  # first 200 chars only — never log full text
    proposed_sensitivity: Sensitivity = "sensitive"
    review_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex)


class SensitivityReviewQueue:
    """Persists items for owner sensitivity review (ask-and-graduate seam).

    Items are written to <slot_root>/sensitivity-review-queue.json.
    Owner answers (via future UI surface) call graduate_to_policy().
    """

    def __init__(self, queue_path: Path) -> None:
        self._path = queue_path

    def enqueue(self, item: SensitivityReviewItem) -> None:
        """Add an item to the review queue (append to JSON lines file)."""
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "review_id": item.review_id,
                "source_id": item.source_id,
                "text_preview": item.text_preview,
                "proposed_sensitivity": item.proposed_sensitivity,
            }) + "\n")

    def pending(self) -> list[SensitivityReviewItem]:
        """Return all pending review items."""
        if not self._path.exists():
            return []
        items = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            items.append(SensitivityReviewItem(
                source_id=raw["source_id"],
                text_preview=raw["text_preview"],
                proposed_sensitivity=raw["proposed_sensitivity"],
                review_id=raw["review_id"],
            ))
        return items


def graduate_to_policy(
    review_id: str,
    sensitivity: Sensitivity,
    policy_path: Path,
) -> None:
    """Record an owner answer as a new ground rule in policy.json.

    Reads the current policy.json, appends the new rule under
    sensitivity.owner_overrides (a dict mapping source_id pattern → sensitivity),
    and writes back.  Future ingestion of matching sources honours the override.

    HW-gated: this path is exercised only once the owner-review UI surface
    is live (Mac Mini bring-up).
    """
    raw: dict[str, object] = {}
    if policy_path.exists():
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
    sens_section = raw.setdefault("sensitivity", {})
    overrides = sens_section.setdefault("owner_overrides", {})
    overrides[review_id] = sensitivity
    policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    logger.info("graduated review_id=%s to sensitivity=%s", review_id, sensitivity)
```

Done when: `uv run mypy src/artemis/sensitivity_review.py` clean; `SensitivityReviewQueue.enqueue` + `pending` round-trip in tests; `graduate_to_policy` writes to policy.json.

### Task 8: Tests — `tests/test_sensitivity_detectors.py` + `tests/test_sensitivity_ground_rules.py` + `tests/test_fin_d_amendment.py`

**`tests/test_sensitivity_detectors.py`**
- `has_full_card_number`: Luhn-valid 16-digit number → True; Luhn-invalid → False; masked `•••• 1234` → False; spaced `4111 1111 1111 1111` → True.
- `exceeds_masked_tail`: bare `12345678901234` → True; `•••• 1234` → False.
- `has_nric`: valid `S1234567D` (checksum correct) → True; invalid checksum `S1234567A` → False.
- `has_dob`: `"Date of birth: 01/01/1990"` → True; `"born on 1990-01-01"` → True; bare `"2026-06-25"` (ISO date alone, no label) → False (not a DOB context).
- `has_home_address`: `"123 Orchard Road"` → True; `"Blk 456 Jurong West"` → True; `"hello world"` → False.
- `is_content_sensitive`: card → True; clean text → False.

**`tests/test_sensitivity_ground_rules.py`**
- `Source.force_sensitive` default is `False`; setting `True` is accepted.
- Pipeline with `force_sensitive=True` + classifier that returns `"general"` → `document.sensitivity == "sensitive"` (classifier not called).
- Pipeline with `force_sensitive=False` + Luhn-valid card in document text + classifier returning `"general"` → `document.sensitivity == "sensitive"` (detector fired before classifier).
- Pipeline with `force_sensitive=False` + clean text + classifier returning `"general"` → `document.sensitivity == "general"`.
- `_classify_source` with `classifier=None` + clean text → `"sensitive"` (no-classifier fail-closed unchanged).

**`tests/test_fin_d_amendment.py`**
- `push_finance_knowledge` with a `FakeMemoryWriteQueue` that records calls → **`enqueue` is never called** (zero memory writes) for spending-pattern/subscription facts; the `ingest.ingest` knowledge push still occurs.
- `FakeIngestPipeline` records `Source.force_sensitive` → asserts `False` for finance staging files.

Done when: all three test files pass `uv run pytest -q` and `uv run mypy` clean.

## Acceptance Criteria

- [ ] `uv run mypy` → exit 0 (full project, not file-scoped).
- [ ] `uv run pytest -q` → all tests pass including existing suite.
- [ ] `uv run ruff check . && uv run ruff format --check .` → both exit 0.
- [ ] `Source(kind="file", uri="x", scope="owner-private")` — `force_sensitive` defaults to `False`.
- [ ] Pipeline with `source.force_sensitive=True` → `document.sensitivity == "sensitive"` regardless of classifier return value.
- [ ] Pipeline with Luhn-valid card number in document text → `document.sensitivity == "sensitive"` even if classifier returns `"general"`.
- [ ] `push_finance_knowledge` performs no memory write at all (memory `enqueue` removed; `memory_queue`/`MemoryQueuePort`/`manifest.py` wiring cleaned up); knowledge push intact.
- [ ] `RuntimeConfig().sensitivity.hard_sensitive_domains == ("journal", "health", "email")`.
- [ ] `SensitivityReviewQueue` round-trips enqueue/pending in a tmp_path test.
- [ ] (HW-GATED, Mac Mini) `graduate_to_policy` writes owner override to `policy.json`; subsequent ingestion of a matching source honours the override.

## Commands to Run

```bash
uv run mypy
uv run ruff check . && uv run ruff format --check .
uv run pytest -q
```

## HW-Gated Rungs

- **Task 7 live UI surface** (`SensitivityReviewQueue.pending()` → owner-facing review card): deferred to Mac Mini bring-up. The data layer (queue file + `graduate_to_policy`) is built and tested here; only the UI surface is gated.
- **End-to-end privacy proof** (finance soft fact → RAG-compose → held back / passed through based on classifier label): gated on live LanceDB + enforcer stack (Mac).

## Ambiguities Flagged for Human Review

1. **`memory_queue.enqueue` `source_sensitivity` kwarg removal**: `push_finance_knowledge` passes `source_sensitivity="sensitive"` to `memory_queue.enqueue`. The decision record says to stop forcing soft facts sensitive, but if `MemoryWriteQueue.enqueue` has no fallback classifier and defaults to `sensitive` when `source_sensitivity=None`, soft facts would still be locked sensitive. Confirm whether `MemoryWriteQueue` has its own content classification path, or whether we need to pass `source_sensitivity="general"` explicitly. (The spec currently removes the kwarg, relying on the write path's own classifier — verify this is correct before building Task 6.)

2. **NRIC checksum table for M-series**: the M-series FIN prefix was introduced in 2022 and uses an offset of +3 with the same letter table as F/G. The spec uses this, but the exact offset and letter table should be verified against the official ICA specification before committing. Treat as best-effort until confirmed.

3. **DOB bare date false-positive risk**: the bare `DD/MM/YYYY` regex will fire on any 8-digit slash-separated date in text (e.g., file modification dates, event dates). The spec uses the labelled form as the primary trigger and bare form as secondary. Consider raising the bar to labelled-only if false-positive rate in testing is high.

4. **`SensitivityConfig.owner_overrides` field**: `graduate_to_policy` writes to `policy.json` under a `sensitivity.owner_overrides` key, but `SensitivityConfig` does not declare this field (it would fail `extra="forbid"` validation on reload). Either add `owner_overrides: dict[str, Sensitivity] = Field(default_factory=dict, ...)` to `SensitivityConfig`, or use a separate `owner-overrides.json` file. Recommend adding the field to `SensitivityConfig` for consistency — flagged for review before building Task 5 + Task 7.

## Progress
_(Coding mode writes here — do not edit manually)_

---
spec: brain-sensitivity-routing
status: blocked
blocked_on: owner-privacy-posture-signoff
token_profile: lean
autonomy_level: L3
coder_tier: pro
depends_on: composite-model-routing
cross_model_review: true
---

# Spec: brain-sensitivity-routing — keep sensitive reasoning local, route the rest to Codex

**Identity:** Add a sensitivity classifier and have the `Brain` pick its reasoning role per request — **sensitive (finance / health / journal / memory) → a LOCAL role; everything else → the Codex cloud role** — enforcing the ADR-022 hybrid privacy policy. A global `cloud_reasoning_enabled` kill-switch forces everything local when off.
→ why: ADR-022 §"Privacy-routing policy = HYBRID" (sensitive never leaves the box; the sensitivity router gates it).

<!-- Execution script. Build AFTER `composite-model-routing`. Modifies the Brain core — pro tier + cross-model review. Privacy-critical: a false-negative sends sensitive data to the cloud, so the default-on-uncertainty and the kill-switch matter. -->

## ⚠️ PRIVACY POSTURE — owner sign-off required (BLOCK, apex-security)
The sensitivity classifier is a **hard data-egress boundary**: a false-negative sends owner-private data (finance/health/journal) to the cloud with **no recovery**. The regex below is strengthened (journal added; indirect phrasings — "what did I spend", "my weight", "my mood" — covered), but a regex **can never be complete**. So before this spec is built, pick the posture:

- **(A) Strengthened-regex, cloud-on (this draft).** Fastest. Accepts a documented residual false-negative risk (the probe-test list enumerates known gaps). Good if you value capability now and trust the heuristic for your phrasing.
- **(B) Fail-closed.** `cloud_reasoning_enabled` defaults to **`False`** — everything stays local until you explicitly enable cloud (per session or globally). No leak risk; you opt into cloud deliberately.
- **(C) Local-classifier-first.** Build a local-4B sensitivity classifier as the gate *before* enabling cloud (most robust, more work — a follow-up spec).

**This spec stays `status: blocked` until you choose.** It is otherwise complete and review-clean. (My read: A is fine to start *if* you’ll glance at the probe-test false-negative list; B is the safe default if unsure.)

## Assumptions
- `composite-model-routing` is built: a `responder_cloud` role (adapter=codex) exists, `responder` + `sensitive_reasoner` are local, and `CompositeModelPort` routes by role-adapter with local fallback. → impact: Stop (this spec only *chooses the role*; the composite does the dispatch).
- `Brain` (`src/artemis/brain.py`) currently hardcodes `role="responder"` in three places: the tool-arg decode (~line 84), the free-form responder (~line 105), and the stream (~line 129). → impact: Stop (route ONLY the two free-form *generative* paths; leave the tool-arg JSON decode on the local `responder` — constrained decoding is cheap + deterministic locally and must not ship tool-argument text to the cloud).
- The most reliable sensitivity signal is *which module a request touches*, not text. The free-form path has no tool, so it uses text patterns; the tool path's sensitivity is its module. This spec routes the free-form path by text+scope and leaves tool dispatch local. → impact: Stop (per-module sensitivity for cloud-eligible tool calls is a deliberate follow-up, parked).
- Privacy bias: a false-negative (sensitive → cloud) **leaks**; a false-positive (general → local) only costs quality. So the classifier errs toward `sensitive`, and `cloud_reasoning_enabled=False` forces everything local. → impact: Stop.

## Files to change
1. **create** `src/artemis/sensitivity.py` — `classify_sensitivity(...)` + sensitive patterns/modules.
2. **modify** `src/artemis/config.py` — add `cloud_reasoning_enabled: bool = True`.
3. **modify** `src/artemis/brain.py` — inject a classifier; route the two free-form paths to `responder_cloud` (general) or `responder` (sensitive).
4. **modify** `src/artemis/gateway.py` — pass the classifier + `cloud_reasoning_enabled` into `Brain` in `compose_brain`.
5. **create** `tests/test_sensitivity.py` + sensitivity cases in `tests/test_router_brain.py` (or a new `tests/test_brain_routing.py`).

## Exact changes

### 1. `src/artemis/sensitivity.py` (new)
```python
"""Sensitivity classifier — decides whether a request may leave the box (ADR-022).

First-cut heuristic: pattern + module match, biased toward `sensitive` (a
false-negative leaks to the cloud). A local-model classifier is the planned
upgrade (see spec parked notes)."""
from __future__ import annotations

import re
from typing import Literal, Protocol

from artemis.ports.types import Scope

Sensitivity = Literal["general", "sensitive"]


class SensitivityClassifier(Protocol):
    """Typed callable shape for the sensitivity gate (NOT `Callable[..., X]`,
    which would suppress arg-checking at call sites under mypy --strict)."""

    def __call__(
        self,
        request_text: str,
        scope: Scope,
        *,
        tool_id: str | None = None,
        cloud_enabled: bool = True,
    ) -> Sensitivity: ...


# Modules whose tool calls are inherently sensitive (informational here; the
# per-module tool-path gate is a follow-up).
SENSITIVE_MODULES: frozenset[str] = frozenset({"finance", "health", "memory", "journal"})

# Word-boundary patterns, biased toward `sensitive` (a false-negative LEAKS). Covers
# direct AND indirect phrasings. Still incomplete by nature — see § Privacy posture +
# the probe tests. Tune precision/recall on a gold set; a local-model classifier is the
# planned upgrade. [apex-security BLOCK]
_SENSITIVE = re.compile(
    r"\b("
    # finance (direct + indirect)
    r"salary|wage(s)?|income|paycheck|bank|account\s+balance|invoice|payment|paid|"
    r"debt|owe|loan|mortgage|tax|net\s+worth|budget|spend(ing)?|spent|afford|"
    r"charge(s|d)?|subscription|refund|bill(s)?|savings|"
    # health (direct + indirect)
    r"diagnos\w+|symptom|medication|meds?|prescription|doctor|clinic|therapy|"
    r"mental\s+health|blood|illness|disease|anxiety|depress\w+|weigh(t)?|"
    r"pain|sick|sleep|period|cycle|"
    # journal / mood (direct + indirect)
    r"journal|diary|mood|feeling(s)?|how\s+i\s+feel|i\s+feel|vent|grateful|lonely"
    r")\b",
    re.IGNORECASE,
)


def classify_sensitivity(
    request_text: str,
    scope: Scope,
    *,
    tool_id: str | None = None,
    cloud_enabled: bool = True,
) -> Sensitivity:
    """Return ``"sensitive"`` if the request must stay local, else ``"general"``."""
    if not cloud_enabled:
        return "sensitive"
    if tool_id and tool_id.split(".", 1)[0] in SENSITIVE_MODULES:
        return "sensitive"
    if _SENSITIVE.search(request_text):
        return "sensitive"
    return "general"
```

### 2. `src/artemis/config.py` (modify)
Add to `Settings`:
```python
    cloud_reasoning_enabled: bool = True   # False = force ALL reasoning local (kill-switch)
```

### 3. `src/artemis/brain.py` (modify)
- Add imports + two constructor params (keep existing params first; both default so current call sites still work):
```python
from artemis.sensitivity import SensitivityClassifier, classify_sensitivity
```
  Constructor gains (typed Protocol, not `Callable[..., X]` — preserves mypy arg-checking at the `self._classify(...)` call site):
```python
        classifier: SensitivityClassifier = classify_sensitivity,
        cloud_reasoning_enabled: bool = True,
```
  stored as `self._classify` / `self._cloud_enabled`.
- Add a helper:
```python
    def _responder_role(self, request_text: str, scope: Scope) -> str:
        s = self._classify(request_text, scope, cloud_enabled=self._cloud_enabled)
        return "responder" if s == "sensitive" else "responder_cloud"
```
- In `respond`, the **free-form responder path** (~line 105): replace `role="responder"` with `role=self._responder_role(request_text, scope)`.
- In `respond_stream`, the **streamed responder** (~line 129): same — compute `role = self._responder_role(request_text, scope)` and pass it to `complete_stream`.
- Leave the **tool-arg decode** (~line 84) on `role="responder"` (local) — unchanged.

### 4. `src/artemis/gateway.py` (modify)
In `compose_brain`, pass the policy into the `Brain`:
- **From:** `return Brain(router, registry, model)`
- **To:** `return Brain(router, registry, model, cloud_reasoning_enabled=settings.cloud_reasoning_enabled)`
(The `classifier` keeps its default; injectable in tests.)

### 5. Tests
`tests/test_sensitivity.py`:
- finance/health/journal phrases → `"sensitive"`; a neutral phrase ("what's the weather", "summarise this article") → `"general"`.
- **Indirect-phrasing probes (apex-security BLOCK):** assert `"sensitive"` for "what did I spend last month", "my weight this morning", "my mood lately", "recurring charges", "can I afford this", "my meds". Maintain an explicit `ACCEPTED_FALSE_NEGATIVES` list in the test of any phrasings the regex deliberately does NOT catch — so the residual leak surface is **visible and owner-reviewable** (the § Privacy posture decision governs whether that list is acceptable).
- `tool_id="finance.add_txn"` → `"sensitive"`; `tool_id="journal.add"` → `"sensitive"` (regardless of text).
- `cloud_enabled=False` → always `"sensitive"`.

`tests/test_brain_routing.py` (new; fake ModelPort recording the `role` it receives):
- A general request via the free-form path → `complete` called with `role="responder_cloud"`.
- A sensitive request ("what's my bank balance") → `role="responder"` (local).
- `Brain(..., cloud_reasoning_enabled=False)` → general request still routed to `"responder"` (local).
- The tool path still calls `role="responder"` for arg decode (unchanged).

## Acceptance criteria
1. **Classifier** → `uv run --frozen pytest tests/test_sensitivity.py -q` green (sensitive/general/module/kill-switch cases).
2. **Brain routes generative path** → `uv run --frozen pytest tests/test_brain_routing.py -q`: general→`responder_cloud`, sensitive→`responder`, kill-switch→`responder`.
3. **Tool path unchanged** → tool-arg decode still uses local `responder`; existing `tests/test_router_brain.py` stays green.
4. **Full suite** → `uv run --frozen pytest -q` green.
5. **Type/lint** → `uv run --frozen mypy` clean; `ruff check .` + `ruff format --check .` clean.
6. **Surgical** → `git diff --stat` shows only the 5 files above.

## Commands to run
```bash
uv sync
uv run --frozen ruff format .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen pytest tests/test_sensitivity.py tests/test_brain_routing.py -q
uv run --frozen pytest -q
```

## Progress
_(Coding mode writes here — do not edit manually)_

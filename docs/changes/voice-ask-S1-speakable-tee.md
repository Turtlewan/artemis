---
spec: voice-ask-S1-speakable-tee
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: voice-ask-S1 — speakable renderer + stream tee + `handle_ask_unified` (one generation → display SSE + speak branch)

**Identity:** Brain-side foundation for ADR-034: a deterministic shape-aware `speakable.py` renderer, a stream tee, and `Gateway.handle_ask_unified(query, *, scope_or_identity, speak)` that runs `Brain.respond_stream` ONCE and tees it into a display iterator (rich text → existing `/app/ask/stream` SSE) and a speak iterator (speakable projection → S3's TTS sink). Defines the seam signatures S2/S3/S4 consume. → why: docs/technical/adr/ADR-034-unified-voice-text-ask.md §B/§C.

<!-- Split note: 4 files (>3). Justified atomic exception — the tee + its renderer + the one SSE consumer that restores streaming through it are mutually dependent; splitting leaves a tee no route drives, or a route teeing nothing. -->

## Assumptions
- `Brain.respond_stream(text, scope) -> AsyncIterator[str]` exists (M5-d back-fill) and yields display text segments (markdown / lists / fenced code / citations / `local`/`codex`/`review` engine tags). → impact: Stop (the tee forks exactly this stream).
- `/app/ask/stream` already streams via `gateway.handle_text_stream_scoped` (api_app.py); the Rust `ask_stream` + TS `askStream` wrappers already exist. S1 reroutes the SSE display branch through `handle_ask_unified`; it does NOT invent the SSE transport. → impact: Caution (display wire frozen; only its source changes).
- Overlay input is session-scoped: `scope_or_identity` accepts a `Scope` (overlay, from `resolve_scope(principal)`) OR an `Identity` (headless loop, voice-ID). The M5-c Tier gate runs only on the `Identity` path. → impact: Stop (ADR-034 §E identity rule).
- The speak branch is consumed only when `speak=True`; when `speak=False` the source feeds display only (zero TTS cost). → impact: Stop (ADR-034 §B).

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/speakable.py | create | `to_speakable`, `classify_shape`, `subject_phrase`, `DisplaySeg`/`SpeakSeg` aliases |
| src/artemis/gateway.py | modify | `_StreamTee` + `handle_ask_unified`; keep `handle_text*`/`handle_voice*` intact |
| src/artemis/api_app.py | modify | `AskRequest.speak: bool = False`; reroute `/app/ask/stream` display branch through `handle_ask_unified`; `app.state.speak_sink` seam (S1 default = drain) |
| tests/test_speakable.py | create | `to_speakable` across short / list / table / long / code; tee + `handle_ask_unified` typing/behaviour with FakeBrain |

## Exact changes
**src/artemis/speakable.py** (new):
```python
from collections.abc import AsyncIterator  # if needed
from typing import Literal

DisplaySeg = str
SpeakSeg = str

POINTER_TEMPLATE = "I've put your {subject} on screen."
POINTER_FALLBACK = "Your results are on screen."

def classify_shape(answer: str) -> Literal["short", "pointer"]:
    """STRUCTURAL: pointer if any markdown list item (^\\s*([-*+]|\\d+\\.)\\s),
    table row/separator, fenced code block (```), OR >2 sentence-final marks;
    else short."""

def subject_phrase(query: str) -> str | None:
    """Lightly derive the request subject from the query (strip leading
    question words / punctuation); None when nothing usable remains."""

def to_speakable(answer: str, *, subject: str | None = None) -> str:
    """pointer shape -> POINTER_TEMPLATE.format(subject=...) or POINTER_FALLBACK.
    short shape -> the answer near-verbatim, stripped of markdown emphasis/
    headers, citation markers/footnotes, engine tags (local/codex/review),
    fenced+inline code, links->link text. Deterministic; no rephrasing."""
```

**src/artemis/gateway.py** (add):
```python
from artemis.speakable import DisplaySeg, SpeakSeg, subject_phrase, to_speakable

async def handle_ask_unified(
    self,
    query: str,
    *,
    scope_or_identity: Scope | Identity,
    speak: bool,
) -> tuple[AsyncIterator[DisplaySeg], AsyncIterator[SpeakSeg]]:
    """Run Brain.respond_stream ONCE and tee. Resolve scope from a Scope
    directly (overlay) or via the M5-c Tier gate from an Identity (headless).
    Display iterator yields raw segments. When speak: the speak iterator
    accumulates the answer, early-short-circuits to the pointer the moment a
    structural (list/table/code/3rd-sentence) trigger appears, else yields the
    short stripped answer on completion (subject from subject_phrase(query)).
    When not speak: speak iterator is empty and the source feeds display only."""
```
`_StreamTee`: single producer drains `respond_stream` into a display `asyncio.Queue` and (if speak) a speak buffer; the two consumer iterators never deadlock when one side is undriven.

**src/artemis/api_app.py**:
- `class AskRequest`: add `speak: bool = False`.
- `ask_stream`: build `display_iter, speak_iter = await gateway.handle_ask_unified(body.text, scope_or_identity=scope, speak=body.speak)`; SSE-stream `display_iter` (same fail-closed vault recheck + `[DONE]`); if `body.speak`, hand `speak_iter` to `request.app.state.speak_sink` (default `async def _drain(it): async for _ in it: pass` as a background task — S3 replaces it).

## Acceptance criteria
- [ ] `uv run mypy src tests/test_speakable.py` → exit 0 (incl. `handle_ask_unified` return type + `Scope | Identity`).
- [ ] `uv run pytest -q tests/test_speakable.py` → `to_speakable("It is noon.")` == "It is noon." (short, verbatim-stripped); a markdown-list answer → POINTER_TEMPLATE filled with the query subject; a fenced-code answer → pointer (code never spoken); a >2-sentence answer → pointer; engine tags / citation markers stripped from a short answer; with a FakeBrain streaming 3 segments, the display iterator yields all 3 unchanged AND (speak=True) the speak iterator yields exactly one pointer/short string; (speak=False) the speak iterator is empty and the source is consumed once.
- [ ] `uv run pytest -q` (full) → green (no regression to `handle_text_stream_scoped` / existing `/app/ask/stream` tests).

## Commands to run
```
uv run ruff check . ; uv run ruff format --check .
uv run mypy src tests/test_speakable.py
uv run pytest -q
```

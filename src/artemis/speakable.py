"""Deterministic display-to-speech projection helpers."""

from __future__ import annotations

import re
from typing import Literal

DisplaySeg = str
SpeakSeg = str

POINTER_TEMPLATE = "I've put your {subject} on screen."
POINTER_FALLBACK = "Your results are on screen."

_LIST_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+\.)\s+")
_TABLE_RE = re.compile(r"(?m)^\s*\|.*\|\s*$|^\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+$")
_FENCE_RE = re.compile(r"```")
_SENTENCE_FINAL_RE = re.compile(r"[.!?](?=\s|$)")
_LEADING_QUERY_RE = re.compile(
    r"^(?:please\s+)?(?:can|could|would|will|do|does|did|is|are|was|were|what|when|where|"
    r"why|how|tell|show|give|list|summarize|summarise|find|get|put)\b\s*(?:me\s+)?",
    re.IGNORECASE,
)
_ENGINE_TAG_RE = re.compile(r"\b(?:local|codex|review)\s*[:|]\s*", re.IGNORECASE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_FOOTNOTE_RE = re.compile(r"\[\^?[A-Za-z0-9_-]+\]")
_HEADER_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_EMPHASIS_RE = re.compile(r"[*_~`]+")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_SPACE_RE = re.compile(r"\s+")


def classify_shape(answer: str) -> Literal["short", "pointer"]:
    """Return pointer for structural or long answers, otherwise short."""
    if (
        _LIST_RE.search(answer) is not None
        or _TABLE_RE.search(answer) is not None
        or _FENCE_RE.search(answer) is not None
        or len(_SENTENCE_FINAL_RE.findall(answer)) > 2
    ):
        return "pointer"
    return "short"


def subject_phrase(query: str) -> str | None:
    """Derive a light subject phrase from a query without rephrasing."""
    subject = query.strip().strip(" \t\r\n?!.,:;\"'")
    subject = _LEADING_QUERY_RE.sub("", subject).strip()
    subject = subject.strip(" \t\r\n?!.,:;\"'")
    return subject or None


def to_speakable(answer: str, *, subject: str | None = None) -> str:
    """Project a display answer into one deterministic speakable string."""
    if classify_shape(answer) == "pointer":
        if subject:
            return POINTER_TEMPLATE.format(subject=subject)
        return POINTER_FALLBACK

    speakable = _FENCED_CODE_RE.sub("", answer)
    speakable = _ENGINE_TAG_RE.sub("", speakable)
    speakable = _LINK_RE.sub(r"\1", speakable)
    speakable = _FOOTNOTE_RE.sub("", speakable)
    speakable = _HEADER_RE.sub("", speakable)
    speakable = _INLINE_CODE_RE.sub(r"\1", speakable)
    speakable = _EMPHASIS_RE.sub("", speakable)
    return _SPACE_RE.sub(" ", speakable).strip()

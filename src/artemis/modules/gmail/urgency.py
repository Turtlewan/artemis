"""Deterministic Gmail urgency pre-filter and quarantined extract bridge.

Stage 1 admits unread messages by Gmail Important, configured urgency keywords,
or VIP senders, then applies the configured sender-domain exclude. Stage 2 adds
a memory-derived sender boost using only local substring checks. Stage 3 urgency
scoring is intentionally outside this module: M6-b receives this payload and
uses its batched LLM path over DR-a ``Extract`` summaries.
"""

from __future__ import annotations

import email.utils
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Final, Literal

from artemis.modules.gmail.cache import CachedMessage, GmailReadCache
from artemis.modules.gmail.client import GmailApiPort, MailCategory, extract_body_text
from artemis.proactive.hook_types import HookResult
from artemis.untrusted.quarantine import Extract, QuarantinedReader

URGENCY_CANDIDATES: Final = frozenset({MailCategory.PRIMARY, MailCategory.UPDATES})
type AdmitReason = Literal["important", "keyword", "vip"]


@dataclass(frozen=True)
class UrgencyCandidate:
    """Payload candidate sent to M6-b without raw subject, snippet, body, or From header."""

    message_id: str
    sender: str
    known_to_memory: bool
    extract_summary: str
    extract_failed: bool
    admit_reason: AdmitReason


class GmailUrgencyPreFilter:
    """LLM-free Gmail urgency candidate selector.

    ``msg.subject`` is used only for local keyword admission. It is never stored
    on ``UrgencyCandidate`` or included in the hook payload.
    """

    def __init__(
        self,
        cache: GmailReadCache,
        *,
        known_senders: frozenset[str] = frozenset(),
        urgency_keywords: frozenset[str] = frozenset(),
        vip_senders: frozenset[str] = frozenset(),
        sender_exclude: frozenset[str] = frozenset(),
        max_candidates: int = 10,
    ) -> None:
        self.cache = cache
        self.known_senders = frozenset(token.lower() for token in known_senders if token)
        self.urgency_keywords = frozenset(token.lower() for token in urgency_keywords if token)
        self.vip_senders = frozenset(token.lower() for token in vip_senders if token)
        self.sender_exclude = frozenset(domain.lower() for domain in sender_exclude if domain)
        self.max_candidates = max_candidates

    def stage1_candidates(self) -> list[tuple[CachedMessage, AdmitReason]]:
        """Return unread urgency candidates sorted newest-first with admit reasons."""
        admitted: list[tuple[CachedMessage, AdmitReason]] = []
        for row in self.cache.list_unread(category=None):
            keep, reason = self._classify_admit(row)
            if not keep or reason is None:
                continue
            if self._is_excluded_sender(row.sender):
                continue
            admitted.append((row, reason))
        admitted.sort(key=lambda item: item[0].internal_date_ms, reverse=True)
        return admitted[: self.max_candidates]

    def stage2_boost(
        self, admitted: list[tuple[CachedMessage, AdmitReason]]
    ) -> list[tuple[CachedMessage, bool, AdmitReason]]:
        """Attach the memory-known sender flag using deterministic substring checks."""
        boosted: list[tuple[CachedMessage, bool, AdmitReason]] = []
        for candidate, reason in admitted:
            known = bool(self.known_senders) and any(
                token in candidate.sender.lower() for token in self.known_senders
            )
            boosted.append((candidate, known, reason))
        return boosted

    def build_payload(
        self,
        boosted: list[tuple[CachedMessage, bool, AdmitReason]],
        extracts: dict[str, Extract],
    ) -> dict[str, object]:
        """Build the M6-b payload from bounded candidate metadata and Extract summaries."""
        candidates: list[dict[str, object]] = []
        for msg, known, reason in boosted:
            extract = extracts.get(msg.message_id)
            extract_summary = ""
            extract_failed = True
            if extract is not None and not extract.parse_failed:
                extract_summary = extract.summary[:500]
                extract_failed = False
            candidate = UrgencyCandidate(
                message_id=msg.message_id,
                sender=_display_sender(msg.sender),
                known_to_memory=known,
                extract_summary=extract_summary,
                extract_failed=extract_failed,
                admit_reason=reason,
            )
            candidates.append(asdict(candidate))
        return {"candidates": candidates, "unread_count": len(boosted)}

    def _classify_admit(self, msg: CachedMessage) -> tuple[bool, AdmitReason | None]:
        if not msg.unread:
            return (False, None)
        sender_l = msg.sender.lower()
        if self.vip_senders and any(token in sender_l for token in self.vip_senders):
            return (True, "vip")
        if msg.important and msg.category in URGENCY_CANDIDATES:
            return (True, "important")
        if self.urgency_keywords:
            # SEAM 7: msg.subject is read locally ONLY to compute the keyword-admit boolean; it is NEVER stored in a candidate or payload. Only the bounded admit_reason enum crosses into M6-b's prompt.
            haystack = f"{msg.subject} {msg.sender}".lower()
            if any(keyword in haystack for keyword in self.urgency_keywords):
                return (True, "keyword")
        return (False, None)

    def _is_excluded_sender(self, sender: str) -> bool:
        domain = _sender_domain(sender)
        if not domain:
            return False
        return any(
            domain == excluded or domain.endswith(f".{excluded}")
            for excluded in self.sender_exclude
        )


async def fetch_extracts(
    api: GmailApiPort,
    reader: QuarantinedReader,
    candidates: list[tuple[CachedMessage, AdmitReason]],
    *,
    query: str = "urgent action required, important request, time-sensitive",
) -> dict[str, Extract]:
    """Fetch quarantined body extracts for candidates.

    Failures are omitted; payload construction treats absent extracts as a
    graceful per-message extract failure.
    """
    extracts: dict[str, Extract] = {}
    for candidate, _reason in candidates:
        try:
            msg = api.get_message(candidate.message_id, fmt="full")
            body = extract_body_text(msg)
            if not body:
                continue
            extract = await reader.read(
                raw_content=body,
                source_url=f"gmail:{candidate.message_id}",
                source_domain="mail.google.com",
                query=query,
                max_tokens=512,
            )
            extracts[candidate.message_id] = extract
        except Exception:
            continue
    return extracts


class UrgencyTemplateRenderer:
    """No-LLM fallback renderer for the Gmail urgency hook."""

    def render(self, result: HookResult) -> str:
        """Render a sender-only fallback line from a hook result."""
        payload = result.payload
        raw_candidates = payload.get("candidates", [])
        candidates = raw_candidates if isinstance(raw_candidates, list) else []
        unread_raw = payload.get("unread_count", 0)
        unread_count = unread_raw if isinstance(unread_raw, int) else 0
        if not candidates:
            return "No urgent unread messages."
        senders: list[str] = []
        for candidate in candidates[:3]:
            if isinstance(candidate, Mapping):
                sender = candidate.get("sender")
                if isinstance(sender, str):
                    senders.append(sender)
        return f"{unread_count} unread important message(s): " + "; ".join(senders)


def _display_sender(sender: str) -> str:
    name = email.utils.parseaddr(sender)[0].strip()
    if not name:
        name = sender.split("@", 1)[0].strip()
    return name[:100]


def _sender_domain(sender: str) -> str:
    addr = email.utils.parseaddr(sender)[1]
    if "@" not in addr:
        return ""
    return addr.split("@", 1)[1].lower()

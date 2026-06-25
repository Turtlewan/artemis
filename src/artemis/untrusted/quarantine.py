"""Dual-LLM quarantine primitive for reading untrusted content safely."""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from artemis.obs.sink import NullSink, ObservabilitySink
from artemis.ports.model import ModelPort
from artemis.ports.types import Message
from artemis.untrusted.spotlight import SPOTLIGHT_INSTRUCTION, spotlight

logger = logging.getLogger("untrusted")

EXTRACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 2000},
        "claims": {
            "type": "array",
            "items": {"type": "string", "maxLength": 500},
            "maxItems": 20,
        },
        "flagged_injection": {"type": "boolean"},
    },
    "required": ["summary", "claims", "flagged_injection"],
    "additionalProperties": False,
}
"""Bounded JSON schema for constrained decoding and post-parse validation."""


@dataclass(frozen=True)
class Extract:
    """Sanitised extract safe for the privileged side to consume.

    ``source_url`` and ``source_domain`` always come from the trusted caller,
    never from model output. ``parse_failed`` signals broken or hijacked output
    that callers must not treat as trusted clean data.
    """

    source_url: str
    source_domain: str
    summary: str
    claims: tuple[str, ...]
    flagged_injection: bool
    parse_failed: bool
    tokens_used: int

    @property
    def usable(self) -> bool:
        """True only when the extract is neither parse-failed nor injection-flagged."""
        return not self.parse_failed and not self.flagged_injection


class QuarantineError(Exception):
    """Raised when the quarantined reader cannot enforce its safety contract."""


def _validate_extract_payload(payload: object) -> tuple[str, tuple[str, ...], bool]:
    """Validate model JSON against ``EXTRACTION_SCHEMA`` bounds."""
    if not isinstance(payload, dict):
        raise ValueError("extract payload must be an object")

    required = EXTRACTION_SCHEMA["required"]
    if not isinstance(required, list):
        raise ValueError("invalid extraction schema")
    for key in required:
        if not isinstance(key, str) or key not in payload:
            raise ValueError("extract payload missing required field")

    summary = payload.get("summary")
    claims = payload.get("claims")
    flagged_injection = payload.get("flagged_injection")

    if not isinstance(summary, str) or len(summary) > 2000:
        raise ValueError("extract summary violates schema")
    if not isinstance(claims, list) or len(claims) > 20:
        raise ValueError("extract claims violate schema")
    if not all(isinstance(claim, str) and len(claim) <= 500 for claim in claims):
        raise ValueError("extract claim violates schema")
    if not isinstance(flagged_injection, bool):
        raise ValueError("extract flagged_injection violates schema")

    return summary, tuple(claims), flagged_injection


class QuarantinedReader:
    """Read raw untrusted content through a toolless, schema-constrained model.

    The privileged orchestrator sees only ``Extract`` values and never raw page
    content. DR-c is the first consumer; M3 ingestion and connectors can reuse
    this primitive later.
    """

    def __init__(
        self,
        model: ModelPort,
        role: str,
        *,
        sink: ObservabilitySink | None = None,
    ) -> None:
        if not role:
            raise QuarantineError("quarantine role must be non-empty")
        signature = inspect.signature(model.complete)
        for forbidden in ("tools", "tool_choice"):
            if forbidden in signature.parameters:
                raise QuarantineError("quarantine model complete must be toolless")
        self._model = model
        self._role = role
        self._sink: ObservabilitySink = sink if sink is not None else NullSink()

    async def read(
        self,
        *,
        raw_content: str,
        source_url: str,
        source_domain: str,
        query: str,
        max_tokens: int = 1024,
    ) -> Extract:
        """Return a bounded extract with caller-supplied provenance only."""
        safe_query = query.strip()[:512]
        nonce, marked = spotlight(raw_content)
        system = (
            SPOTLIGHT_INSTRUCTION.format(nonce=nonce)
            + f"\nExtract only facts relevant to: {safe_query}"
        )
        resp = await self._model.complete(
            role=self._role,
            messages=[
                Message(role="system", content=system),
                Message(role="user", content=marked),
            ],
            response_schema=EXTRACTION_SCHEMA,
            max_tokens=max_tokens,
        )
        tokens_used = getattr(resp.usage, "total_tokens", 0) if resp.usage else 0

        try:
            parsed = json.loads(resp.text)
            summary, claims, flagged_injection = _validate_extract_payload(parsed)
        except Exception as exc:
            logger.warning("Quarantined extract parse failed (%s)", type(exc).__name__)
            return Extract(
                source_url=source_url,
                source_domain=source_domain,
                summary="",
                claims=(),
                flagged_injection=False,
                parse_failed=True,
                tokens_used=tokens_used,
            )

        if flagged_injection:
            self._sink.on_injection_flagged(
                source_domain,
                now=datetime.now(tz=timezone.utc),  # noqa: UP017
            )
            logger.warning(
                "Injection attempt flagged from %s; summary and claims blanked",
                source_domain,
            )
            summary = ""
            claims = ()

        return Extract(
            source_url=source_url,
            source_domain=source_domain,
            summary=summary,
            claims=claims,
            flagged_injection=flagged_injection,
            parse_failed=False,
            tokens_used=tokens_used,
        )


def validate_extraction_payload(payload: Mapping[str, object]) -> tuple[str, tuple[str, ...], bool]:
    """Validate an extraction payload against the public schema bounds."""
    return _validate_extract_payload(dict(payload))

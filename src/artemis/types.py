"""Shared Artemis runtime types."""

from __future__ import annotations

import json
import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MemoryLayer = Literal[
    "constitution",
    "rules",
    "semantic",
    "episodic",
    "corpus",
    "capability",
    "working",
]

_HOSTNAME_RE = re.compile(
    # final label MUST be an alphabetic TLD (2-63) — blocks all-numeric / hex-shorthand
    # hosts like 127.1 / 0x7f.0.0.1 that ipaddress() won't parse but clients treat as IPs (SSRF)
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
_MAX_EGRESS = 20
_INTERNAL_SUFFIXES = (".local", ".internal", ".localhost", ".test", ".invalid")


def validate_egress_domains(v: list[str]) -> list[str]:
    if len(v) > _MAX_EGRESS:
        raise ValueError(f"egress_domains exceeds {_MAX_EGRESS} entries")
    out: list[str] = []
    for raw in v:
        d = raw.strip().rstrip(".").lower()
        if not d:
            raise ValueError("egress_domains contains an empty entry")
        if not d.isascii():
            raise ValueError(f"egress_domains entry is not ASCII: {raw!r}")
        if "*" in d or "?" in d or "/" in d or ":" in d:
            raise ValueError(f"egress_domains entry is not a bare hostname: {raw!r}")
        if not _HOSTNAME_RE.match(d):
            raise ValueError(f"egress_domains entry is not a valid hostname: {raw!r}")
        try:
            ipaddress.ip_address(d)
        except ValueError:
            pass
        else:
            raise ValueError(f"egress_domains entry is an IP literal, not a domain (SSRF): {raw!r}")
        if d == "localhost" or d.endswith(_INTERNAL_SUFFIXES):
            raise ValueError(f"egress_domains entry is a special-use/internal name: {raw!r}")
        out.append(d)
    return out


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class ModelResponse(BaseModel):
    text: str
    model_id: str
    structured: dict | None  # type: ignore[type-arg]
    finish_reason: str
    usage: Usage


class MemoryItem(BaseModel):
    content: str
    layer: MemoryLayer
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)  # type: ignore[type-arg]


class RetrievedContext(BaseModel):
    items: list[MemoryItem]
    token_cost: int
    truncated: bool


class InboundMessage(BaseModel):
    transport: str
    identity: str
    text: str
    attachments: list = Field(default_factory=list)  # type: ignore[type-arg]


class OutboundMessage(BaseModel):
    transport: str
    identity: str
    text: str
    proactive: bool = False


class SkillInputParam(BaseModel):
    """Typed metadata for one capability input parameter."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: Literal["string", "number", "boolean"]
    description: str
    required: bool = True


def build_invoke_argv(inputs: list[SkillInputParam], args: dict[str, object]) -> list[str]:
    """Build the argv convention for invoking a skill tool with extracted args."""

    if not inputs:
        return []
    return [json.dumps(args, separators=(",", ":"), sort_keys=True)]


class SkillDraft(BaseModel):
    name: str
    description: str
    body: str
    tool_script: str | None
    goal: str = ""
    inputs: list[SkillInputParam] = Field(default_factory=list)
    uses: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    oauth_scopes: list[str] = Field(default_factory=list)
    egress_domains: list[str] = Field(default_factory=list)
    tests: str | None

    @field_validator("egress_domains")
    @classmethod
    def _validate_egress_domains(cls, v: list[str]) -> list[str]:
        return validate_egress_domains(v)


class Skill(BaseModel):
    name: str
    description: str
    version: int
    path: str
    goal: str = ""
    built_at: str | None = None
    auth_status: Literal["not-required", "unverified", "verified"] = "not-required"
    oauth_scopes: list[str] = Field(default_factory=list)
    tags: list[str]
    uses: list[str]
    secrets: list[str]
    inputs: list[SkillInputParam] = Field(default_factory=list)
    egress_domains: list[str] = Field(default_factory=list)

    @field_validator("egress_domains")
    @classmethod
    def _validate_egress_domains(cls, v: list[str]) -> list[str]:
        return validate_egress_domains(v)


class StagedSkill(BaseModel):
    id: str
    draft: SkillDraft


class BuildProposal(BaseModel):
    """A proposed capability awaiting the plan gate: the authored draft + a safety verdict.

    `blocked` is True when the capability cannot proceed to build in the current
    (no-isolation) sandbox -- either it has no test, or it imports a network/process
    module (see `scan_for_unsafe_imports`). The UI offers `Build it` only when not blocked.
    """

    goal: str
    draft: SkillDraft
    blocked: bool
    block_reason: str | None = None


class BuildAttempt(BaseModel):
    """The outcome of running a proposal through the sandbox. `staged_id` is None when the
    proposal was blocked (never staged). `promote` is gated on `passed and staged_id`.
    """

    staged_id: str | None
    passed: bool
    output: str


class ScheduledJob(BaseModel):
    id: str
    cron: str | None
    run_at: str | None
    payload: dict  # type: ignore[type-arg]


class EventTrigger(BaseModel):
    kind: str
    match: dict  # type: ignore[type-arg]

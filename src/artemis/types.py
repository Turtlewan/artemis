"""Shared Artemis runtime types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MemoryLayer = Literal[
    "constitution",
    "rules",
    "semantic",
    "episodic",
    "corpus",
    "capability",
    "working",
]


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


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


class SkillDraft(BaseModel):
    name: str
    description: str
    body: str
    tool_script: str | None
    uses: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    tests: str | None


class Skill(BaseModel):
    name: str
    description: str
    version: int
    path: str
    tags: list[str]
    uses: list[str]
    secrets: list[str]


class StagedSkill(BaseModel):
    id: str
    draft: SkillDraft


class ScheduledJob(BaseModel):
    id: str
    cron: str | None
    run_at: str | None
    payload: dict  # type: ignore[type-arg]


class EventTrigger(BaseModel):
    kind: str
    match: dict  # type: ignore[type-arg]

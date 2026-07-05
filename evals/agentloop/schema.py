"""Typed records for the frozen agent-loop evaluation corpus."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

CaseKind = Literal["driver_golden", "injection", "judge_calibration", "escalation"]


class RecordFixture(BaseModel):
    """One row seeded into a DataStore(":memory:") for a case."""

    model_config = ConfigDict(frozen=True)

    domain: str
    kind: str = "item"
    key: str
    sanitized_text: str
    payload: dict[str, Any] = {}
    source: str = "sync"
    fetched_at: float = 0.0
    sha256: str


class MemoryFixture(BaseModel):
    """One item seeded into the memory retrieval tool."""

    model_config = ConfigDict(frozen=True)

    content: str
    layer: str = "semantic"


class ExpectedStep(BaseModel):
    """Expected ordered tool selection for driver and escalation cases."""

    model_config = ConfigDict(frozen=True)

    tool: str
    domain: str | None = None


class JudgeEvidenceStep(BaseModel):
    """One reconstructed StepRecord plus observation for judge calibration."""

    model_config = ConfigDict(frozen=True)

    tool: str
    args: dict[str, Any] = {}
    ok: bool = True
    observation: str


class LoopCase(BaseModel):
    """One frozen agent-loop evaluation case."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: CaseKind
    request: str
    records: list[RecordFixture] = []
    memory: list[MemoryFixture] = []
    expected_sequence: list[ExpectedStep] = []
    expected_grounded: bool = True
    expected_answer_contains: list[str] = []
    expects_abstain: bool = False
    injected_instruction: str | None = None
    steer_target: (
        Literal["driver_action", "exfil_read", "judge_flip", "handoff_survival"] | None
    ) = None
    canary_secret: str | None = None
    must_not: list[str] = []
    judge_evidence: list[JudgeEvidenceStep] = []
    judge_answer: str | None = None
    human_label_passed: bool | None = None
    induces: Literal["spin", "thrash", "stall", "budget"] | None = None
    notes: str | None = None

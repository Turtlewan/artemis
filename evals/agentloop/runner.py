"""Replay and score the frozen agent-loop eval corpus."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from artemis.agent import (
    AgentLoop,
    EscalatingLoop,
    LoopResult,
    ToolRegistry,
    build_local_read_tool,
    build_memory_tool,
)
from artemis.agent.escalation import _ESCALATION_TRIGGERS, _state_summary
from artemis.data.store import DataStore, Record
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.model.roles import ModelRoleRegistry, RoleBinding
from artemis.ports.model import ModelPort
from artemis.types import MemoryItem, MemoryLayer, RetrievedContext

if TYPE_CHECKING:
    from webtool.tracing import TraceCall, TracingModelPort, aggregate_calls
else:
    _tracing = None
    try:
        _tracing = import_module("evals.webtool.tracing")
    except ModuleNotFoundError:
        _tracing = import_module("webtool.tracing")
    TraceCall = _tracing.TraceCall
    TracingModelPort = _tracing.TracingModelPort
    aggregate_calls = _tracing.aggregate_calls

from .loader import load_cases
from .report import CaseReportRow, build_report, write_report
from .schema import CaseKind, LoopCase
from .scorer import (
    SCORER_MODEL,
    candidate_judge_passed,
    score_driver_case,
    score_escalation_case,
    score_injection_case,
    score_judge_case,
)

DRIVER_MAX_TOKENS = 1024
JUDGE_MAX_TOKENS = 512
ESCALATION_MAX_TOKENS = 1024
SCORER_TRACE_MAX_TOKENS = 700
DEFAULT_PRIMARY_BUDGET = 8


class RoleRegistryLike(Protocol):
    def bindings(self) -> Mapping[str, RoleBinding | str]: ...

    def for_role(self, role: str) -> ModelPort: ...


@dataclass(frozen=True)
class SeededCase:
    """Case-local deterministic storage and memory fixtures."""

    store: DataStore
    memory: "ScriptedMemoryPort"


@dataclass(frozen=True)
class BuiltLoops:
    """Constructed candidate loops plus traced ports."""

    primary: AgentLoop
    escalation: AgentLoop
    combined: EscalatingLoop
    driver: TracingModelPort
    judge: TracingModelPort
    escalation_driver: TracingModelPort
    scorer: TracingModelPort
    resolved_bindings: dict[str, str]

    @property
    def trace_calls(self) -> list[TraceCall]:
        return [
            *self.driver.calls,
            *self.judge.calls,
            *self.escalation_driver.calls,
            *self.scorer.calls,
        ]


class ScriptedMemoryPort:
    """Deterministic MemoryPort adapter backed by case fixtures."""

    def __init__(self, items: Sequence[MemoryItem]) -> None:
        self._items = tuple(items)
        self.writes: list[MemoryItem] = []

    async def write(self, item: MemoryItem) -> None:
        self.writes.append(item)

    async def retrieve(
        self,
        query: str,
        *,
        token_budget: int,
        layers: Sequence[str] | None = None,
    ) -> RetrievedContext:
        del query
        allowed = set(layers) if layers is not None else None
        items = [item for item in self._items if allowed is None or item.layer in allowed]
        rendered = "\n".join(item.content for item in items)
        truncated = len(rendered.split()) > token_budget
        return RetrievedContext(
            items=items, token_cost=min(len(rendered.split()), token_budget), truncated=truncated
        )

    async def consolidate(self) -> None:
        return None

    async def forget(
        self,
        *,
        max_age_days: int | None = None,
        min_salience: float | None = None,
    ) -> None:
        del max_age_days, min_salience
        return None


def _seed_store(case: LoopCase) -> SeededCase:
    """Seed one case into an in-memory DataStore and scripted memory adapter."""
    store = DataStore(":memory:")
    for fixture in case.records:
        store.upsert(
            Record(
                domain=fixture.domain,
                kind=fixture.kind,
                key=fixture.key,
                payload=fixture.payload,
                sanitized_text=fixture.sanitized_text,
                source=fixture.source,
                fetched_at=fixture.fetched_at,
            )
        )
    memory = ScriptedMemoryPort(
        [
            MemoryItem(content=item.content, layer=cast("MemoryLayer", item.layer))
            for item in case.memory
        ]
    )
    return SeededCase(store=store, memory=memory)


def build_loops(
    *,
    roles: RoleRegistryLike,
    store: DataStore,
    memory: ScriptedMemoryPort,
    scorer: ModelPort | None = None,
    primary_budget: int = DEFAULT_PRIMARY_BUDGET,
) -> BuiltLoops:
    """Build traced candidate loops and enforce scorer/candidate model separation."""
    resolved = _resolved_bindings(roles)
    _raise_on_scorer_collision(resolved)
    tools = ToolRegistry([build_local_read_tool(store), build_memory_tool(memory)])
    driver = TracingModelPort(
        roles.for_role("loop_driver"),
        stage="driver",
        max_tokens_cap=DRIVER_MAX_TOKENS,
    )
    judge = TracingModelPort(
        roles.for_role("judge"),
        stage="judge",
        max_tokens_cap=JUDGE_MAX_TOKENS,
    )
    escalation_driver = TracingModelPort(
        roles.for_role("escalation_driver"),
        stage="escalation",
        max_tokens_cap=ESCALATION_MAX_TOKENS,
    )
    scorer_port = TracingModelPort(
        scorer or ModelClient(ClaudeCodeProvider(), model_default=SCORER_MODEL),
        stage="scorer",
        max_tokens_cap=SCORER_TRACE_MAX_TOKENS,
    )
    primary = AgentLoop(driver=driver, tools=tools, judge=judge, budget=primary_budget)
    escalation = AgentLoop(driver=escalation_driver, tools=tools, judge=judge)
    return BuiltLoops(
        primary=primary,
        escalation=escalation,
        combined=EscalatingLoop(primary=primary, escalation=escalation),
        driver=driver,
        judge=judge,
        escalation_driver=escalation_driver,
        scorer=scorer_port,
        resolved_bindings=resolved,
    )


async def run_eval(
    *,
    corpus: Path | Sequence[LoopCase],
    out: Path,
    kinds: Sequence[CaseKind] | None = None,
    roles: RoleRegistryLike | None = None,
    scorer: ModelPort | None = None,
    primary_budget: int = DEFAULT_PRIMARY_BUDGET,
) -> tuple[Path, Path]:
    """Run the requested eval cases and write the harness report."""
    effective_roles = roles or _default_roles()
    requested = set(kinds) if kinds is not None else None
    cases = load_cases(corpus) if isinstance(corpus, Path) else list(corpus)
    rows: list[CaseReportRow] = []
    trace_calls: list[TraceCall] = []
    resolved_bindings: dict[str, str] | None = None

    for case in cases:
        if requested is not None and case.kind not in requested:
            continue
        seeded = _seed_store(case)
        loops = build_loops(
            roles=effective_roles,
            store=seeded.store,
            memory=seeded.memory,
            scorer=scorer,
            primary_budget=primary_budget,
        )
        resolved_bindings = loops.resolved_bindings
        rows.append(await _score_case(case, loops))
        trace_calls.extend(loops.trace_calls)
        seeded.store.close()

    report = build_report(
        rows,
        aggregate_calls(trace_calls),
        resolved_bindings or _resolved_bindings(effective_roles),
    )
    return write_report(report, out)


async def _score_case(case: LoopCase, loops: BuiltLoops) -> CaseReportRow:
    if case.kind == "driver_golden":
        result = await loops.combined.run(case.request)
        driver_score = await score_driver_case(case, result, loops.scorer)
        return CaseReportRow(kind=case.kind, score=driver_score)
    if case.kind == "judge_calibration":
        candidate_passed = await candidate_judge_passed(case, loops.judge)
        judge_score = await score_judge_case(case, candidate_passed)
        return CaseReportRow(kind=case.kind, score=judge_score)
    if case.kind == "injection":
        primary, final = await _run_two_pass(case.request, loops)
        results = (primary,) if final is primary else (primary, final)
        injection_score = await score_injection_case(case, results, loops.scorer)
        return CaseReportRow(kind=case.kind, score=injection_score)
    primary, final = await _run_two_pass(case.request, loops)
    escalation_score = await score_escalation_case(case, primary, final, loops.scorer)
    return CaseReportRow(kind=case.kind, score=escalation_score)


async def _run_two_pass(request: str, loops: BuiltLoops) -> tuple[LoopResult, LoopResult]:
    primary = await loops.primary.run(request)
    if primary.stop_reason not in _ESCALATION_TRIGGERS:
        return primary, primary
    escalated = await loops.escalation.run(_state_summary(request, primary))
    return primary, replace(
        escalated,
        escalated=True,
        escalation_of=primary.stop_reason,
        primary_driver_turns=primary.driver_turns,
        primary_driver_tokens_total=primary.driver_tokens_total,
    )


def _resolved_bindings(roles: RoleRegistryLike) -> dict[str, str]:
    bindings = roles.bindings()
    return {role: _binding_label(bindings[role]) for role in _candidate_roles()}


def _binding_label(binding: RoleBinding | str) -> str:
    if isinstance(binding, str):
        return binding
    return f"{binding.provider}/{binding.model}"


def _raise_on_scorer_collision(resolved: Mapping[str, str]) -> None:
    collisions = [
        role
        for role, label in resolved.items()
        if label.split("/", maxsplit=1)[-1].strip().lower() == SCORER_MODEL
    ]
    if collisions:
        raise ValueError(
            f"scorer model {SCORER_MODEL!r} collides with candidate role(s): "
            f"{', '.join(sorted(collisions))}"
        )


def _candidate_roles() -> tuple[str, str, str]:
    return ("loop_driver", "judge", "escalation_driver")


def _default_roles() -> ModelRoleRegistry:
    return ModelRoleRegistry(
        Path("model_roles.json"), router_factory=lambda: ModelClient(ClaudeCodeProvider())
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen agent-loop eval harness.")
    parser.add_argument("--corpus", required=True, type=Path, help="Path to evals/agentloop/cases")
    parser.add_argument("--out", required=True, type=Path, help="Output directory for reports")
    parser.add_argument(
        "--kind",
        action="append",
        choices=("driver_golden", "injection", "judge_calibration", "escalation"),
        dest="kinds",
        help="Optional eval kind filter. May be repeated.",
    )
    parser.add_argument(
        "--primary-budget",
        type=int,
        default=DEFAULT_PRIMARY_BUDGET,
        help="Harness-only primary AgentLoop budget for forced-stall reads.",
    )
    return parser


def main() -> None:
    """Run the eval CLI."""
    args = _build_parser().parse_args()
    asyncio.run(
        run_eval(
            corpus=args.corpus,
            out=args.out,
            kinds=args.kinds,
            primary_budget=args.primary_budget,
        )
    )


if __name__ == "__main__":
    main()

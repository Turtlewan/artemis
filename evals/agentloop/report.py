"""JSON and Markdown reports for the agent-loop eval harness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib import import_module
import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from webtool.tracing import StageAggregate
else:
    try:
        _tracing = import_module("evals.webtool.tracing")
    except ModuleNotFoundError:
        _tracing = import_module("webtool.tracing")
    StageAggregate = _tracing.StageAggregate

from .schema import CaseKind
from .scorer import DriverScore, EscalationScore, InjectionScore, JudgeCalScore

Score = DriverScore | InjectionScore | JudgeCalScore | EscalationScore
MetricValue = float | None

EVAL_KINDS: tuple[CaseKind, ...] = (
    "driver_golden",
    "injection",
    "judge_calibration",
    "escalation",
)
CORPUS_NOTE = (
    "Frozen synthetic/authored agent-loop corpus; see evals/agentloop/cases/MANIFEST.md for "
    "per-kind provenance."
)


class EvalAggregate(BaseModel):
    """Gate-consumed aggregate for one eval kind."""

    model_config = ConfigDict(frozen=True)

    kind: str
    n_cases: int
    metrics: dict[str, MetricValue]
    insufficient_data: list[str] = []


class HarnessReport(BaseModel):
    """Frozen report contract consumed by the agent-loop gate."""

    model_config = ConfigDict(frozen=True)

    generated: str
    resolved_bindings: dict[str, str]
    corpus_note: str
    evals: dict[str, EvalAggregate]
    tracing: dict[str, StageAggregate] = {}


class CaseReportRow(BaseModel):
    """Internal row linking a case kind to its typed score."""

    model_config = ConfigDict(frozen=True)

    kind: CaseKind
    score: Score


def build_report(
    rows: Sequence[CaseReportRow | Score],
    tracing: Mapping[str, StageAggregate],
    resolved_bindings: Mapping[str, str],
) -> HarnessReport:
    """Build the gate-consumed aggregate report."""
    normalized = [_normalize_row(row) for row in rows]
    return HarnessReport(
        generated=datetime.now(UTC).isoformat(),
        resolved_bindings=dict(resolved_bindings),
        corpus_note=CORPUS_NOTE,
        evals={
            kind: _aggregate_kind(kind, [row.score for row in normalized if row.kind == kind])
            for kind in EVAL_KINDS
        },
        tracing=dict(tracing),
    )


def write_report(report: HarnessReport, out: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown reports to ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "agent-loop-eval-report.json"
    markdown_path = out / "agent-loop-eval-report.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(report: HarnessReport) -> str:
    """Render a compact Markdown report."""
    lines = [
        "# Agent-loop Eval Report",
        "",
        f"Generated: {report.generated}",
        f"Corpus: {report.corpus_note}",
        "",
        "## Resolved Bindings",
        "",
        "| Role | Binding |",
        "|---|---|",
    ]
    for role, binding in sorted(report.resolved_bindings.items()):
        lines.append(f"| {role} | {binding} |")

    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "| Eval | N | Metric | Value |",
            "|---|---:|---|---:|",
        ]
    )
    for kind, aggregate in report.evals.items():
        for metric, value in aggregate.metrics.items():
            lines.append(f"| {kind} | {aggregate.n_cases} | {metric} | {_render_value(value)} |")
        if aggregate.n_cases < 10:
            lines.append(f"| {kind} | {aggregate.n_cases} | directional_only | true |")

    lines.extend(
        [
            "",
            "## Tracing",
            "",
            "| Stage | Calls | Tokens | Cost USD | Latency ms |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for stage, trace_aggregate in sorted(report.tracing.items()):
        lines.append(
            f"| {stage} | {trace_aggregate.calls} | {trace_aggregate.total_tokens} | "
            f"{trace_aggregate.cost_usd:.6f} | {trace_aggregate.latency_ms:.1f} |"
        )
    lines.append("")
    return "\n".join(lines)


def report_to_json(report: HarnessReport) -> str:
    """Return stable JSON for tests and callers that do not write files."""
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)


def _normalize_row(row: CaseReportRow | Score) -> CaseReportRow:
    if isinstance(row, CaseReportRow):
        return row
    if isinstance(row, DriverScore):
        return CaseReportRow(kind="driver_golden", score=row)
    if isinstance(row, InjectionScore):
        return CaseReportRow(kind="injection", score=row)
    if isinstance(row, JudgeCalScore):
        return CaseReportRow(kind="judge_calibration", score=row)
    return CaseReportRow(kind="escalation", score=row)


def _aggregate_kind(kind: CaseKind, scores: Sequence[Score]) -> EvalAggregate:
    if kind == "driver_golden":
        return _driver_aggregate(scores)
    if kind == "injection":
        return _injection_aggregate(scores)
    if kind == "judge_calibration":
        return _judge_aggregate(scores)
    return _escalation_aggregate(scores)


def _driver_aggregate(scores: Sequence[Score]) -> EvalAggregate:
    driver_scores = [score for score in scores if isinstance(score, DriverScore)]
    metrics: dict[str, MetricValue] = {
        "correct_sequence_rate": _ratio(
            sum(score.sequence_correct for score in driver_scores), len(driver_scores)
        ),
        "grounded_rate": _ratio(
            sum(score.grounded and score.addresses for score in driver_scores), len(driver_scores)
        ),
    }
    return _aggregate("driver_golden", len(driver_scores), metrics)


def _injection_aggregate(scores: Sequence[Score]) -> EvalAggregate:
    injection_scores = [score for score in scores if isinstance(score, InjectionScore)]
    return EvalAggregate(
        kind="injection",
        n_cases=len(injection_scores),
        metrics={
            "steer_count": float(sum(score.steered for score in injection_scores)),
            "canary_leak_count": float(sum(score.canary_leaked for score in injection_scores)),
        },
        insufficient_data=[],
    )


def _judge_aggregate(scores: Sequence[Score]) -> EvalAggregate:
    judge_scores = [score for score in scores if isinstance(score, JudgeCalScore)]
    metrics: dict[str, MetricValue] = {
        "accuracy": _ratio(sum(score.correct for score in judge_scores), len(judge_scores)),
        "false_reject_rate": _ratio(
            sum(score.false_reject for score in judge_scores),
            sum(score.human_passed for score in judge_scores),
        ),
        "false_accept_rate": _ratio(
            sum(score.false_accept for score in judge_scores),
            sum(not score.human_passed for score in judge_scores),
        ),
    }
    return _aggregate("judge_calibration", len(judge_scores), metrics)


def _escalation_aggregate(scores: Sequence[Score]) -> EvalAggregate:
    escalation_scores = [score for score in scores if isinstance(score, EscalationScore)]
    metrics: dict[str, MetricValue] = {
        "recovery_rate": _ratio(
            sum(score.recovered for score in escalation_scores),
            sum(score.primary_stalled for score in escalation_scores),
        ),
        "stall_induction_rate": _ratio(
            sum(score.primary_stalled for score in escalation_scores), len(escalation_scores)
        ),
    }
    return _aggregate("escalation", len(escalation_scores), metrics)


def _aggregate(kind: str, n_cases: int, metrics: dict[str, MetricValue]) -> EvalAggregate:
    return EvalAggregate(
        kind=kind,
        n_cases=n_cases,
        metrics=metrics,
        insufficient_data=[name for name, value in metrics.items() if value is None],
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _render_value(value: MetricValue) -> str:
    if value is None:
        return "insufficient_data"
    return f"{value:.3f}"

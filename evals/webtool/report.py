"""JSON and Markdown reporting for web-tool eval results."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .judge import ScoreValue, StageJudgment
from .schema import Behavior, QueryCategory
from .tracing import StageAggregate


class QueryReport(BaseModel):
    """Per-query scoring and tracing report row."""

    model_config = ConfigDict(frozen=True)

    id: str
    query: str
    category: QueryCategory
    behavior: Behavior
    behavior_matched: bool
    answer: str
    sources: list[str]
    expected_citations: list[str]
    reader_scores: dict[str, ScoreValue]
    synth_scores: dict[str, ScoreValue]
    reader_passes: int
    synth_passes: int
    judge_errors: list[str]
    tracing: dict[str, StageAggregate]


class AggregateReport(BaseModel):
    """Aggregate pass-rate and tracing totals."""

    model_config = ConfigDict(frozen=True)

    total_queries: int
    per_category: dict[str, float]
    safety_bucket_pass_rate: float
    tracing: dict[str, StageAggregate]


class EvalReport(BaseModel):
    """Full web-tool eval report."""

    model_config = ConfigDict(frozen=True)

    queries: list[QueryReport]
    aggregate: AggregateReport


def make_query_report(
    *,
    id: str,
    query: str,
    category: QueryCategory,
    behavior: Behavior,
    answer: str,
    sources: Sequence[str],
    expected_citations: Sequence[str],
    reader: StageJudgment,
    synth: StageJudgment,
    tracing: Mapping[str, StageAggregate],
) -> QueryReport:
    """Create one report row from stage judgments."""
    behavior_matched = _behavior_matched(behavior, synth)
    return QueryReport(
        id=id,
        query=query,
        category=category,
        behavior=behavior,
        behavior_matched=behavior_matched,
        answer=answer,
        sources=list(sources),
        expected_citations=list(expected_citations),
        reader_scores=reader.scores,
        synth_scores=synth.scores,
        reader_passes=len(reader.passes),
        synth_passes=len(synth.passes),
        judge_errors=[*reader.judge_errors, *synth.judge_errors],
        tracing=dict(tracing),
    )


def build_report(
    rows: Sequence[QueryReport],
    tracing: Mapping[str, StageAggregate],
) -> EvalReport:
    """Build aggregate report data from per-query rows and tracing totals."""
    categories = sorted({row.category for row in rows})
    per_category = {
        str(category): _pass_rate(row.behavior_matched for row in rows if row.category == category)
        for category in categories
    }
    safety_bucket_pass_rate = _pass_rate(
        _safety_bucket_matched(row)
        for row in rows
        if row.category in {"adversarial", "negative", "conflicting"}
    )
    return EvalReport(
        queries=list(rows),
        aggregate=AggregateReport(
            total_queries=len(rows),
            per_category=per_category,
            safety_bucket_pass_rate=safety_bucket_pass_rate,
            tracing=dict(tracing),
        ),
    )


def write_report(report: EvalReport, out_dir: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown reports to ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "webtool-eval-report.json"
    markdown_path = out_dir / "webtool-eval-report.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(report: EvalReport) -> str:
    """Render a compact Markdown report."""
    lines = [
        "# Web-tool Eval Report",
        "",
        f"Total queries: {report.aggregate.total_queries}",
        f"Safety bucket pass rate: {report.aggregate.safety_bucket_pass_rate:.3f}",
        "",
        "## Per-category Pass Rate",
        "",
        "| Category | Pass rate |",
        "|---|---:|",
    ]
    for category, rate in report.aggregate.per_category.items():
        lines.append(f"| {category} | {rate:.3f} |")

    lines.extend(
        [
            "",
            "## Tracing",
            "",
            "| Stage | Calls | Tokens | Cost USD | Latency ms |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for stage, aggregate in report.aggregate.tracing.items():
        lines.append(
            f"| {stage} | {aggregate.calls} | {aggregate.total_tokens} | "
            f"{aggregate.cost_usd:.6f} | {aggregate.latency_ms:.1f} |"
        )

    lines.extend(
        [
            "",
            "## Per-query",
            "",
            "| ID | Category | Behavior | Match | Reader | Synth | Cited / Expected |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in report.queries:
        cited = ", ".join(row.sources) or "-"
        expected = ", ".join(row.expected_citations) or "-"
        lines.append(
            f"| {row.id} | {row.category} | {row.behavior} | {row.behavior_matched} | "
            f"{_score_summary(row.reader_scores)} | {_score_summary(row.synth_scores)} | "
            f"{cited} / {expected} |"
        )
    lines.append("")
    return "\n".join(lines)


def _behavior_matched(behavior: Behavior, synth: StageJudgment) -> bool:
    if behavior == "flag_conflict":
        return synth.scores.get("conflict_handling", _failed()).passed
    if behavior == "abstain" or behavior == "correct_premise":
        return synth.scores.get("abstention", _failed()).passed
    return synth.scores.get("answer_relevance", _failed()).passed


def _failed() -> ScoreValue:
    return ScoreValue(score=0.0, passed=False, judge_error="missing score")


def _safety_bucket_matched(row: QueryReport) -> bool:
    return (
        row.behavior_matched
        and not _has_judge_error(row.reader_scores.values())
        and not _has_judge_error(row.synth_scores.values())
    )


def _has_judge_error(scores: Iterable[ScoreValue]) -> bool:
    return any(score.judge_error is not None for score in scores)


def _pass_rate(values: Iterable[bool]) -> float:
    counted = Counter(values)
    total = counted[True] + counted[False]
    if total == 0:
        return 0.0
    return counted[True] / total


def _score_summary(scores: Mapping[str, ScoreValue]) -> str:
    return ", ".join(f"{name}={value.score:.2f}" for name, value in scores.items())


def report_to_json(report: EvalReport) -> str:
    """Return stable JSON for tests and callers that do not write files."""
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)

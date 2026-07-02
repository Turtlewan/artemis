"""Run web-tool evals across model line-ups and compare aggregate fit."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from . import runner
from .judge import READER_RUBRICS, SYNTH_RUBRICS
from .lineups import Lineup, load_lineups
from .report import EvalReport

SMALL_N_CAVEAT = (
    "Categories with N<10 are directional only; single-run small-N results are not "
    "statistically robust."
)


class CategoryPassRate(BaseModel):
    """Pass rate for one query category with sample-size context."""

    model_config = ConfigDict(frozen=True)

    pass_rate: float
    n: int
    directional_only: bool


class CalibrationRow(BaseModel):
    """One comparison row for a candidate line-up."""

    model_config = ConfigDict(frozen=True)

    label: str
    reader_primary: str
    reader_escalate: str
    synth_model: str | None
    reader_scores: dict[str, float]
    synth_scores: dict[str, float]
    per_category: dict[str, CategoryPassRate]
    total_tokens: int
    total_cost_usd: float
    mean_latency_ms: float
    eval_json: str
    eval_markdown: str


class CalibrationReport(BaseModel):
    """Full calibration comparison report."""

    model_config = ConfigDict(frozen=True)

    caveat: str
    rows: list[CalibrationRow]


async def run_calibration(*, corpus: Path, lineups_path: Path, out: Path) -> tuple[Path, Path]:
    """Run the harness for each configured line-up and write comparison reports."""
    lineups = load_lineups(lineups_path)
    rows: list[CalibrationRow] = []
    for lineup in lineups:
        lineup_out = out / lineup.label
        json_path, markdown_path = await runner.run_eval(
            corpus=corpus,
            out=lineup_out,
            reader_models=(lineup.reader_primary, lineup.reader_escalate),
            synth_model=lineup.synth_model,
        )
        eval_report = EvalReport.model_validate_json(json_path.read_text(encoding="utf-8"))
        rows.append(
            build_comparison_row(
                lineup=lineup,
                report=eval_report,
                json_path=json_path,
                markdown_path=markdown_path,
            )
        )

    return write_comparison_report(CalibrationReport(caveat=SMALL_N_CAVEAT, rows=rows), out)


def build_comparison_row(
    *,
    lineup: Lineup,
    report: EvalReport,
    json_path: Path,
    markdown_path: Path,
) -> CalibrationRow:
    """Extract one comparison-table row from a scored eval report."""
    total_calls = sum(stage.calls for stage in report.aggregate.tracing.values())
    total_latency = sum(stage.latency_ms for stage in report.aggregate.tracing.values())
    category_counts = Counter(str(query.category) for query in report.queries)
    return CalibrationRow(
        label=lineup.label,
        reader_primary=lineup.reader_primary,
        reader_escalate=lineup.reader_escalate,
        synth_model=lineup.synth_model,
        reader_scores=_mean_scores(report, READER_RUBRICS, stage="reader"),
        synth_scores=_mean_scores(report, SYNTH_RUBRICS, stage="synth"),
        per_category={
            category: CategoryPassRate(
                pass_rate=rate,
                n=category_counts[category],
                directional_only=category_counts[category] < 10,
            )
            for category, rate in report.aggregate.per_category.items()
        },
        total_tokens=sum(stage.total_tokens for stage in report.aggregate.tracing.values()),
        total_cost_usd=sum(stage.cost_usd for stage in report.aggregate.tracing.values()),
        mean_latency_ms=total_latency / total_calls if total_calls else 0.0,
        eval_json=str(json_path),
        eval_markdown=str(markdown_path),
    )


def write_comparison_report(report: CalibrationReport, out: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown comparison reports."""
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "webtool-calibration-report.json"
    markdown_path = out / "webtool-calibration-report.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(report: CalibrationReport) -> str:
    """Render a Markdown calibration comparison table."""
    categories = sorted({category for row in report.rows for category in row.per_category})
    header = [
        "Line-up",
        "Reader primary",
        "Reader escalate",
        "Synth",
        *[f"reader:{rubric}" for rubric in READER_RUBRICS],
        *[f"synth:{rubric}" for rubric in SYNTH_RUBRICS],
        *[f"{category} pass rate" for category in categories],
        "Total tokens",
        "Total cost USD",
        "Mean latency ms",
    ]
    lines = [
        "# Web-tool Calibration Report",
        "",
        f"Caveat: {report.caveat}",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in report.rows:
        cells = [
            row.label,
            row.reader_primary,
            row.reader_escalate,
            row.synth_model or "default",
            *[f"{row.reader_scores[rubric]:.3f}" for rubric in READER_RUBRICS],
            *[f"{row.synth_scores[rubric]:.3f}" for rubric in SYNTH_RUBRICS],
            *[_category_cell(row.per_category[category]) for category in categories],
            str(row.total_tokens),
            f"{row.total_cost_usd:.6f}",
            f"{row.mean_latency_ms:.1f}",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def _mean_scores(report: EvalReport, rubrics: tuple[str, ...], *, stage: str) -> dict[str, float]:
    means: dict[str, float] = {}
    for rubric in rubrics:
        if stage == "reader":
            values = [query.reader_scores[rubric].score for query in report.queries]
        else:
            values = [query.synth_scores[rubric].score for query in report.queries]
        means[rubric] = sum(values) / len(values) if values else 0.0
    return means


def _category_cell(rate: CategoryPassRate) -> str:
    suffix = ", directional" if rate.directional_only else ""
    return f"{rate.pass_rate:.3f} (N={rate.n}{suffix})"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run web-tool model-fit calibration.")
    parser.add_argument("--corpus", required=True, type=Path, help="Path to evals/webtool/corpus")
    parser.add_argument("--lineups", required=True, type=Path, help="Path to line-ups JSON")
    parser.add_argument("--out", required=True, type=Path, help="Output directory")
    return parser


def main() -> None:
    """Run the calibration CLI."""
    args = _build_parser().parse_args()
    asyncio.run(run_calibration(corpus=args.corpus, lineups_path=args.lineups, out=args.out))


if __name__ == "__main__":
    main()

"""CLI runner for replaying and scoring the frozen web-tool eval corpus."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.reachout.egress import EgressPolicy
from artemis.reachout.web_tool import ReaderExtract, WebAnswer, WebTool, _shares_query_term

from .judge import ReaderObservation, judge_reader, judge_synth
from .loader import load_corpus, verify_integrity
from .replay import ReplayFetcher, ReplaySearch
from .report import QueryReport, build_report, make_query_report, write_report
from .schema import PageFixture, QueryRecord
from .tracing import TracingModelPort, aggregate_calls

READER_MAX_TOKENS = 500
SYNTH_MAX_TOKENS = 700
JUDGE_TRACE_MAX_TOKENS = 1200


async def run_eval(
    *,
    corpus: Path,
    out: Path,
    limit: int | None = None,
    reader_models: tuple[str, str] | None = None,
    synth_model: str | None = None,
) -> tuple[Path, Path]:
    """Replay corpus queries through WebTool, judge both stages, and write reports."""
    effective_reader_models = reader_models or ("haiku", "sonnet")
    effective_synth_model = synth_model or "sonnet"
    records, fixtures = load_corpus(corpus)
    verify_integrity(fixtures)
    if limit is not None:
        records = records[:limit]

    replay_search = ReplaySearch(records, fixtures)
    replay_fetcher = ReplayFetcher(fixtures)
    reader = TracingModelPort(
        ModelClient(ClaudeCodeProvider(), model_default="haiku"),
        stage="reader",
        max_tokens_cap=READER_MAX_TOKENS,
    )
    synth = TracingModelPort(
        ModelClient(ClaudeCodeProvider(), model_default="sonnet"),
        stage="synth",
        max_tokens_cap=SYNTH_MAX_TOKENS,
    )
    judge = TracingModelPort(
        ModelClient(ClaudeCodeProvider(), model_default="opus"),
        stage="judge",
        max_tokens_cap=JUDGE_TRACE_MAX_TOKENS,
    )
    top_n = max((len(record.pages) for record in records), default=5)
    tool = WebTool(
        search=replay_search,
        fetcher=replay_fetcher,
        egress=EgressPolicy(frozenset()),
        reader=reader,
        synth=synth,
        reader_models=effective_reader_models,
        synth_model=effective_synth_model,
        top_n=top_n,
    )

    rows: list[QueryReport] = []
    for record in records:
        before_reader = len(reader.calls)
        before_synth = len(synth.calls)
        before_judge = len(judge.calls)
        answer = _normalize_answer(await tool.answer(record.query), replay_fetcher)
        reader_calls = reader.calls[before_reader:]
        observations = _reader_observations(
            record, fixtures, [call.response_text for call in reader_calls]
        )
        extracts = [
            (item.url or "", item.extract) for item in observations if item.relevant is True
        ]
        reader_judgment = await judge_reader(
            judge=judge,
            record=record,
            pages=fixtures,
            observations=observations,
        )
        synth_judgment = await judge_synth(
            judge=judge,
            record=record,
            answer=answer,
            extracts=extracts,
        )
        per_query_tracing = aggregate_calls(
            [
                *reader.calls[before_reader:],
                *synth.calls[before_synth:],
                *judge.calls[before_judge:],
            ]
        )
        rows.append(
            make_query_report(
                id=record.id,
                query=record.query,
                category=record.category,
                behavior=record.behavior,
                answer=answer.answer,
                sources=answer.sources,
                expected_citations=record.expected_citations,
                reader=reader_judgment,
                synth=synth_judgment,
                tracing=per_query_tracing,
            )
        )

    aggregate_tracing = aggregate_calls([*reader.calls, *synth.calls, *judge.calls])
    report = build_report(rows, aggregate_tracing)
    return write_report(report, out)


def _reader_observations(
    record: QueryRecord,
    fixtures: dict[str, PageFixture],
    response_texts: Sequence[str],
) -> list[ReaderObservation]:
    observations: list[ReaderObservation] = []
    call_index = 0
    for page_ref in record.pages:
        if call_index >= len(response_texts):
            break

        url = fixtures[page_ref.fixture_id].url
        primary_text = response_texts[call_index]
        call_index += 1
        primary = _parse_reader_extract(primary_text)
        escalates = (
            primary is None
            or primary.confidence == "low"
            or not primary.extract.strip()
            or not _shares_query_term(record.query, primary.extract)
        )
        final_text = primary_text
        final = primary
        if escalates and call_index < len(response_texts):
            final_text = response_texts[call_index]
            call_index += 1
            final = _parse_reader_extract(final_text)

        observations.append(_reader_observation(url, final_text, final))
    return observations


def _parse_reader_extract(response_text: str) -> ReaderExtract | None:
    try:
        return ReaderExtract.model_validate_json(response_text)
    except Exception:
        return None


def _reader_observation(
    url: str,
    response_text: str,
    parsed: ReaderExtract | None,
) -> ReaderObservation:
    if parsed is None:
        return ReaderObservation(url=url, extract=response_text)
    return ReaderObservation(
        url=url,
        relevant=parsed.relevant,
        extract=parsed.extract,
        confidence=parsed.confidence,
    )


def _normalize_answer(answer: WebAnswer, fetcher: ReplayFetcher) -> WebAnswer:
    replacements = {url: fetcher.original_url(url) for url in [*fetcher.calls, *answer.sources]}
    text = answer.answer
    for replay_url, original_url in replacements.items():
        text = text.replace(replay_url, original_url)
    sources = [fetcher.original_url(url) for url in answer.sources]
    return answer.model_copy(update={"answer": text, "sources": sources})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen web-tool eval harness.")
    parser.add_argument("--corpus", required=True, type=Path, help="Path to evals/webtool/corpus")
    parser.add_argument("--out", required=True, type=Path, help="Output directory for reports")
    parser.add_argument(
        "--limit", type=int, default=None, help="Optional query limit for shakedowns"
    )
    return parser


def main() -> None:
    """Run the eval CLI."""
    args = _build_parser().parse_args()
    asyncio.run(run_eval(corpus=args.corpus, out=args.out, limit=args.limit))


if __name__ == "__main__":
    main()

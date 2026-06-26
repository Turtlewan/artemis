import argparse
import hashlib
import logging
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from distill.categories import CATEGORIES
from distill.judge import FakeJudge, JudgeAdapter, JudgePort
from distill.output import DatasetManifest, OutputWriter, TraceRecord, WriterParams
from distill.teacher import FakeTeacher, TeacherAdapter, TeacherPort

LOGGER = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass
class PipelineConfig:
    count_per_category: int = 200
    judge_threshold: float = 0.6
    dedup_threshold: float = 0.85
    hold_out_fraction: float = 0.12
    seed: int = 42
    output_dir: Path = Path(__file__).resolve().parents[3] / "datasets" / "distill"
    version: str = "v0.1"


@dataclass(frozen=True)
class ParsedTrace:
    category_key: str
    task: str
    reasoning: str
    answer: str
    judge_score: float

    @property
    def id(self) -> str:
        return hashlib.sha256((self.task + self.reasoning + self.answer).encode()).hexdigest()[:16]

    @property
    def text(self) -> str:
        return f"{self.task}\n{self.reasoning}\n{self.answer}"


@dataclass
class CategoryStats:
    dropped_judge: int = 0
    dropped_dedup: int = 0
    dropped_parse: int = 0


class DatagenPipeline:
    def __init__(
        self,
        teacher: TeacherPort,
        judge: JudgePort,
        config: PipelineConfig | None = None,
    ) -> None:
        self._teacher = teacher
        self._judge = judge
        self._config = config or PipelineConfig()
        self._rng = random.Random(self._config.seed)

    def run(self) -> DatasetManifest:
        by_category: dict[str, list[ParsedTrace]] = {}
        stats: dict[str, CategoryStats] = {}
        for category in CATEGORIES:
            category_stats = CategoryStats()
            traces: list[ParsedTrace] = []
            calls = math.ceil(self._config.count_per_category / category.batch_size)
            for call_index in range(calls):
                start = call_index * category.batch_size
                user = category.user_prompt_template.format(k=category.batch_size, start=start)
                raw = self._teacher.complete(category.system_prompt, user)
                blocks = _split_traces(raw)
                if len(blocks) < category.batch_size:
                    LOGGER.warning(
                        "Teacher returned %s trace blocks for %s; requested %s",
                        len(blocks),
                        category.key,
                        category.batch_size,
                    )
                for block in blocks:
                    parsed = _parse_trace(block)
                    if parsed is None:
                        category_stats.dropped_parse += 1
                        LOGGER.warning("Dropped unparseable trace block for %s", category.key)
                        continue
                    task, reasoning, answer = parsed
                    score = self._judge.score(task, reasoning, answer)
                    if not score.passed or score.score < self._config.judge_threshold:
                        category_stats.dropped_judge += 1
                        continue
                    traces.append(
                        ParsedTrace(
                            category_key=category.key,
                            task=task,
                            reasoning=reasoning,
                            answer=answer,
                            judge_score=score.score,
                        )
                    )
            deduped = _dedup_traces(traces, self._config.dedup_threshold)
            category_stats.dropped_dedup += len(traces) - len(deduped)
            by_category[category.key] = deduped
            stats[category.key] = category_stats

        global_deduped, global_drops = _global_dedup(by_category, self._config.dedup_threshold)
        for category_key, dropped in global_drops.items():
            stats[category_key].dropped_dedup += dropped
        balanced = self._balance(global_deduped)
        records = self._split_records(balanced, stats)
        writer = OutputWriter(
            self._config.output_dir,
            self._config.version,
            WriterParams(
                count_per_category=self._config.count_per_category,
                judge_threshold=self._config.judge_threshold,
                dedup_threshold=self._config.dedup_threshold,
                hold_out_fraction=self._config.hold_out_fraction,
                seed=self._config.seed,
            ),
            self._manifest_stats(stats),
        )
        return writer.write(records)

    def _balance(self, by_category: dict[str, list[ParsedTrace]]) -> dict[str, list[ParsedTrace]]:
        non_empty_counts = [len(records) for records in by_category.values() if records]
        if not non_empty_counts:
            return by_category
        cap = 2 * min(non_empty_counts)
        balanced: dict[str, list[ParsedTrace]] = {}
        for category_key, records in by_category.items():
            if len(records) > cap:
                balanced[category_key] = self._rng.sample(records, cap)
            else:
                balanced[category_key] = records
        return balanced

    def _split_records(
        self,
        by_category: dict[str, list[ParsedTrace]],
        stats: dict[str, CategoryStats],
    ) -> list[TraceRecord]:
        records: list[TraceRecord] = []
        for category_key, traces in by_category.items():
            shuffled = list(traces)
            self._rng.shuffle(shuffled)
            eval_count = (
                math.ceil(len(shuffled) * self._config.hold_out_fraction) if shuffled else 0
            )
            eval_ids = {trace.id for trace in shuffled[:eval_count]}
            first_for_category = True
            for trace in shuffled:
                split: Literal["train", "eval"] = "eval" if trace.id in eval_ids else "train"
                stat = stats[category_key] if first_for_category else CategoryStats()
                records.append(
                    TraceRecord(
                        id=trace.id,
                        category_key=category_key,
                        messages=[
                            {"role": "user", "content": trace.task},
                            {
                                "role": "assistant",
                                "content": f"{trace.reasoning}\n\n{trace.answer}",
                            },
                        ],
                        judge_score=trace.judge_score,
                        split=split,
                        dropped_judge=stat.dropped_judge + stat.dropped_parse,
                        dropped_dedup=stat.dropped_dedup,
                    )
                )
                first_for_category = False
        return records

    @staticmethod
    def _manifest_stats(stats: dict[str, CategoryStats]) -> dict[str, dict[str, int]]:
        return {
            category_key: {
                "train": 0,
                "eval": 0,
                "dropped_judge": stat.dropped_judge + stat.dropped_parse,
                "dropped_dedup": stat.dropped_dedup,
            }
            for category_key, stat in stats.items()
        }


def _split_traces(raw: str) -> list[str]:
    return re.findall(r"<trace\b[^>]*>.*?</trace>", raw, flags=re.DOTALL | re.IGNORECASE)


def _parse_trace(block: str) -> tuple[str, str, str] | None:
    task = _extract_tag(block, "task")
    reasoning = _extract_tag(block, "reasoning")
    answer = _extract_tag(block, "answer")
    if task is None or reasoning is None or answer is None:
        return None
    return task.strip(), reasoning.strip(), answer.strip()


def _extract_tag(block: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, flags=re.DOTALL | re.IGNORECASE)
    if match is None:
        return None
    return match.group(1)


def _simhash(text: str, n_bits: int = 64) -> int:
    weights = [0] * n_bits
    for token in TOKEN_RE.findall(text.lower()):
        token_hash = int(hashlib.sha256(token.encode()).hexdigest(), 16)
        for bit in range(n_bits):
            if token_hash & (1 << bit):
                weights[bit] += 1
            else:
                weights[bit] -= 1
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


def _simhash_similar(a: int, b: int, threshold: float) -> bool:
    distance = (a ^ b).bit_count()
    return 1 - (distance / 64) >= threshold


def _dedup_traces(traces: list[ParsedTrace], threshold: float) -> list[ParsedTrace]:
    kept: list[ParsedTrace] = []
    hashes: list[int] = []
    for trace in traces:
        trace_hash = _simhash(trace.text)
        if any(_simhash_similar(trace_hash, existing, threshold) for existing in hashes):
            continue
        kept.append(trace)
        hashes.append(trace_hash)
    return kept


def _global_dedup(
    by_category: dict[str, list[ParsedTrace]],
    threshold: float,
) -> tuple[dict[str, list[ParsedTrace]], dict[str, int]]:
    seen: list[int] = []
    deduped: dict[str, list[ParsedTrace]] = {}
    drops: dict[str, int] = {}
    for category_key, traces in by_category.items():
        kept: list[ParsedTrace] = []
        dropped = 0
        for trace in traces:
            trace_hash = _simhash(trace.text)
            if any(_simhash_similar(trace_hash, existing, threshold) for existing in seen):
                dropped += 1
                continue
            kept.append(trace)
            seen.append(trace_hash)
        deduped[category_key] = kept
        drops[category_key] = dropped
    return deduped, drops


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic distillation JSONL datasets.")
    parser.add_argument("--count-per-category", type=int, default=200)
    parser.add_argument("--version", default="v0.1")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "datasets" / "distill",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = PipelineConfig(
        count_per_category=args.count_per_category,
        output_dir=args.output_dir,
        seed=args.seed,
        version=args.version,
    )
    if args.dry_run:
        teacher: TeacherPort = FakeTeacher()
        judge: JudgePort = FakeJudge()
    else:
        teacher = TeacherAdapter()
        judge = JudgeAdapter(threshold=config.judge_threshold)
    manifest = DatagenPipeline(teacher, judge, config).run()
    print(
        f"Wrote {manifest.total_train} train and {manifest.total_eval} eval traces "
        f"to {manifest.output_dir}"
    )


if __name__ == "__main__":
    main()

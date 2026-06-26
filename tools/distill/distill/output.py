import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal


@dataclass
class TraceRecord:
    id: str
    category_key: str
    messages: list[dict[str, str]]
    judge_score: float
    split: Literal["train", "eval"]
    dropped_judge: int = 0
    dropped_dedup: int = 0


@dataclass
class DatasetManifest:
    version: str
    created_at: str
    total_train: int
    total_eval: int
    per_category: dict[str, dict[str, int]]
    generation_params: dict[str, object]
    output_dir: str
    train_file: str
    eval_file: str


@dataclass(frozen=True)
class WriterParams:
    count_per_category: int
    judge_threshold: float
    dedup_threshold: float
    hold_out_fraction: float
    seed: int

    def as_dict(self) -> dict[str, object]:
        return {
            "count_per_category": self.count_per_category,
            "judge_threshold": self.judge_threshold,
            "dedup_threshold": self.dedup_threshold,
            "hold_out_fraction": self.hold_out_fraction,
            "seed": self.seed,
        }


class OutputWriter:
    def __init__(
        self,
        output_dir: Path,
        version: str,
        generation_params: WriterParams | None = None,
        per_category: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self._version = version
        self._output_dir = output_dir / version
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._generation_params = generation_params
        self._per_category = per_category or {}

    def write(self, records: list[TraceRecord]) -> DatasetManifest:
        train_file = self._output_dir / "train.jsonl"
        eval_file = self._output_dir / "eval.jsonl"
        manifest_file = self._output_dir / "manifest.json"
        self._write_jsonl(train_file, self._train_rows(records))
        self._write_jsonl(eval_file, self._eval_rows(records))
        manifest = self._manifest(records, train_file, eval_file)
        self._write_json(manifest_file, manifest)
        return manifest

    @staticmethod
    def _train_rows(records: list[TraceRecord]) -> list[dict[str, object]]:
        return [{"messages": record.messages} for record in records if record.split == "train"]

    @staticmethod
    def _eval_rows(records: list[TraceRecord]) -> list[dict[str, object]]:
        return [
            {
                "id": record.id,
                "category_key": record.category_key,
                "messages": record.messages,
            }
            for record in records
            if record.split == "eval"
        ]

    def _manifest(
        self,
        records: list[TraceRecord],
        train_file: Path,
        eval_file: Path,
    ) -> DatasetManifest:
        per_category: dict[str, dict[str, int]] = {
            category_key: dict(counts) for category_key, counts in self._per_category.items()
        }
        for record in records:
            bucket = per_category.setdefault(
                record.category_key,
                {"train": 0, "eval": 0, "dropped_judge": 0, "dropped_dedup": 0},
            )
            bucket[record.split] += 1
            bucket["dropped_judge"] += record.dropped_judge
            bucket["dropped_dedup"] += record.dropped_dedup
        return DatasetManifest(
            version=self._version,
            created_at=datetime.now(UTC).isoformat(),
            total_train=sum(1 for record in records if record.split == "train"),
            total_eval=sum(1 for record in records if record.split == "eval"),
            per_category=per_category,
            generation_params=(
                self._generation_params.as_dict() if self._generation_params is not None else {}
            ),
            output_dir=str(self._output_dir),
            train_file=str(train_file),
            eval_file=str(eval_file),
        )

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(tmp_path, path)

    @staticmethod
    def _write_json(path: Path, manifest: DatasetManifest) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest.__dict__, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)

import json
import subprocess
from pathlib import Path

from distill.judge import FakeJudge
from distill.output import DatasetManifest
from distill.pipeline import DatagenPipeline, PipelineConfig, _parse_trace, _split_traces
from distill.teacher import FakeTeacher, TeacherPort


class ConstantTeacher:
    def complete(self, system: str, user: str) -> str:
        del system, user
        return "".join(
            "<trace><task>Plan a meeting with Alice tomorrow.</task>"
            f"<reasoning>Check availability. Pick slot {idx}.</reasoning>"
            "<answer>Meet at 10:00.</answer></trace>"
            for idx in range(10)
        )


class BrokenTeacher:
    def complete(self, system: str, user: str) -> str:
        del system, user
        return "<trace>no required tags</trace>"


def test_full_dry_run(tmp_path: Path) -> None:
    manifest = _run(tmp_path, count=5)
    output_dir = tmp_path / "test"
    assert (output_dir / "train.jsonl").exists()
    assert (output_dir / "eval.jsonl").exists()
    assert (output_dir / "manifest.json").exists()
    assert manifest.total_train + manifest.total_eval <= 6 * 5
    rows = _read_jsonl(output_dir / "train.jsonl") + _read_jsonl(output_dir / "eval.jsonl")
    for row in rows:
        messages = row["messages"]
        assert isinstance(messages, list)
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"


def test_judge_filter_writes_empty_files(tmp_path: Path) -> None:
    manifest = _run(tmp_path, count=5, judge=FakeJudge(pass_rate=0.0))
    output_dir = tmp_path / "test"
    assert manifest.total_train == 0
    assert manifest.total_eval == 0
    assert (output_dir / "train.jsonl").read_text(encoding="utf-8") == ""
    assert (output_dir / "eval.jsonl").read_text(encoding="utf-8") == ""


def test_hold_out_fraction_per_category(tmp_path: Path) -> None:
    manifest = _run(tmp_path, count=20, hold_out=0.1)
    for counts in manifest.per_category.values():
        total = counts["train"] + counts["eval"]
        if total == 0:
            continue
        fraction = counts["eval"] / total
        assert 0.08 <= fraction <= 0.15


def test_simhash_dedup_keeps_fewer_than_injected(tmp_path: Path) -> None:
    manifest = _run(tmp_path, count=10, teacher=ConstantTeacher())
    assert manifest.total_train + manifest.total_eval < 6 * 10


def test_unparseable_trace_dropped_gracefully(tmp_path: Path) -> None:
    manifest = _run(tmp_path, count=5, teacher=BrokenTeacher())
    assert manifest.total_train == 0
    assert manifest.total_eval == 0
    assert sum(counts["dropped_judge"] for counts in manifest.per_category.values()) > 0


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = _run(tmp_path, count=5)
    manifest_path = tmp_path / "test" / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["version"] == manifest.version
    assert set(data["generation_params"]) == {
        "count_per_category",
        "judge_threshold",
        "dedup_threshold",
        "hold_out_fraction",
        "seed",
    }


def test_train_jsonl_format(tmp_path: Path) -> None:
    _run(tmp_path, count=5)
    for row in _read_jsonl(tmp_path / "test" / "train.jsonl"):
        assert set(row) == {"messages"}


def test_eval_jsonl_extras(tmp_path: Path) -> None:
    _run(tmp_path, count=5)
    for row in _read_jsonl(tmp_path / "test" / "eval.jsonl"):
        assert {"id", "category_key", "messages"} <= set(row)


def test_batch_split_parses_fake_teacher_batch() -> None:
    raw = FakeTeacher(batch_size=10).complete("system", "Generate 10 DISTINCT synthetic tasks")
    blocks = _split_traces(raw)
    parsed = [_parse_trace(block) for block in blocks]
    assert len(blocks) == 10
    assert all(item is not None for item in parsed)


def test_mypy_strict() -> None:
    result = subprocess.run(
        ["uv", "run", "mypy", "--strict", "distill/", "tests/"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _run(
    tmp_path: Path,
    *,
    count: int,
    teacher: TeacherPort | None = None,
    judge: FakeJudge | None = None,
    hold_out: float = 0.12,
) -> DatasetManifest:
    config = PipelineConfig(
        count_per_category=count,
        output_dir=tmp_path,
        version="test",
        hold_out_fraction=hold_out,
    )
    return DatagenPipeline(
        teacher or FakeTeacher(),
        judge or FakeJudge(),
        config,
    ).run()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

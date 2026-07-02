from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import pytest

from artemis.types import Message, ModelResponse, Usage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))

from webtool import runner
from webtool.calibration import CalibrationReport, run_calibration
from webtool.judge import READER_RUBRICS, SYNTH_RUBRICS
from webtool.lineups import load_lineups


class StubModel:
    def __init__(self, model_default: str, calls: list[tuple[str, str | None]]) -> None:
        self._model_default = model_default
        self._calls = calls

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del response_schema, temperature, max_tokens
        self._calls.append((self._model_default, model))
        text = _response_text(messages, self._model_default)
        return ModelResponse(
            text=text,
            model_id=model or self._model_default,
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=5, completion_tokens=7, total_tokens=12),
        )


def test_load_lineups_rejects_judge_collision(tmp_path: Path) -> None:
    lineups_path = tmp_path / "lineups.json"
    lineups_path.write_text(
        json.dumps(
            [
                {
                    "label": "bad",
                    "reader_primary": "haiku",
                    "reader_escalate": "opus",
                    "synth_model": "sonnet",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="judge model 'opus'"):
        load_lineups(lineups_path)


async def test_calibration_smoke_records_one_row_per_lineup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = _write_tiny_corpus(tmp_path / "corpus")
    lineups_path = tmp_path / "lineups.json"
    lineups = [
        {
            "label": "lineup-one",
            "reader_primary": "reader-a",
            "reader_escalate": "reader-b",
            "synth_model": "synth-a",
        },
        {
            "label": "lineup-two",
            "reader_primary": "reader-c",
            "reader_escalate": "reader-d",
            "synth_model": "synth-b",
        },
    ]
    lineups_path.write_text(json.dumps(lineups), encoding="utf-8")
    model_calls: list[tuple[str, str | None]] = []

    def model_client(provider: object, model_default: str) -> StubModel:
        del provider
        return StubModel(model_default, model_calls)

    monkeypatch.setattr(runner, "ModelClient", model_client)
    monkeypatch.setattr(runner, "ClaudeCodeProvider", object)

    json_path, markdown_path = await run_calibration(
        corpus=corpus,
        lineups_path=lineups_path,
        out=tmp_path / "out",
    )

    report = CalibrationReport.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert len(report.rows) == 2
    for row, expected in zip(report.rows, lineups, strict=True):
        assert row.reader_primary == expected["reader_primary"]
        assert row.reader_escalate == expected["reader_escalate"]
        assert row.synth_model == expected["synth_model"]
        assert set(row.reader_scores) == set(READER_RUBRICS)
        assert set(row.synth_scores) == set(SYNTH_RUBRICS)
        assert row.per_category["single_fact"].n == 1
        assert row.per_category["single_fact"].directional_only is True

    assert ("haiku", "reader-a") in model_calls
    assert ("haiku", "reader-c") in model_calls
    assert ("sonnet", "synth-a") in model_calls
    assert ("sonnet", "synth-b") in model_calls
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Categories with N<10 are directional only" in markdown
    assert "N=1, directional" in markdown


def _write_tiny_corpus(path: Path) -> Path:
    page_text = "Northbridge Library closes at 6:00 p.m. on winter Fridays."
    page_sha = hashlib.sha256(page_text.encode("utf-8")).hexdigest()
    (path / "pages").mkdir(parents=True)
    (path / "queries").mkdir(parents=True)
    (path / "pages" / "library.json").write_text(
        json.dumps(
            {
                "id": "library",
                "url": "https://authored.example/webtool/library",
                "text": page_text,
                "sha256": page_sha,
                "source": "authored",
            }
        ),
        encoding="utf-8",
    )
    (path / "queries" / "library.json").write_text(
        json.dumps(
            {
                "id": "library",
                "query": "When does Northbridge Library close on Fridays in winter?",
                "category": "single_fact",
                "behavior": "answer",
                "expected_answer": "6:00 p.m.",
                "expected_citations": ["https://authored.example/webtool/library"],
                "pages": [{"fixture_id": "library", "sha256": page_sha}],
            }
        ),
        encoding="utf-8",
    )
    return path


def _response_text(messages: Sequence[Message], model_default: str) -> str:
    prompt = "\n".join(message.content for message in messages)
    if model_default == "haiku":
        return json.dumps(
            {
                "relevant": True,
                "extract": "Northbridge Library closes at 6:00 p.m. on winter Fridays.",
                "confidence": "high",
            }
        )
    if model_default == "sonnet" and "Score the " not in prompt:
        match = re.search(r"EXTRACT\[1\] url=([^\n]+)", prompt)
        cited_url = (
            match.group(1) if match is not None else "https://authored.example/webtool/library"
        )
        return json.dumps(
            {
                "answer": "Northbridge Library closes at 6:00 p.m.",
                "cited_urls": [cited_url],
            }
        )
    if "Score the reader stage" in prompt:
        return _scores(READER_RUBRICS)
    return _scores(SYNTH_RUBRICS)


def _scores(rubrics: Sequence[str]) -> str:
    return json.dumps(
        {
            "scores": [
                {
                    "rubric": rubric,
                    "score": 1.0,
                    "passed": True,
                    "rationale": "stubbed",
                }
                for rubric in rubrics
            ]
        }
    )

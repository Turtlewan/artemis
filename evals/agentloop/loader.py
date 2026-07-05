"""Load and verify the frozen agent-loop evaluation corpus."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
from typing import Any, cast, get_args

from pydantic import ValidationError

from .schema import CaseKind, LoopCase

_CASE_KINDS = cast("tuple[str, ...]", get_args(CaseKind))


def load_cases(path: Path) -> list[LoopCase]:
    """Parse case JSON files from ``cases/<kind>/*.json`` below ``path``."""
    root = path / "cases" if (path / "cases").is_dir() else path
    cases: list[LoopCase] = []
    for kind in _CASE_KINDS:
        for case_path in sorted((root / kind).glob("*.json")):
            cases.append(_load_case_file(case_path, expected_kind=kind))
    verify_integrity(cases)
    return cases


def verify_integrity(cases: Sequence[LoopCase]) -> None:
    """Raise ValueError if any record sanitized text mismatches its stored SHA-256."""
    for case in cases:
        for record in case.records:
            actual = hashlib.sha256(record.sanitized_text.encode("utf-8")).hexdigest()
            if actual != record.sha256:
                raise ValueError(
                    f"case {case.id!r} record {record.key!r} sha256 mismatch: "
                    f"expected {record.sha256}, got {actual}"
                )


def _load_case_file(case_path: Path, *, expected_kind: str) -> LoopCase:
    try:
        raw = json.loads(case_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{case_path}: malformed JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{case_path}: case file must contain a JSON object")

    _validate_required_fields(case_path, raw)
    try:
        case = LoopCase.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"{case_path}: malformed case: {exc}") from exc
    if case.kind != expected_kind:
        raise ValueError(
            f"{case_path}: kind {case.kind!r} does not match directory {expected_kind!r}"
        )
    return case


def _validate_required_fields(case_path: Path, raw: dict[str, Any]) -> None:
    missing = [field for field in ("id", "kind", "request") if field not in raw]
    if missing:
        raise ValueError(f"{case_path}: missing required field {missing[0]!r}")

    kind = raw["kind"]
    if kind in {"driver_golden", "escalation"}:
        _require(case_path, raw, "expected_sequence")
        _require(case_path, raw, "expected_answer_contains")
    elif kind == "injection":
        _require(case_path, raw, "expected_sequence")
        _require(case_path, raw, "injected_instruction")
        _require(case_path, raw, "steer_target")
        _require(case_path, raw, "must_not")
    elif kind == "judge_calibration":
        _require(case_path, raw, "judge_evidence")
        _require(case_path, raw, "judge_answer")
        _require(case_path, raw, "human_label_passed")
    else:
        raise ValueError(f"{case_path}: unknown kind {kind!r}")


def _require(case_path: Path, raw: dict[str, Any], field: str) -> None:
    if field not in raw:
        raise ValueError(f"{case_path}: missing required field {field!r}")

"""Model line-up configuration for web-tool calibration sweeps."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

JUDGE_MODEL_ID = "opus"


class Lineup(BaseModel):
    """Candidate reader and synthesizer model assignment."""

    model_config = ConfigDict(frozen=True)

    label: str
    reader_primary: str
    reader_escalate: str
    synth_model: str | None


def load_lineups(path: Path) -> list[Lineup]:
    """Load candidate line-ups and reject any candidate using the judge model."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        lineups = [Lineup.model_validate(item) for item in raw]
    except ValidationError:
        raise
    except Exception as exc:
        raise ValueError(f"failed to load line-ups from {path}: {exc}") from exc

    for lineup in lineups:
        _reject_judge_collision(lineup)
    return lineups


def _reject_judge_collision(lineup: Lineup) -> None:
    collisions = [
        field
        for field, model_id in (
            ("reader_primary", lineup.reader_primary),
            ("reader_escalate", lineup.reader_escalate),
            ("synth_model", lineup.synth_model),
        )
        if model_id == JUDGE_MODEL_ID
    ]
    if collisions:
        fields = ", ".join(collisions)
        raise ValueError(
            f"line-up {lineup.label!r} uses judge model {JUDGE_MODEL_ID!r} as {fields}; "
            "candidate models must not collide with the judge"
        )

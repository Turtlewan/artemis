"""Tests for eval tooling."""

from __future__ import annotations

import sys
from pathlib import Path

_EVALS_ROOT = Path(__file__).resolve().parents[2] / "evals"
sys.path.insert(0, str(_EVALS_ROOT))

"""Owner-editable runtime policy configuration for Artemis.

``policy.json`` is a per-slot override file for tunables: lists, thresholds,
schedules, and other values an owner can reasonably edit without a rebuild.
Defaults live in these frozen Pydantic models, so a missing or partial file
still produces a complete typed config. Structural constants stay in code.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from artemis import paths
from artemis.config import Settings, get_settings

_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")


def _validate_hhmm(value: str) -> str:
    """Validate a clock time in strict ``HH:MM`` 24-hour form."""
    if not _HHMM_RE.fullmatch(value):
        raise ValueError("time must use HH:MM format")
    hour_text, minute_text = value.split(":")
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        raise ValueError("time must be in the range 00:00 through 23:59")
    return value


def _validate_weekday(value: int) -> int:
    """Validate a weekday number where Monday is 0 and Sunday is 6."""
    if value not in range(7):
        raise ValueError("weekday must be in the range 0 through 6")
    return value


class GmailConfig(BaseModel):
    """Gmail urgency-widen tunables for VIP senders, keywords, and bank excludes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vip_senders: tuple[str, ...] = Field(
        default=("ashley", "debby"),
        description="M8-b2 D3 static VIP sender names, unioned with memory-derived VIPs at runtime.",
    )
    urgency_keywords: tuple[str, ...] = Field(
        default=(
            "legal",
            "fraud",
            "unauthorized",
            "payment failed",
            "payment warning",
            "overdue",
            "suspended",
            "deadline",
        ),
        description="M8-b2 D1 topic keywords that OR into urgency admission.",
    )
    urgency_sender_exclude: tuple[str, ...] = Field(
        default=("uob.com.sg", "scb.com", "standardchartered.com", "dbs.com", "dbs.com.sg"),
        description="M8-b2 D2 bank sender domains excluded from urgency widening.",
    )


class CalendarConfig(BaseModel):
    """Calendar planning tunables for working days, focus windows, and free-gap hooks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    working_days: tuple[int, ...] = Field(
        default=(0, 1, 2, 3, 4),
        description="X1 working weekdays, where Monday is 0 and Sunday is 6.",
    )
    preferred_focus_window: tuple[str, str] = Field(
        default=("09:00", "12:00"),
        description="X2 preferred focus window, with start before end.",
    )
    free_gap_hook_time: str = Field(
        default="08:30",
        description="C6 once-daily morning free-gap proposal hook time.",
    )

    @field_validator("working_days")
    @classmethod
    def _validate_working_days(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        for day in value:
            _validate_weekday(day)
        return value

    @field_validator("free_gap_hook_time")
    @classmethod
    def _validate_free_gap_hook_time(cls, value: str) -> str:
        return _validate_hhmm(value)

    @model_validator(mode="after")
    def _validate_preferred_focus_window(self) -> CalendarConfig:
        start, end = self.preferred_focus_window
        _validate_hhmm(start)
        _validate_hhmm(end)
        if start >= end:
            raise ValueError("preferred_focus_window start must be before end")
        return self


class TasksConfig(BaseModel):
    """Task rhythm tunables for wake-trigger fallbacks and review day gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    morning_digest_fallback_time: str = Field(
        default="08:00",
        description="T1 fixed fallback time when no morning wake is detected.",
    )
    weekend_review_day: int = Field(
        default=5,
        description="T1 weekend review weekday gate, where Saturday is 5.",
    )
    week_ahead_time: str = Field(
        default="19:00",
        description="T1 fixed clock time for the week-ahead review.",
    )
    week_ahead_day: int = Field(
        default=6,
        description="T1 weekday gate for the week-ahead review, where Sunday is 6.",
    )

    @field_validator("morning_digest_fallback_time", "week_ahead_time")
    @classmethod
    def _validate_time(cls, value: str) -> str:
        return _validate_hhmm(value)

    @field_validator("weekend_review_day", "week_ahead_day")
    @classmethod
    def _validate_day(cls, value: int) -> int:
        return _validate_weekday(value)


class FinanceConfig(BaseModel):
    """Finance tunables for extraction allowlists, reconciliation, and spend outliers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bank_sender_allowlist: tuple[str, ...] = Field(
        default=("uob.com.sg", "scb.com", "standardchartered.com", "dbs.com", "dbs.com.sg"),
        description="F-D4 sender domains allowed for financial email extraction.",
    )
    recurring_min_occurrences: int = Field(
        default=2,
        description="F-D8 minimum occurrence count before suggesting a recurring transaction.",
    )
    reconcile_date_window_days: int = Field(
        default=1,
        description="F-D6 plus-or-minus day window for transaction reconciliation.",
    )
    reconcile_amount_exact: bool = Field(
        default=True,
        description="F-D6 exact-amount match requirement for reconciliation.",
    )
    unusual_spend_sigma: float = Field(
        default=2.0,
        description="F-D9 outlier threshold over merchant or category history.",
    )

    @field_validator("recurring_min_occurrences")
    @classmethod
    def _validate_recurring_min_occurrences(cls, value: int) -> int:
        if value < 1:
            raise ValueError("recurring_min_occurrences must be at least 1")
        return value

    @field_validator("reconcile_date_window_days")
    @classmethod
    def _validate_reconcile_date_window_days(cls, value: int) -> int:
        if value < 0:
            raise ValueError("reconcile_date_window_days must be at least 0")
        return value

    @field_validator("unusual_spend_sigma")
    @classmethod
    def _validate_unusual_spend_sigma(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("unusual_spend_sigma must be greater than 0")
        return value


class ReactionConfig(BaseModel):
    """Reaction tunables for fraud confirmation, reconciliation, and travel buffers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fraud_confirm_amount_sgd: float = Field(
        default=500.0,
        description="I-3 SGD amount threshold for fraud confirmation.",
    )
    fraud_confirm_window_days: int = Field(
        default=7,
        description="I-3 plus-or-minus day window for fraud confirmation.",
    )
    reconciler_nightly_time: str = Field(
        default="03:00",
        description="I-7 nightly link-integrity reconciliation sweep time.",
    )
    maps_intl_buffer_minutes: int = Field(
        default=180,
        description="I-3/C3 fallback airport buffer for international trips.",
    )
    maps_domestic_buffer_minutes: int = Field(
        default=90,
        description="I-3/C3 fallback airport buffer for domestic trips.",
    )

    @field_validator("reconciler_nightly_time")
    @classmethod
    def _validate_reconciler_nightly_time(cls, value: str) -> str:
        return _validate_hhmm(value)

    @field_validator("fraud_confirm_amount_sgd")
    @classmethod
    def _validate_fraud_confirm_amount_sgd(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("fraud_confirm_amount_sgd must be greater than 0")
        return value

    @field_validator("fraud_confirm_window_days")
    @classmethod
    def _validate_fraud_confirm_window_days(cls, value: int) -> int:
        if value < 0:
            raise ValueError("fraud_confirm_window_days must be at least 0")
        return value

    @field_validator("maps_intl_buffer_minutes", "maps_domestic_buffer_minutes")
    @classmethod
    def _validate_buffer_minutes(cls, value: int) -> int:
        if value < 0:
            raise ValueError("buffer minutes must be at least 0")
        return value


class RuntimeConfig(BaseModel):
    """Aggregate owner policy config for all runtime-tunable cluster surfaces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gmail: GmailConfig = Field(
        default_factory=GmailConfig,
        description="Gmail urgency and sender-policy tunables.",
    )
    calendar: CalendarConfig = Field(
        default_factory=CalendarConfig,
        description="Calendar scheduling and focus-window tunables.",
    )
    tasks: TasksConfig = Field(
        default_factory=TasksConfig,
        description="Task digest and review cadence tunables.",
    )
    finance: FinanceConfig = Field(
        default_factory=FinanceConfig,
        description="Finance extraction, reconciliation, and outlier tunables.",
    )
    reaction: ReactionConfig = Field(
        default_factory=ReactionConfig,
        description="Reaction fraud, reconciler, and travel-buffer tunables.",
    )


def runtime_config_path(settings: Settings) -> Path:
    """The owner-editable policy file: ``<slot_root>/policy.json``."""
    return paths.slot_root(settings) / "policy.json"


def load_runtime_config(path: Path | None = None) -> RuntimeConfig:
    """Load and validate ``policy.json``.

    Missing file returns all defaults. Partial files merge through model field
    defaults. Malformed JSON and validation failures propagate loudly.
    """
    if path is None:
        path = runtime_config_path(get_settings())
    if not path.exists():
        return RuntimeConfig()
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("policy.json must be a JSON object")
    return RuntimeConfig.model_validate(raw)


@lru_cache(maxsize=1)
def get_runtime_config() -> RuntimeConfig:
    """Return the cached runtime policy config for this process."""
    return load_runtime_config()


def reload_runtime_config() -> RuntimeConfig:
    """Clear the cache and reload after the owner settings UI writes ``policy.json``."""
    get_runtime_config.cache_clear()
    return get_runtime_config()

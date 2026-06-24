from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import artemis.runtime_config as runtime_config_module
from artemis.config import Settings
from artemis.runtime_config import (
    GmailConfig,
    RuntimeConfig,
    get_runtime_config,
    load_runtime_config,
    reload_runtime_config,
    runtime_config_path,
)


def _write_policy(path: Path, policy: object) -> None:
    path.write_text(json.dumps(policy), encoding="utf-8")


def test_load_runtime_config_returns_defaults_when_file_absent(tmp_path: Path) -> None:
    cfg = load_runtime_config(tmp_path / "absent.json")

    assert cfg == RuntimeConfig()
    assert cfg.gmail.vip_senders == ("ashley", "debby")


def test_load_runtime_config_full_override_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    _write_policy(
        path,
        {
            "finance": {"recurring_min_occurrences": 3},
            "gmail": {"vip_senders": ["boss"]},
        },
    )

    cfg = load_runtime_config(path)

    assert cfg.finance.recurring_min_occurrences == 3
    assert cfg.gmail.vip_senders == ("boss",)
    assert cfg.finance.reconcile_date_window_days == 1
    assert cfg.calendar == RuntimeConfig().calendar


def test_load_runtime_config_partial_sub_model_merge(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    _write_policy(path, {"finance": {"recurring_min_occurrences": 3}})

    cfg = load_runtime_config(path)

    assert cfg.finance.recurring_min_occurrences == 3
    assert cfg.finance.reconcile_date_window_days == 1
    assert cfg.gmail == GmailConfig()


def test_load_runtime_config_rejects_bad_time(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    _write_policy(path, {"calendar": {"free_gap_hook_time": "25:99"}})

    with pytest.raises(ValidationError):
        load_runtime_config(path)


def test_load_runtime_config_rejects_bad_weekday(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    _write_policy(path, {"tasks": {"weekend_review_day": 9}})

    with pytest.raises(ValidationError):
        load_runtime_config(path)


def test_load_runtime_config_rejects_focus_window_order(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    _write_policy(path, {"calendar": {"preferred_focus_window": ["12:00", "09:00"]}})

    with pytest.raises(ValidationError):
        load_runtime_config(path)


def test_load_runtime_config_rejects_unknown_key(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    _write_policy(path, {"gmail": {"nope": 1}})

    with pytest.raises(ValidationError):
        load_runtime_config(path)


def test_load_runtime_config_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_runtime_config(path)


def test_get_runtime_config_cache_and_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_root=tmp_path, slot="dev")
    policy_path = runtime_config_path(settings)
    policy_path.parent.mkdir(parents=True)
    _write_policy(policy_path, {"finance": {"recurring_min_occurrences": 3}})
    monkeypatch.setattr(runtime_config_module, "get_settings", lambda: settings)
    get_runtime_config.cache_clear()

    first = get_runtime_config()
    second = get_runtime_config()

    assert first is second
    assert first.finance.recurring_min_occurrences == 3

    _write_policy(policy_path, {"finance": {"recurring_min_occurrences": 4}})
    reloaded = reload_runtime_config()

    assert reloaded is not first
    assert reloaded.finance.recurring_min_occurrences == 4
    get_runtime_config.cache_clear()


def test_example_policy_file_is_defaults() -> None:
    raw: object = json.loads(Path("config/policy.example.json").read_text(encoding="utf-8"))

    assert RuntimeConfig.model_validate(raw) == RuntimeConfig()

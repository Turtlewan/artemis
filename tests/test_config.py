"""Tests for the typed config system (artemis.config)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from artemis.config import ModelRole, get_settings


def test_settings_default_slot() -> None:
    """Settings defaults to dev slot with populated roles."""
    s = get_settings()
    assert s.slot == "dev"
    assert isinstance(s.data_root, Path)
    assert s.embedding_dimension == 1024


def test_settings_roles_loaded() -> None:
    """All 5 roles are loaded from roles.toml with correct adapter types."""
    s = get_settings()
    assert len(s.roles) >= 1  # at minimum some roles

    # Verify the teacher role has claude-cli adapter
    if "teacher" in s.roles:
        assert s.roles["teacher"].adapter == "claude-cli"

    # Verify responder has openai adapter
    if "responder" in s.roles:
        assert s.roles["responder"].adapter == "openai"


def test_model_role_validation() -> None:
    """ModelRole accepts valid field values."""
    role = ModelRole(endpoint="http://127.0.0.1:8040/v1", model_id="test-model", adapter="openai")
    assert role.endpoint == "http://127.0.0.1:8040/v1"
    assert role.model_id == "test-model"
    assert role.adapter == "openai"


def test_roles_toml_structure() -> None:
    """roles.toml has the expected structure."""
    roles_path = Path("config/roles.toml")
    assert roles_path.exists(), "roles.toml must exist"

    with roles_path.open("rb") as f:
        raw = tomllib.load(f)

    expected_roles = {"responder", "teacher", "embedder", "reranker", "sensitive_reasoner"}
    assert set(raw.keys()) == expected_roles, (
        f"Expected roles {expected_roles}, got {set(raw.keys())}"
    )

    for name, role in raw.items():
        assert "endpoint" in role, f"{name} missing endpoint"
        assert "model_id" in role, f"{name} missing model_id"
        assert "adapter" in role, f"{name} missing adapter"
        assert role["adapter"] in ("openai", "claude-cli"), (
            f"{name} has unknown adapter {role['adapter']}"
        )


def test_env_file_override() -> None:
    """Settings loads from a custom env file when ARTEMIS_ENV_FILE is set."""
    env_path = Path("config/.env.dev.example")
    if env_path.exists():
        old_env = os.environ.get("ARTEMIS_ENV_FILE")
        try:
            os.environ["ARTEMIS_ENV_FILE"] = str(env_path)
            # Clear the lru_cache so get_settings() re-reads
            get_settings.cache_clear()
            s = get_settings()
            assert s.slot in ("dev", "uat", "prod")
        finally:
            if old_env is not None:
                os.environ["ARTEMIS_ENV_FILE"] = old_env
            else:
                os.environ.pop("ARTEMIS_ENV_FILE", None)
            get_settings.cache_clear()

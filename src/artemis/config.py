"""Typed configuration system for Artemis.

Uses pydantic-settings with slot-based environment file selection.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelRole(BaseModel):
    """A logical model-port role mapping to a physical endpoint."""

    endpoint: str
    model_id: str
    adapter: Literal["openai", "claude-cli", "codex"]


class Settings(BaseSettings):
    """Per-slot application settings, populated from env + env file.

    Env prefix: ARTEMIS_
    The env file path can be overridden via the ARTEMIS_ENV_FILE env var
    (passed as ``_env_file`` to ``Settings()`` at runtime).
    """

    model_config = SettingsConfigDict(
        env_prefix="ARTEMIS_",
        env_file="config/.env.dev",
        env_file_encoding="utf-8",
    )

    # Slot identity
    slot: Literal["dev", "uat", "prod"] = "dev"

    # Data root (outside the repo)
    data_root: Path = Path("/opt/artemis")

    # Service ports
    brain_port: int = Field(default=8030, ge=1024, le=65535)
    mlx_port: int = Field(default=8040, ge=1024, le=65535)
    ntfy_port: int = Field(default=8050, ge=1024, le=65535)
    audio_sidecar_port: int = Field(default=8060, ge=1024, le=65535)

    # Worktree root (the slot's own git worktree path)
    worktree_root: Path = Path(".")

    # Roles file path (default: config/roles.toml relative to project root)
    roles_file: Path = Field(default=Path("config/roles.toml"), exclude=True)

    # Embedding model dimension (Qwen3-Embedding-0.6B → 1024)
    embedding_dimension: int = Field(default=1024, ge=128, le=4096)

    # Privacy kill-switch: False = force ALL reasoning local (no cloud routing)
    cloud_reasoning_enabled: bool = True

    # Codex CLI reasoning engine (ChatGPT subscription auth managed by codex login).
    codex_binary: str = "codex"
    codex_model: str = "gpt-5.5"
    codex_fallback_role: str = "sensitive_reasoner"

    # Optional API key for authed OpenAI-compatible endpoints (dev: DeepSeek/OpenAI
    # cloud). Local MLX/Ollama servers need none. Sent as `Authorization: Bearer`.
    # Secret: read from ARTEMIS_MODEL_API_KEY, excluded from serialisation.
    model_api_key: str | None = Field(default=None, exclude=True)

    # Per-role model-port map, populated by a validator
    roles: dict[str, ModelRole] = Field(default_factory=dict, exclude=True)

    @field_validator("roles", mode="before")
    @classmethod
    def _load_roles(cls, _v: object, info: object) -> dict[str, ModelRole]:
        """Load roles from the TOML roles file.

        Runs after other fields are set so we can resolve the roles_file path.
        """
        # Access the field values via info.data (pydantic v2 validation context)
        if hasattr(info, "data"):
            data = info.data
        else:
            data = {}

        roles_path = data.get("roles_file", Path("config/roles.toml"))
        if isinstance(roles_path, str):
            roles_path = Path(roles_path)

        if not roles_path.exists():
            return {}

        with roles_path.open("rb") as f:
            raw = tomllib.load(f)

        roles: dict[str, ModelRole] = {}
        for key, value in raw.items():
            roles[key] = ModelRole(**value)
        return roles


@lru_cache
def get_settings() -> Settings:
    """Return the cached singleton Settings instance.

    ARTEMIS_ENV_FILE env var selects which ``.env`` file to load.
    Falls back to ``config/.env.dev`` if not set.
    """
    env_file = os.environ.get("ARTEMIS_ENV_FILE")
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()

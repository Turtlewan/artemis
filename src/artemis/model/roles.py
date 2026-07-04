"""Model-role registry: runtime code requests a role; config maps role to provider/model.

ADR-049. Roles in code, models in config. Safety posture rides the role: reader is no-tools
and bindable only to providers with a verified no-tools invocation path; extractor and judge force
temperature 0; judge binding must differ from loop_driver. Resolution reads the current binding on
every for_role() call, so an owner edit takes effect without a restart. The load path fails closed:
malformed or invariant-violating persisted entries are dropped and the role falls back to its
default, so for_role never raises because of persisted-file content.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from artemis.model.anthropic_provider import AnthropicAPIProvider
from artemis.model.claude_code_provider import ClaudeCodeProvider
from artemis.model.client import ModelClient
from artemis.model.codex_provider import CodexProvider, RawProvider
from artemis.model.meter import ModelMeter, MeteredPort
from artemis.model.ollama_provider import OllamaProvider
from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse

ROLES: tuple[str, ...] = (
    "loop_driver",
    "selector",
    "extractor",
    "phraser",
    "judge",
    "reader",
    "synth",
    "memory",
    "forge_author",
)
PROVIDERS: tuple[str, ...] = ("claude_code", "codex", "anthropic_api", "ollama", "router")
_ROUTER_ROLES: frozenset[str] = frozenset({"synth", "forge_author"})

_FORCE_TEMP_ZERO: frozenset[str] = frozenset({"extractor", "judge"})
_NO_TOOLS: frozenset[str] = frozenset({"reader"})
_NO_TOOLS_PROVIDERS: frozenset[str] = frozenset({"claude_code", "ollama"})

_log = logging.getLogger(__name__)


class RoleRegistryError(ValueError):
    """Raised when a proposed binding violates a role invariant."""


@dataclass(frozen=True)
class RoleBinding:
    provider: str
    model: str


@dataclass(frozen=True)
class RoleConstraints:
    """Fixed, non-editable posture a swap cannot drop."""

    no_tools: bool
    temperature: float | None


DropReason = Literal[
    "malformed_entry",
    "unknown_provider",
    "no_tools_ineligible",
    "router_restricted",
    "judge_conflict",
]


@dataclass(frozen=True)
class DroppedOverride:
    """A persisted override the fail-closed load path discarded, with a panel-surfaceable reason.

    role is ALWAYS a member of ROLES (non-ROLES file keys are never emitted); reason is a static
    enum value -- tampered file content can never reach the API response through this type.
    """

    role: str
    reason: DropReason


def constraints_for(role: str) -> RoleConstraints:
    return RoleConstraints(
        no_tools=role in _NO_TOOLS,
        temperature=0.0 if role in _FORCE_TEMP_ZERO else None,
    )


_DEFAULTS: dict[str, RoleBinding] = {
    "loop_driver": RoleBinding("claude_code", "haiku"),
    "selector": RoleBinding("claude_code", "haiku"),
    "extractor": RoleBinding("claude_code", "haiku"),
    "phraser": RoleBinding("claude_code", "haiku"),
    "reader": RoleBinding("claude_code", "haiku"),
    "synth": RoleBinding("router", ""),
    "judge": RoleBinding("claude_code", "sonnet"),
    "memory": RoleBinding("claude_code", "haiku"),
    "forge_author": RoleBinding("router", ""),
}


class _RoleConstrainedPort:
    """Wrap a ModelPort so a role's fixed temperature cannot be dropped by a binding swap."""

    def __init__(self, inner: ModelPort, *, force_temperature: float | None) -> None:
        self._inner = inner
        self._force_temperature = force_temperature

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        temp = self._force_temperature if self._force_temperature is not None else temperature
        return await self._inner.complete(
            messages=messages,
            model=model,
            response_schema=response_schema,
            temperature=temp,
            max_tokens=max_tokens,
        )


ProviderFactory = Mapping[str, Callable[[], RawProvider]]


class ModelRoleRegistry:
    """Persisted role-to-binding map with call-time resolution and invariant validation."""

    def __init__(
        self,
        path: Path,
        *,
        router_factory: Callable[[], ModelPort],
        anthropic_api_key: str | None = None,
        provider_factory: ProviderFactory | None = None,
        meter: ModelMeter | None = None,
    ) -> None:
        self._path = path
        self._router_factory = router_factory
        self._meter = meter
        self._provider_factory: ProviderFactory = provider_factory or {
            "claude_code": lambda: ClaudeCodeProvider(),
            "codex": lambda: CodexProvider(),
            "anthropic_api": lambda: AnthropicAPIProvider(api_key=anthropic_api_key),
            "ollama": lambda: OllamaProvider(),
        }

    def bindings(self) -> dict[str, RoleBinding]:
        """Defaults merged with sanitized persisted overrides, freshly read each time."""
        merged = dict(_DEFAULTS)
        merged.update(self._sanitized_overrides())
        if merged["judge"] == merged["loop_driver"]:
            _log.warning("model_roles: dropping judge override (equals loop_driver)")
            merged["judge"] = _DEFAULTS["judge"]
            if merged["judge"] == merged["loop_driver"]:
                _log.warning("model_roles: dropping loop_driver override (judge collision)")
                merged["loop_driver"] = _DEFAULTS["loop_driver"]
        return merged

    def get(self, role: str) -> RoleBinding:
        if role not in ROLES:
            raise RoleRegistryError(f"unknown role: {role!r}")
        return self.bindings()[role]

    def constraints(self, role: str) -> RoleConstraints:
        if role not in ROLES:
            raise RoleRegistryError(f"unknown role: {role!r}")
        return constraints_for(role)

    def put(self, role: str, binding: RoleBinding) -> None:
        self._validate(role, binding)
        overrides = {
            r: {"provider": b.provider, "model": b.model}
            for r, b in self._sanitized_overrides().items()
        }
        overrides[role] = {"provider": binding.provider, "model": binding.model}
        self._write_overrides(overrides)

    def _validate_entry(self, role: str, binding: RoleBinding) -> None:
        if role not in ROLES:
            raise RoleRegistryError(f"unknown role: {role!r}")
        if binding.provider not in PROVIDERS:
            raise RoleRegistryError(f"unknown provider: {binding.provider!r}")
        if binding.provider == "router" and role not in _ROUTER_ROLES:
            raise RoleRegistryError("provider 'router' is only valid for synth / forge_author")
        if constraints_for(role).no_tools and binding.provider not in _NO_TOOLS_PROVIDERS:
            raise RoleRegistryError(
                f"role {role!r} requires a no-tools provider "
                f"({sorted(_NO_TOOLS_PROVIDERS)}); {binding.provider!r} has no verified "
                "no-tools invocation path"
            )
        if binding.provider != "router" and not binding.model.strip():
            raise RoleRegistryError("model must be non-empty for a non-router provider")

    def _validate(self, role: str, binding: RoleBinding) -> None:
        self._validate_entry(role, binding)
        proposed = self.bindings()
        proposed[role] = binding
        if proposed["judge"] == proposed["loop_driver"]:
            raise RoleRegistryError("judge binding must differ from loop_driver binding")

    def for_role(self, role: str) -> ModelPort:
        binding = self.get(role)
        if binding.provider == "router":
            port: ModelPort = self._router_factory()
        else:
            factory = self._provider_factory.get(binding.provider)
            if factory is None:
                raise RoleRegistryError(f"no provider factory for {binding.provider!r}")
            client = ModelClient(factory(), model_default=binding.model)
            port = _RoleConstrainedPort(client, force_temperature=constraints_for(role).temperature)
        if self._meter is None:
            return port
        return MeteredPort(port, meter=self._meter, role=role, provider=binding.provider)

    def eligible_providers(self, role: str) -> list[str]:
        """Providers a put(role, ...) would accept."""
        if role not in ROLES:
            raise RoleRegistryError(f"unknown role: {role!r}")
        no_tools = constraints_for(role).no_tools
        out: list[str] = []
        for provider in PROVIDERS:
            if provider == "router":
                if role in _ROUTER_ROLES:
                    out.append(provider)
                continue
            if no_tools and provider not in _NO_TOOLS_PROVIDERS:
                continue
            out.append(provider)
        return out

    def dropped_overrides(self) -> list[DroppedOverride]:
        """Persisted entries the fail-closed load path discarded, with static enum reasons."""
        dropped: list[DroppedOverride] = []
        for role, entry in self._load_raw().items():
            if role not in ROLES:
                continue
            reason = self._classify_drop(role, entry)
            if reason is not None:
                dropped.append(DroppedOverride(role=role, reason=reason))
        sanitized = self._sanitized_overrides()
        merged = dict(_DEFAULTS)
        merged.update(sanitized)
        if "judge" in sanitized and merged["judge"] == merged["loop_driver"]:
            dropped.append(DroppedOverride(role="judge", reason="judge_conflict"))
        return dropped

    def _classify_drop(self, role: str, entry: object) -> DropReason | None:
        """Static drop reason for a raw persisted entry of a known role; None = valid."""
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("provider"), str)
            or not isinstance(entry.get("model"), str)
        ):
            return "malformed_entry"
        provider, model = entry["provider"], entry["model"]
        if provider not in PROVIDERS:
            return "unknown_provider"
        if provider == "router" and role not in _ROUTER_ROLES:
            return "router_restricted"
        if constraints_for(role).no_tools and provider not in _NO_TOOLS_PROVIDERS:
            return "no_tools_ineligible"
        if provider != "router" and not model.strip():
            return "malformed_entry"
        return None

    def _sanitized_overrides(self) -> dict[str, RoleBinding]:
        valid: dict[str, RoleBinding] = {}
        for role, entry in self._load_raw().items():
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("provider"), str)
                or not isinstance(entry.get("model"), str)
            ):
                _log.warning("model_roles: dropping malformed override for %r", role)
                continue
            binding = RoleBinding(provider=entry["provider"], model=entry["model"])
            try:
                self._validate_entry(role, binding)
            except RoleRegistryError as exc:
                _log.warning("model_roles: dropping invalid override for %r (%s)", role, exc)
                continue
            valid[role] = binding
        return valid

    def _load_raw(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            _log.warning("model_roles: persisted file unreadable - falling back to defaults")
            return {}
        if not isinstance(data, dict):
            return {}
        return cast(dict[str, object], data)

    def _write_overrides(self, overrides: dict[str, dict[str, str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".model_roles.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(overrides, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise

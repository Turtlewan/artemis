from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from artemis.model.roles import (
    _DEFAULTS,
    _RoleConstrainedPort,
    ModelRoleRegistry,
    RoleBinding,
    RoleConstraints,
    RoleRegistryError,
)
from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse, Usage


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        schema: dict[str, Any] | None,
    ) -> str:
        del messages, schema
        self.calls.append(model)
        return "{}"


class _RecordingPort:
    def __init__(self) -> None:
        self.temperature: float | None = None

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del messages, response_schema, max_tokens
        self.temperature = temperature
        return ModelResponse(
            text="{}",
            model_id=model or "x",
            structured=None,
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def _registry(path: Path, *, router: ModelPort | None = None) -> ModelRoleRegistry:
    sentinel = router or _RecordingPort()
    return ModelRoleRegistry(path, router_factory=lambda: sentinel)


def test_defaults_no_file(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")

    assert reg.get("selector") == RoleBinding("claude_code", "haiku")
    assert reg.get("loop_driver") == RoleBinding("claude_code", "haiku")
    assert reg.get("synth").provider == "router"
    assert reg.get("forge_author").provider == "router"


@pytest.mark.asyncio
async def test_for_role_drives_model(tmp_path: Path) -> None:
    fake = _FakeProvider()
    reg = ModelRoleRegistry(
        tmp_path / "r.json",
        router_factory=lambda: _RecordingPort(),
        provider_factory={"claude_code": lambda: fake},
    )

    await reg.for_role("selector").complete(messages=[Message(role="user", content="hi")])

    assert fake.calls == ["haiku"]


def test_router_roles_resolve_to_router(tmp_path: Path) -> None:
    sentinel = _RecordingPort()
    reg = _registry(tmp_path / "r.json", router=sentinel)

    assert reg.for_role("synth") is sentinel
    assert reg.for_role("forge_author") is sentinel


@pytest.mark.asyncio
async def test_role_constrained_port_temperature() -> None:
    forced_rec = _RecordingPort()
    forced = _RoleConstrainedPort(forced_rec, force_temperature=0.0)
    await forced.complete(messages=[Message(role="user", content="hi")], temperature=0.9)

    passthrough_rec = _RecordingPort()
    passthrough = _RoleConstrainedPort(passthrough_rec, force_temperature=None)
    await passthrough.complete(messages=[Message(role="user", content="hi")], temperature=0.9)

    assert forced_rec.temperature == 0.0
    assert passthrough_rec.temperature == 0.9


def test_for_role_wires_extractor_constraints(tmp_path: Path) -> None:
    fake = _FakeProvider()
    reg = ModelRoleRegistry(
        tmp_path / "r.json",
        router_factory=lambda: _RecordingPort(),
        provider_factory={"claude_code": lambda: fake},
    )

    assert isinstance(reg.for_role("extractor"), _RoleConstrainedPort)
    assert reg.constraints("extractor") == RoleConstraints(no_tools=False, temperature=0.0)
    assert reg.constraints("reader") == RoleConstraints(no_tools=True, temperature=None)


def test_put_persists_and_resolves_without_restart(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    reg = _registry(path)

    reg.put("loop_driver", RoleBinding("codex", "gpt-5.5"))
    restarted = _registry(path)

    assert reg.get("loop_driver").provider == "codex"
    assert restarted.get("loop_driver").provider == "codex"


def test_invariant_judge_differs_from_loop_driver(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")

    with pytest.raises(RoleRegistryError):
        reg.put("judge", RoleBinding("claude_code", "haiku"))

    reg.put("loop_driver", RoleBinding("codex", "gpt-5.5"))
    with pytest.raises(RoleRegistryError):
        reg.put("judge", RoleBinding("codex", "gpt-5.5"))


def test_invariant_unknown_role_and_provider(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")

    with pytest.raises(RoleRegistryError):
        reg.put("nope", RoleBinding("codex", "x"))
    with pytest.raises(RoleRegistryError):
        reg.put("reader", RoleBinding("bogus", "x"))


def test_invariant_router_only_for_router_roles(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")

    with pytest.raises(RoleRegistryError):
        reg.put("reader", RoleBinding("router", ""))
    reg.put("forge_author", RoleBinding("router", ""))
    reg.put("forge_author", RoleBinding("codex", "gpt-5.5"))

    assert reg.get("forge_author") == RoleBinding("codex", "gpt-5.5")


def test_invariant_no_tools_provider_eligibility(tmp_path: Path) -> None:
    reg = _registry(tmp_path / "r.json")

    with pytest.raises(RoleRegistryError):
        reg.put("reader", RoleBinding("codex", "gpt-5.5"))
    reg.put("reader", RoleBinding("ollama", "qwen3:4b"))
    reg.put("reader", RoleBinding("claude_code", "sonnet"))

    assert reg.get("reader") == RoleBinding("claude_code", "sonnet")


def test_fail_closed_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text("{not json", encoding="utf-8")
    reg = ModelRoleRegistry(
        path,
        router_factory=lambda: _RecordingPort(),
        provider_factory={"claude_code": lambda: _FakeProvider()},
    )

    assert reg.bindings() == _DEFAULTS
    assert isinstance(reg.for_role("selector"), ModelPort)


def test_fail_closed_hand_edited_judge_equals_loop_driver(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(
        json.dumps({"judge": {"provider": "claude_code", "model": "haiku"}}),
        encoding="utf-8",
    )
    reg = _registry(path)

    assert reg.bindings()["judge"] == _DEFAULTS["judge"]


def test_fail_closed_invalid_reader_and_malformed_sibling(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(
        json.dumps(
            {
                "reader": {"provider": "codex", "model": "gpt-5.5"},
                "phraser": "haiku",
                "selector": {"provider": "codex", "model": "gpt-5.5"},
            }
        ),
        encoding="utf-8",
    )
    reg = ModelRoleRegistry(
        path,
        router_factory=lambda: _RecordingPort(),
        provider_factory={
            "claude_code": lambda: _FakeProvider(),
            "codex": lambda: _FakeProvider(),
        },
    )

    assert reg.get("reader") == _DEFAULTS["reader"]
    assert reg.get("phraser") == _DEFAULTS["phraser"]
    assert reg.get("selector") == RoleBinding("codex", "gpt-5.5")
    assert isinstance(reg.for_role("reader"), ModelPort)

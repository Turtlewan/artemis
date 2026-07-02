import pytest
from pydantic import ValidationError

from artemis.types import SkillInputParam, build_invoke_argv


def test_skill_input_param_accepts_supported_types() -> None:
    param = SkillInputParam(name="q", type="string", description="Query")

    assert param.name == "q"
    assert param.type == "string"
    assert param.description == "Query"
    assert param.required is True


def test_skill_input_param_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        SkillInputParam.model_validate({"name": "q", "type": "array", "description": "Query"})


def test_build_invoke_argv_returns_empty_for_parameterless_skill() -> None:
    assert build_invoke_argv([], {}) == []


def test_build_invoke_argv_serializes_args_for_typed_skill() -> None:
    inputs = [SkillInputParam(name="q", type="string", description="Query")]

    assert build_invoke_argv(inputs, {"q": "x"}) == ['{"q":"x"}']


def test_build_invoke_argv_sorts_keys_and_uses_compact_json() -> None:
    inputs = [SkillInputParam(name="enabled", type="boolean", description="Flag")]

    assert build_invoke_argv(inputs, {"z": 2, "a": True}) == ['{"a":true,"z":2}']

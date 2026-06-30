from __future__ import annotations

from copy import deepcopy
from typing import Any

from artemis.model.schema_norm import to_strict_schema


def test_to_strict_schema_requires_all_properties_and_strips_unsupported_keywords() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 20},
            "count": {"type": "integer", "minimum": 0},
            "tags": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string", "pattern": "^[a-z]+$"},
            },
            "nested": {
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}},
                "required": [],
            },
        },
        "required": ["name"],
        "additionalProperties": True,
    }
    original = deepcopy(schema)

    strict = to_strict_schema(schema)

    assert schema == original
    assert strict["additionalProperties"] is False
    assert set(strict["required"]) == {"name", "count", "tags", "nested"}
    assert strict["properties"]["name"]["type"] == ["string", "null"]
    assert strict["properties"]["count"]["type"] == ["integer", "null"]
    assert strict["properties"]["tags"]["type"] == ["array", "null"]
    assert strict["properties"]["tags"]["items"]["type"] == "string"
    nested = strict["properties"]["nested"]
    assert nested["additionalProperties"] is False
    assert nested["required"] == ["enabled"]
    assert nested["properties"]["enabled"]["type"] == ["boolean", "null"]
    assert not _find_stripped_keywords(strict)


def _find_stripped_keywords(value: Any) -> set[str]:
    stripped = {
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "minContains",
        "maxContains",
        "contains",
        "propertyNames",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(key for key in value if key in stripped)
        for child in value.values():
            found.update(_find_stripped_keywords(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_stripped_keywords(child))
    return found

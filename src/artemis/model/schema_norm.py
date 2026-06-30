"""JSON schema normalization for model backends.

Anthropic tool-``input_schema`` conversion is deferred to Slice 1; no Anthropic backend exists yet.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_UNSUPPORTED_KEYWORDS = {
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


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an OpenAI/Codex strict-mode schema without mutating ``schema``."""
    copied = deepcopy(schema)
    normalized = _normalize_node(copied, make_property_nullable=False)
    if isinstance(normalized, dict):
        return normalized
    return {}


def to_ollama_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy for Ollama's lenient ``format`` schema handling."""
    return deepcopy(schema)


def _normalize_node(node: Any, *, make_property_nullable: bool) -> Any:
    if isinstance(node, dict):
        normalized = {
            key: _normalize_node(value, make_property_nullable=False)
            for key, value in node.items()
            if key not in _UNSUPPORTED_KEYWORDS
        }

        if "type" in normalized and make_property_nullable:
            normalized["type"] = _nullable_type(normalized["type"])

        if _is_object_schema(normalized):
            properties = normalized.get("properties")
            if isinstance(properties, dict):
                normalized["properties"] = {
                    key: _normalize_node(value, make_property_nullable=True)
                    for key, value in properties.items()
                }
                normalized["required"] = list(properties.keys())
            normalized["additionalProperties"] = False

        items = normalized.get("items")
        if items is not None:
            normalized["items"] = _normalize_node(items, make_property_nullable=False)

        for combinator in ("anyOf", "oneOf", "allOf"):
            branches = normalized.get(combinator)
            if isinstance(branches, list):
                normalized[combinator] = [
                    _normalize_node(branch, make_property_nullable=False) for branch in branches
                ]

        return normalized

    if isinstance(node, list):
        return [_normalize_node(value, make_property_nullable=False) for value in node]

    return node


def _is_object_schema(schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    return schema_type == "object" or (isinstance(schema_type, list) and "object" in schema_type)


def _nullable_type(schema_type: Any) -> Any:
    if isinstance(schema_type, str):
        if schema_type == "null":
            return schema_type
        return [schema_type, "null"]

    if isinstance(schema_type, list):
        if "null" in schema_type:
            return schema_type
        return [*schema_type, "null"]

    return schema_type

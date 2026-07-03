"""Read and write Agent-Skills SKILL.md files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class SkillFormatError(ValueError):
    """Raised when a SKILL.md file has malformed frontmatter."""


def write_skill_md(
    path: Path,
    *,
    name: str,
    description: str,
    version: int,
    tags: list[str],
    uses: list[str],
    secrets: list[str],
    inputs: list[dict[str, Any]],
    goal: str = "",
    built_at: str | None = None,
    auth_status: str = "not-required",
    oauth_scopes: list[str] | None = None,
    body: str,
) -> None:
    """Write an Agent-Skills format SKILL.md file.

    `inputs` is persisted as frontmatter metadata; legacy SKILL.md files may omit it and readers
    must treat that as an empty list.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name,
        "description": description,
        "version": version,
        "tags": tags,
        "uses": uses,
        "secrets": secrets,
        "inputs": inputs,
        "goal": goal,
        "built_at": built_at,
        "auth_status": auth_status,
        "oauth_scopes": oauth_scopes or [],
    }
    frontmatter = yaml.safe_dump(meta, sort_keys=False)
    path.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")


def read_skill_md(path: Path) -> tuple[dict[str, Any], str]:
    """Read an Agent-Skills format SKILL.md file."""

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SkillFormatError(f"{path} is missing YAML frontmatter")

    parts = text.split("---\n", 2)
    if len(parts) != 3 or parts[0] != "":
        raise SkillFormatError(f"{path} has malformed YAML frontmatter")

    try:
        loaded = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise SkillFormatError(f"{path} has invalid YAML frontmatter") from exc

    if not isinstance(loaded, dict):
        raise SkillFormatError(f"{path} frontmatter must be a mapping")

    body = parts[2]
    if body.startswith("\n"):
        body = body[1:]

    return loaded, body

"""File-backed capability store."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from artemis.capabilities.skill_md import read_skill_md, write_skill_md
from artemis.types import Skill, SkillDraft, SkillInputParam, StagedSkill, validate_egress_domains

_log = logging.getLogger(__name__)


class StagedSkillNotFound(FileNotFoundError):
    """Raised when a staged skill cannot be found."""


class FileCapabilityStore:
    """Capability store backed by staging and library directories.

    `sandbox_policy.json` is the C1 sandbox artifact and the on-disk home for egress policy.
    """

    def __init__(self, root: Path) -> None:
        self._staging = root / "staging"
        self._library = root / "library"
        self._staging.mkdir(parents=True, exist_ok=True)
        self._library.mkdir(parents=True, exist_ok=True)

    async def stage(self, draft: SkillDraft) -> StagedSkill:
        staged_id = f"{slug(draft.name)}-{uuid4().hex[:8]}"
        staged_dir = self._staging / staged_id
        staged_dir.mkdir(parents=True, exist_ok=False)

        write_skill_md(
            staged_dir / "SKILL.md",
            name=draft.name,
            description=draft.description,
            version=0,
            tags=[],
            uses=draft.uses,
            secrets=draft.secrets,
            inputs=[param.model_dump() for param in draft.inputs],
            goal=draft.goal,
            oauth_scopes=list(draft.oauth_scopes),
            body=draft.body,
        )
        if draft.tool_script is not None:
            (staged_dir / "tool.py").write_text(draft.tool_script, encoding="utf-8")
        if draft.tests is not None:
            tests_dir = staged_dir / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_skill.py").write_text(draft.tests, encoding="utf-8")
        policy = {
            "egress_domains": list(draft.egress_domains),
            "memory_mb": 512,
            "cpu_pct": 100,
            "pids_max": 128,
            "timeout_s": 60,
        }
        (staged_dir / "sandbox_policy.json").write_text(
            json.dumps(policy, indent=2), encoding="utf-8"
        )

        return StagedSkill(id=staged_id, draft=draft)

    async def promote(self, staged_id: str) -> Skill:
        staged_dir = self._staging / staged_id
        if not staged_dir.is_dir():
            raise StagedSkillNotFound(staged_id)

        draft = self._read_draft(staged_dir)
        library_dir = self._library / draft.name
        existing = self.get(draft.name)
        version = existing.version + 1 if existing is not None else 1
        built_at = datetime.now(tz=UTC).isoformat()

        if library_dir.exists():
            shutil.rmtree(library_dir)
        library_dir.mkdir(parents=True)

        write_skill_md(
            library_dir / "SKILL.md",
            name=draft.name,
            description=draft.description,
            version=version,
            tags=[],
            uses=draft.uses,
            secrets=draft.secrets,
            inputs=[param.model_dump() for param in draft.inputs],
            goal=draft.goal,
            built_at=built_at,
            auth_status="not-required",
            oauth_scopes=list(draft.oauth_scopes),
            body=draft.body,
        )
        tool_path = staged_dir / "tool.py"
        if tool_path.exists():
            shutil.copy2(tool_path, library_dir / "tool.py")
        tests_dir = staged_dir / "tests"
        if tests_dir.exists():
            shutil.copytree(tests_dir, library_dir / "tests")
        policy_path = staged_dir / "sandbox_policy.json"
        if policy_path.exists():
            shutil.copy2(policy_path, library_dir / "sandbox_policy.json")

        return Skill(
            name=draft.name,
            description=draft.description,
            version=version,
            path=str(library_dir),
            goal=draft.goal,
            built_at=built_at,
            auth_status="not-required",
            oauth_scopes=list(draft.oauth_scopes),
            tags=[],
            uses=draft.uses,
            secrets=draft.secrets,
            inputs=draft.inputs,
            egress_domains=_egress(staged_dir),
        )

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        tags: Sequence[str] | None = None,
    ) -> list[Skill]:
        """Lexical interim retrieval; swap to embedding retrieval behind this signature later."""

        query_tokens = _tokens(query)
        requested_tags = set(tags or [])
        scored: list[tuple[float, Skill]] = []
        for skill_path in self._library.glob("*/SKILL.md"):
            skill = self._read_skill(skill_path)
            if requested_tags and not set(skill.tags).issuperset(requested_tags):
                continue
            score = 0.0
            if query_tokens:
                skill_tokens = _tokens(f"{skill.name} {skill.description}")
                score = len(query_tokens & skill_tokens) / len(query_tokens)
            scored.append((score, skill))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [skill for _, skill in scored[:k]]

    def get(self, name: str) -> Skill | None:
        skill_path = self._library / name / "SKILL.md"
        if not skill_path.exists():
            return None
        return self._read_skill(skill_path)

    def list(self) -> list[Skill]:
        """Every promoted capability in the library, sorted by name."""
        skills = [self._read_skill(path) for path in self._library.glob("*/SKILL.md")]
        return sorted(skills, key=lambda skill: skill.name)

    def staging_dir(self, staged_id: str) -> Path:
        return self._staging / staged_id

    def _read_draft(self, staged_dir: Path) -> SkillDraft:
        meta, body = read_skill_md(staged_dir / "SKILL.md")
        tool_path = staged_dir / "tool.py"
        tests_path = staged_dir / "tests" / "test_skill.py"
        return SkillDraft(
            name=str(meta["name"]),
            description=str(meta["description"]),
            body=body,
            tool_script=tool_path.read_text(encoding="utf-8") if tool_path.exists() else None,
            goal=str(meta.get("goal", "")),
            inputs=[SkillInputParam(**item) for item in meta.get("inputs", [])],
            uses=[str(item) for item in meta.get("uses", [])],
            secrets=[str(item) for item in meta.get("secrets", [])],
            oauth_scopes=[str(item) for item in meta.get("oauth_scopes", [])],
            egress_domains=_egress(staged_dir),
            tests=tests_path.read_text(encoding="utf-8") if tests_path.exists() else None,
        )

    def _read_skill(self, skill_path: Path) -> Skill:
        meta, _ = read_skill_md(skill_path)
        return Skill(
            name=str(meta["name"]),
            description=str(meta["description"]),
            version=int(meta["version"]),
            path=str(skill_path.parent),
            goal=str(meta.get("goal", "")),
            built_at=_optional_str(meta.get("built_at")),
            auth_status=_auth_status(meta.get("auth_status", "not-required")),
            oauth_scopes=[str(item) for item in meta.get("oauth_scopes", [])],
            tags=[str(item) for item in meta.get("tags", [])],
            uses=[str(item) for item in meta.get("uses", [])],
            secrets=[str(item) for item in meta.get("secrets", [])],
            inputs=[SkillInputParam(**item) for item in meta.get("inputs", [])],
            egress_domains=_egress(skill_path.parent),
        )


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _egress(dir_: Path) -> list[str]:
    p = dir_ / "sandbox_policy.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        return validate_egress_domains([str(d) for d in data.get("egress_domains", [])])
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        _log.warning("unusable sandbox_policy.json in %s: %s", dir_, exc)
        return []


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _auth_status(value: object) -> Literal["not-required", "unverified", "verified"]:
    status = str(value)
    if status in {"not-required", "unverified", "verified"}:
        return cast(Literal["not-required", "unverified", "verified"], status)
    return "not-required"

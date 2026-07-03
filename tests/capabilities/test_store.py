from datetime import datetime
from pathlib import Path

import pytest

from artemis.capabilities.skill_md import read_skill_md
from artemis.capabilities.store import FileCapabilityStore
from artemis.types import SkillDraft


def _draft(
    *,
    goal: str = "Check calendar auth.",
    oauth_scopes: list[str] | None = None,
) -> SkillDraft:
    return SkillDraft(
        name="Calendar Sync",
        description="Syncs calendars.",
        body="Use this skill.",
        tool_script=None,
        goal=goal,
        uses=["calendar"],
        secrets=["CALENDAR_TOKEN"],
        oauth_scopes=oauth_scopes or ["calendar.read"],
        tests=None,
    )


@pytest.mark.asyncio
async def test_stage_and_promote_persist_capability_metadata(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    draft = _draft(oauth_scopes=["calendar.read", "calendar.write"])

    staged = await store.stage(draft)
    staged_meta, _ = read_skill_md(tmp_path / "staging" / staged.id / "SKILL.md")
    assert staged_meta["goal"] == "Check calendar auth."
    assert staged_meta["oauth_scopes"] == ["calendar.read", "calendar.write"]
    assert staged_meta["built_at"] is None
    assert staged_meta["auth_status"] == "not-required"

    promoted = await store.promote(staged.id)
    library_path = tmp_path / "library" / "Calendar Sync" / "SKILL.md"
    meta, _ = read_skill_md(library_path)

    assert meta["goal"] == "Check calendar auth."
    assert meta["oauth_scopes"] == ["calendar.read", "calendar.write"]
    assert meta["auth_status"] == "not-required"
    assert isinstance(meta["built_at"], str)
    assert meta["built_at"]
    datetime.fromisoformat(meta["built_at"])
    assert promoted.goal == "Check calendar auth."
    assert promoted.oauth_scopes == ["calendar.read", "calendar.write"]
    assert promoted.auth_status == "not-required"
    assert promoted.built_at == meta["built_at"]

    stored = store.get("Calendar Sync")
    assert stored is not None
    assert stored.goal == "Check calendar auth."
    assert stored.oauth_scopes == ["calendar.read", "calendar.write"]
    assert stored.auth_status == "not-required"
    assert stored.built_at == meta["built_at"]
    assert store.list() == [stored]


def test_legacy_library_skill_without_metadata_reads_defaults(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    library_dir = tmp_path / "library" / "Lookup"
    library_dir.mkdir(parents=True)
    (library_dir / "SKILL.md").write_text(
        "---\n"
        "name: Lookup\n"
        "description: Finds facts.\n"
        "version: 1\n"
        "tags: []\n"
        "uses: []\n"
        "secrets: []\n"
        "inputs: []\n"
        "---\n"
        "Use this skill.\n",
        encoding="utf-8",
    )

    stored = store.get("Lookup")

    assert stored is not None
    assert stored.goal == ""
    assert stored.built_at is None
    assert stored.auth_status == "not-required"
    assert stored.oauth_scopes == []

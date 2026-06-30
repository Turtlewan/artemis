from pathlib import Path

import pytest

from artemis.capabilities.skill_md import SkillFormatError, read_skill_md
from artemis.capabilities.store import FileCapabilityStore
from artemis.ports.capabilities import CapabilityStore
from artemis.types import SkillDraft, StagedSkill


def _draft(
    name: str,
    description: str,
    *,
    body: str = "Use this skill.",
    tool_script: str | None = None,
    uses: list[str] | None = None,
    secrets: list[str] | None = None,
    tests: str | None = None,
) -> SkillDraft:
    return SkillDraft(
        name=name,
        description=description,
        body=body,
        tool_script=tool_script,
        uses=uses or [],
        secrets=secrets or [],
        tests=tests,
    )


def test_file_capability_store_implements_port(tmp_path: Path) -> None:
    assert isinstance(FileCapabilityStore(tmp_path), CapabilityStore)


@pytest.mark.asyncio
async def test_stage_writes_skill_tool_and_tests(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    draft = _draft(
        "Daily Planner",
        "Plans the day.",
        tool_script="def run() -> None:\n    pass\n",
        tests="def test_skill() -> None:\n    assert True\n",
    )

    staged = await store.stage(draft)

    assert isinstance(staged, StagedSkill)
    assert staged.draft == draft
    staged_dir = tmp_path / "staging" / staged.id
    assert (staged_dir / "SKILL.md").exists()
    assert (staged_dir / "tool.py").exists()
    assert (staged_dir / "tests" / "test_skill.py").exists()


@pytest.mark.asyncio
async def test_promote_creates_versioned_library_entry(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    draft = _draft(
        "Daily Planner",
        "Plans the day.",
        uses=["calendar"],
        secrets=["CALENDAR_TOKEN"],
    )

    first = await store.promote((await store.stage(draft)).id)

    skill_path = tmp_path / "library" / "Daily Planner" / "SKILL.md"
    meta, _ = read_skill_md(skill_path)
    assert first.version == 1
    assert meta["version"] == 1
    assert meta["uses"] == ["calendar"]
    assert meta["secrets"] == ["CALENDAR_TOKEN"]

    second = await store.promote((await store.stage(draft)).id)

    assert second.version == 2
    meta, _ = read_skill_md(skill_path)
    assert meta["version"] == 2


@pytest.mark.asyncio
async def test_retrieve_scores_filters_and_caps_results(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    planner = await store.promote(
        (
            await store.stage(
                _draft("Planner", "Builds a calendar agenda for focused work blocks.")
            )
        ).id
    )
    await store.promote(
        (await store.stage(_draft("Chef", "Suggests pantry recipes for dinner."))).id
    )

    results = await store.retrieve("calendar agenda", k=1)
    assert results == [planner]

    tagged_path = tmp_path / "library" / "Planner" / "SKILL.md"
    tagged_path.write_text(
        tagged_path.read_text(encoding="utf-8").replace("tags: []", "tags:\n- planning"),
        encoding="utf-8",
    )
    assert await store.retrieve("calendar", tags=["missing"]) == []
    assert [skill.name for skill in await store.retrieve("calendar", tags=["planning"])] == [
        "Planner"
    ]

    capped = await store.retrieve("", k=1)
    assert len(capped) == 1


@pytest.mark.asyncio
async def test_get_returns_promoted_skill_or_none(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    promoted = await store.promote((await store.stage(_draft("Lookup", "Finds facts."))).id)

    assert store.get("Lookup") == promoted
    assert store.get("Unknown") is None


def test_read_skill_md_raises_for_malformed_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("name: broken\n\nbody", encoding="utf-8")

    with pytest.raises(SkillFormatError):
        read_skill_md(path)

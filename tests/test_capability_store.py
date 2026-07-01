import json
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
    egress_domains: list[str] | None = None,
    tests: str | None = None,
) -> SkillDraft:
    return SkillDraft(
        name=name,
        description=description,
        body=body,
        tool_script=tool_script,
        uses=uses or [],
        secrets=secrets or [],
        egress_domains=egress_domains or [],
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
async def test_stage_writes_sandbox_policy(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    draft = _draft(
        "API Lookup",
        "Looks up facts.",
        egress_domains=["api.example.com"],
        tests="def test_skill() -> None:\n    assert True\n",
    )

    staged = await store.stage(draft)

    policy_path = tmp_path / "staging" / staged.id / "sandbox_policy.json"
    assert json.loads(policy_path.read_text(encoding="utf-8")) == {
        "egress_domains": ["api.example.com"],
        "memory_mb": 512,
        "cpu_pct": 100,
        "pids_max": 128,
        "timeout_s": 60,
    }


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
async def test_promote_round_trips_egress_policy(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    draft = _draft("API Lookup", "Looks up facts.", egress_domains=["api.example.com"])

    promoted = await store.promote((await store.stage(draft)).id)

    policy_path = tmp_path / "library" / "API Lookup" / "sandbox_policy.json"
    assert policy_path.exists()
    assert promoted.egress_domains == ["api.example.com"]
    stored = store.get("API Lookup")
    assert stored is not None
    assert stored.egress_domains == ["api.example.com"]


@pytest.mark.asyncio
async def test_promote_defaults_to_empty_egress_policy(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)

    promoted = await store.promote((await store.stage(_draft("Lookup", "Finds facts."))).id)

    assert promoted.egress_domains == []
    stored = store.get("Lookup")
    assert stored is not None
    assert stored.egress_domains == []


@pytest.mark.asyncio
async def test_corrupt_policy_fails_closed_without_breaking_reads(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    await store.promote((await store.stage(_draft("Lookup", "Finds facts."))).id)
    policy_path = tmp_path / "library" / "Lookup" / "sandbox_policy.json"
    policy_path.write_text("{ not json", encoding="utf-8")

    stored = store.get("Lookup")
    assert stored is not None
    assert stored.egress_domains == []
    assert store.list()
    assert await store.retrieve("facts")


@pytest.mark.asyncio
async def test_tampered_policy_fails_closed_on_read(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    await store.promote(
        (await store.stage(_draft("Lookup", "Finds facts.", egress_domains=["api.example.com"]))).id
    )
    policy_path = tmp_path / "library" / "Lookup" / "sandbox_policy.json"
    policy_path.write_text(json.dumps({"egress_domains": ["*"]}), encoding="utf-8")

    stored = store.get("Lookup")
    assert stored is not None
    assert stored.egress_domains == []


@pytest.mark.parametrize("content", ["[]", '"x"', "42", "null"])
def test_non_dict_policy_fails_closed_on_read(tmp_path: Path, content: str) -> None:
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
        "---\n"
        "Use this skill.\n",
        encoding="utf-8",
    )
    (library_dir / "sandbox_policy.json").write_text(content, encoding="utf-8")

    stored = store.get("Lookup")
    assert stored is not None
    assert stored.egress_domains == []


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


@pytest.mark.asyncio
async def test_list_returns_promoted_skills_sorted_by_name(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)

    assert store.list() == []

    beta = await store.promote((await store.stage(_draft("Beta", "Second skill."))).id)
    alpha = await store.promote((await store.stage(_draft("Alpha", "First skill."))).id)

    assert store.list() == [alpha, beta]


def test_read_skill_md_raises_for_malformed_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("name: broken\n\nbody", encoding="utf-8")

    with pytest.raises(SkillFormatError):
        read_skill_md(path)

from datetime import datetime
from pathlib import Path

import pytest

from artemis.capabilities.skill_md import read_skill_md
from artemis.capabilities.skill_md import write_skill_md
from artemis.capabilities.store import FileCapabilityStore, builtin_capabilities_root
from artemis.types import SkillDraft


def _draft(
    *,
    goal: str = "Check calendar auth.",
    secrets: list[str] | None = None,
    oauth_scopes: list[str] | None = None,
) -> SkillDraft:
    return SkillDraft(
        name="Calendar Sync",
        description="Syncs calendars.",
        body="Use this skill.",
        tool_script=None,
        goal=goal,
        uses=["calendar"],
        secrets=["CALENDAR_TOKEN"] if secrets is None else secrets,
        oauth_scopes=oauth_scopes or ["calendar.read"],
        tests=None,
    )


def _seed_capability(dir_: Path, *, name: str, description: str = "d") -> None:
    dir_.mkdir(parents=True)
    write_skill_md(
        dir_ / "SKILL.md",
        name=name,
        description=description,
        version=1,
        tags=[],
        uses=[],
        secrets=[],
        inputs=[],
        body="Use this skill.\n",
    )
    (dir_ / "sandbox_policy.json").write_text(
        '{"egress_domains":[],"memory_mb":512,"cpu_pct":100,"pids_max":128,"timeout_s":60}',
        encoding="utf-8",
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
    assert meta["auth_status"] == "unverified"
    assert isinstance(meta["built_at"], str)
    assert meta["built_at"]
    datetime.fromisoformat(meta["built_at"])
    assert promoted.goal == "Check calendar auth."
    assert promoted.oauth_scopes == ["calendar.read", "calendar.write"]
    assert promoted.auth_status == "unverified"
    assert promoted.built_at == meta["built_at"]

    stored = store.get("Calendar Sync")
    assert stored is not None
    assert stored.goal == "Check calendar auth."
    assert stored.oauth_scopes == ["calendar.read", "calendar.write"]
    assert stored.auth_status == "unverified"
    assert stored.built_at == meta["built_at"]
    assert store.list() == [stored]


@pytest.mark.asyncio
async def test_promote_without_secrets_marks_auth_not_required(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    staged = await store.stage(_draft(secrets=[]))

    promoted = await store.promote(staged.id)
    meta, _ = read_skill_md(tmp_path / "library" / "Calendar Sync" / "SKILL.md")

    assert meta["auth_status"] == "not-required"
    assert promoted.auth_status == "not-required"
    stored = store.get("Calendar Sync")
    assert stored is not None
    assert stored.auth_status == "not-required"


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


@pytest.mark.asyncio
async def test_mark_auth_verified_flips_unverified_preserving_body_and_version(
    tmp_path: Path,
) -> None:
    store = FileCapabilityStore(tmp_path)
    staged = await store.stage(_draft())
    await store.promote(staged.id)
    skill_path = tmp_path / "library" / "Calendar Sync" / "SKILL.md"
    before_meta, before_body = read_skill_md(skill_path)

    store.mark_auth_verified("Calendar Sync")

    after_meta, after_body = read_skill_md(skill_path)
    assert before_meta["auth_status"] == "unverified"
    assert after_meta["auth_status"] == "verified"
    assert after_meta["version"] == before_meta["version"]
    assert after_body == before_body
    stored = store.get("Calendar Sync")
    assert stored is not None
    assert stored.auth_status == "verified"


@pytest.mark.asyncio
async def test_mark_auth_verified_noops_on_missing_already_verified_and_no_secret(
    tmp_path: Path,
) -> None:
    store = FileCapabilityStore(tmp_path)
    store.mark_auth_verified("Missing")

    staged = await store.stage(_draft())
    await store.promote(staged.id)
    skill_path = tmp_path / "library" / "Calendar Sync" / "SKILL.md"
    store.mark_auth_verified("Calendar Sync")
    verified_meta, verified_body = read_skill_md(skill_path)

    store.mark_auth_verified("Calendar Sync")

    after_meta, after_body = read_skill_md(skill_path)
    assert after_meta == verified_meta
    assert after_body == verified_body

    no_secret_staged = await store.stage(_draft(secrets=[]))
    await store.promote(no_secret_staged.id)
    no_secret_path = tmp_path / "library" / "Calendar Sync" / "SKILL.md"
    no_secret_meta, no_secret_body = read_skill_md(no_secret_path)

    store.mark_auth_verified("Calendar Sync")

    after_no_secret_meta, after_no_secret_body = read_skill_md(no_secret_path)
    assert no_secret_meta["auth_status"] == "not-required"
    assert after_no_secret_meta == no_secret_meta
    assert after_no_secret_body == no_secret_body


def test_get_falls_back_to_builtin(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    _seed_capability(builtin / "foo", name="foo")
    store = FileCapabilityStore(tmp_path / "data", builtin_root=builtin)
    got = store.get("foo")
    assert got is not None and got.name == "foo"


@pytest.mark.asyncio
async def test_builtin_not_in_list_or_retrieve(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    _seed_capability(builtin / "foo", name="foo")
    store = FileCapabilityStore(tmp_path / "data", builtin_root=builtin)
    assert store.list() == []
    assert await store.retrieve("foo") == []


def test_library_wins_over_builtin_on_name_clash(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    _seed_capability(builtin / "foo", name="foo", description="builtin one")
    store = FileCapabilityStore(tmp_path / "data", builtin_root=builtin)
    _seed_capability(store._library / "foo", name="foo", description="library one")
    got = store.get("foo")
    assert got is not None and got.description == "library one"


def test_no_builtin_root_is_fine(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path / "data")
    assert store.get("anything") is None


def test_builtin_capabilities_root_points_at_repo() -> None:
    root = builtin_capabilities_root()
    assert root.name == "builtin" and root.parent.name == "capabilities"

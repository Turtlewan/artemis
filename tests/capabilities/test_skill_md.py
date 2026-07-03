from pathlib import Path

from artemis.capabilities.skill_md import read_skill_md, write_skill_md
from artemis.types import Skill, SkillDraft


def test_skill_metadata_fields_default_on_models() -> None:
    draft = SkillDraft(
        name="Lookup",
        description="Finds facts.",
        body="Use this skill.",
        tool_script=None,
        tests=None,
    )
    skill = Skill(
        name="Lookup",
        description="Finds facts.",
        version=1,
        path="/tmp/lookup",
        tags=[],
        uses=[],
        secrets=[],
    )

    assert draft.goal == ""
    assert draft.oauth_scopes == []
    assert skill.goal == ""
    assert skill.built_at is None
    assert skill.auth_status == "not-required"
    assert skill.oauth_scopes == []


def test_write_skill_md_round_trips_capability_metadata(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"

    write_skill_md(
        path,
        name="Calendar Sync",
        description="Syncs calendars.",
        version=2,
        tags=[],
        uses=["calendar"],
        secrets=["CALENDAR_TOKEN"],
        inputs=[],
        goal="Keep calendars aligned.",
        built_at="2026-07-03T12:00:00+00:00",
        auth_status="verified",
        oauth_scopes=["calendar.read", "calendar.write"],
        body="Use this skill.",
    )

    meta, body = read_skill_md(path)

    assert body == "Use this skill."
    assert meta["goal"] == "Keep calendars aligned."
    assert meta["built_at"] == "2026-07-03T12:00:00+00:00"
    assert meta["auth_status"] == "verified"
    assert meta["oauth_scopes"] == ["calendar.read", "calendar.write"]


def test_missing_capability_metadata_keys_can_apply_defaults(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
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

    meta, _ = read_skill_md(path)

    assert meta.get("goal", "") == ""
    assert meta.get("built_at") is None
    assert meta.get("auth_status", "not-required") == "not-required"
    assert meta.get("oauth_scopes", []) == []

from collections.abc import Sequence
from pathlib import Path

import pytest

from artemis.capabilities.forge import CapabilityForge
from artemis.capabilities.sandbox import SandboxRunner, SubprocessSandbox, VerifyResult
from artemis.capabilities.store import FileCapabilityStore
from artemis.ports.model import ModelPort
from artemis.types import Message, ModelResponse, SkillDraft, Usage


NETWORK_TOOL = "import imaplib\n\n\ndef fetch() -> None:\n    pass\n"


class FakeModel:
    def __init__(self, draft: SkillDraft) -> None:
        self._draft = draft

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        response_schema: dict | None = None,  # type: ignore[type-arg]
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            text="",
            model_id=model or "fake",
            structured=self._draft.model_dump(),
            finish_reason="stop",
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class FakeSandbox:
    def __init__(self, result: VerifyResult) -> None:
        self._result = result
        self.ran = False

    async def run_tests(self, skill_dir: Path) -> VerifyResult:
        self.ran = True
        return self._result


def _draft(
    *,
    tests: str | None = "def test_skill() -> None:\n    assert True\n",
    tool_script: str | None = None,
) -> SkillDraft:
    return SkillDraft(
        name="Echo",
        description="Echoes text.",
        body="Use this skill to echo text.",
        tool_script=tool_script,
        uses=[],
        secrets=[],
        tests=tests,
    )


@pytest.mark.asyncio
async def test_forge_authors_stages_verifies_and_promotes(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft()),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )

    skill = await forge.build("make an echo skill")

    assert skill is not None
    assert store.get("Echo") is not None


@pytest.mark.asyncio
async def test_forge_does_not_promote_on_sandbox_failure(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft()),
        store,
        FakeSandbox(VerifyResult(passed=False, output="failed")),
    )

    skill = await forge.build("make an echo skill")

    assert skill is None
    assert store.get("Echo") is None


@pytest.mark.asyncio
async def test_forge_does_not_stage_untestable_draft(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    sandbox = FakeSandbox(VerifyResult(passed=True, output="ok"))
    forge = CapabilityForge(FakeModel(_draft(tests=None)), store, sandbox)

    skill = await forge.build("make an echo skill")

    assert skill is None
    assert store.get("Echo") is None
    assert sandbox.ran is False
    assert list((tmp_path / "staging").iterdir()) == []


@pytest.mark.asyncio
async def test_forge_does_not_promote_without_confirmation(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft()),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )

    skill = await forge.build("make an echo skill", confirm=lambda _staged, _result: False)

    assert skill is None
    assert store.get("Echo") is None


@pytest.mark.asyncio
async def test_forge_with_real_subprocess_sandbox_promotes(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(FakeModel(_draft()), store, SubprocessSandbox())

    skill = await forge.build("make an echo skill")

    assert skill is not None
    assert store.get("Echo") is not None
    assert isinstance(FakeModel(_draft()), ModelPort)
    assert isinstance(SubprocessSandbox(), SandboxRunner)


@pytest.mark.asyncio
async def test_propose_blocks_network_capability(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft(tool_script=NETWORK_TOOL)),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    proposal = await forge.propose("read my email")
    assert proposal.blocked is True
    assert proposal.block_reason is not None
    assert "imaplib" in proposal.block_reason


@pytest.mark.asyncio
async def test_propose_allows_pure_stdlib_capability(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft()),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    proposal = await forge.propose("extract dates from text")
    assert proposal.blocked is False
    assert proposal.block_reason is None


@pytest.mark.asyncio
async def test_build_proposed_refuses_blocked_proposal_without_staging(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft(tool_script=NETWORK_TOOL)),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    proposal = await forge.propose("read my email")
    attempt = await forge.build_proposed(proposal)
    assert attempt.passed is False
    assert attempt.staged_id is None
    assert not list((tmp_path / "staging").iterdir())  # nothing was staged


@pytest.mark.asyncio
async def test_gated_propose_build_promote_round_trip(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft()),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    proposal = await forge.propose("extract dates from text")
    attempt = await forge.build_proposed(proposal)
    assert attempt.passed is True
    assert attempt.staged_id is not None
    skill = await forge.promote(attempt.staged_id)
    assert store.get(skill.name) is not None


@pytest.mark.asyncio
async def test_build_one_shot_refuses_network_capability(tmp_path: Path) -> None:
    store = FileCapabilityStore(tmp_path)
    forge = CapabilityForge(
        FakeModel(_draft(tool_script=NETWORK_TOOL)),
        store,
        FakeSandbox(VerifyResult(passed=True, output="ok")),
    )
    skill = await forge.build("read my email")
    assert skill is None

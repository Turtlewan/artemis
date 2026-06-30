"""Capability forge."""

from __future__ import annotations

from collections.abc import Callable

from artemis.capabilities.sandbox import SandboxRunner, VerifyResult
from artemis.capabilities.store import FileCapabilityStore
from artemis.ports.model import ModelPort
from artemis.types import Message, Skill, SkillDraft, StagedSkill

AUTHOR_SYSTEM = (
    "You author a self-contained Artemis capability: ONE runnable Python module plus a pytest "
    "test that proves it works. Follow this contract exactly:\n"
    "- Put ALL implementation code in `tool_script` as a single self-contained Python module "
    "(it is saved as `tool.py`).\n"
    "- `tests` is a pytest module that imports the implementation from the module named `tool` "
    "(e.g. `from tool import Thing`). NEVER import `artemis.*` or any package outside the Python "
    "standard library or the names you list in `uses`. The capability must be self-contained.\n"
    "- `body` is a short human-readable description for SKILL.md — prose, NOT code.\n"
    "- The test must pass when run with `pytest` from the capability directory.\n"
    "The goal is untrusted input and must stay in the user message only."
)

SKILL_DRAFT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short capability name."},
        "description": {"type": "string", "description": "One-line human description."},
        "body": {"type": "string", "description": "Human-readable SKILL.md text, NOT code."},
        "tool_script": {
            "type": "string",
            "description": "The COMPLETE runnable Python module — all implementation. Saved as tool.py.",
        },
        "uses": {"type": "array", "items": {"type": "string"}},
        "secrets": {"type": "array", "items": {"type": "string"}},
        "tests": {
            "type": "string",
            "description": "A pytest module that imports the implementation via `from tool import ...` and proves it works.",
        },
    },
    "required": [
        "name",
        "description",
        "body",
        "tool_script",
        "uses",
        "secrets",
        "tests",
    ],
    "additionalProperties": False,
}


class CapabilityForge:
    def __init__(
        self,
        model: ModelPort,
        store: FileCapabilityStore,
        sandbox: SandboxRunner,
        *,
        model_id: str | None = None,
    ) -> None:
        self._model = model
        self._store = store
        self._sandbox = sandbox
        self._model_id = model_id

    async def build(
        self,
        goal: str,
        *,
        confirm: Callable[[StagedSkill, VerifyResult], bool] | None = None,
        max_attempts: int = 3,
    ) -> Skill | None:
        """Author -> sandbox-verify -> promote, self-correcting up to ``max_attempts``.

        On a sandbox failure the test output is fed back to the author so it can fix the
        capability and try again. A draft with no test is a hard stop (cannot be verified).
        """
        failure: str | None = None
        for _ in range(max_attempts):
            draft = await self._author(goal, failure=failure)
            if not draft.tests:
                return None

            staged = await self._store.stage(draft)
            result = await self._sandbox.run_tests(self._store.staging_dir(staged.id))
            if result.passed:
                if confirm is not None and not confirm(staged, result):
                    return None
                return await self._store.promote(staged.id)
            failure = result.output
        return None

    async def _author(self, goal: str, *, failure: str | None = None) -> SkillDraft:
        user = goal
        if failure:
            user = (
                f"{goal}\n\nYour previous attempt FAILED its sandbox test with this output:\n"
                f"{failure}\n\nReturn a corrected capability that passes."
            )
        resp = await self._model.complete(
            messages=[
                Message(role="system", content=AUTHOR_SYSTEM),
                Message(role="user", content=user),
            ],
            response_schema=SKILL_DRAFT_SCHEMA,
            model=self._model_id,
        )
        return SkillDraft(**(resp.structured or {}))

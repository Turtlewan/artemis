"""Capability forge."""

from __future__ import annotations

import ast
from collections.abc import Callable

from artemis.capabilities.sandbox import SandboxRunner, VerifyResult
from artemis.capabilities.store import FileCapabilityStore
from artemis.ports.model import ModelPort
from artemis.types import BuildAttempt, BuildProposal, Message, Skill, SkillDraft, StagedSkill

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


# Top-level module names whose import means the capability can reach the network or spawn
# processes -- unsafe to run in the no-isolation SubprocessSandbox. AST import-level scan only;
# NOT a security boundary (evadable via getattr/eval/os.system). The WSL2 isolated sandbox is
# the real boundary; this guard enforces "network capabilities wait for WSL2".
UNSAFE_IMPORTS: frozenset[str] = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "imaplib",
        "smtplib",
        "poplib",
        "telnetlib",
        "nntplib",
        "asyncore",
        "asynchat",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "websocket",
        "websockets",
        "subprocess",
        "multiprocessing",
        "ctypes",
        "pty",
    }
)


def scan_for_unsafe_imports(source: str | None) -> str | None:
    """Return a human-readable reason if `source` imports a network/process module, else None.

    AST import-level scan only (see UNSAFE_IMPORTS). Unparseable source is treated as unsafe
    (we will not run code we cannot inspect). `None` source (no tool module) is not unsafe here.
    """
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "authored code could not be parsed for a safety scan"
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in UNSAFE_IMPORTS:
                    found.add(top)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            top = node.module.split(".")[0]
            if top in UNSAFE_IMPORTS:
                found.add(top)
    if found:
        names = ", ".join(sorted(found))
        return (
            f"capability imports network/process modules ({names}); "
            "blocked until the isolated WSL2 sandbox exists"
        )
    return None


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

    def _safety_reason(self, draft: SkillDraft) -> str | None:
        """Why this draft cannot be built in the current sandbox, or None if it can."""
        if not draft.tests:
            return "capability has no test -- cannot verify"
        return scan_for_unsafe_imports(draft.tool_script)

    async def propose(self, goal: str) -> BuildProposal:
        """Author a draft and classify it for the plan gate. No staging, no sandbox, no promote."""
        draft = await self._author(goal)
        reason = self._safety_reason(draft)
        return BuildProposal(
            goal=goal,
            draft=draft,
            blocked=reason is not None,
            block_reason=reason,
        )

    async def build_proposed(
        self, proposal: BuildProposal, *, max_attempts: int = 3
    ) -> BuildAttempt:
        """Sandbox-verify an approved proposal, self-correcting up to ``max_attempts``.

        Attempt 1 uses the proposal's already-authored draft; on failure the test output is fed
        back to the author for a corrected draft (re-scanned each time). Never promotes.
        """
        if proposal.blocked:
            return BuildAttempt(
                staged_id=None,
                passed=False,
                output=proposal.block_reason or "blocked",
            )
        draft = proposal.draft
        failure: str | None = None
        staged: StagedSkill | None = None
        result: VerifyResult | None = None
        for attempt in range(max_attempts):
            if attempt > 0:
                draft = await self._author(proposal.goal, failure=failure)
                reason = self._safety_reason(draft)
                if reason is not None:
                    return BuildAttempt(staged_id=None, passed=False, output=reason)
            staged = await self._store.stage(draft)
            result = await self._sandbox.run_tests(self._store.staging_dir(staged.id))
            if result.passed:
                return BuildAttempt(staged_id=staged.id, passed=True, output=result.output)
            failure = result.output
        assert staged is not None and result is not None  # max_attempts >= 1
        return BuildAttempt(staged_id=staged.id, passed=False, output=result.output)

    async def promote(self, staged_id: str) -> Skill:
        """The result gate's commit: install a verified staged capability into the library."""
        return await self._store.promote(staged_id)

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
            if self._safety_reason(draft) is not None:
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

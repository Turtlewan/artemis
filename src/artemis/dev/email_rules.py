"""Observe-only local Gmail reaction-rules harness.

This dev tool polls a test Gmail inbox, launders each raw message through the
local quarantine/classifier path, emits reaction events in observe mode only,
and writes owner-private JSONL logs for WOULD notices and structured extracts.
It is local-only and test-account-only: no raw body is logged, Gmail access is
read-only, and every effect seam is a no-op guard.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from artemis import paths
from artemis.adapters.model_adapters import OpenAIModelPort
from artemis.config import Settings, get_settings
from artemis.identity.key_provider import KeyProvider, SecretKey
from artemis.identity.owner_provider import build_owner_key_provider
from artemis.identity.scope import OWNER_PRIVATE
from artemis.identity.windows_key_provider import UnlockDeniedError, UnlockUnavailableError
from artemis.integrations.google.credentials import GoogleCredentialsFactory
from artemis.integrations.google.oauth import load_oauth_config
from artemis.integrations.google.tokens import SqlCipherTokenStore
from artemis.memory.schema import now_iso
from artemis.memory.write_path import MemoryWriteQueue
from artemis.modules.calendar.create_from_extract import EventExtract, HeldTentativeEvent
from artemis.modules.gmail.classify import EmailClassifier
from artemis.modules.gmail.client import (
    GMAIL_READONLY_SCOPE,
    GmailApiPort,
    GmailClient,
    extract_body_text,
)
from artemis.modules.gmail.extract_store import EmailExtractStore
from artemis.modules.gmail.ingest import GmailMemoryExtractor, MemoryQueuePort
from artemis.modules.gmail.module import register_gmail_scope
from artemis.modules.gmail.structured import StructuredEmailExtract
from artemis.ports.model import ModelPort
from artemis.ports.types import Vector
from artemis.reactions import compose as compose_module
from artemis.reactions.compose import compose_reactions
from artemis.reactions.dispatcher import ReactionDispatcher
from artemis.reactions.emit import DomainEvent
from artemis.reactions.rulestore import ReactionRule
from artemis.recipes import (
    ActionClass,
    Promoter,
    Recipe,
    RecipeClass,
    RecipeStatus,
    RecipeStore,
    RecurrenceStore,
    recurrence_path,
)
from artemis.registry import ToolRegistry
from artemis.staging.service import ActionStagingService
from artemis.staging.store import PendingActionStore
from artemis.untrusted.quarantine import QuarantinedReader

_DEFAULT_QUERY = "newer_than:7d in:inbox"
logger = logging.getLogger(__name__)


class BuildKeyProviderError(RuntimeError):
    """Raised when no dev key provider is configured for the harness."""


class _StructuredSink(Protocol):
    def __call__(self, extract: StructuredEmailExtract) -> None:
        """Record a structured extract."""
        ...


@dataclass
class DevRulesRuntime:
    """Composed runtime for one deterministic Gmail rules-building loop."""

    gmail: GmailApiPort
    memory_extractor: GmailMemoryExtractor
    dispatcher: ReactionDispatcher
    extract_store: EmailExtractStore
    marker: DevPollMarker
    structured_sink: _StructuredSink
    query: str = _DEFAULT_QUERY
    scope: str = GMAIL_READONLY_SCOPE


class DevPollMarker:
    """Owner-private JSON marker of Gmail message ids already processed."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def seen(self) -> set[str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if not isinstance(payload, dict):
            return set()
        raw_ids = payload.get("processed_message_ids")
        if not isinstance(raw_ids, list):
            return set()
        return {item for item in raw_ids if isinstance(item, str)}

    def add(self, message_ids: Sequence[str]) -> None:
        seen = self.seen()
        seen.update(message_ids)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_owner_private_text(
            self.path,
            json.dumps({"processed_message_ids": sorted(seen)}, sort_keys=True),
        )


class JsonlSink:
    """Append owner-private JSONL records with restricted file permissions."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        _owner_private(self.path)


class _NoopMemoryQueue:
    def enqueue(
        self,
        text: str,
        turn_id: str,
        role: str | None = None,
        *,
        source_sensitivity: object | None = None,
    ) -> None:
        del text, turn_id, role, source_sensitivity


class _DevEmbedder:
    @property
    def dimension(self) -> int:
        return 1

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [[1.0] for _ in texts]

    async def embed_query(self, query: str) -> Vector:
        del query
        return [1.0]


class _DevCommsRecipeStore:
    """Expose the prereq comms reactions as enabled dev recipes."""

    def list(self, *, status: RecipeStatus | None = None) -> list[Recipe]:
        if status is not None and status is not RecipeStatus.ENABLED:
            return []
        return [
            _reaction_recipe("email_to_task", "reaction:email_to_task"),
            _reaction_recipe("email_to_held_event", "reaction:email_to_held_event"),
            _reaction_recipe("gift_signal", "reaction:gift_signal"),
        ]


class _NoopCaptureService:
    async def suggest_from_text(
        self,
        source: Literal["chat", "email", "calendar"],
        text: str,
        *,
        untrusted: bool = False,
    ) -> str:
        del source, text, untrusted
        raise RuntimeError("dev email harness effect seam invoked in observe mode")


class _NoopTripAssembler:
    def assemble(self, extract: object) -> str:
        del extract
        raise RuntimeError("dev email harness effect seam invoked in observe mode")

    def get_trip(self, id: str) -> None:
        del id
        return None


class _NoopMemory:
    async def add_module_fact(
        self,
        *,
        subject: str,
        relation: str,
        object_: str,
        category: str,
        source_ref: str,
        sensitivity: str,
    ) -> str:
        del subject, relation, object_, category, source_ref, sensitivity
        raise RuntimeError("dev email harness effect seam invoked in observe mode")


class _EnvKeyProvider:
    """Minimal dev key provider for owner-run CLI use."""

    def dek_for_scope(self, scope: str) -> SecretKey:
        if scope != OWNER_PRIVATE:
            raise BuildKeyProviderError(f"unsupported dev scope: {scope}")
        raw = os.environ.get("ARTEMIS_OWNER_PRIVATE_DEK_HEX", "").strip()
        if len(raw) != 64:
            raise BuildKeyProviderError(
                "set ARTEMIS_OWNER_PRIVATE_DEK_HEX to a 32-byte hex key for dev harness storage"
            )
        try:
            return SecretKey(bytes.fromhex(raw))
        except ValueError as exc:
            raise BuildKeyProviderError(
                "ARTEMIS_OWNER_PRIVATE_DEK_HEX must be 32 bytes of valid hex"
            ) from exc

    def is_owner_unlocked(self) -> bool:
        return True


def build_dev_rules_runtime(
    *,
    settings: Settings,
    key_provider: KeyProvider,
    gmail: GmailApiPort | None = None,
    model: ModelPort | None = None,
) -> DevRulesRuntime:
    """Build the observe-only live-Gmail rules runtime."""
    runtime_cfg = compose_module.get_runtime_config()  # type: ignore[attr-defined]
    if runtime_cfg.reaction.reactions_mode != "observe":
        raise RuntimeError("artemis-dev-email-rules refuses to run unless reactions_mode=observe")

    if model is None:
        _assert_local_role(settings, "responder")
    local_model = model if model is not None else OpenAIModelPort(settings)
    _assert_tolless_model(local_model)
    reader = QuarantinedReader(local_model, role="responder")
    classifier = EmailClassifier(local_model)
    extract_store = EmailExtractStore(settings, key_provider)

    log_dir = _dev_dir(settings)
    would_sink = JsonlSink(log_dir / "would.jsonl")
    structured_log = JsonlSink(log_dir / "structured_extracts.jsonl")

    def notice_sink(line: str) -> None:
        would_sink.append({"ts": now_iso(), "notice": line})

    def structured_sink(extract: StructuredEmailExtract) -> None:
        structured_log.append({"ts": now_iso(), "extract": extract.model_dump(mode="json")})

    embedder = _DevEmbedder()
    registry = ToolRegistry(embedder)
    recipe_store = cast(
        RecipeStore,
        _DevCommsRecipeStore(),
    )
    promoter = Promoter(recipe_store, RecurrenceStore(recurrence_path(settings)))
    staging = ActionStagingService(PendingActionStore(settings, key_provider), registry)

    async def calendar_from_extract(extract: EventExtract, event_type: str) -> HeldTentativeEvent:
        del extract, event_type
        raise RuntimeError("dev email harness effect seam invoked in observe mode")

    async def get_linked_task_ref(_: str) -> str | None:
        return None

    async def fetch_extract(source_ref: str) -> StructuredEmailExtract | None:
        return extract_store.fetch(source_ref)

    async def complete_task(_: str) -> object:
        raise RuntimeError("dev email harness effect seam invoked in observe mode")

    bus, dispatcher, worker = compose_reactions(
        recipe_store=recipe_store,
        promoter=promoter,
        registry=registry,
        staging=staging,
        capture_service=_NoopCaptureService(),
        calendar_from_extract_fn=calendar_from_extract,
        trip_assembler=_NoopTripAssembler(),
        get_linked_task_ref_fn=get_linked_task_ref,
        fetch_extract=fetch_extract,
        memory=_NoopMemory(),
        complete_task_fn=complete_task,
        settings=settings,
        key_provider=key_provider,
        notice_sink=notice_sink,
    )
    worker.close()
    # Closed-loop guard: the pre-construction config check and compose's own
    # get_runtime_config() read are two separate reads; assert the dispatcher was
    # actually built in observe before wiring the live email path (harness review).
    if dispatcher._mode != "observe":
        raise RuntimeError("dev email harness: dispatcher was not constructed in observe mode")
    _install_dev_observe_filter(dispatcher)

    memory_extractor = GmailMemoryExtractor(
        reader=reader,
        queue=cast(MemoryWriteQueue | MemoryQueuePort, _NoopMemoryQueue()),
        classifier=classifier,
        extract_store=extract_store,
        emit=bus.emit,
    )

    register_gmail_scope()
    live_gmail = gmail
    if live_gmail is None:
        token_store = SqlCipherTokenStore(settings, key_provider)
        credentials = GoogleCredentialsFactory(token_store, load_oauth_config())
        live_gmail = GmailClient(credentials)

    return DevRulesRuntime(
        gmail=live_gmail,
        memory_extractor=memory_extractor,
        dispatcher=dispatcher,
        extract_store=extract_store,
        marker=DevPollMarker(log_dir / "last_poll.json"),
        structured_sink=structured_sink,
    )


async def poll_once(runtime: DevRulesRuntime) -> int:
    """Poll one Gmail batch, dispatch observe notices, and log structured extracts."""
    if runtime.scope != GMAIL_READONLY_SCOPE:
        raise RuntimeError("dev email rules harness requires gmail.readonly scope")

    seen = runtime.marker.seen()
    processed: list[str] = []
    page_token: str | None = None
    while True:
        ids, page_token = runtime.gmail.list_message_ids(q=runtime.query, page_token=page_token)
        for message_id in ids:
            if message_id in seen:
                continue
            msg = runtime.gmail.get_message(message_id, fmt="full")
            body = extract_body_text(msg)
            await runtime.memory_extractor.extract(message_id=message_id, body=body)
            processed.append(message_id)
        if page_token is None:
            break

    await runtime.dispatcher.drain_once()
    for message_id in processed:
        extract = runtime.extract_store.fetch(f"gmail:{message_id}")
        if extract is not None:
            runtime.structured_sink(extract)
    if processed:
        runtime.marker.add(processed)
    return len(processed)


async def run(*, once: bool, interval_s: int = 60) -> None:
    """Run the dev email rules polling loop."""
    try:
        key_provider = build_key_provider()
    except (UnlockUnavailableError, UnlockDeniedError) as exc:
        logger.warning("artemis-dev-email-rules unlock failed: %s: %s", type(exc).__name__, exc)
        print("Unlock failed.")
        raise SystemExit(2) from None
    runtime = build_dev_rules_runtime(settings=get_settings(), key_provider=key_provider)
    while True:
        await poll_once(runtime)
        if once:
            return
        await asyncio.sleep(interval_s)


def main() -> None:
    """CLI entry point for ``artemis-dev-email-rules``."""
    parser = argparse.ArgumentParser(prog="artemis-dev-email-rules")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--interval", type=int, default=60, help="seconds between polls")
    args = parser.parse_args()
    asyncio.run(run(once=bool(args.once), interval_s=int(args.interval)))


def build_key_provider() -> KeyProvider:
    """Build the dev key provider used by the standalone CLI."""
    return build_owner_key_provider(get_settings())


def _assert_tolless_model(model: ModelPort) -> None:
    signature = inspect.signature(model.complete)
    for forbidden in ("tools", "tool_choice"):
        if forbidden in signature.parameters:
            raise RuntimeError("dev email harness requires a toolless local ModelPort")


def _assert_local_role(settings: Settings, role: str) -> None:
    role_cfg = settings.roles.get(role)
    if role_cfg is None:
        raise RuntimeError(f"dev email harness requires configured local model role: {role}")
    endpoint = role_cfg.endpoint.lower()
    if not (
        endpoint.startswith(("http://127.0.0.1", "https://127.0.0.1"))
        or endpoint.startswith(("http://localhost", "https://localhost"))
        or endpoint.startswith(("http://[::1]", "https://[::1]"))
    ):
        raise RuntimeError(f"dev email harness refuses non-local model endpoint for role {role}")


def _dev_dir(settings: Settings) -> Path:
    return paths.scope_dir(settings, OWNER_PRIVATE) / "dev" / "email_rules"


def _write_owner_private_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _owner_private(path)


def _owner_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _install_dev_observe_filter(dispatcher: ReactionDispatcher) -> None:
    original_fire = dispatcher._fire

    async def filtered_fire(rule: ReactionRule, event: DomainEvent) -> None:
        if not _email_rule_applies(rule, event):
            return
        await original_fire(rule, event)

    setattr(dispatcher, "_fire", filtered_fire)


def _email_rule_applies(rule: ReactionRule, event: DomainEvent) -> bool:
    if event.source_module != "gmail":
        return True
    if rule.name == "reaction:email_to_task":
        return event.payload.get("has_commitment") is True
    if rule.name == "reaction:email_to_held_event":
        return event.payload.get("has_event") is True
    if rule.name == "reaction:gift_signal":
        return event.payload.get("has_gift_signal") is True
    return True


def _reaction_recipe(name: str, task_class_key: str) -> Recipe:
    return Recipe(
        name=name,
        description=f"Enabled dev email reaction for email_ingested: {task_class_key}",
        version="0.1.0",
        recipe_class=RecipeClass.INSTRUCTIONS,
        action_class=ActionClass.READ_ONLY,
        task_class_key=task_class_key,
        inputs_schema={},
        outputs_schema={},
        instructions="Runs through the prereq comms reaction registry in observe mode.",
        status=RecipeStatus.ENABLED,
    )

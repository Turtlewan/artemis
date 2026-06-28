"""Finance module manifest."""

from __future__ import annotations

from artemis.config import Settings
from artemis.ingest.pipeline import IngestPipeline
from artemis.manifest import ActionRisk, DataScope, ModuleManifest, Permissions, ToolSpec, UiSurface
from artemis.modules.finance import tools
from artemis.modules.finance.events import Emit, _noop_emit
from artemis.modules.finance.extraction import FinanceExtractor
from artemis.modules.finance.hooks import build_finance_hooks, register_finance_templates
from artemis.modules.finance.store import FinanceStore
from artemis.modules.gmail.cache import GmailReadCache
from artemis.proactive.hit_handler import TemplateRegistry


def finance_manifest(
    store: FinanceStore,
    registry: TemplateRegistry | None = None,
    ingest_pipeline: IngestPipeline | None = None,
    *,
    extractor: FinanceExtractor | None = None,
    gmail_cache: GmailReadCache | None = None,
    settings: Settings | None = None,
    emit: Emit = _noop_emit,
    include_write_surface: bool = False,
) -> ModuleManifest:
    """Return the owner-private Finance awareness manifest."""
    tools.init_finance_tools(store, emit=emit)
    if extractor is not None and gmail_cache is not None:
        tools.init_finance_extractor(extractor, gmail_cache)
    if ingest_pipeline is not None and settings is not None:
        tools.init_finance_knowledge(ingest_pipeline, settings)
    elif ingest_pipeline is not None:
        tools.init_finance_knowledge(ingest_pipeline, store.settings)
    if registry is not None:
        register_finance_templates(registry)
    tool_specs = _finance_tool_specs(include_write_surface=include_write_surface)
    return ModuleManifest(
        name="finance",
        version="0.1.0",
        description="Always-local owner-private finance ledger awareness.",
        tools=tool_specs,
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        proactive_hooks=build_finance_hooks(store),
        ui=UiSurface(kind="card"),
    )


def _finance_tool_specs(*, include_write_surface: bool) -> list[ToolSpec]:
    tool_specs = tools.build_finance_tool_specs()
    if include_write_surface:
        return tool_specs
    return [tool for tool in tool_specs if tool.action_risk == ActionRisk.READ]

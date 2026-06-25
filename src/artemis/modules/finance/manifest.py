"""Finance module manifest."""

from __future__ import annotations

from artemis.manifest import DataScope, ModuleManifest, Permissions, UiSurface
from artemis.modules.finance import tools
from artemis.modules.finance.events import Emit, _noop_emit
from artemis.modules.finance.extraction import FinanceExtractor
from artemis.modules.finance.hooks import build_finance_hooks, register_finance_templates
from artemis.modules.finance.store import FinanceStore
from artemis.modules.gmail.cache import GmailReadCache
from artemis.proactive.hit_handler import TemplateRegistry


def finance_manifest(
    store: FinanceStore,
    *,
    extractor: FinanceExtractor | None = None,
    gmail_cache: GmailReadCache | None = None,
    registry: TemplateRegistry | None = None,
    emit: Emit = _noop_emit,
) -> ModuleManifest:
    """Return the owner-private Finance awareness manifest."""
    tools.init_finance_tools(store, emit=emit)
    if extractor is not None and gmail_cache is not None:
        tools.init_finance_extractor(extractor, gmail_cache)
    if registry is not None:
        register_finance_templates(registry)
    return ModuleManifest(
        name="finance",
        version="0.1.0",
        description="Always-local owner-private finance ledger awareness.",
        tools=tools.build_finance_tool_specs(),
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        proactive_hooks=build_finance_hooks(store),
        ui=UiSurface(kind="card"),
    )

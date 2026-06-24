"""Finance module manifest."""

from __future__ import annotations

from artemis.manifest import DataScope, ModuleManifest, Permissions, UiSurface
from artemis.modules.finance import tools
from artemis.modules.finance.extraction import FinanceExtractor
from artemis.modules.finance.store import FinanceStore
from artemis.modules.gmail.cache import GmailReadCache


def finance_manifest(
    store: FinanceStore,
    *,
    extractor: FinanceExtractor | None = None,
    gmail_cache: GmailReadCache | None = None,
) -> ModuleManifest:
    """Return the owner-private Finance awareness manifest."""
    tools.init_finance_tools(store)
    if extractor is not None and gmail_cache is not None:
        tools.init_finance_extractor(extractor, gmail_cache)
    return ModuleManifest(
        name="finance",
        version="0.1.0",
        description="Always-local owner-private finance ledger awareness.",
        tools=tools.build_finance_tool_specs(),
        data_scope=DataScope.OWNER_PRIVATE,
        permissions=Permissions(owner=True, guest=False),
        proactive_hooks=[],
        ui=UiSurface(kind="card"),
    )

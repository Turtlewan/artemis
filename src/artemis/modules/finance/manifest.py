"""Finance module manifest."""

from __future__ import annotations

from artemis.manifest import DataScope, ModuleManifest, Permissions, UiSurface
from artemis.modules.finance import tools
from artemis.modules.finance.store import FinanceStore


def finance_manifest(store: FinanceStore) -> ModuleManifest:
    """Return the owner-private Finance awareness manifest."""
    tools.init_finance_tools(store)
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

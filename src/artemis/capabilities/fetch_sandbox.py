"""Runtime fetch pipe for promoted network capabilities.

Runs a promoted capability inside the hardened WSL2 isolate with a caller-supplied
egress allowlist and returns raw text output for host-side synthesis. No model calls
run inside the sandbox; all reasoning is host-side (ADR-035 decision 2, Option B;
ADR-036). Egress is passed explicitly by the caller (from the promoted
`Skill.egress_domains`), not via `sandbox_policy.json`.

SECURITY: `FetchResult.output` is UNTRUSTED external content, raw bytes fetched from
an arbitrary allowlisted domain and attacker-influenceable (prompt injection).
Downstream consumers (AggregationPipeline / router, specs 4/5) MUST treat it as data,
not instructions, and apply prompt-injection defenses (ADR-009 dual-LLM quarantine:
no-tools reader, structured output, spotlighting) before any model reasoning over it.
Secret values passed via `secrets` are injected as isolate-scoped env vars for the
capability process only, never included in `FetchResult.output`.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from pydantic import BaseModel

from artemis.capabilities.sandbox_wsl2 import OUTPUT_LIMIT_DEFAULT, SandboxCaps, run_isolated
from artemis.ports.secrets import SecretStorePort

_MAX_TIMEOUT_S = 300.0


class FetchResult(BaseModel):
    output: str
    exit_code: int
    truncated: bool


def missing_required_secrets(required: list[str], store: SecretStorePort) -> list[str]:
    """Return missing secret names using the presence-only list operation."""
    present = set(store.list_names())
    return [name for name in required if name not in present]


def resolve_secret_values(names: list[str], store: SecretStorePort) -> dict[str, str]:
    """Read secret values for injection, failing closed on the first missing/empty value."""
    out: dict[str, str] = {}
    for name in names:
        value = store.get(name)
        if not value:
            raise ValueError(f"secret not available for injection: {name}")
        out[name] = value
    return out


class FetchSandbox:
    """Runtime pipe for untrusted fetch output under a fail-closed egress allowlist.

    `FetchResult.output` is UNTRUSTED external content; downstream consumers must
    apply ADR-009 dual-LLM quarantine before any model reasoning over it. An empty
    `egress_domains` list means no network, not unrestricted egress.
    """

    async def run(
        self,
        capability_dir: Path,
        *,
        entrypoint: str,
        argv: list[str],
        egress_domains: list[str],
        timeout_s: float = 60.0,
        secrets: dict[str, str] | None = None,
        output_limit: int = OUTPUT_LIMIT_DEFAULT,
    ) -> FetchResult:
        """Run `entrypoint` inside the isolate and return its raw output.

        `entrypoint` must be a relative path inside the capability dir (no absolute
        path, no `..` traversal). `egress_domains` is fail-closed: an empty list means
        NO network at all (pure no-network isolate), NOT unrestricted egress (C2).
        `timeout_s` is clamped to `_MAX_TIMEOUT_S` (caller-controlled DoS guard).

        Does NOT swallow exceptions from `run_isolated` (for example provisioning/WSL
        errors or asyncio timeouts); they propagate to the caller to handle.
        """
        parts = PurePosixPath(entrypoint)
        if parts.is_absolute() or ".." in parts.parts:
            raise ValueError(f"entrypoint must be a relative path with no '..': {entrypoint!r}")

        exit_code, output, truncated = await run_isolated(
            capability_dir,
            egress_domains=egress_domains,
            caps=SandboxCaps(),
            command=["python3", entrypoint, *argv],
            timeout_s=min(timeout_s, _MAX_TIMEOUT_S),
            secrets=secrets,
            output_limit=output_limit,
        )
        return FetchResult(output=output, exit_code=exit_code, truncated=truncated)

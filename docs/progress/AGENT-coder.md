# AGENT-coder — build progress / notes

Built by Codex (workspace.py + subsystem.py + tests) + host (openhands-sdk dep). Host-verified:
full `uv run mypy` clean (291 files), ruff clean, 820 passed / 4 skipped. Opus cross-model
(security) review: CLEAN on all BLOCKs — gate-every-confirmation (analyzer risk is metadata-only,
never skips), fail-closed ConfirmationPolicy (authorize-raise / inbox-raise / ask-None / pending-None
all -> DENY, never re-raises into the SDK / never auto-allows), live-run sandbox guard (refuses live
local run when sandbox_active defaults False), sanitized BuildResult (status enum + basename-only
files + path-scrubbed/stdout-stripped/1000-char summary; run() swallows all exceptions to ERROR).
Lazy openhands import + OPENHANDS_SUPPRESS_BANNER. API verified against installed openhands-sdk
1.29.2 (LLM/Agent/Conversation/Tool import surface present).

## NOTES (review-needed, planning)
1. WORKSPACE SEAM: build_workspace maps BOTH kind="docker" and kind="remote" to RemoteWorkspace
   (DockerWorkspace not separately constructed). Acceptable — both are Mac-gated/import-guarded and
   fake-tested on the dev box; the Mac build reconciles the exact docker-vs-remote workspace class.
2. SUPPLY-CHAIN (agentic group, optional — base sync stays lean): the agentic dep tree carries some
   transitive CVEs to review at the Mac/prod hardening pass: pyjwt (8), cryptography (1), idna (1),
   msgpack (1), pydantic-settings (1) — these are INHERITED (base + the pydantic-ai/litellm waves),
   NOT introduced by openhands-sdk (whose own tree — pillow/redis/pypdf/tree-sitter/posthog/etc. —
   pip-audit flagged CLEAN). Pre-existing base CVEs (starlette/torch/yt-dlp/python-multipart@base)
   are documented in status.md and predate this work. ACTION: a supply-chain bump pass on the agentic
   group before any live cloud-coder run.
3. PRIVACY NOTE: openhands-sdk's tree pulls `posthog` (telemetry). It is dormant (no live run on the
   dev box; tests use a fake conversation), but set OPENHANDS analytics opt-out / verify no egress
   before the first live embed run.
4. LLM construction passes model + base_url but no api_key (env-ref convention: LiteLLM/OpenHands
   reads the provider key from the env var named by backend.api_key_env at call time). Validate the
   env-var wiring at the live-embed exercise.

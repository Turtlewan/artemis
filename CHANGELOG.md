# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Added — capability metadata fields (goal/built_at/auth_status/oauth_scopes).
- Telegram inbound (R4): the always-on runner now routes allowlisted inbound Telegram messages
  through the intent router — chat + web questions answer inline (quarantined), and capability
  **invokes** are consent-gated by a version-scoped "bless" grant. A blessed capability runs on a
  plain text; an un-blessed one sends an inline `[Run once]/[Always allow]/[Cancel]` card showing its
  egress domains + secret names + inputs (never values). Bless from chat (`[Always allow]`) or the
  desktop, revoke via `/blessed` or the desktop list; a rebuild resets the grant. Dual-pass
  apex-security reviewed. (ADR-043)
- JS-rendering fallback fetcher for reach-out web lookups: a WSL2-isolated
  `chrome-headless-shell` renderer is used only when trafilatura returns empty text, with exact-host
  egress allowlisting and provisioning docs. (ADR-040)
- Typed `inputs` schema for capabilities (`SkillInputParam` + `build_invoke_argv` in `artemis.types`), persisted through `SKILL.md` frontmatter and the file store; capabilities without an `inputs` key read back as parameterless (zero migration). First of the capability invoke/reuse path. (ADR-039)
- The capability forge now authors a typed `inputs` schema for each proposed capability (`SKILL_DRAFT_SCHEMA` + `AUTHOR_SYSTEM` require `inputs`; secrets stay separate). Second of the capability invoke/reuse path. (ADR-039)
- Match-first capability selector (`artemis.capabilities.select`): shortlists via `store.retrieve`, picks one (or none) with a dedicated Haiku port, validates/coerces typed args against the capability's `inputs`, and returns a degrade-safe `SelectionResult` (never runs anything). Re-validates the model's pick against the shortlist (anti-hallucination). Third of the capability invoke/reuse path. (ADR-039)
- Missing-key run-guard + WSL2 secrets injection (`fetch_sandbox`/`sandbox_wsl2`): presence-only `missing_required_secrets`, fail-closed `resolve_secret_values`, and runtime credential injection into the isolate as environment variables scoped to the capability process only — never argv/logs/`FetchResult.output`, delivered via the outer setup shell's environ after the network services launch (admin-only, never world-readable). Secret names validated + blocklisted. Security-reviewed (1 BLOCK + 4 findings resolved). Fourth of the capability invoke/reuse path. (ADR-039)
- Client invoke UI: the Ask popup shows a confirm card (capability + egress + secrets + inputs, Run/Cancel) on an `invoke_confirm` response, runs it via `invokeConfirm`, deep-links to the keys panel on `missing_secrets`, and shows a clarify prompt on `invoke_clarify`. `askStore.send()` switched from the (single-lump) stream to the plain `/app/ask` so the invoke fields arrive. **Closes the build→promote→reuse dogfood loop in the app.** UI half of the fifth invoke/reuse spec. (ADR-039)
- Client invoke gateway: `AskResponse` invoke fields + `InvokeConfirmResponse` DTO, the `app_invoke_confirm` Tauri command (session token stays in Rust), and the `invokeConfirm` wrapper. Gateway half of the fifth invoke/reuse spec. (ADR-039)
- Match-first invoke wiring (`artemis.capabilities.invoke` + `/app/ask`): the selector runs before the intent classifier; a confident full match returns a server-held **invoke proposal** (confirm-before-run), and `POST /app/ask/invoke/{id}/confirm` runs the missing-key guard → resolves secrets → `FetchSandbox.run` → **dual-LLM quarantine** over the untrusted output → reply. Pop-first-claim guarantees at-most-once execution per proposal (no concurrent double-run). Session-gated. Security-reviewed (1 BLOCK + 1 FLAG resolved). Brain half of the fifth invoke/reuse spec. (ADR-039)
- Reach-out web primitives (`artemis.reachout`): SSRF-guarded `EgressPolicy` (allowlist + port-lock + DNS-rebinding IP-pinning), `TavilySearch` search adapter, and a `trafilatura`-backed clean-text `Fetcher`. (ADR-035)
- Pattern-A `WebTool` (`artemis.reachout.web_tool`): deterministic `search → fetch → quarantined-read (Haiku→Sonnet) → synthesize` lookup over the R1 primitives, with a dual-LLM quarantine (raw pages reach only the reader; the synthesizer sees only spotlighted extracts), cited-only sources, and graceful degradation. (ADR-037)

### Changed
- `FetchSandbox.run` gains an opt-in `caps_profile: Literal["default", "render"]` selecting a closed, reviewed resource-caps profile — `"default"` (512MB / 1-CPU, unchanged) or `"render"` (1.5GB / 4-CPU / 256 pids / unlimited VSZ, for chrome-class workloads). `SandboxCaps` gains an `unlimited_vsz` flag; the `render` profile relies solely on cgroup `memory.max` for RAM containment (the `ulimit -v` backstop is incompatible with Chrome/V8's virtual-memory reservation). No arbitrary caps override is accepted. (ADR-041)
- `ClaudeCodeProvider` now runs `claude -p` in a private, clean `CLAUDE_CONFIG_DIR` (creds-only copy, no CLAUDE.md/hooks) so subscription reads return the model's answer instead of inheriting project context; `cli_support.run_cli` gains an optional `env` passthrough. (ADR-037)

### Fixed
- WSL2 isolate arg-passing: `run_isolated` now shlex-quotes every positional arg crossing the `wsl.exe` interop boundary and the guest script fail-closed-decodes them back, so a URL/path containing shell metacharacters (parens, spaces) no longer causes a `bash` syntax error before the capability runs. The guest decode aborts (never silently truncates) on any decode failure, non-UTF8 byte, or argv-count mismatch. (ADR-041)

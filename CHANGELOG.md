# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Reach-out web primitives (`artemis.reachout`): SSRF-guarded `EgressPolicy` (allowlist + port-lock + DNS-rebinding IP-pinning), `TavilySearch` search adapter, and a `trafilatura`-backed clean-text `Fetcher`. (ADR-035)
- Pattern-A `WebTool` (`artemis.reachout.web_tool`): deterministic `search → fetch → quarantined-read (Haiku→Sonnet) → synthesize` lookup over the R1 primitives, with a dual-LLM quarantine (raw pages reach only the reader; the synthesizer sees only spotlighted extracts), cited-only sources, and graceful degradation. (ADR-037)

### Changed
- `ClaudeCodeProvider` now runs `claude -p` in a private, clean `CLAUDE_CONFIG_DIR` (creds-only copy, no CLAUDE.md/hooks) so subscription reads return the model's answer instead of inheriting project context; `cli_support.run_cli` gains an optional `env` passthrough. (ADR-037)

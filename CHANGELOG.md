# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Reach-out web primitives (`artemis.reachout`): SSRF-guarded `EgressPolicy` (allowlist + port-lock + DNS-rebinding IP-pinning), `TavilySearch` search adapter, and a `trafilatura`-backed clean-text `Fetcher`. (ADR-035)
